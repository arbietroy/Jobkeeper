"""Shared data types."""

from __future__ import annotations

import hashlib
import html
import re
from dataclasses import dataclass, field
from datetime import datetime, timezone

_TAG_RE = re.compile(r"<[^>]+>")
_WS_RE = re.compile(r"\s+")


def clean_text(text: str | None, limit: int = 1500) -> str:
    """Strip HTML tags and collapse whitespace."""
    if not text:
        return ""
    text = html.unescape(_TAG_RE.sub(" ", text))
    text = _WS_RE.sub(" ", text).strip()
    return text[:limit]


@dataclass
class Item:
    """A single opportunity: a job post or a lead (someone who needs a website)."""

    source: str
    title: str
    url: str
    kind: str = "job"  # "job" or "lead"
    company: str = ""
    location: str = ""
    description: str = ""
    posted_at: datetime | None = None
    extra: dict = field(default_factory=dict)

    # Filled in by the AI step.
    score: int = 0
    reason: str = ""
    pitch: str = ""

    @property
    def id(self) -> str:
        key = (self.url or f"{self.source}:{self.title}:{self.company}").strip().lower()
        return hashlib.sha1(key.encode()).hexdigest()[:16]

    def age_days(self) -> float | None:
        if not self.posted_at:
            return None
        posted = self.posted_at
        if posted.tzinfo is None:
            posted = posted.replace(tzinfo=timezone.utc)
        return (datetime.now(timezone.utc) - posted).total_seconds() / 86400

    def haystack(self) -> str:
        return f"{self.title} {self.company} {self.location} {self.description}".lower()
