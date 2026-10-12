"""Load config.yaml and secrets from the environment."""

from __future__ import annotations

import os
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent


def load_config(path: str | os.PathLike | None = None) -> dict:
    path = Path(path or os.environ.get("JOBKEEPER_CONFIG", ROOT / "config.yaml"))
    with open(path, encoding="utf-8") as f:
        cfg = yaml.safe_load(f) or {}
    cfg.setdefault("profile", {})
    cfg.setdefault("filters", {})
    cfg.setdefault("ai", {})
    cfg.setdefault("sources", {})
    cfg.setdefault("telegram", {})
    return cfg


def env(name: str) -> str | None:
    value = os.environ.get(name, "").strip()
    return value or None
