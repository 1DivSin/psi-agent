"""Left-side protocol adapter.  ``AiClient.stream()`` does HTTP→SSE
parsing→``AiDelta``.  Self-contained — depends only on the socket resolver
and protocol types.
"""

from __future__ import annotations

import json
import time
from collections.abc import AsyncGenerator

import aiohttp
from loguru import logger

from psi_agent._sockets import resolve_connector_and_endpoint
from psi_agent.protocol import (
    FINISH_REASON_ERROR,
    FINISH_REASON_TOOL_CALLS,
    FINISH_REASON_USAGE,
    SSE_DONE,
    is_auxiliary_finish,
    parse_sse_data,
)
from psi_agent.session.protocol import AiDelta


class AiClient:
    """Protocol adapter for the AI backend — handles HTTP/SSE and yields AiDelta."""

    def __init__(self, ai_socket: str) -> None:
        self.ai_socket = ai_socket

    def _build_connector_and_endpoint(self) -> tuple[aiohttp.BaseConnector, str]:
        return resolve_connector_and_endpoint(self.ai_socket)

    @staticmethod
    def _as_int(value: object) -> int:
        """Coerce an untrusted SSE field to int; 0 when absent or malformed.

        ``bool`` is rejected explicitly: it is a subclass of ``int``, so a JSON
        ``true`` would otherwise silently become ``1`` token.
        """
        if isinstance(value, bool):
            return 0
        if isinstance(value, int):
            return value if value >= 0 else 0
        if isinstance(value, str):
            try:
                return int(value)
            except ValueError:
                return 0
        return 0

    @staticmethod
    def _as_token_count(value: object) -> int | None:
        """Validate one usage count without turning unknown values into zero."""

        if isinstance(value, bool) or not isinstance(value, int) or value < 0:
            return None
        return value

    @classmethod
    def _usage_counts(
        cls,
        usage_signal: dict[str, object],
    ) -> tuple[int | None, int | None, int | None, int | None]:
        input_tokens = cls._as_token_count(usage_signal.get("prompt_tokens"))
        output_tokens = cls._as_token_count(usage_signal.get("completion_tokens"))
        cached_input_tokens = cls._as_token_count(usage_signal.get("cached_input_tokens"))
        cache_creation_input_tokens = cls._as_token_count(usage_signal.get("cache_creation_input_tokens"))
        if input_tokens is None:
            return input_tokens, output_tokens, None, None
        if cached_input_tokens is not None and cached_input_tokens > input_tokens:
            cached_input_tokens = None
        if cache_creation_input_tokens is not None and cache_creation_input_tokens > input_tokens:
            cache_creation_input_tokens = None
        if (
            cached_input_tokens is not None
            and cache_creation_input_tokens is not None
            and cached_input_tokens + cache_creation_input_tokens > input_tokens
        ):
            cached_input_tokens = None
            cache_creation_input_tokens = None
        return input_tokens, output_tokens, cached_input_tokens, cache_creation_input_tokens

    async def stream(self, request_body: dict) -> AsyncGenerator[AiDelta]:
        started = time.perf_counter()
        status: int | None = None
        first_delta_ms: float | None = None
        delta_count = 0
        finish_reason: str | None = None
        messages = request_body.get("messages")
        tools = request_body.get("tools")
        message_count = len(messages) if isinstance(messages, list) else 0
        tool_count = len(tools) if isinstance(tools, list) else 0
        pending_tool_terminal: AiDelta | None = None
        try:
            connector, endpoint = self._build_connector_and_endpoint()
            async with (
                aiohttp.ClientSession(connector=connector, timeout=aiohttp.ClientTimeout(total=None)) as session,
                session.post(endpoint, json=request_body) as resp,
            ):
                status = resp.status
                headers_ms = (time.perf_counter() - started) * 1000
                logger.bind(
                    event="ai_request_headers",
                    status=status,
                    elapsed_ms=round(headers_ms, 3),
                    message_count=message_count,
                    tool_count=tool_count,
                ).info("AI response headers received")
                if resp.status != 200:
                    error_text = await resp.text()
                    logger.error(f"AI error from {self.ai_socket!r}: {error_text[:1000]!r}")
                    finish_reason = FINISH_REASON_ERROR
                    yield AiDelta(finish_reason=FINISH_REASON_ERROR, content=f"[AI Error: {resp.status}]")
                    return

                logger.debug("Starting to consume SSE stream")
                async for raw_line in resp.content:
                    line = raw_line.decode().strip()
                    data_str = parse_sse_data(line)
                    # Empty payloads are heartbeats on some OpenAI-compatible
                    # servers; skip them silently rather than letting them reach
                    # ``json.loads`` and log a warning per beat.
                    if not data_str or data_str == SSE_DONE:
                        continue

                    try:
                        data = json.loads(data_str)
                    except json.JSONDecodeError:
                        logger.warning(f"Failed to parse SSE data: {data_str[:1000]!r}")
                        continue

                    choices_data = data.get("choices", [])
                    if not isinstance(choices_data, list):
                        logger.warning(f"Expected choices as list, got {type(choices_data).__name__}")
                        continue
                    if len(choices_data) > 1:
                        logger.warning(f"Expected 1 choice, got {len(choices_data)}, yielding error")
                        finish_reason = FINISH_REASON_ERROR
                        yield AiDelta(
                            finish_reason=FINISH_REASON_ERROR,
                            content=f"[AI Error: expected 1 choice, got {len(choices_data)}]",
                        )
                        return
                    if not choices_data:
                        continue

                    c = choices_data[0]
                    if not isinstance(c, dict):
                        logger.warning(f"Expected choice as dict, got {type(c).__name__}")
                        continue
                    if first_delta_ms is None:
                        first_delta_ms = (time.perf_counter() - started) * 1000
                        logger.bind(
                            event="ai_request_ttft",
                            ttft_ms=round(first_delta_ms, 3),
                            status=status,
                            message_count=message_count,
                            tool_count=tool_count,
                        ).info("AI first response delta received")
                    delta_count += 1
                    delta_data = c.get("delta")
                    if not isinstance(delta_data, dict):
                        delta_data = {}
                    compaction_signal = data.get("psi_compaction", {})
                    compaction_needed = isinstance(compaction_signal, dict) and compaction_signal.get("needed", False)
                    usage_signal = data.get("psi_usage", {})
                    has_usage = isinstance(usage_signal, dict) and c.get("finish_reason") == FINISH_REASON_USAGE
                    usage_counts = self._usage_counts(usage_signal) if has_usage else (None, None, None, None)
                    current_finish = c.get("finish_reason")
                    if finish_reason is None and isinstance(current_finish, str):
                        finish_reason = current_finish
                    parsed_delta = AiDelta(
                        content=delta_data.get("content"),
                        reasoning=delta_data.get("reasoning"),
                        kind=delta_data.get("kind") if isinstance(delta_data.get("kind"), str) else None,
                        tool_calls=delta_data.get("tool_calls"),
                        finish_reason=current_finish,
                        compaction_needed=compaction_needed,
                        prompt_tokens=self._as_int(compaction_signal.get("prompt_tokens"))
                        if isinstance(compaction_signal, dict)
                        else 0,
                        compaction_threshold=self._as_int(compaction_signal.get("threshold"))
                        if isinstance(compaction_signal, dict)
                        else 0,
                        input_tokens=usage_counts[0],
                        output_tokens=usage_counts[1],
                        cached_input_tokens=usage_counts[2],
                        cache_creation_input_tokens=usage_counts[3],
                    )
                    if pending_tool_terminal is not None and not is_auxiliary_finish(current_finish):
                        # Trailing auxiliary signals belong to the completed model
                        # call. Preserve the historical terminal boundary if a
                        # normal business frame follows instead.
                        yield pending_tool_terminal
                        return
                    if current_finish == FINISH_REASON_TOOL_CALLS:
                        if pending_tool_terminal is None:
                            pending_tool_terminal = parsed_delta
                        else:
                            logger.warning("Ignoring duplicate tool_calls terminal finish in SSE stream")
                        continue
                    yield parsed_delta
                if pending_tool_terminal is not None:
                    yield pending_tool_terminal
                logger.debug("SSE stream consumed successfully")
        finally:
            logger.bind(
                event="ai_request_complete",
                status=status,
                total_ms=round((time.perf_counter() - started) * 1000, 3),
                ttft_ms=round(first_delta_ms, 3) if first_delta_ms is not None else None,
                delta_count=delta_count,
                finish_reason=finish_reason,
                message_count=message_count,
                tool_count=tool_count,
            ).info("AI request completed")
