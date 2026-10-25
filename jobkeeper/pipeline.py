"""One full hunt: collect → dedupe → pre-filter → AI score → send to Telegram."""

from __future__ import annotations

import logging
import re

from . import ai, eligibility
from .config import env
from .models import Item
from .sources import collect, make_http
from .state import SeenStore
from .telegram import Telegram, format_item

log = logging.getLogger("jobkeeper")

# Sources whose results are already targeted, so the keyword pre-filter would only throw good items away.
PRETARGETED = {"Web search", "Google Maps"}


def _keyword_re(words: list[str]) -> re.Pattern | None:
    """Whole-word match, so "ai" matches "AI Engineer" but not "maintain"."""
    words = [w.strip().lower() for w in words if w.strip()]
    if not words:
        return None
    return re.compile(r"(?<![a-z0-9])(" + "|".join(re.escape(w) for w in words) + r")(?![a-z0-9])", re.I)


def _keyword_text(item: Item, where: str) -> str:
    # Matching the title (not the whole description) is what keeps random jobs out: almost every
    # description mentions "website" or "AI" somewhere. Hacker News posts have no real title.
    if where == "anywhere" or item.source.startswith("Hacker News"):
        return item.haystack()
    return f"{item.title} {item.extra.get('tags', '')}"


def prefilter(cfg: dict, items: list[Item], seen: SeenStore) -> list[Item]:
    f = cfg["filters"]
    include = _keyword_re(f.get("include_keywords") or [])
    exclude = _keyword_re(f.get("exclude_keywords") or [])
    where = f.get("match_keywords_in", "title")
    max_age = f.get("max_age_days", 7)
    entry_only = f.get("entry_level_only", False)
    must_be_eligible = f.get("require_nigeria_eligible", False)

    out, ids = [], set()
    dropped = {"old": 0, "keywords": 0, "seniority": 0, "location": 0}
    for item in items:
        if not item.url or item.id in ids or item.id in seen:
            continue
        ids.add(item.id)
        age = item.age_days()
        if age is not None and age > max_age:
            dropped["old"] += 1
            continue
        if exclude and exclude.search(item.haystack()):
            dropped["keywords"] += 1
            continue
        if item.kind == "job":
            if include and item.source not in PRETARGETED and not include.search(_keyword_text(item, where)):
                dropped["keywords"] += 1
                continue
            ok, why = eligibility.seniority(item)
            if entry_only and not ok:
                dropped["seniority"] += 1
                continue
            status, reason = eligibility.nigeria_eligibility(item)
            if must_be_eligible and status == eligibility.NO:
                dropped["location"] += 1
                continue
            item.extra["eligibility"] = status
            item.extra["eligibility_reason"] = reason
        out.append(item)
    log.info("pre-filter dropped: %s", ", ".join(f"{v} {k}" for k, v in dropped.items()))
    return out


def run(cfg: dict, dry_run: bool = False) -> list[Item]:
    seen = SeenStore()
    with make_http() as http:
        raw = collect(cfg, http)
    candidates = prefilter(cfg, raw, seen)
    log.info("collected %d, %d new after filtering", len(raw), len(candidates))

    # Newest first; cap how many go to the AI per run to keep costs predictable.
    candidates.sort(key=lambda i: (i.age_days() is None, i.age_days() or 0))
    candidates = candidates[: cfg["ai"].get("max_items_per_run", 120)]

    min_score = cfg["filters"].get("min_score", 65)
    if cfg["ai"].get("enabled", True) and env("ANTHROPIC_API_KEY"):
        scored = ai.score_items(cfg, candidates)
    else:
        # Unranked: send only what the rules could confirm a Nigerian can apply for;
        # "unclear" ones wait (unseen) until an AI key is added to judge them.
        log.warning("AI scoring disabled (no ANTHROPIC_API_KEY): sending only rule-confirmed matches, unranked")
        scored = []
        for item in candidates:
            if item.kind == "job" and item.extra.get("eligibility") != eligibility.YES:
                continue
            item.score = min_score
            scored.append(item)

    max_messages = cfg["telegram"].get("max_messages_per_run", 15)
    matches = sorted((i for i in scored if i.score >= min_score), key=lambda i: -i.score)
    to_send, overflow = matches[:max_messages], matches[max_messages:]
    log.info("%d scored, %d good matches, sending %d", len(scored), len(matches), len(to_send))

    if dry_run:
        for item in to_send:
            print(format_item(item), end="\n\n" + "─" * 40 + "\n\n")
        return to_send

    tg = Telegram()
    if to_send:
        jobs = sum(i.kind == "job" for i in to_send)
        tg.send(f"🔎 <b>Jobkeeper</b>: {len(to_send)} new — {jobs} job(s), {len(to_send) - jobs} lead(s)"
                + (f"\n({len(overflow)} more queued for next run)" if overflow else ""))
    for item in to_send:
        try:
            tg.send(format_item(item))
        except Exception as e:  # noqa: BLE001
            log.warning("could not send %s: %s", item.url, e)
            continue
        seen.add(item.id)

    # Low scorers are done with; overflow matches stay unseen so they're sent next run.
    overflow_ids = {i.id for i in overflow}
    for item in scored:
        if item.score < min_score and item.id not in overflow_ids:
            seen.add(item.id)
    seen.save()
    return to_send
