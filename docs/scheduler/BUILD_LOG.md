# Hidden Scheduler — Build Log

Chronological record of this build. Append newest at the bottom.
Spec and locked decisions live in `SPEC.md`.

---

## 2026-07-27 — Requirements & architecture

**Request:** a hidden, Gemini-managed schedule manager attached to the
portfolio at `/s`, plus `/spublic` and `/sprivate`, with Telegram reminders.

**Findings from investigating the repo before designing:**

1. The portfolio is a **pure static site** — no `package.json`, no `vercel.json`,
   no `api/`, no build step. Everything requested (password gate, stored Gemini
   key, persisted events, Telegram) needs server-side code that does not exist
   yet. This is an additive backend, not a page.
2. `davidseheonchang.xyz` is **live** — 308-redirects to `www.davidseheonchang.xyz`,
   which returns 200.
3. **Vercel Hobby cron cannot drive reminders.** It is capped at once per day and
   fires at an arbitrary moment within the target hour.
   (https://vercel.com/docs/cron-jobs/usage-and-pricing)
4. This server already runs `heonbot` under systemd
   (`~/projects/telegram-claude-bot/systemd/heonbot.service`) — an existing,
   always-on host for a precise reminder loop.

**Decisions locked with the user (answers to 5 open questions):**

| # | Question | Answer |
|---|---|---|
| 1 | `/spublic` vs `/sprivate` naming looked inverted | Confirmed inverted — `spublic` = availability, `sprivate` = specifics |
| 2 | Month-view "busy" threshold | 1 critical **or** 3 mid events |
| 3 | Markdown memory interpretation | Confirmed — drop passed events from active context, keep permanent log |
| 4 | Brute-force protection on 4-digit passwords | 3 attempts, then lockout |
| 5 | Telegram bot token | **New** dedicated bot, do not reuse heonbot's |

Also directed: log everything about this change for future traceability
(this file + `SPEC.md`).

**Chosen stack:** vanilla JS frontend / Python serverless function on Vercel /
Neon Postgres / systemd reminder loop on this server. Timezone `Asia/Seoul`.

**Key security decision:** the three pages' HTML is served *by the serverless
function behind the auth gate*, not as static files. A static `/s/index.html`
would be readable by anyone who guessed the URL, defeating the whole point.

---

## 2026-07-27 — Phase 1: auth skeleton

Scope: routing, the password gate, lockout, and session cookies — built and
verified *before* anything sensitive sits behind it.

Files added:
- `docs/scheduler/SPEC.md` — spec and locked decisions
- `docs/scheduler/BUILD_LOG.md` — this log
- `vercel.json` — routes `/s`, `/spublic`, `/sprivate`, `/api/*` to the function;
  sets `noindex` headers
- `requirements.txt` — Python deps for the Vercel function
- `api/index.py` — FastAPI app: gate, sessions, lockout
- `api/auth.py` — password check, HMAC session tokens, lockout logic
- `api/db.py` — Neon connection + schema bootstrap

**Gotcha caught before deploy:** every `.py` file in `/api` that exports an
ASGI app or handler becomes its own Vercel Function. The helper modules were
originally `db.py` / `auth.py` / `pages.py`, which would have been picked up as
routes. Renamed to `_db.py` / `_auth.py` / `_pages.py` — files prefixed with
`_` are excluded from becoming functions.
(https://vercel.com/docs/functions/runtimes/python)

**Verification** — `tests/test_scheduler_auth.py`, 17/17 passing:
- `/s` and `/sprivate` render the login form and leak no app content when
  unauthenticated; a valid cookie unlocks `/s`
- `/spublic` is reachable without a password, by design
- session tokens are scope-bound (an `/s` token does not open `/sprivate`);
  tampered and garbage tokens are rejected
- correct/wrong/empty passwords behave; the two scopes use different passwords
- `X-Robots-Tag: noindex` present on responses
- `/api/health` reports which env vars are set without echoing their values
- no static path collides with `/s`, `/spublic`, `/sprivate`; the existing
  portfolio files are untouched

---

## 2026-07-27 — Phase 1 complete: verified against real Neon

User supplied the Neon connection string. Schema bootstrapped successfully
against PostgreSQL 18.4 (ap-southeast-1); all five tables created:
`app_settings`, `event_log`, `events`, `login_attempts`, `reminders`.

**Secret handling:** added `.gitignore` covering `.env*` *before* writing any
env file, and confirmed with `git check-ignore` that `.env.local` is excluded.
Local file is `chmod 600`. Real values belong in the Vercel dashboard;
`.env.example` documents the shape with empty values.

**Lockout now verified** — `tests/test_scheduler_lockout.py`, 11/11 passing
against the live database:
- attempts count down (2 left, 1 left) then lock on the 3rd
- **the correct password is refused while locked**, and no session cookie is
  issued — this is the property that actually matters
- the lock is per-IP: a different address is unaffected
- access is restored once failures are cleared
- the `/s` passcode is rejected on `/sprivate` (scopes do not cross over)

Test rows were cleaned up afterwards; `login_attempts` and `events` are empty,
so real logins start from a clean slate.

Phase 1 total: **28/28 checks passing** (17 auth + 11 lockout).

Status: Phase 1 code complete and verified locally. Not yet deployed — pending
Vercel env vars and the Telegram bot token.

---

## 2026-07-27 — Phases 2-6: calendar, Gemini, public pages, reminders

Files added:
- `api/_events.py` — event CRUD, the busy rule, availability finder, markdown
  memory, reminder scheduling
- `api/_gemini.py` — function-calling CRUD, server-side key storage
- `api/_ui.py` — the calendar frontend (month/week/day), rendered per page mode
- `scheduler_bot/reminder_loop.py` — systemd daemon polling for due reminders
- `scheduler_bot/systemd/schedulebot.service`

**Page modes** share one calendar engine with a `MODE` switch, so the three
pages cannot drift apart:
- `full` (`/s`) — details, editing, Gemini chat
- `detail` (`/sprivate`) — details, read-only, availability finder
- `public` (`/spublic`) — availability only; the API returns `events: []`, so
  titles are never sent to the browser rather than merely hidden by CSS

**Access model:** `/sprivate`'s passcode grants read access to details but is
rejected for any write and for Gemini. Only `/s` can mutate.

### Bug found by testing: short-notice events were never reminded

`sync_reminder` originally skipped scheduling whenever the ideal reminder time
(start − 30 min) had already passed. An event created 20 minutes before it
began therefore produced **no reminder at all**. Fixed by clamping: if the
event start is still in the future, the reminder is scheduled at
`max(start − 30min, now)`. Back-filled past events still queue nothing.
Rationale: an immediate heads-up is recoverable, a missed appointment is not.

### systemd: user units cannot drop capabilities

The unit initially copied heonbot's hardening block and failed with
`status=218/CAPABILITIES`. `ProtectKernelTunables`, `ProtectControlGroups`,
`ProtectKernelModules`, `RestrictSUIDSGID` and friends require privileges a
*user* unit does not have. Reduced to `NoNewPrivileges` + `PrivateTmp`, which
start cleanly. `loginctl Linger=yes` is already enabled, so the loop survives
logout.

**Verification — 4 suites, all passing:**
- `test_scheduler_auth.py` (17) — gate, sessions, scope isolation
- `test_scheduler_lockout.py` (11) — 3-strike lockout against the live DB
- `test_scheduler_api.py` (34) — CRUD, the 1-critical/3-mid busy rule proven
  incrementally, availability finder, audit logging, memory archiving, and a
  check that `/spublic` leaks no event titles
- `test_reminder_loop.py` (16) — auto-scheduling, reschedule-without-duplicate,
  cascade on delete, delivery, and retry-on-failure
- `test_gemini_tools.py` (20) — tool dispatch, malformed-input handling,
  audit actor, key storage

Live Gemini calls are **not** covered: they need the user's AI Studio key,
which is entered through the UI at runtime.

---

## 2026-07-27 — Deployed and verified in production

Commit `de3ccdf` pushed to `master`; Vercel auto-deployed.

**Vercel picked up the Python function without extra config.** `api/index.py`
matches a recognised entrypoint name and exports a top-level `app`, which is
what the runtime looks for. `requirements.txt` at the project root supplied the
dependencies. The routes 404'd for a few minutes purely as deploy lag, not a
routing fault.

**Live verification against https://www.davidseheonchang.xyz:**

- Portfolio unaffected — `/` and `/projects/tessera/` both 200
- `/api/health` reports all four env vars present (user had set them)
- `/s` unauthenticated shows the passcode prompt and contains **no** calendar
  markup — the gate holds in production, not just in tests
- `X-Robots-Tag: noindex, nofollow, noarchive` present
- Wrong passcode → 401 "Incorrect. 2 tries left."
- Correct passcode → 303, session cookie issued, `/s` then serves the calendar
  and the Gemini chat
- `/spublic` availability finder works unauthenticated and returned a real slot
- Access control confirmed live: the `/sprivate` passcode reads details (200)
  but is refused for event creation (401) and for Gemini (401); anonymous
  callers cannot read details (401)

**Outstanding:** the Telegram chat must be opened from the user's side — a bot
cannot initiate. Until `/start` is sent to @heonschedulebot, delivery fails
with "chat not found" and reminders stay queued for retry (verified: the loop
retried rather than dropping). Live Gemini calls remain untested until an AI
Studio key is entered in `/s`.

---

## 2026-07-27 — Gemini quota: models are blocked, not exhausted

User hit "quota exceeded" on `gemini-2.0-flash-lite` **without having called
it**. Probing the real key explained why:

    gemini-2.5-flash       ok
    gemini-2.5-pro         blocked
    gemini-2.0-flash       blocked
    gemini-2.0-flash-lite  blocked

The 429 detail is the giveaway: a blocked model violates
`GenerateRequestsPerMinutePerProjectPerModel-FreeTier` on its *first* request.
A per-minute limit cannot be exhausted by a user who never called the model —
so the free-tier allocation for those models on this project is effectively
zero. They are retired from the free tier, not used up.

Lesson: a model's availability is **not** knowable from its name. Quota is
granted per model per project, so the only honest source is the key itself.
The earlier fix (hardcoding a better default) was therefore only half a fix —
the dropdown still offered three models that could never work.

Changes:
- `probe_models()` + `GET /api/settings/models/probe` — asks the key which
  models it can actually call. A "Check" button in the chat header marks dead
  options as disabled and `(blocked)`.
- **Automatic fallback**: `chat()` now validates the selected model with a
  1-token request first, and on 429 walks `FALLBACK_ORDER` to a working model,
  persists the switch, and reports it as `switched_from` so the UI can say so.
  Verified by setting the model to `gemini-2.0-flash-lite` and sending a real
  message: it switched to `gemini-2.5-flash`, created the event, and saved the
  new selection.
- The pre-flight costs one tiny request but prevents burning the full
  tool-calling exchange against a model that cannot answer.

100 tests passing; `test_gemini_tools.py` confirmed it restores the live key.
