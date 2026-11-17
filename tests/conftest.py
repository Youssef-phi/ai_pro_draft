import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tests"))

# Tests never touch a hosted provider or a real key.
for name in ("LLM_API_KEY", "NVIDIA_API_KEY", "LLM_PROVIDER", "LLM_MODEL", "PANEL_MODE", "DEBATE_ROUNDS",
             "WAITLIST_TARGET", "MIN_SOURCED_CLAIMS"):
    os.environ[name] = ""
