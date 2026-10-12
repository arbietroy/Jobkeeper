"""Remembers which opportunities were already seen, so you never get the same one twice."""

from __future__ import annotations

import json
import time
from pathlib import Path

from .config import ROOT

DEFAULT_PATH = ROOT / "state" / "seen.json"
KEEP_DAYS = 60


class SeenStore:
    def __init__(self, path: Path = DEFAULT_PATH):
        self.path = Path(path)
        try:
            self.data: dict[str, float] = json.loads(self.path.read_text())
        except (FileNotFoundError, json.JSONDecodeError):
            self.data = {}

    def __contains__(self, item_id: str) -> bool:
        return item_id in self.data

    def add(self, item_id: str) -> None:
        self.data.setdefault(item_id, time.time())

    def save(self) -> None:
        cutoff = time.time() - KEEP_DAYS * 86400
        self.data = {k: v for k, v in self.data.items() if v >= cutoff}
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(json.dumps(self.data, indent=0, sort_keys=True))
