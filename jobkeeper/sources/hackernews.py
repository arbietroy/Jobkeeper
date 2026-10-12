"""Hacker News monthly "Who is hiring?" and "Freelancer? Seeking freelancer?" threads."""

from __future__ import annotations

import time

import httpx

from ..models import Item, clean_text
from . import parse_date

ALGOLIA = "https://hn.algolia.com/api/v1"


def fetch(cfg: dict, http: httpx.Client) -> list[Item]:
    max_age = cfg["filters"].get("max_age_days", 7)
    since = int(time.time() - max_age * 86400)

    r = http.get(f"{ALGOLIA}/search_by_date", params={"tags": "story,author_whoishiring", "hitsPerPage": 6})
    r.raise_for_status()
    # Newest "Who is hiring?" thread and newest "Freelancer?" thread.
    threads = {}
    for h in r.json().get("hits", []):
        title = h.get("title", "").lower()
        kind = "hiring" if "who is hiring" in title else "freelance" if "freelancer" in title else None
        if kind and kind not in threads:
            threads[kind] = h

    items = []
    for thread in threads.values():
        story_id = thread["objectID"]
        freelance = "freelancer" in thread.get("title", "").lower()
        r = http.get(f"{ALGOLIA}/search_by_date", params={
            "tags": f"comment,story_{story_id}",
            "numericFilters": f"created_at_i>{since}",
            "hitsPerPage": 500,
        })
        r.raise_for_status()
        for c in r.json().get("hits", []):
            # Only top-level comments are actual posts.
            if str(c.get("parent_id")) != str(story_id):
                continue
            text = clean_text(c.get("comment_text"), limit=2000)
            if freelance and "seeking freelancer" not in text.lower():
                continue  # skip people advertising themselves
            first_line = text.split("|")[0][:80] if "|" in text else text[:80]
            items.append(Item(
                source="Hacker News" + (" (freelance)" if freelance else ""),
                title=first_line,
                url=f"https://news.ycombinator.com/item?id={c['objectID']}",
                company=first_line,
                description=text,
                posted_at=parse_date(c.get("created_at_i")),
            ))
    return items
