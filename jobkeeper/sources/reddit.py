"""Reddit: hiring subreddits (jobs) and searches for people asking for a website (leads)."""

from __future__ import annotations

import logging
import time
from urllib.parse import quote_plus

import httpx

from ..models import Item
from .rss import parse_feed

log = logging.getLogger("jobkeeper")

DEFAULT_JOB_SUBS = ["forhire", "hiring", "jobbit", "freelance_forhire", "remotejs", "WebDeveloperJobs"]
DEFAULT_LEAD_SEARCHES = [
    {"sub": "smallbusiness", "query": '"need a website" OR "website for my business" OR "build a website"'},
    {"sub": "Entrepreneur", "query": '"need a website" OR "looking for a web designer" OR "website developer"'},
    {"sub": "startups", "query": '"looking for a developer" OR "need a website"'},
    {"sub": "all", "query": '"looking for a web designer" OR "need someone to build a website"'},
]


def _get_feed(http: httpx.Client, url: str) -> bytes | None:
    """Fetch one feed; Reddit rate-limits hard, so skip just this feed on failure instead of all of Reddit."""
    time.sleep(2)
    try:
        r = http.get(url)
        r.raise_for_status()
        return r.content
    except httpx.HTTPError as e:
        log.info("reddit: skipped %s (%s)", url, e)
        return None


def fetch(cfg: dict, http: httpx.Client) -> list[Item]:
    rcfg = cfg["sources"]["reddit"]
    items = []
    for sub in rcfg.get("job_subreddits") or DEFAULT_JOB_SUBS:
        content = _get_feed(http, f"https://www.reddit.com/r/{sub}/new/.rss?limit=50")
        for item in parse_feed(content, f"Reddit r/{sub}") if content else []:
            # r/forhire mixes [Hiring] and [For Hire]; only keep people hiring.
            if "[for hire]" in item.title.lower():
                continue
            items.append(item)

    for s in rcfg.get("lead_searches") or DEFAULT_LEAD_SEARCHES:
        sub, query = s["sub"], s["query"]
        url = (f"https://www.reddit.com/r/{sub}/search.rss?q={quote_plus(query)}"
               f"&restrict_sr={'0' if sub == 'all' else '1'}&sort=new&t=week")
        content = _get_feed(http, url)
        if content:
            items.extend(parse_feed(content, f"Reddit r/{sub}", kind="lead"))
    return items
