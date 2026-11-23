"""Send notifications to Telegram and/or Slack, whichever is configured.

Configuration comes from environment variables (GitHub Actions secrets), or a local .env file:
    TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID   -> Telegram bot message
    SLACK_WEBHOOK_URL                      -> Slack incoming webhook

    python -m sgpools.notify --test        # send a test message to every configured channel
    python -m sgpools.notify --chat-id     # list chat IDs that have messaged your bot (setup helper)
"""
from __future__ import annotations

import argparse
import html
import os
from dataclasses import dataclass
from pathlib import Path

import requests

ENV_PATH = Path(__file__).resolve().parent.parent / ".env"
TELEGRAM_API = "https://api.telegram.org/bot{token}/{method}"


def load_env() -> None:
    """Minimal .env loader (KEY=VALUE lines); real environment variables win."""
    if not ENV_PATH.exists():
        return
    for line in ENV_PATH.read_text().splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            k, v = line.split("=", 1)
            os.environ.setdefault(k.strip(), v.strip().strip("'\""))


@dataclass
class Message:
    """One message, pre-rendered for each channel's markup."""
    slack: str      # Slack mrkdwn
    telegram: str   # Telegram HTML

    @classmethod
    def plain(cls, text: str) -> "Message":
        return cls(slack=text, telegram=html.escape(text))


def channels() -> list[str]:
    load_env()
    out = []
    if os.environ.get("TELEGRAM_BOT_TOKEN") and os.environ.get("TELEGRAM_CHAT_ID"):
        out.append("telegram")
    if os.environ.get("SLACK_WEBHOOK_URL"):
        out.append("slack")
    return out


def _send_telegram(text: str) -> None:
    token = os.environ["TELEGRAM_BOT_TOKEN"]
    r = requests.post(
        TELEGRAM_API.format(token=token, method="sendMessage"),
        json={"chat_id": os.environ["TELEGRAM_CHAT_ID"], "text": text,
              "parse_mode": "HTML", "disable_web_page_preview": True},
        timeout=20,
    )
    body = r.json() if r.headers.get("content-type", "").startswith("application/json") else {}
    if not body.get("ok"):
        # never echo the token: report only Telegram's description
        raise RuntimeError(f"Telegram sendMessage failed (HTTP {r.status_code}): {body.get('description', 'no details')}")


def _send_slack(text: str) -> None:
    r = requests.post(os.environ["SLACK_WEBHOOK_URL"], json={"text": text}, timeout=20)
    if r.status_code != 200:
        raise RuntimeError(f"Slack webhook returned HTTP {r.status_code}: {r.text[:200]}")


def send(msg: Message) -> list[str]:
    """Send to every configured channel. Raises if none is configured or any channel fails."""
    chans = channels()
    if not chans:
        raise RuntimeError("No notification channel configured: set TELEGRAM_BOT_TOKEN + TELEGRAM_CHAT_ID "
                           "and/or SLACK_WEBHOOK_URL (GitHub secrets or .env).")
    errors = []
    for ch in chans:
        try:
            _send_telegram(msg.telegram) if ch == "telegram" else _send_slack(msg.slack)
        except Exception as e:
            errors.append(f"{ch}: {e}")
    if errors:
        raise RuntimeError("; ".join(errors))
    return chans


def send_text(text: str) -> list[str]:
    return send(Message.plain(text))


def _chat_ids() -> None:
    load_env()
    token = os.environ.get("TELEGRAM_BOT_TOKEN")
    if not token:
        raise SystemExit("Set TELEGRAM_BOT_TOKEN first (env var or .env).")
    r = requests.get(TELEGRAM_API.format(token=token, method="getUpdates"), timeout=20).json()
    if not r.get("ok"):
        raise SystemExit(f"getUpdates failed: {r.get('description')}")
    seen = {}
    for u in r.get("result", []):
        chat = (u.get("message") or u.get("channel_post") or {}).get("chat")
        if chat:
            seen[chat["id"]] = chat.get("username") or chat.get("title") or chat.get("first_name")
    if not seen:
        print("No messages yet. Open your bot in Telegram, press Start (or send 'hi'), then run this again.")
    for cid, name in seen.items():
        print(f"chat_id={cid}  ({name})")


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--test", action="store_true", help="send a test message")
    p.add_argument("--chat-id", action="store_true", help="list chat IDs that messaged the bot")
    args = p.parse_args()
    if args.chat_id:
        _chat_ids()
    elif args.test:
        print("sent to:", ", ".join(send(Message(
            slack=":white_check_mark: TOTO/4D notifier test - this channel is working.",
            telegram="✅ <b>TOTO/4D notifier test</b> - this channel is working."))))
    else:
        p.print_help()


if __name__ == "__main__":
    main()
