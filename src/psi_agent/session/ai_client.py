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
    SSE_DONE,
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
            return value
        if isinstance(value, str):
            try:
                return int(value)
            except ValueError:
                return 0
        return 0

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
                    candidate_finish_reason = c.get("finish_reason")
                    if finish_reason is None and isinstance(candidate_finish_reason, str):
                        finish_reason = candidate_finish_reason
                    yield AiDelta(
                        content=delta_data.get("content"),
                        reasoning=delta_data.get("reasoning"),
                        kind=delta_data.get("kind") if isinstance(delta_data.get("kind"), str) else None,
                        tool_calls=delta_data.get("tool_calls"),
                        finish_reason=candidate_finish_reason,
                        compaction_needed=compaction_needed,
                        prompt_tokens=self._as_int(compaction_signal.get("prompt_tokens"))
                        if isinstance(compaction_signal, dict)
                        else 0,
                        compaction_threshold=self._as_int(compaction_signal.get("threshold"))
                        if isinstance(compaction_signal, dict)
                        else 0,
                    )
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
