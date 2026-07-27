# Hidden Scheduler — Spec & Locked Decisions

Private, Gemini-managed schedule manager bolted onto the static portfolio.
**Not linked from any portfolio UI.** Reachable only by typing the URL.

Last updated: 2026-07-27

---

## 1. Pages

| Path | Purpose | Password |
|---|---|---|
| `/s` | Full manager. Calendar + Gemini chat CRUD. | `1219` (env var) |
| `/sprivate` | Event **specifics** (titles, times, details). | `1111` (env var) |
| `/spublic` | **Availability only** — no event details leak. | none (public) |

> **Naming note:** the original request had `/spublic` and `/sprivate` swapped.
> Confirmed inverted on 2026-07-27. The table above is authoritative:
> `spublic` = public availability, `sprivate` = detailed but password-gated.

All three are mobile-first.

## 2. Authentication

- Passwords are **never hardcoded** — read from environment variables.
- Compared in constant time (`hmac.compare_digest`) to avoid timing leaks.
- Session = HMAC-signed, HTTP-only, `Secure`, `SameSite=Lax` cookie.
- **Page HTML is served by the serverless function, behind the gate** — not as
  a static file. A static file at `/s/index.html` would be readable by anyone,
  which defeats the "hidden" requirement.
- **Lockout: 3 failed attempts**, then a timed lock keyed by client IP.
  Attempt counters live in Postgres (serverless memory does not persist).
- `X-Robots-Tag: noindex, nofollow` on all three routes.
- Deliberately **absent** from `robots.txt` and any sitemap — listing them
  there would advertise the very paths we are hiding.

## 3. Importance & colors

Set by Gemini per event; if the user does not state one, Gemini **must ask**.

- `critical` — red
- `mid` — amber
- `low` — green

## 4. Availability rule (the "busy" threshold)

A day is rendered **unavailable** (dark block) in month view when:

> `critical >= 1` **OR** `mid >= 3`

`low` events never make a day unavailable.

Used by `/spublic` and `/sprivate` month views, and by the
"find closest availability" helper.

## 5. Availability finder (`/spublic` + `/sprivate`, no Gemini)

Query: `(weekday | weekend) x (morning | afternoon | evening)`.
Returns the soonest matching free slot. Pure SQL + date math — no LLM,
so these pages stay fast and cannot leak the Gemini key.

Time bands (Asia/Seoul):
- morning: 09:00–12:00
- afternoon: 12:00–17:00
- evening: 17:00–22:00

## 6. Gemini

- User pastes a **free AI Studio key** into `/s`. Stored **server-side**,
  encrypted at rest. Never sent to the browser. Persists until it fails auth,
  then the UI prompts for a new one.
- CRUD via **function calling** (structured tool schema), not freeform text
  parsing — far more reliable for dates and mutations.
- Available only on `/s`.

## 7. Markdown memory (confirmed 2026-07-27)

- A compact **markdown snapshot of upcoming events** is fed to Gemini as
  context each turn.
- Once an event's date/time **passes**, it is dropped from that active memory
  so context stays small...
- ...but is **never deleted** — it moves to a permanent append-only log.

## 8. Reminders — Telegram

- **A new, dedicated bot** (not heonbot's token).
- Reminder loop runs on **this always-on server** under systemd, polling
  Postgres every minute.
- **Why not Vercel Cron:** the Hobby plan caps cron at *once per day* and fires
  at an arbitrary point within the hour, which cannot deliver
  "30 minutes before" reminders.
  https://vercel.com/docs/cron-jobs/usage-and-pricing

## 9. Stack

- **Frontend:** vanilla HTML/CSS/JS. No framework, no build step — matches the
  existing portfolio, keeps the static site's zero-risk deploy.
- **Backend:** Python serverless function on Vercel (same pattern as the
  2ID BJJ club project).
- **DB:** Neon Postgres. Relational, because month views and availability math
  are date-range queries.
- **Timezone:** `Asia/Seoul` throughout.

## 10. Constraint: the portfolio must not break

The portfolio is a pure static site with no build step. All scheduler work is
**additive**. Any change that risks the existing pages is out of scope.
