"""No API key may ever appear in a tracked file. .env stays untracked; .env.example holds placeholders."""
import re
from pathlib import Path

from test_repo_layout import tracked_files

ROOT = Path(__file__).resolve().parent.parent


def test_no_secrets_in_tracked_files():
    pattern = re.compile(r"sk-hc-v1-[0-9a-fA-F]{16,}|nvapi-[A-Za-z0-9_\-]{20,}")
    for path in tracked_files():
        try:
            text = path.read_text(encoding="utf-8")
        except (UnicodeDecodeError, OSError):
            continue
        assert not pattern.search(text), f"possible API key in {path.relative_to(ROOT)}"


def test_env_file_is_ignored_and_example_has_placeholders_only():
    ignore = (ROOT / ".gitignore").read_text().splitlines()
    assert ".env" in ignore
    example = (ROOT / ".env.example").read_text()
    assert "LLM_API_KEY=sk-hc-v1-your-key-here" in example
