"""Job boards with free public APIs / feeds."""

from __future__ import annotations

from urllib.parse import quote_plus

import feedparser
import httpx

from ..models import Item, clean_text
from . import parse_date


def _as_list(value) -> list[str]:
    if not value:
        return []
    return [str(v) for v in value] if isinstance(value, list) else [str(value)]


def _terms(cfg: dict) -> list[str]:
    return cfg["profile"].get("search_terms") or ["web developer"]


def remotive(cfg: dict, http: httpx.Client) -> list[Item]:
    items = []
    for term in _terms(cfg):
        r = http.get(f"https://remotive.com/api/remote-jobs?search={quote_plus(term)}&limit=50")
        r.raise_for_status()
        for j in r.json().get("jobs", []):
            items.append(Item(
                source="Remotive",
                title=j.get("title", ""),
                url=j.get("url", ""),
                company=j.get("company_name", ""),
                location=j.get("candidate_required_location", "") or "Remote",
                description=clean_text(j.get("description")),
                posted_at=parse_date(j.get("publication_date")),
                extra={"salary": j.get("salary", "")},
            ))
    return items


def remoteok(cfg: dict, http: httpx.Client) -> list[Item]:
    r = http.get("https://remoteok.com/api")
    r.raise_for_status()
    items = []
    for j in r.json():
        if not isinstance(j, dict) or "position" not in j:
            continue  # first element is a legal notice
        items.append(Item(
            source="RemoteOK",
            title=j.get("position", ""),
            url=j.get("url") or f"https://remoteok.com/remote-jobs/{j.get('slug', j.get('id'))}",
            company=j.get("company", ""),
            location=j.get("location", "") or "Remote",
            description=clean_text(j.get("description")),
            posted_at=parse_date(j.get("epoch") or j.get("date")),
            extra={"tags": " ".join(j.get("tags") or [])},
        ))
    return items


WWR_FEEDS = [
    "https://weworkremotely.com/categories/remote-full-stack-programming-jobs.rss",
    "https://weworkremotely.com/categories/remote-front-end-programming-jobs.rss",
    "https://weworkremotely.com/categories/remote-design-jobs.rss",
]


def weworkremotely(cfg: dict, http: httpx.Client) -> list[Item]:
    feeds = (cfg["sources"].get("weworkremotely") or {}).get("feeds") or WWR_FEEDS
    items = []
    for feed_url in feeds:
        r = http.get(feed_url)
        r.raise_for_status()
        for e in feedparser.parse(r.content).entries:
            company, _, title = e.get("title", "").partition(": ")
            if not title:
                company, title = "", company
            items.append(Item(
                source="WeWorkRemotely",
                title=title,
                url=e.get("link", ""),
                company=company,
                location=e.get("region", "") or "Remote",
                description=clean_text(e.get("summary")),
                posted_at=parse_date(e.get("published")),
            ))
    return items


def jobicy(cfg: dict, http: httpx.Client) -> list[Item]:
    items = []
    for term in _terms(cfg):
        r = http.get(f"https://jobicy.com/api/v2/remote-jobs?count=50&tag={quote_plus(term)}")
        r.raise_for_status()
        for j in r.json().get("jobs", []) or []:
            items.append(Item(
                source="Jobicy",
                title=j.get("jobTitle", ""),
                url=j.get("url", ""),
                company=j.get("companyName", ""),
                location=j.get("jobGeo", "") or "Remote",
                description=clean_text(j.get("jobExcerpt") or j.get("jobDescription")),
                posted_at=parse_date(j.get("pubDate")),
            ))
    return items


def himalayas(cfg: dict, http: httpx.Client) -> list[Item]:
    r = http.get("https://himalayas.app/jobs/api?limit=100")
    r.raise_for_status()
    items = []
    for j in r.json().get("jobs", []):
        locations = j.get("locationRestrictions") or []
        items.append(Item(
            source="Himalayas",
            title=j.get("title", ""),
            url=j.get("applicationLink") or j.get("guid", ""),
            company=j.get("companyName", ""),
            location=", ".join(locations) if locations else "Remote (worldwide)",
            description=clean_text(j.get("excerpt") or j.get("description")),
            posted_at=parse_date(j.get("pubDate")),
            extra={"tags": " ".join(_as_list(j.get("categories")) + _as_list(j.get("seniority")))},
        ))
    return items


def arbeitnow(cfg: dict, http: httpx.Client) -> list[Item]:
    r = http.get("https://www.arbeitnow.com/api/job-board-api")
    r.raise_for_status()
    items = []
    for j in r.json().get("data", []):
        items.append(Item(
            source="Arbeitnow",
            title=j.get("title", ""),
            url=j.get("url", ""),
            company=j.get("company_name", ""),
            location=("Remote" if j.get("remote") else "") or j.get("location", ""),
            description=clean_text(j.get("description")),
            posted_at=parse_date(j.get("created_at")),
        ))
    return items
