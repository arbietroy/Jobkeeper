"""The "nook and cranny" hunter: Claude searches the open web for you.

Job sites like LinkedIn, X/Twitter, Instagram and Facebook have no free API and
block scrapers, but their public posts are indexed by search engines. Claude uses
its web search tool to run many targeted searches (hiring posts, "need a website"
posts, forum threads, niche job boards) and returns what it found as structured data.
"""

from __future__ import annotations

import json
import logging
import re
from datetime import date

import anthropic
import httpx

from ..models import Item, clean_text
from . import parse_date

log = logging.getLogger("jobkeeper")

FALLBACK_BETA = "server-side-fallback-2026-07-01"

PROMPT = """You are a relentless opportunity hunter working for one job seeker. Today is {today}.

## Who you're hunting for
{profile}

## Their preferences
{preferences}

## Your job
Use web search to find FRESH opportunities (posted in roughly the last {max_age} days) that this person can
actually apply for and get. Dig beyond the big job boards: public LinkedIn posts ("hiring", "we're looking
for"), X/Twitter posts, Reddit and forum threads, n8n / Make / Zapier community job boards, Wellfound and
startup careers pages, Africa-focused and Nigerian job boards (Jobberman, MyJobMag, Hot Nigerian Jobs),
remote boards that hire worldwide, and Upwork-style agencies posting contract roles.

Two kinds of opportunity:
- "job": someone is hiring (full-time, part-time, contract, internship, freelance gig).
- "lead": a person or business that clearly needs the services in the profile but hasn't posted a formal
  job — someone this person could pitch.

Hard requirements for every "job" you return:
- A person living in Nigeria with no visa or foreign work permit can be hired: the post says worldwide,
  anywhere, Africa, EMEA or Nigeria, or hires contractors globally. Skip anything limited to the US, UK, EU,
  Canada, etc., or needing work authorization, citizenship or residency elsewhere. If the post doesn't say,
  only include it when the company is known to hire globally, and say so in the summary.
- Entry-level or junior is realistic: skip senior, lead and manager roles and ones asking for 3+ years.

Suggested searches to start with (adapt and add your own; vary sites and phrasing):
{queries}

Rules:
- Only include items with a real, specific URL you actually saw in search results. Never invent links.
- Skip expired posts, aggregator spam, pay-to-apply schemes, and people advertising their own services.
- Prefer quality over quantity; up to {max_results} items.

When you are done searching, reply with ONLY a JSON array (no prose) in this shape:
[{{"kind": "job" | "lead", "title": "...", "company": "...", "location": "...", "url": "https://...",
  "posted": "YYYY-MM-DD or empty", "summary": "1-2 sentences: what they need, who can apply, why it fits"}}]
"""

def parse_results(text: str) -> list[dict]:
    """Pull the JSON array out of Claude's final message (tolerates code fences or stray prose)."""
    text = text.strip()
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?\s*|\s*```$", "", text)
    start, end = text.find("["), text.rfind("]")
    for candidate in (text, text[start:end + 1] if 0 <= start < end else ""):
        try:
            data = json.loads(candidate)
        except json.JSONDecodeError:
            continue
        if isinstance(data, list):
            return [d for d in data if isinstance(d, dict) and d.get("url")]
    return []


def fetch(cfg: dict, http: httpx.Client) -> list[Item]:
    wcfg = cfg["sources"]["web_search"]
    ai = cfg["ai"]
    queries = "\n".join(f"- {q}" for q in wcfg.get("queries") or [])
    prompt = PROMPT.format(
        today=date.today().isoformat(),
        profile=cfg["profile"].get("about", "").strip(),
        preferences=cfg["profile"].get("preferences", "").strip() or "(none given)",
        max_age=cfg["filters"].get("max_age_days", 7),
        queries=queries or "- (choose your own)",
        max_results=wcfg.get("max_results", 25),
    )

    client = anthropic.Anthropic()
    messages = [{"role": "user", "content": prompt}]
    tools = [{"type": "web_search_20260209", "name": "web_search", "max_uses": wcfg.get("max_searches", 20)}]

    response = None
    for _ in range(6):  # resume server-tool turns that pause
        with client.beta.messages.stream(
            model=ai.get("model", "claude-opus-5-5"),
            max_tokens=32000,
            betas=[FALLBACK_BETA],
            fallbacks="default",
            output_config={"effort": wcfg.get("effort", "medium")},
            tools=tools,
            messages=messages,
        ) as stream:
            response = stream.get_final_message()
        if response.stop_reason != "pause_turn":
            break
        messages.append({"role": "assistant", "content": response.content})

    if response is None or response.stop_reason == "refusal":
        log.warning("web_search: model declined the request")
        return []

    text = "".join(b.text for b in response.content if b.type == "text")
    results = parse_results(text)
    if not results:
        log.warning("web_search: could not parse results: %s", text[:300])

    return [
        Item(
            source="Web search",
            kind="lead" if r.get("kind") == "lead" else "job",
            title=clean_text(r.get("title"), limit=200),
            url=r["url"],
            company=r.get("company", ""),
            location=r.get("location", ""),
            description=clean_text(r.get("summary")),
            posted_at=parse_date(r.get("posted")),
        )
        for r in results
    ]
