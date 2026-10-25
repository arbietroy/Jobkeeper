"""Rule-based checks that run before any AI: can someone in Nigeria apply, and is it entry-level?

These are deliberately simple and conservative. They catch the obvious cases ("USA only",
"Senior", "must be authorized to work in the US") for free, so the AI (or you) only sees
jobs that pass. Anything ambiguous is marked "unclear" and left for the AI to judge.
"""

from __future__ import annotations

import re

from .models import Item

YES, NO, UNCLEAR = "yes", "no", "unclear"

# Location text that means "a Nigerian can apply".
OPEN_LOCATION = re.compile(
    r"worldwide|anywhere|global|work from anywhere|all countries|international|"
    r"africa|emea|nigeria|lagos|abuja|\bwat\b|\bgmt\s*\+\s*1\b|\butc\s*\+\s*1\b",
    re.I,
)
# Phrases in a description that mean the same. Stricter than the location list: "global" alone in
# a description usually describes the company, not who can apply.
OPEN_TEXT = re.compile(
    r"work from anywhere|anywhere in the world|(remote|open to (candidates|applicants|everyone)|hire|hiring) "
    r"(from )?(worldwide|globally|anywhere)|\bafrica\b|\bnigeria\b|\bemea\b|any (country|timezone|time zone)",
    re.I,
)
# Location text that carries no restriction either way.
NEUTRAL_LOCATION = re.compile(r"^\s*(100%\s*)?(fully\s+)?remote(\s*job|\s*first)?\s*$|^\s*$", re.I)

# Phrases in a description that shut out applicants outside a specific country.
BLOCKERS = re.compile(
    r"(authori[sz]ed|eligible|legally able|right) to work in (the )?(us|u\.s\.|united states|uk|united kingdom|"
    r"canada|eu|europe|australia|germany)"
    r"|us work authori[sz]ation|u\.s\. citizen|us citizen(ship)?|green card|security clearance|\bw-?2\b"
    r"|(us|u\.s\.|usa)[- ]based (candidates|applicants) only|(us|usa|uk|eu|canada)[- ]only"
    r"|must (be )?(located|based|reside|live) in (the )?(us|u\.s\.|usa|united states|uk|canada|europe|eu|"
    r"australia|india|germany|latam|latin america)"
    r"|remote \((us|usa|uk|eu|canada|europe)[^)]*\)"
    r"|we are unable to (hire|employ|sponsor) (outside|in countries)",
    re.I,
)
FOREIGN_ONLY_LOCATION = re.compile(
    r"\b(us|usa|u\.s\.|united states|canada|uk|united kingdom|europe|eu|latam|latin america|americas|"
    r"north america|india|australia|apac|asia|germany|france|spain|netherlands|poland|brazil|mexico)\b",
    re.I,
)

SENIOR_TITLE = re.compile(
    r"\b(senior|sr\.?|staff|principal|lead|head of|director|vp|vice president|architect|chief|"
    r"manager|expert|ii|iii|iv)\b",
    re.I,
)
YEARS_EXPERIENCE = re.compile(
    r"\b(\d{1,2})\s*\+?\s*(?:(?:-|–|to)\s*\d{1,2}\s*\+?\s*)?years?(?:'|’)?\s+(?:of\s+)?"
    r"(?:[\w-]+\s+){0,2}experience",
    re.I,
)
MAX_YEARS_FOR_ENTRY = 3  # "3+ years" / "3-5 years" is not entry-level
ENTRY_LEVEL = re.compile(r"\b(junior|jr\.?|entry[- ]level|intern(ship)?|graduate|trainee|apprentice|0-2 years|no experience)\b", re.I)


def nigeria_eligibility(item: Item) -> tuple[str, str]:
    """Return (yes/no/unclear, short reason)."""
    location = item.location or ""
    text = f"{item.title} {item.description}"

    blocker = BLOCKERS.search(text)
    if blocker:
        return NO, f'says "{blocker.group(0)}"'
    if OPEN_LOCATION.search(location):
        return YES, f"open to {location.strip()}"
    if not NEUTRAL_LOCATION.match(location) and FOREIGN_ONLY_LOCATION.search(location):
        return NO, f"limited to {location.strip()}"
    if OPEN_TEXT.search(text):
        return YES, "post says it's open worldwide / to Africa"
    return UNCLEAR, "location not stated"


def seniority(item: Item) -> tuple[bool, str]:
    """Return (ok_for_entry_level, reason)."""
    if m := SENIOR_TITLE.search(item.title):
        return False, f'title says "{m.group(0)}"'
    if ENTRY_LEVEL.search(item.title):
        return True, "entry-level title"
    for m in YEARS_EXPERIENCE.finditer(item.description):
        if int(m.group(1)) >= MAX_YEARS_FOR_ENTRY:
            return False, f'asks for "{m.group(0)}"'
    return True, ""
