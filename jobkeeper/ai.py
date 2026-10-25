"""Claude reads every new opportunity, scores how well it fits you, and drafts a pitch for leads."""

from __future__ import annotations

import json
import logging

import anthropic

from .models import Item

log = logging.getLogger("jobkeeper")

FALLBACK_BETA = "server-side-fallback-2026-07-01"
BATCH_SIZE = 20

SYSTEM = """You screen opportunities for one job seeker and only pass on ones they can realistically apply for
and get. Be strict: sending them a job they can't get wastes their time.

About the job seeker:
{profile}

Their preferences:
{preferences}

For each opportunity, judge three things.

1. eligible — can someone living in Nigeria, with a Nigerian passport and no visa or foreign work permit, be
   hired for this? Read the location and the whole description.
   - "yes": open worldwide / anywhere / Africa / EMEA / Nigeria, or hiring contractors globally, or the time zone
     fits WAT (UTC+1) with no country restriction.
   - "no": limited to other countries or regions (US, UK, EU, Canada, LATAM, India...), requires work
     authorization, citizenship, residency, a security clearance or W-2, or is on-site outside Nigeria.
   - "unclear": the post doesn't say. Never guess "yes".
2. level — is it realistic for an entry-level / junior candidate? Senior, lead, manager roles, or ones asking for
   3+ years of experience are not.
3. fit — does the work match what they do and want (see profile)? A role that merely mentions AI or websites
   in passing is not a fit.

Return for each:
- score (0-100): 80+ = strong match they can apply to today, 65-79 = decent, below 50 = skip.
  Score 0 if eligible is "no". Cap at 40 if the level is clearly too senior. Cap at 60 if eligible is "unclear".
  Score 0 for scams, unpaid / "exposure" work, pay-to-apply, and people advertising their own services.
- eligible: "yes", "no" or "unclear".
- eligibility_reason: a few words quoting or paraphrasing the post (e.g. "Remote — worldwide", "US only").
- reason: one short sentence on why it fits or doesn't.
- requirements: for jobs, a short "Have: … · Gap: …" comparing the post's key requirements to the profile.
  For leads, "".
- pitch: for kind "lead" with score >= 60, a 2-3 sentence friendly opening message (specific, no placeholders).
  For jobs, a one-line tip on how to stand out. Otherwise "".
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
                    "eligible": {"type": "string", "enum": ["yes", "no", "unclear"]},
                    "eligibility_reason": {"type": "string"},
                    "reason": {"type": "string"},
                    "requirements": {"type": "string"},
                    "pitch": {"type": "string"},
                },
                "required": ["id", "score", "eligible", "eligibility_reason", "reason", "requirements", "pitch"],
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
        "rule_check": item.extra.get("eligibility_reason", ""),
        "posted_days_ago": round(item.age_days(), 1) if item.age_days() is not None else None,
        "description": item.description[:2500],
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
            if item.kind == "job":
                item.extra["eligibility"] = r.get("eligible", "unclear")
                item.extra["eligibility_reason"] = r.get("eligibility_reason", "")
                item.extra["requirements"] = r.get("requirements", "")
                if item.extra["eligibility"] == "no":
                    item.score = 0
            scored.append(item)
    return scored
