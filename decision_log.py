"""Append-only decision log: one entry per agent action.

Every entry always has the five required keys (action, sources, model, cost,
approved_by) plus timestamp and agent. Gate entries add "outcome".
"""
from __future__ import annotations

import datetime as dt
import json
import threading
from pathlib import Path

REQUIRED_KEYS = ("timestamp", "agent", "action", "sources", "model", "cost", "approved_by")


class DecisionLog:
    def __init__(self, path: Path | str):
        self.path = Path(path)
        self._lock = threading.Lock()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        if not self.path.exists():
            self.path.write_text("[]\n", encoding="utf-8")

    def read(self) -> list[dict]:
        try:
            return json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return []

    def append(self, agent: str, action: str, sources: list[str] | None = None, model: str | None = None,
               cost: float = 0, approved_by: str | None = None, **extra) -> dict:
        entry = {
            "timestamp": dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "agent": agent,
            "action": action,
            "sources": list(sources or []),
            "model": model,
            "cost": cost,
            "approved_by": approved_by,
        }
        entry.update({k: v for k, v in extra.items() if v is not None})
        with self._lock:
            entries = self.read()
            entries.append(entry)
            self.path.write_text(json.dumps(entries, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")
        return entry
