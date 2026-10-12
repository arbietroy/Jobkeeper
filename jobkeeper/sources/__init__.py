"""Opportunity sources.

Every source is a function ``fetch(cfg, http) -> list[Item]``. A failing source
is logged and skipped so one broken site never stops the whole run.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime

import httpx

from ..models import Item

log = logging.getLogger("jobkeeper")

USER_AGENT = "Mozilla/5.0 (compatible; Jobkeeper/1.0; +https://github.com/arbietroy/jobkeeper)"


def make_http() -> httpx.Client:
    return httpx.Client(
        headers={"User-Agent": USER_AGENT, "Accept": "application/json, application/xml, text/xml, */*"},
        timeout=25,
        follow_redirects=True,
    )


def parse_date(value) -> datetime | None:
    """Best-effort parse of the many date formats job boards use."""
    if value is None or value == "":
        return None
    try:
        if isinstance(value, (int, float)):
            # Some APIs use milliseconds.
            if value > 1e12:
                value /= 1000
            return datetime.fromtimestamp(value, tz=timezone.utc)
        text = str(value).strip()
        if text.isdigit():
            return parse_date(int(text))
        try:
            dt = datetime.fromisoformat(text.replace("Z", "+00:00"))
        except ValueError:
            dt = parsedate_to_datetime(text)
        return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)
    except (ValueError, TypeError, OverflowError):
        return None


def collect(cfg: dict, http: httpx.Client) -> list[Item]:
    from . import boards, hackernews, places, reddit, rss, websearch

    registry = {
        "remotive": boards.remotive,
        "remoteok": boards.remoteok,
        "weworkremotely": boards.weworkremotely,
        "jobicy": boards.jobicy,
        "himalayas": boards.himalayas,
        "arbeitnow": boards.arbeitnow,
        "hackernews": hackernews.fetch,
        "reddit": reddit.fetch,
        "rss": rss.fetch,
        "google_places": places.fetch,
        "web_search": websearch.fetch,
    }
    sources_cfg = cfg.get("sources", {})
    items: list[Item] = []
    for name, fn in registry.items():
        scfg = sources_cfg.get(name) or {}
        if not scfg.get("enabled", False):
            continue
        try:
            found = fn(cfg, http)
            log.info("%-15s %4d items", name, len(found))
            items.extend(found)
        except Exception as e:  # noqa: BLE001 - one bad source must not kill the run
            log.warning("%-15s FAILED: %s", name, e)
    return items
