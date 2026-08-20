import sys
from pathlib import Path

FUSION_FLOW_ROOT = Path(__file__).resolve().parents[4] / "skills" / "workflow"
sys.path.insert(0, str(FUSION_FLOW_ROOT))
