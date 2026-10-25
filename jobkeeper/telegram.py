"""Send opportunities to your Telegram via a bot."""

from __future__ import annotations

import html
import logging
import time

import httpx

from .config import env
from .models import Item

log = logging.getLogger("jobkeeper")
API = "https://api.telegram.org/bot{token}/{method}"
MAX_LEN = 4000  # Telegram's hard limit is 4096


def _esc(text: str) -> str:
    return html.escape(text or "", quote=False)


def format_item(item: Item) -> str:
    icon = "💼" if item.kind == "job" else "🎯"
    label = "JOB" if item.kind == "job" else "LEAD — pitch them"
    lines = [f"{icon} <b>{label}</b> · fit {item.score}/100", f"<b>{_esc(item.title)}</b>"]
    meta = " · ".join(p for p in [item.company, item.location] if p and p != item.title)
    if meta:
        lines.append(_esc(meta))
    age = item.age_days()
    lines.append(f"📍 {_esc(item.source)}" + (f" · posted {age:.0f}d ago" if age is not None and age >= 1
                                              else " · posted today" if age is not None else ""))
    elig = item.extra.get("eligibility")
    if item.kind == "job" and elig:
        icon = {"yes": "✅", "unclear": "❔"}.get(elig, "⛔")
        label = {"yes": "Open to Nigeria", "unclear": "Nigeria: not stated, check before applying"}.get(elig, "Not open to Nigeria")
        why = item.extra.get("eligibility_reason", "")
        lines.append(f"🌍 {icon} {label}" + (f" ({_esc(why)})" if why else ""))
    if item.extra.get("salary"):
        lines.append(f"💰 {_esc(str(item.extra['salary']))}")
    if item.reason:
        lines.append(f"\n🧠 {_esc(item.reason)}")
    if item.extra.get("requirements"):
        lines.append(f"📋 {_esc(item.extra['requirements'])}")
    if item.pitch:
        lines.append(f"\n✍️ <i>{_esc(item.pitch)}</i>")
    if item.url:
        lines.append(f'\n<a href="{html.escape(item.url, quote=True)}">Open →</a>')
    return "\n".join(lines)[:MAX_LEN]


class Telegram:
    def __init__(self, token: str | None = None, chat_id: str | None = None, http: httpx.Client | None = None):
        self.token = token or env("TELEGRAM_BOT_TOKEN")
        self.chat_id = chat_id or env("TELEGRAM_CHAT_ID")
        self.http = http or httpx.Client(timeout=20)

    def _call(self, method: str, **payload) -> dict:
        if not self.token:
            raise RuntimeError("TELEGRAM_BOT_TOKEN is not set")
        for attempt in range(3):
            r = self.http.post(API.format(token=self.token, method=method), json=payload)
            if r.status_code == 429:  # flood control
                time.sleep(r.json().get("parameters", {}).get("retry_after", 3))
                continue
            data = r.json()
            if not data.get("ok"):
                raise RuntimeError(f"Telegram {method} failed: {data.get('description')}")
            return data
        raise RuntimeError(f"Telegram {method} kept hitting rate limits")

    def send(self, text: str) -> None:
        if not self.chat_id:
            raise RuntimeError("TELEGRAM_CHAT_ID is not set")
        self._call("sendMessage", chat_id=self.chat_id, text=text, parse_mode="HTML",
                   link_preview_options={"is_disabled": True})
        time.sleep(1.1)  # stay under ~1 message/second per chat

    def find_chat_ids(self) -> list[tuple[str, str]]:
        """Chats that have messaged the bot recently: (chat_id, name)."""
        updates = self._call("getUpdates").get("result", [])
        seen = {}
        for u in updates:
            chat = (u.get("message") or u.get("channel_post") or {}).get("chat")
            if chat:
                seen[str(chat["id"])] = chat.get("username") or chat.get("title") or chat.get("first_name", "")
        return list(seen.items())
