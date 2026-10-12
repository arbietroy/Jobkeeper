"""Command line entry point.

    python -m jobkeeper run          # hunt and send to Telegram
    python -m jobkeeper run --dry    # hunt and print, send nothing, remember nothing
    python -m jobkeeper chat-id      # find your Telegram chat id (message your bot first)
    python -m jobkeeper ping         # send a test message to Telegram
"""

from __future__ import annotations

import argparse
import logging
import sys

from .config import load_config
from .pipeline import run
from .telegram import Telegram


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="jobkeeper", description="AI job & lead hunter that reports to Telegram")
    parser.add_argument("--config", help="path to config.yaml")
    sub = parser.add_subparsers(dest="cmd", required=True)
    p_run = sub.add_parser("run", help="hunt for opportunities")
    p_run.add_argument("--dry", action="store_true", help="print results instead of sending them")
    sub.add_parser("chat-id", help="show chat ids that have messaged your bot")
    sub.add_parser("ping", help="send a test message")
    args = parser.parse_args(argv)

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

    if args.cmd == "chat-id":
        chats = Telegram().find_chat_ids()
        if not chats:
            print("No messages found. Open your bot in Telegram, send it any message, then run this again.")
        for chat_id, name in chats:
            print(f"TELEGRAM_CHAT_ID={chat_id}   ({name})")
        return 0
    if args.cmd == "ping":
        Telegram().send("✅ Jobkeeper is connected. Opportunities will show up here.")
        print("Sent.")
        return 0

    run(load_config(args.config), dry_run=args.dry)
    return 0


if __name__ == "__main__":
    sys.exit(main())
