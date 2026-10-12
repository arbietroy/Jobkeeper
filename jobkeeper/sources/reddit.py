"""Reddit: hiring subreddits (jobs) and searches for people asking for a website (leads)."""

from __future__ import annotations

from urllib.parse import quote_plus

import httpx

from ..models import Item
from .rss import parse_feed

DEFAULT_JOB_SUBS = ["forhire", "hiring", "jobbit", "freelance_forhire", "remotejs", "WebDeveloperJobs"]
DEFAULT_LEAD_SEARCHES = [
    {"sub": "smallbusiness", "query": '"need a website" OR "website for my business" OR "build a website"'},
    {"sub": "Entrepreneur", "query": '"need a website" OR "looking for a web designer" OR "website developer"'},
    {"sub": "startups", "query": '"looking for a developer" OR "need a website"'},
    {"sub": "all", "query": '"looking for a web designer" OR "need someone to build a website"'},
]


def fetch(cfg: dict, http: httpx.Client) -> list[Item]:
    rcfg = cfg["sources"]["reddit"]
    items = []
    for sub in rcfg.get("job_subreddits") or DEFAULT_JOB_SUBS:
        r = http.get(f"https://www.reddit.com/r/{sub}/new/.rss?limit=50")
        r.raise_for_status()
        for item in parse_feed(r.content, f"Reddit r/{sub}"):
            # r/forhire mixes [Hiring] and [For Hire]; only keep people hiring.
            if "[for hire]" in item.title.lower():
                continue
            items.append(item)

    for s in rcfg.get("lead_searches") or DEFAULT_LEAD_SEARCHES:
        sub, query = s["sub"], s["query"]
        url = (f"https://www.reddit.com/r/{sub}/search.rss?q={quote_plus(query)}"
               f"&restrict_sr={'0' if sub == 'all' else '1'}&sort=new&t=week")
        r = http.get(url)
        r.raise_for_status()
        items.extend(parse_feed(r.content, f"Reddit r/{sub}", kind="lead"))
    return items

