# Hidden Scheduler — Runbook

Operational reference. Design lives in `SPEC.md`, history in `BUILD_LOG.md`.

## URLs

- `https://davidseheonchang.xyz/s` — full manager (passcode, Gemini)
- `https://davidseheonchang.xyz/sprivate` — event details, read-only (passcode)
- `https://davidseheonchang.xyz/spublic` — availability only (no passcode)

None are linked from the portfolio, and they are deliberately kept out of
`robots.txt` — listing them there would advertise them.

## Vercel environment variables

Set in Project → Settings → Environment Variables:

| Variable | Purpose |
|---|---|
| `DATABASE_URL` | Neon pooled connection string |
| `SESSION_SECRET` | signs session cookies |
| `SCHEDULER_PASSWORD` | passcode for `/s` |
| `SPRIVATE_PASSWORD` | passcode for `/sprivate` |

The Gemini key is **not** an env var — it is entered in the `/s` UI and stored
in the `app_settings` table, server-side only.

## Reminder daemon (this server)

Runs as a systemd **user** service; `loginctl Linger` is enabled so it survives
logout.

    systemctl --user status schedulebot
    systemctl --user restart schedulebot
    journalctl --user -u schedulebot -f

Config comes from `.env.local` in the repo root (chmod 600, git-ignored):
`DATABASE_URL`, `TELEGRAM_BOT_TOKEN`, `TELEGRAM_CHAT_ID`.

Reminders fire 30 minutes before an event
(`_events.REMINDER_LEAD_MINUTES`). Booking something at shorter notice still
reminds you — the time is clamped to now rather than skipped.

### "Chat not found" in the logs

Telegram forbids a bot from opening a conversation. Send `/start` to
**@heonschedulebot** once from your account. Pending reminders retry
automatically, so nothing is lost.

## Tests

    /tmp/schedvenv/bin/python tests/test_scheduler_auth.py     # gate + sessions
    /tmp/schedvenv/bin/python tests/test_scheduler_lockout.py  # 3-strike lockout
    /tmp/schedvenv/bin/python tests/test_scheduler_api.py      # CRUD + availability
    /tmp/schedvenv/bin/python tests/test_reminder_loop.py      # reminders
    /tmp/schedvenv/bin/python tests/test_gemini_tools.py       # Gemini dispatch

They run against the **live Neon database** and clear the tables around each
run — do not run them once real events matter without pointing `DATABASE_URL`
at a scratch database first.

## Locked out?

The lock is per-IP and lasts 15 minutes. To clear immediately:

    DELETE FROM login_attempts;

## Data model

- `events` — the calendar. Importance is `critical` | `mid` | `low`.
- `event_log` — append-only history, including a `passed` entry once an event's
  time goes by. Nothing is ever destroyed here.
- `reminders` — pending Telegram pings, drained by the daemon.
- `app_settings` — the Gemini key and model name.
- `login_attempts` — failed-passcode counters driving the lockout.
