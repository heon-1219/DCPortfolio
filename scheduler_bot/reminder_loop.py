#!/usr/bin/env python3
"""Telegram reminder loop for the hidden scheduler.

Runs on the always-on server under systemd rather than as a Vercel cron job:
Vercel's Hobby plan caps cron at once per day and fires at an arbitrary point
within the hour, which cannot deliver a "30 minutes before" reminder.
https://vercel.com/docs/cron-jobs/usage-and-pricing

Polls Postgres every minute, sends anything due, and marks it sent. Claiming a
reminder and sending it are ordered so a crash re-sends rather than silently
drops: a duplicate ping is recoverable, a missed appointment is not.
"""

import json
import logging
import os
import signal
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import psycopg
from psycopg.rows import dict_row

TZ = ZoneInfo("Asia/Seoul")
POLL_SECONDS = 60
ENV_FILE = Path(__file__).resolve().parent.parent / ".env.local"

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
)
log = logging.getLogger("reminders")

_running = True


def _stop(signum, frame):
    global _running
    log.info("Signal %s received, shutting down.", signum)
    _running = False


def load_env() -> None:
    """Load .env.local when present; real deployments may use the environment."""
    if not ENV_FILE.exists():
        return
    for line in ENV_FILE.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        os.environ.setdefault(key.strip(), value.strip())


def require(name: str) -> str:
    value = os.environ.get(name)
    if not value:
        log.error("%s is not set; cannot start.", name)
        sys.exit(1)
    return value


def send_telegram(token: str, chat_id: str, text: str) -> bool:
    payload = urllib.parse.urlencode(
        {"chat_id": chat_id, "text": text, "parse_mode": "HTML"}
    ).encode()
    url = f"https://api.telegram.org/bot{token}/sendMessage"
    try:
        with urllib.request.urlopen(url, data=payload, timeout=20) as response:
            return json.loads(response.read()).get("ok", False)
    except urllib.error.HTTPError as exc:
        body = exc.read().decode(errors="replace")
        if "chat not found" in body:
            log.error("Chat not found — send /start to the bot from your account.")
        else:
            log.error("Telegram HTTP %s: %s", exc.code, body[:200])
    except urllib.error.URLError as exc:
        log.error("Telegram unreachable: %s", exc.reason)
    return False


def format_reminder(row) -> str:
    starts = row["starts_at"].astimezone(TZ)
    minutes = max(0, int((starts - datetime.now(TZ)).total_seconds() // 60))
    marker = {"critical": "[CRITICAL]", "mid": "[mid]", "low": "[low]"}.get(
        row["importance"], ""
    )
    lines = [
        f"<b>{marker} {row['title']}</b>",
        f"Starts in {minutes} min — {starts.strftime('%a %d %b, %H:%M')}",
    ]
    if row["notes"]:
        lines.append(str(row["notes"]))
    return "\n".join(lines)


def drain_due(conn, token: str, chat_id: str) -> int:
    """Send every reminder that has come due. Returns how many were sent."""
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT r.id, e.title, e.starts_at, e.importance, e.notes
            FROM reminders r
            JOIN events e ON e.id = r.event_id
            WHERE r.sent_at IS NULL AND r.remind_at <= now()
            ORDER BY r.remind_at
            """
        )
        due = cur.fetchall()

    sent = 0
    for row in due:
        if send_telegram(token, chat_id, format_reminder(row)):
            with conn.cursor() as cur:
                cur.execute(
                    "UPDATE reminders SET sent_at = now() WHERE id = %s", (row["id"],)
                )
            conn.commit()
            sent += 1
            log.info("Sent reminder %s (%s)", row["id"], row["title"])
        else:
            # Leave sent_at NULL so the next pass retries.
            log.warning("Delivery failed for reminder %s; will retry.", row["id"])
    return sent


def main() -> None:
    load_env()
    database_url = require("DATABASE_URL")
    token = require("TELEGRAM_BOT_TOKEN")
    chat_id = require("TELEGRAM_CHAT_ID")

    signal.signal(signal.SIGTERM, _stop)
    signal.signal(signal.SIGINT, _stop)

    log.info("Reminder loop started (polling every %ss).", POLL_SECONDS)
    while _running:
        try:
            with psycopg.connect(database_url, row_factory=dict_row) as conn:
                drain_due(conn, token, chat_id)
        except Exception as exc:  # keep the daemon alive across transient faults
            log.error("Poll failed: %s", exc)

        for _ in range(POLL_SECONDS):
            if not _running:
                break
            time.sleep(1)

    log.info("Reminder loop stopped.")


if __name__ == "__main__":
    main()
