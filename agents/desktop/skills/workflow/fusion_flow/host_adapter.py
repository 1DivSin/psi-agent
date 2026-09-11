"""Host integration seams for embedding FusionFlow in non-Haitun agents."""
from __future__ import annotations
import os
from pathlib import Path
WORKSPACE_ENV = "PSI_WORKFLOW_WORKSPACE"
TOOLS_ENV = "PSI_WORKFLOW_TOOLS_DIR"
def workspace_dir(default: Path) -> Path:
    value = os.environ.get(WORKSPACE_ENV, "").strip()
    return Path(value).expanduser() if value else default
def tools_dir(default: Path) -> Path:
    value = os.environ.get(TOOLS_ENV, "").strip()
    return Path(value).expanduser() if value else default