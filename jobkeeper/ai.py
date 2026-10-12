"""Claude reads every new opportunity, scores how well it fits you, and drafts a pitch for leads."""

from __future__ import annotations

import json
import logging

import anthropic

from .models import Item

log = logging.getLogger("jobkeeper")

FALLBACK_BETA = "server-side-fallback-2026-07-01"
BATCH_SIZE = 20

SYSTEM = """You screen opportunities for one freelancer and decide which are worth their time.

About the freelancer:
{profile}

Their preferences:
{preferences}

For each opportunity, return:
- score (0-100): how good a fit it is. 80+ = apply/pitch today, 60-79 = worth a look, below 40 = irrelevant.
  Penalise: wrong field, seniority far off, location they can't work from, scams, unpaid/"exposure" work,
  people advertising their own services, posts that are clearly expired.
- reason: one short sentence on why it fits or doesn't.
- pitch: for kind "lead" with score >= 60, a 2-3 sentence friendly opening message the freelancer could send
  (specific to that business, no placeholders). For jobs, a one-line tip on how to stand out. Otherwise "".
"""

SCHEMA = {
    "type": "object",
    "properties": {
        "results": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "id": {"type": "string"},
                    "score": {"type": "integer"},
                    "reason": {"type": "string"},
                    "pitch": {"type": "string"},
                },
                "required": ["id", "score", "reason", "pitch"],
                "additionalProperties": False,
            },
        }
    },
    "required": ["results"],
    "additionalProperties": False,
}


def _describe(item: Item) -> dict:
    return {
        "id": item.id,
        "kind": item.kind,
        "source": item.source,
        "title": item.title,
        "company": item.company,
        "location": item.location,
        "posted_days_ago": round(item.age_days(), 1) if item.age_days() is not None else None,
        "description": item.description[:1200],
    }


def score_items(cfg: dict, items: list[Item]) -> list[Item]:
    """Fill in score/reason/pitch on each item. Returns the items that were scored."""
    if not items:
        return []
    ai = cfg["ai"]
    profile = cfg["profile"]
    system = SYSTEM.format(
        profile=profile.get("about", "").strip(),
        preferences=profile.get("preferences", "").strip() or "(none given)",
    )
    client = anthropic.Anthropic()
    by_id = {item.id: item for item in items}
    scored: list[Item] = []

    for start in range(0, len(items), BATCH_SIZE):
        batch = items[start:start + BATCH_SIZE]
        try:
            response = client.beta.messages.create(
                model=ai.get("model", "claude-opus-5-5"),
                max_tokens=16000,
                betas=[FALLBACK_BETA],
                fallbacks="default",
                output_config={
                    "effort": ai.get("effort", "low"),
                    "format": {"type": "json_schema", "schema": SCHEMA},
                },
                # The system prompt is identical across batches and runs, so cache it.
                system=[{"type": "text", "text": system, "cache_control": {"type": "ephemeral"}}],
                messages=[{
                    "role": "user",
                    "content": "Score these opportunities:\n" + json.dumps([_describe(i) for i in batch], ensure_ascii=False),
                }],
            )
        except anthropic.RateLimitError:
            log.warning("AI scoring rate-limited; skipping remaining %d items this run", len(items) - start)
            break
        except anthropic.APIStatusError as e:
            log.warning("AI scoring failed for a batch (%s): %s", e.status_code, e.message)
            continue
        except anthropic.APIConnectionError as e:
            log.warning("AI scoring connection error: %s", e)
            continue

        if response.stop_reason == "refusal":
            log.warning("AI scoring: batch declined by the model; skipping it")
            continue
        text = next((b.text for b in response.content if b.type == "text"), "")
        try:
            results = json.loads(text)["results"]
        except (json.JSONDecodeError, KeyError, TypeError):
            log.warning("AI scoring: unparseable response (stop_reason=%s)", response.stop_reason)
            continue
        for r in results:
            item = by_id.get(r.get("id"))
            if item is None:
                continue
            item.score = max(0, min(100, int(r.get("score", 0))))
            item.reason = r.get("reason", "")
            item.pitch = r.get("pitch", "")
            scored.append(item)
    return scored
