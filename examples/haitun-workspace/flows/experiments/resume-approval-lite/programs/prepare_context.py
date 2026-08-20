"""Load one batch's live standards and destination without revision hashing."""

from __future__ import annotations

import json
import os
import secrets
import sys
from collections.abc import Callable, Mapping
from datetime import datetime, timedelta, timezone
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

_API_ROOT = "https://open.feishu.cn/open-apis"
_DEFAULTS_PATH = "flows/workflows/resume-approval/resume-approval.defaults.json"
_DOCUMENTS = (
    ("resume_scoring", "resume_scoring_document_token"),
    ("role_information", "role_information_document_token"),
)
_FEISHU_KEYS = (
    "app_token",
    "base_url",
    "talent_pool_table_id",
    "user_key",
    "identity",
)
RequestJson = Callable[[str, str, dict[str, str] | None, dict[str, str] | None], dict[str, Any]]


def _inside(child: str, parent: str) -> bool:
    try:
        return os.path.commonpath((child, parent)) == parent
    except ValueError:
        return False


def _load_json(workspace_root: str, relative_path: str) -> Any:
    path = os.path.realpath(os.path.join(workspace_root, relative_path))
    if not _inside(path, workspace_root) or not os.path.isfile(path):
        raise FileNotFoundError(f"Required configuration is missing: {relative_path}")
    with open(path, encoding="utf-8") as source:
        return json.load(source)


def _default_request_json(
    method: str,
    url: str,
    headers: dict[str, str] | None = None,
    payload: dict[str, str] | None = None,
) -> dict[str, Any]:
    request_headers = {"Accept": "application/json", **(headers or {})}
    data = None
    if payload is not None:
        data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        request_headers["Content-Type"] = "application/json"
    request = Request(url, data=data, headers=request_headers, method=method)
    try:
        with urlopen(request, timeout=30) as response:
            result = json.loads(response.read().decode("utf-8"))
    except (HTTPError, URLError, TimeoutError, UnicodeDecodeError, json.JSONDecodeError) as error:
        raise RuntimeError("Feishu API request failed") from error
    if not isinstance(result, dict):
        raise RuntimeError("Feishu API returned a non-object response")
    return result


def _validate_resume_files(value: Any) -> list[Any]:
    if not isinstance(value, list) or not value:
        raise ValueError("resume_files must be a non-empty list")
    for index, item in enumerate(value):
        valid_string = isinstance(item, str) and bool(item.strip())
        valid_object = isinstance(item, dict) and isinstance(item.get("path"), str) and bool(item["path"].strip())
        if not valid_string and not valid_object:
            raise TypeError(f"resume_files[{index}] must be a path or path object")
    return value


def run(
    inputs: Mapping[str, Any],
    workspace_root: str | None = None,
    *,
    environment: Mapping[str, str] | None = None,
    request_json: RequestJson | None = None,
    batch_id: str | None = None,
) -> dict[str, Any]:
    """Return live source text once per batch and no content revision digest."""
    resume_files = _validate_resume_files(inputs.get("resume_files"))
    root = os.path.realpath(workspace_root or os.getcwd())
    defaults = _load_json(root, _DEFAULTS_PATH)
    if not isinstance(defaults, dict):
        raise TypeError("resume-approval defaults must be an object")

    feishu_config = defaults.get("feishu_config")
    if not isinstance(feishu_config, dict):
        raise TypeError("feishu_config must be an object")
    missing = [key for key in _FEISHU_KEYS if not feishu_config.get(key)]
    if missing:
        raise ValueError("feishu_config is incomplete: " + ", ".join(missing))

    env = os.environ if environment is None else environment
    app_id = env.get("PSI_FEISHU_APP_ID")
    app_secret = env.get("PSI_FEISHU_APP_SECRET")
    if not isinstance(app_id, str) or not app_id.strip():
        raise ValueError("PSI_FEISHU_APP_ID is required")
    if not isinstance(app_secret, str) or not app_secret.strip():
        raise ValueError("PSI_FEISHU_APP_SECRET is required")

    transport = request_json or _default_request_json
    authentication = transport(
        "POST",
        f"{_API_ROOT}/auth/v3/tenant_access_token/internal",
        None,
        {"app_id": app_id, "app_secret": app_secret},
    )
    tenant_token = authentication.get("tenant_access_token")
    if authentication.get("code") != 0 or not isinstance(tenant_token, str) or not tenant_token:
        raise RuntimeError("Feishu authentication failed")

    headers = {"Authorization": f"Bearer {tenant_token}"}
    documents: dict[str, dict[str, str]] = {}
    for purpose, token_key in _DOCUMENTS:
        token = defaults.get(token_key)
        if not isinstance(token, str) or not token.strip():
            raise ValueError(f"{token_key} is required")
        response = transport(
            "GET",
            f"{_API_ROOT}/docx/v1/documents/{token.strip()}/raw_content",
            headers,
            None,
        )
        data = response.get("data")
        content = data.get("content") if isinstance(data, dict) else None
        if response.get("code") != 0 or not isinstance(content, str) or not content.strip():
            raise RuntimeError(f"Required recruitment document is unavailable: {purpose}")
        documents[purpose] = {"purpose": purpose, "content": content}

    if batch_id is None:
        china_time = timezone(timedelta(hours=8))
        timestamp = datetime.now(china_time).strftime("%Y%m%d-%H%M%S")
        prefix = defaults.get("batch_prefix", "resume-lite")
        batch_id = f"{prefix}-lite-{timestamp}-{secrets.token_hex(3)}"

    return {
        "batch_context": {
            "schema_version": "lite-1.0",
            "batch_id": batch_id,
            "resume_count": len(resume_files),
            "scoring_document": documents["resume_scoring"],
            "role_document": documents["role_information"],
        },
        "feishu_config": {key: feishu_config[key] for key in feishu_config},
    }


def _load_inputs() -> dict[str, Any]:
    payload = json.load(sys.stdin)
    if not isinstance(payload, dict) or not isinstance(payload.get("inputs"), dict):
        raise TypeError("Program stdin must contain an inputs object")
    return payload["inputs"]


def main() -> None:
    if hasattr(sys.stdin, "reconfigure"):
        sys.stdin.reconfigure(encoding="utf-8", errors="strict")
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="strict")
    result = run(_load_inputs())
    sys.stdout.write(json.dumps(result, ensure_ascii=False, sort_keys=True, allow_nan=False))


if __name__ == "__main__":
    main()
