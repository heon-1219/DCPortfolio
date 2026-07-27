"""Event storage, availability maths, and the markdown memory.

All wall-clock reasoning happens in Asia/Seoul. Timestamps are stored as
timestamptz so the database keeps the absolute instant, and day-grouping is
done by converting into the local zone.
"""

import json
from datetime import date, datetime, time, timedelta
from zoneinfo import ZoneInfo

TZ = ZoneInfo("Asia/Seoul")

IMPORTANCE = ("critical", "mid", "low")

# Colours for event blocks, keyed by importance.
IMPORTANCE_COLOR = {
    "critical": "#e5484d",
    "mid": "#f5a524",
    "low": "#46a758",
}

# A day is "unavailable" at 1 critical OR 3 mid events. Low never counts.
BUSY_CRITICAL = 1
BUSY_MID = 3

# How far ahead of an event the Telegram reminder fires.
REMINDER_LEAD_MINUTES = 30

# Time-of-day bands used by the availability finder.
BANDS = {
    "morning": (time(9, 0), time(12, 0)),
    "afternoon": (time(12, 0), time(17, 0)),
    "evening": (time(17, 0), time(22, 0)),
}


def now() -> datetime:
    return datetime.now(TZ)


def _row_to_event(row) -> dict:
    starts = row["starts_at"].astimezone(TZ)
    ends = row["ends_at"].astimezone(TZ)
    return {
        "id": row["id"],
        "title": row["title"],
        "start": starts.isoformat(),
        "end": ends.isoformat(),
        "day": starts.date().isoformat(),
        "importance": row["importance"],
        "color": IMPORTANCE_COLOR.get(row["importance"], IMPORTANCE_COLOR["mid"]),
        "notes": row["notes"] or "",
    }


# --- logging -------------------------------------------------------------


def write_log(conn, event_id, action: str, snapshot: dict, actor: str = "user") -> None:
    """Append-only history. Never deletes; this is the permanent record."""
    with conn.cursor() as cur:
        cur.execute(
            "INSERT INTO event_log (event_id, action, snapshot, actor) "
            "VALUES (%s, %s, %s, %s)",
            (event_id, action, json.dumps(snapshot, default=str), actor),
        )


# --- reads ---------------------------------------------------------------


def list_events(conn, start: datetime, end: datetime) -> list:
    with conn.cursor() as cur:
        cur.execute(
            "SELECT * FROM events WHERE starts_at < %s AND ends_at > %s "
            "ORDER BY starts_at",
            (end, start),
        )
        return [_row_to_event(r) for r in cur.fetchall()]


def get_event(conn, event_id: int):
    with conn.cursor() as cur:
        cur.execute("SELECT * FROM events WHERE id = %s", (event_id,))
        row = cur.fetchone()
    return _row_to_event(row) if row else None


# --- writes --------------------------------------------------------------


def create_event(conn, title, starts_at, ends_at, importance, notes="", actor="user"):
    if importance not in IMPORTANCE:
        raise ValueError(f"importance must be one of {IMPORTANCE}")
    if ends_at <= starts_at:
        raise ValueError("end must be after start")
    with conn.cursor() as cur:
        cur.execute(
            "INSERT INTO events (title, starts_at, ends_at, importance, notes) "
            "VALUES (%s, %s, %s, %s, %s) RETURNING *",
            (title, starts_at, ends_at, importance, notes),
        )
        event = _row_to_event(cur.fetchone())
    write_log(conn, event["id"], "create", event, actor)
    sync_reminder(conn, event["id"], starts_at)
    conn.commit()
    return event


def sync_reminder(conn, event_id: int, starts_at: datetime) -> None:
    """(Re)schedule the pending reminder for an event.

    Unsent reminders are replaced so a rescheduled event does not fire at its
    old time. Already-sent rows are left alone — they are history.
    """
    current = now()
    with conn.cursor() as cur:
        cur.execute(
            "DELETE FROM reminders WHERE event_id = %s AND sent_at IS NULL",
            (event_id,),
        )
        # Only future events are worth announcing; back-filling an old event
        # must not ping. But an event booked at short notice still deserves a
        # reminder, so clamp to now rather than dropping it — an immediate
        # heads-up beats silence.
        if starts_at > current:
            remind_at = max(starts_at - timedelta(minutes=REMINDER_LEAD_MINUTES), current)
            cur.execute(
                "INSERT INTO reminders (event_id, remind_at) VALUES (%s, %s)",
                (event_id, remind_at),
            )


def update_event(conn, event_id, actor="user", **fields):
    allowed = {"title", "starts_at", "ends_at", "importance", "notes"}
    updates = {k: v for k, v in fields.items() if k in allowed and v is not None}
    if not updates:
        return get_event(conn, event_id)
    if "importance" in updates and updates["importance"] not in IMPORTANCE:
        raise ValueError(f"importance must be one of {IMPORTANCE}")

    sets = ", ".join(f"{k} = %s" for k in updates)
    values = list(updates.values()) + [event_id]
    with conn.cursor() as cur:
        cur.execute(
            f"UPDATE events SET {sets}, updated_at = now() WHERE id = %s RETURNING *",
            values,
        )
        row = cur.fetchone()
        if not row:
            return None
        event = _row_to_event(row)
        # Guard the CHECK constraint's intent with a clear error.
        if row["ends_at"] <= row["starts_at"]:
            conn.rollback()
            raise ValueError("end must be after start")
    write_log(conn, event_id, "update", event, actor)
    if "starts_at" in updates:
        sync_reminder(conn, event_id, updates["starts_at"])
    conn.commit()
    return event


def delete_event(conn, event_id, actor="user") -> bool:
    existing = get_event(conn, event_id)
    if not existing:
        return False
    # Log before deleting so the snapshot survives the row.
    write_log(conn, event_id, "delete", existing, actor)
    with conn.cursor() as cur:
        cur.execute("DELETE FROM events WHERE id = %s", (event_id,))
    conn.commit()
    return True


# --- availability --------------------------------------------------------


def day_counts(conn, start_day: date, end_day: date) -> dict:
    """Per-day importance tallies, keyed by ISO date."""
    start = datetime.combine(start_day, time.min, TZ)
    end = datetime.combine(end_day + timedelta(days=1), time.min, TZ)
    counts = {}
    for event in list_events(conn, start, end):
        bucket = counts.setdefault(
            event["day"], {"critical": 0, "mid": 0, "low": 0, "total": 0}
        )
        bucket[event["importance"]] += 1
        bucket["total"] += 1
    return counts


def is_busy(counts: dict) -> bool:
    """The agreed rule: 1 critical OR 3 mid marks a day unavailable."""
    if not counts:
        return False
    return counts.get("critical", 0) >= BUSY_CRITICAL or counts.get("mid", 0) >= BUSY_MID


def availability_map(conn, start_day: date, end_day: date) -> dict:
    counts = day_counts(conn, start_day, end_day)
    out = {}
    cursor = start_day
    while cursor <= end_day:
        key = cursor.isoformat()
        bucket = counts.get(key, {})
        out[key] = {
            "busy": is_busy(bucket),
            "critical": bucket.get("critical", 0),
            "mid": bucket.get("mid", 0),
            "low": bucket.get("low", 0),
            "total": bucket.get("total", 0),
        }
        cursor += timedelta(days=1)
    return out


def find_availability(conn, day_type: str, band: str, horizon_days: int = 90):
    """Soonest free slot matching (weekday|weekend) x (morning|afternoon|evening).

    Pure date maths and SQL — no LLM — so the public pages stay fast and can
    never touch the Gemini key.
    """
    if band not in BANDS:
        raise ValueError(f"band must be one of {tuple(BANDS)}")
    if day_type not in ("weekday", "weekend", "any"):
        raise ValueError("day_type must be weekday, weekend, or any")

    band_start, band_end = BANDS[band]
    current = now()
    today = current.date()
    horizon_end = today + timedelta(days=horizon_days)

    counts = day_counts(conn, today, horizon_end)
    events = list_events(
        conn,
        datetime.combine(today, time.min, TZ),
        datetime.combine(horizon_end + timedelta(days=1), time.min, TZ),
    )
    by_day = {}
    for event in events:
        by_day.setdefault(event["day"], []).append(event)

    for offset in range(horizon_days + 1):
        day = today + timedelta(days=offset)
        is_weekend = day.weekday() >= 5
        if day_type == "weekday" and is_weekend:
            continue
        if day_type == "weekend" and not is_weekend:
            continue

        if is_busy(counts.get(day.isoformat(), {})):
            continue

        slot_start = datetime.combine(day, band_start, TZ)
        slot_end = datetime.combine(day, band_end, TZ)
        # Never propose a slot that has already begun.
        if slot_end <= current:
            continue
        if slot_start < current:
            slot_start = current

        clash = any(
            datetime.fromisoformat(e["start"]) < slot_end
            and datetime.fromisoformat(e["end"]) > slot_start
            for e in by_day.get(day.isoformat(), [])
        )
        if clash:
            continue

        return {
            "found": True,
            "date": day.isoformat(),
            "weekday": day.strftime("%A"),
            "band": band,
            "start": slot_start.isoformat(),
            "end": slot_end.isoformat(),
        }

    return {"found": False, "band": band, "day_type": day_type}


# --- markdown memory -----------------------------------------------------


def build_memory(conn, horizon_days: int = 45) -> str:
    """Markdown snapshot of UPCOMING events, used as Gemini's context.

    Passed events are deliberately excluded to keep context small; they remain
    in the database and in event_log, so nothing is lost.
    """
    current = now()
    end = current + timedelta(days=horizon_days)
    events = list_events(conn, current, end)
    if not events:
        return f"# Schedule\n\nNow: {current.isoformat()}\n\nNo upcoming events."

    lines = [
        "# Schedule",
        "",
        f"Now: {current.isoformat()} (Asia/Seoul)",
        f"Upcoming events (next {horizon_days} days): {len(events)}",
        "",
    ]
    current_day = None
    for event in events:
        if event["day"] != current_day:
            current_day = event["day"]
            weekday = date.fromisoformat(current_day).strftime("%A")
            lines.append(f"## {current_day} ({weekday})")
        start = datetime.fromisoformat(event["start"]).strftime("%H:%M")
        end_t = datetime.fromisoformat(event["end"]).strftime("%H:%M")
        note = f" — {event['notes']}" if event["notes"] else ""
        lines.append(
            f"- [id:{event['id']}] {start}–{end_t} **{event['title']}** "
            f"({event['importance']}){note}"
        )
    return "\n".join(lines)


def archive_passed(conn) -> int:
    """Record events whose time has passed into the permanent log.

    Rows are NOT deleted — they simply stop appearing in the active memory.
    Logged once each, guarded by the existing 'passed' entry.
    """
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT e.* FROM events e
            WHERE e.ends_at <= now()
              AND NOT EXISTS (
                  SELECT 1 FROM event_log l
                  WHERE l.event_id = e.id AND l.action = 'passed'
              )
            """
        )
        rows = cur.fetchall()
        for row in rows:
            write_log(conn, row["id"], "passed", _row_to_event(row), actor="system")
    conn.commit()
    return len(rows)
