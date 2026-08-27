from __future__ import annotations

import json
from collections.abc import AsyncIterator
from typing import Any, cast

import anyio
from aiohttp import web
from any_llm.api import ChatCompletionChunk, acompletion
from loguru import logger

from psi_agent.protocol import make_compaction_signal, make_error_chunk, make_usage_signal


def _optional_token_count(value: object) -> int | None:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        return None
    return value


def _cache_token_counts(usage: object) -> tuple[int | None, int | None]:
    """Read normalized cache details without treating missing metrics as zero."""

    details = getattr(usage, "prompt_tokens_details", None)
    cached_input_tokens = _optional_token_count(getattr(details, "cached_tokens", None))
    if cached_input_tokens is None:
        cached_input_tokens = _optional_token_count(getattr(usage, "cache_read_input_tokens", None))

    cache_creation_input_tokens = _optional_token_count(getattr(details, "cache_creation_tokens", None))
    if cache_creation_input_tokens is None:
        cache_creation_input_tokens = _optional_token_count(getattr(usage, "cache_creation_input_tokens", None))

    prompt_tokens = _optional_token_count(getattr(usage, "prompt_tokens", None))
    if prompt_tokens is None:
        return None, None
    if cached_input_tokens is not None and cached_input_tokens > prompt_tokens:
        logger.warning("Ignoring cached input token count greater than total prompt tokens")
        cached_input_tokens = None
    if cache_creation_input_tokens is not None and cache_creation_input_tokens > prompt_tokens:
        logger.warning("Ignoring cache creation token count greater than total prompt tokens")
        cache_creation_input_tokens = None
    if (
        cached_input_tokens is not None
        and cache_creation_input_tokens is not None
        and cached_input_tokens + cache_creation_input_tokens > prompt_tokens
    ):
        logger.warning("Ignoring cache token breakdown greater than total prompt tokens")
        return None, None
    return cached_input_tokens, cache_creation_input_tokens


async def handle_chat_completions(request: web.Request) -> web.StreamResponse:
    logger.info("Received chat completion request")
    try:
        body: dict[str, Any] = await request.json()
        logger.debug(f"Request body: {json.dumps(body, ensure_ascii=False)[:1000]}")
    except Exception as e:
        logger.error(f"Failed to parse request body: {e!r}")
        # OpenAI-compatible error response.
        return web.json_response(
            {"error": {"message": str(e), "type": "invalid_request_error", "param": None, "code": 400}},
            status=400,
        )

    provider = request.app["provider"]
    model = request.app["model"]
    api_key = request.app["api_key"]
    base_url = request.app["base_url"]
    # ``client_args`` 走的是 provider 的 client 构造, 不是请求体 —— 换掉 TLS
    # 上下文只能从这里进去, any-llm 内部自己 new httpx client。client 由
    # ``serve_ai`` 按 provider 建 (不收 http_client 的 provider 拿到 None)、
    # 进程退出时关。见 psi_agent._tls 与 _build_http_client。
    # 用 get 而不是 []: 这个 handler 也被不经 ``serve_ai`` 装配的 app 用 (测试、
    # 将来的嵌入式用法), 少一个键不该变成 500。缺了就走 any-llm 默认 client。
    http_client = request.app.get("http_client")
    client_args: dict[str, Any] = {"client_args": {"http_client": http_client}} if http_client else {}

    logger.debug(f"Body keys before pop: {list(body)}")
    messages = body.pop("messages", [])
    body.pop("stream", None)
    body.pop("provider", None)
    body.pop("model", None)
    body.pop("api_key", None)
    body.pop("api_base", None)
    body.pop("routing", None)
    stream_opts = body.get("stream_options", {})
    if isinstance(stream_opts, dict):
        stream_opts["include_usage"] = True
        body["stream_options"] = stream_opts
    else:
        body["stream_options"] = {"include_usage": True}
    logger.debug(f"Body keys to passthrough: {list(body)}")

    response = web.StreamResponse(
        status=200,
        reason="OK",
        headers={
            # SSE standard headers — per MDN / HTML spec
            "Content-Type": "text/event-stream",
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )
    try:
        await response.prepare(request)
    except Exception:
        logger.warning("Client disconnected before SSE response prepared")
        return response

    logger.debug(f"Forwarding to upstream: provider={provider!r}, model={model!r}, base_url={base_url!r}")
    upstream_error = False
    client_gone = False
    compaction_needed = False
    token_usage: dict[str, int | None] = {}
    stream: AsyncIterator[ChatCompletionChunk] | None = None
    try:
        stream = cast(
            AsyncIterator[ChatCompletionChunk],
            # ``acompletion()`` returns ``ChatCompletion | AsyncIterator[ChatCompletionChunk]``
            # depending on the ``stream`` flag.  We always pass ``stream=True``, so the
            # runtime type is always ``AsyncIterator[ChatCompletionChunk]`` — the cast is safe.
            await acompletion(
                provider=provider,
                model=model,
                messages=messages,
                stream=True,
                api_key=api_key,
                api_base=base_url,
                **client_args,
                **body,
            ),
        )
        logger.debug("Starting to consume upstream SSE stream")
        max_context_tokens: int = request.app.get("max_context_tokens", 0)
        compaction_usage: dict[str, int] = {}
        async for chunk in stream:
            if chunk.usage:
                cached_input_tokens, cache_creation_input_tokens = _cache_token_counts(chunk.usage)
                token_usage = {
                    "prompt_tokens": chunk.usage.prompt_tokens,
                    "completion_tokens": chunk.usage.completion_tokens,
                    "total_tokens": chunk.usage.total_tokens,
                    "cached_input_tokens": cached_input_tokens,
                    "cache_creation_input_tokens": cache_creation_input_tokens,
                }
            if max_context_tokens > 0 and chunk.usage and chunk.usage.prompt_tokens > max_context_tokens:
                compaction_needed = True
                compaction_usage = {"prompt_tokens": chunk.usage.prompt_tokens}
                logger.debug(
                    f"Compaction needed: prompt_tokens={chunk.usage.prompt_tokens} > threshold={max_context_tokens}"
                )
            data = chunk.model_dump_json()
            logger.debug(f"SSE chunk: {data[:1000]}")
            await response.write(f"data: {data}\n\n".encode())
        if token_usage:
            signal = json.dumps(
                make_usage_signal(
                    prompt_tokens=cast(int, token_usage["prompt_tokens"]),
                    completion_tokens=cast(int, token_usage["completion_tokens"]),
                    total_tokens=cast(int, token_usage["total_tokens"]),
                    cached_input_tokens=token_usage["cached_input_tokens"],
                    cache_creation_input_tokens=token_usage["cache_creation_input_tokens"],
                )
            )
            logger.debug(f"SSE usage signal: {signal[:500]}")
            await response.write(f"data: {signal}\n\n".encode())
        if compaction_needed:
            signal = json.dumps(
                make_compaction_signal(
                    prompt_tokens=compaction_usage.get("prompt_tokens", 0),
                    threshold=max_context_tokens,
                )
            )
            logger.debug(f"SSE compaction signal: {signal[:500]}")
            await response.write(f"data: {signal}\n\n".encode())
    except ConnectionResetError:
        # Downstream client (session/channel) disconnected — e.g. user pressed
        # "stop". The finally block closes the upstream provider stream.
        client_gone = True
        logger.info("Client disconnected; cancelling upstream stream")
    except Exception as e:
        upstream_error = True
        logger.error(f"Error forwarding to upstream (provider={provider!r}, model={model!r}): {e!r}")
        err_chunk = json.dumps(make_error_chunk(f"[Upstream Error]: {e}"))
        logger.debug(f"SSE error chunk: {err_chunk[:1000]}")
        try:
            await response.write(f"data: {err_chunk}\n\n".encode())
        except Exception:
            logger.warning("Failed to send upstream error chunk to client")
    else:
        if compaction_needed:
            logger.debug("Request completed with compaction signal")
        else:
            logger.debug("Upstream stream completed successfully")
    finally:
        # Always release the upstream connection, even on cancellation
        # (client disconnect / shutdown). Shielded so aclose() completes
        # while a CancelledError is propagating through this finally.
        if stream is not None:
            aclose = getattr(stream, "aclose", None)
            if aclose is not None:
                logger.debug("Closing upstream stream")
                with anyio.CancelScope(shield=True):
                    try:
                        await aclose()
                    except Exception as close_err:
                        logger.warning(f"Failed to close upstream stream: {close_err}")

    if client_gone:
        logger.info("Request cancelled by client disconnect")
    elif upstream_error:
        logger.info("Request completed with upstream error")
    else:
        logger.info("Request completed successfully")
    return response
