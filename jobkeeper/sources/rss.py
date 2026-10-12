"""Any extra RSS/Atom feeds you add in config.yaml.

This is how you plug in sources that have no public API. Services like
rss.app, RSS.app, FetchRSS or Zapier can turn LinkedIn job searches, X/Twitter
searches, Instagram hashtags and Facebook pages into RSS feeds — paste those URLs
under ``sources.rss.feeds``.
"""

from __future__ import annotations

import feedparser
import httpx

from ..models import Item, clean_text
from . import parse_date


def parse_feed(content: bytes, name: str, kind: str = "job") -> list[Item]:
    items = []
    for e in feedparser.parse(content).entries:
        items.append(Item(
            source=name,
            kind=kind,
            title=clean_text(e.get("title"), limit=200),
            url=e.get("link", ""),
            company=e.get("author", ""),
            description=clean_text(e.get("summary") or e.get("description")),
            posted_at=parse_date(e.get("published") or e.get("updated")),
        ))
    return items


def fetch(cfg: dict, http: httpx.Client) -> list[Item]:
    items = []
    for feed in cfg["sources"]["rss"].get("feeds") or []:
        if isinstance(feed, str):
            feed = {"url": feed}
        r = http.get(feed["url"])
        r.raise_for_status()
        items.extend(parse_feed(r.content, feed.get("name", "RSS"), feed.get("kind", "job")))
    return items
