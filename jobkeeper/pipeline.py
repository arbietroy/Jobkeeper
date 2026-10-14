"""One full hunt: collect → dedupe → pre-filter → AI score → send to Telegram."""

from __future__ import annotations

import logging

from . import ai
from .config import env
from .models import Item
from .sources import collect, make_http
from .state import SeenStore
from .telegram import Telegram, format_item

log = logging.getLogger("jobkeeper")

# Sources whose results are already targeted, so the keyword pre-filter would only throw good items away.
PRETARGETED = {"Web search", "Google Maps"}


def prefilter(cfg: dict, items: list[Item], seen: SeenStore) -> list[Item]:
    f = cfg["filters"]
    include = [k.lower() for k in f.get("include_keywords") or []]
    exclude = [k.lower() for k in f.get("exclude_keywords") or []]
    max_age = f.get("max_age_days", 7)

    out, ids = [], set()
    for item in items:
        if not item.url or item.id in ids or item.id in seen:
            continue
        ids.add(item.id)
        age = item.age_days()
        if age is not None and age > max_age:
            continue
        text = item.haystack()
        if any(k in text for k in exclude):
            continue
        if include and item.kind == "job" and item.source not in PRETARGETED and not any(k in text for k in include):
            continue
        out.append(item)
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
        # Unranked: let every keyword match through rather than marking them all as rejected.
        log.warning("AI scoring disabled (no ANTHROPIC_API_KEY): sending keyword matches unranked")
        for item in candidates:
            item.score = min_score
        scored = candidates

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
