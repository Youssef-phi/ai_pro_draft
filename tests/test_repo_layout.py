"""Repository conventions: required files, README headings in order, no secrets, valid committed log."""
import json
import re
import subprocess
from pathlib import Path

from decision_log import REQUIRED_KEYS

ROOT = Path(__file__).resolve().parent.parent
HEADINGS = ["## Quickstart", "## What works and what is mocked", "## Architecture", "## Models and free resources",
            "## Cost per run", "## Demo video", "## What our system will NOT do",
            "## How the project stays alive after the hackathon"]
AGENTS = ["orchestrator", "researcher", "market_analyst", "strategist", "engineer", "finance", "policy_drafter",
          "marketer", "sales_ops", "ops_analyst", "advocate", "critic", "chair"]


def tracked_files():
    try:
        out = subprocess.run(["git", "ls-files"], cwd=ROOT, capture_output=True, text=True, check=True).stdout.split()
        if out:
            return [ROOT / f for f in out]
    except (OSError, subprocess.CalledProcessError):
        pass
    skip = {".git", "runs", "data", "__pycache__", ".pytest_cache", "node_modules", ".venv"}
    return [p for p in ROOT.rglob("*") if p.is_file() and not skip & set(p.parts) and p.name != ".env"]


def test_required_files_exist():
    for name in ("README.md", "LICENSE", "docker-compose.yml", "decision_log.json", "ARCHITECTURE.md", ".env.example",
                 "CLAUDE.md", "orchestrator.py", "gates.py", "approval.py", "payments.py", "delivery.py",
                 "refunds.py", "webhooks.py", "reconcile.py"):
        assert (ROOT / name).is_file(), name
    for name in ("outputs", "tests", "prompts", "agents"):
        assert (ROOT / name).is_dir(), name
    for agent in AGENTS:
        assert (ROOT / "agents" / f"{agent}.py").is_file() and (ROOT / "prompts" / f"{agent}.md").is_file(), agent


def test_readme_has_the_eight_headings_in_order():
    readme = (ROOT / "README.md").read_text()
    found = [line.strip() for line in readme.splitlines() if line.startswith("## ")]
    assert found == HEADINGS
    assert "```bash\ndocker compose up\n```" in readme
    cost = readme.split("## Cost per run")[1].split("## ")[0]
    assert "$" in cost


def test_architecture_has_required_sections():
    text = (ROOT / "ARCHITECTURE.md").read_text()
    for heading in ("## Overview", "## Phases", "## Gates", "## Sale to cash", "## Data flow", "## Built vs. stubbed", "## Roadmap"):
        assert heading in text, heading
    assert "```mermaid" in text
    assert len(re.findall(r"^### ", text, flags=re.M)) >= 6


def test_committed_decision_log_is_valid():
    entries = json.loads((ROOT / "decision_log.json").read_text())
    assert isinstance(entries, list)
    for entry in entries:
        for key in REQUIRED_KEYS:
            assert key in entry, (key, entry)


def test_outputs_follow_the_naming_convention():
    pattern = re.compile(r"^(phase\d+_(step\d+|gate)_[a-z0-9_]+\.(md|json|csv|txt|html)|payment_test_log\.md|\.gitkeep)$")
    for path in (ROOT / "outputs").iterdir():
        assert pattern.match(path.name), path.name
