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

`test_gemini_tools.py` stashes and restores the stored Gemini key, because it
wipes `app_settings`. It did destroy the key once before that guard existed;
if a run ever leaves `/s` asking for a key again, that is why — re-enter it via
"Ask Gemini" -> "API key".

## Browser (end-to-end) test

`tests/e2e_scheduler.py` drives the real deployed site and asserts that no
interaction on `/s` ever navigates away.

    FONTCONFIG_FILE=/tmp/fc/fonts.conf \
    LD_LIBRARY_PATH=/tmp/chromedeps/root/usr/lib/x86_64-linux-gnu \
    /tmp/schedvenv/bin/python tests/e2e_scheduler.py

Chromium was installed without root, since `playwright install-deps` needs
sudo. Recreate it with:

    /tmp/schedvenv/bin/playwright install chromium
    cd /tmp/chromedeps && apt-get download <libs> && dpkg-deb -x *.deb root/

Libraries needed: libatk1.0-0t64, libatk-bridge2.0-0t64, libatspi2.0-0t64,
libcups2t64, libxkbcommon0, libxcomposite1, libxdamage1, libxfixes3,
libxrandr2, libgbm1, libpango-1.0-0, libcairo2, libasound2t64, libnspr4,
libnss3, libdrm2, libxshmfence1, libxrender1, libxext6, libxi6, libxtst6,
libxcursor1, libxinerama1, libgtk-3-0t64, libxres1, fonts-liberation.
A minimal `fonts.conf` is also required or Chromium aborts on first paint.

Known quirk: `page.fill()` silently does nothing against
chrome-headless-shell here. The DOM is fine (`element.value = ...` from JS
works), so the test sets the passcode that way.

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
