"""Google Maps businesses that have NO website (or only a social page) — prime pitch targets.

Needs a GOOGLE_MAPS_API_KEY with the "Places API (New)" enabled.
"""

from __future__ import annotations

import httpx

from ..config import env
from ..models import Item

SEARCH_URL = "https://places.googleapis.com/v1/places:searchText"
FIELDS = ",".join(f"places.{f}" for f in [
    "id", "displayName", "formattedAddress", "websiteUri", "nationalPhoneNumber",
    "internationalPhoneNumber", "googleMapsUri", "rating", "userRatingCount", "primaryTypeDisplayName",
])
SOCIAL_ONLY = ("facebook.com", "instagram.com", "linktr.ee", "wa.me", "whatsapp.com", "tiktok.com", "x.com", "twitter.com")


def needs_website(website: str | None) -> bool:
    if not website:
        return True
    return any(domain in website.lower() for domain in SOCIAL_ONLY)


def fetch(cfg: dict, http: httpx.Client) -> list[Item]:
    key = env("GOOGLE_MAPS_API_KEY")
    if not key:
        raise RuntimeError("GOOGLE_MAPS_API_KEY is not set")
    pcfg = cfg["sources"]["google_places"]
    min_reviews = pcfg.get("min_reviews", 5)

    items = []
    for query in pcfg.get("queries") or []:
        r = http.post(
            SEARCH_URL,
            headers={"X-Goog-Api-Key": key, "X-Goog-FieldMask": FIELDS},
            json={"textQuery": query, "pageSize": 20},
        )
        r.raise_for_status()
        for p in r.json().get("places", []):
            website = p.get("websiteUri")
            reviews = p.get("userRatingCount") or 0
            # Established (has reviews) but no real website = good lead.
            if not needs_website(website) or reviews < min_reviews:
                continue
            name = (p.get("displayName") or {}).get("text", "")
            category = (p.get("primaryTypeDisplayName") or {}).get("text", "")
            phone = p.get("internationalPhoneNumber") or p.get("nationalPhoneNumber") or ""
            items.append(Item(
                source="Google Maps",
                kind="lead",
                title=f"{name} has no website" if not website else f"{name} only has a social page",
                url=p.get("googleMapsUri", ""),
                company=name,
                location=p.get("formattedAddress", ""),
                description=(f"{category}. Rating {p.get('rating', '?')} from {reviews} reviews. "
                             f"Phone: {phone or 'n/a'}. Current link: {website or 'none'}. Found via search: {query}"),
                extra={"phone": phone},
            ))
    return items
