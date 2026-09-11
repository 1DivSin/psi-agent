"""稳定的 workflow 错误载荷，避免宿主依赖 Haitun 异常文本。"""
from __future__ import annotations
from typing import Any

def error_payload(*, phase: str, kind: str, message: str, attempts: list[dict[str, Any]]) -> dict[str, object]:
    return {"phase": phase, "kind": kind, "message": message, "attempts": attempts}