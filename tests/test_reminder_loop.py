"""Reminder scheduling + delivery logic, with Telegram stubbed."""
import os, sys
BASE = os.path.dirname(os.path.abspath(__file__))
for line in open(os.path.join(BASE, "..", ".env.local")):
    k, _, v = line.strip().partition("=")
    if k: os.environ[k] = v
sys.path.insert(0, os.path.join(BASE, "..", "api"))
sys.path.insert(0, os.path.join(BASE, "..", "scheduler_bot"))

from datetime import timedelta
import _db as db, _events as ev
import reminder_loop as rl

fails = []
def check(name, cond):
    print(("PASS  " if cond else "FAIL  ") + name)
    if not cond: fails.append(name)

conn = db.connect()
with conn.cursor() as cur:
    cur.execute("DELETE FROM reminders"); cur.execute("DELETE FROM event_log"); cur.execute("DELETE FROM events")
conn.commit()

def pending():
    with conn.cursor() as cur:
        cur.execute("SELECT * FROM reminders WHERE sent_at IS NULL ORDER BY remind_at")
        return cur.fetchall()

# A future event auto-schedules a reminder 30 min ahead.
start = ev.now() + timedelta(hours=5)
e1 = ev.create_event(conn, "Standup", start, start+timedelta(hours=1), "mid")
rows = pending()
check("reminder auto-created", len(rows) == 1)
lead = (start - rows[0]["remind_at"]).total_seconds() / 60
check("lead time is 30 min", abs(lead - ev.REMINDER_LEAD_MINUTES) < 0.1)

# Rescheduling the event moves the pending reminder.
new_start = ev.now() + timedelta(hours=9)
ev.update_event(conn, e1["id"], starts_at=new_start, ends_at=new_start+timedelta(hours=1))
rows = pending()
check("reschedule replaces reminder (no duplicate)", len(rows) == 1)
check("reminder follows new start",
      abs((new_start - rows[0]["remind_at"]).total_seconds()/60 - 30) < 0.1)

# Short notice: still reminded, clamped to now rather than dropped.
soon = ev.now() + timedelta(minutes=5)
ev.create_event(conn, "Imminent", soon, soon+timedelta(minutes=30), "low")
rows = pending()
check("short-notice event still gets a reminder", len(rows) == 2)
check("clamped to now, not back-dated",
      min(r["remind_at"] for r in rows) >= ev.now() - timedelta(seconds=5))

# A past event must NOT ping (back-filling history stays silent).
old = ev.now() - timedelta(days=2)
ev.create_event(conn, "Backfill", old, old+timedelta(hours=1), "mid")
check("past event queues no reminder", len(pending()) == 2)

# Deleting the event removes its reminder (FK cascade).
ev.delete_event(conn, e1["id"])
check("reminder cascades on delete", not any(r["event_id"] == e1["id"] for r in pending()))

# --- delivery ------------------------------------------------------------
# Clear the queue so this section measures only what it creates.
with conn.cursor() as cur:
    cur.execute("DELETE FROM reminders")
conn.commit()
due = ev.now() - timedelta(minutes=1)
e2 = ev.create_event(conn, "Dentist", ev.now()+timedelta(minutes=29),
                     ev.now()+timedelta(minutes=89), "critical", notes="molar")
with conn.cursor() as cur:                       # force it due
    cur.execute("UPDATE reminders SET remind_at=%s WHERE event_id=%s", (due, e2["id"]))
conn.commit()

sent_texts = []
rl.send_telegram = lambda t, c, text: (sent_texts.append(text), True)[1]
n = rl.drain_due(conn, "tok", "chat")
check("due reminder sent", n == 1)
check("message names the event", "Dentist" in sent_texts[0])
check("critical is flagged in message", "CRITICAL" in sent_texts[0])
check("notes included", "molar" in sent_texts[0])
check("marked sent", len(pending()) == 0)
check("not re-sent on next poll", rl.drain_due(conn, "tok", "chat") == 0)

# Failed delivery must retry, not silently drop.
e3 = ev.create_event(conn, "Retry me", ev.now()+timedelta(minutes=29),
                     ev.now()+timedelta(minutes=59), "mid")
with conn.cursor() as cur:
    cur.execute("UPDATE reminders SET remind_at=%s WHERE event_id=%s", (due, e3["id"]))
conn.commit()
rl.send_telegram = lambda t, c, text: False
rl.drain_due(conn, "tok", "chat")
check("failed send stays pending for retry", len(pending()) == 1)
rl.send_telegram = lambda t, c, text: True
check("retry succeeds", rl.drain_due(conn, "tok", "chat") == 1)

with conn.cursor() as cur:
    cur.execute("DELETE FROM reminders"); cur.execute("DELETE FROM event_log"); cur.execute("DELETE FROM events")
conn.commit(); conn.close()

print()
print("FAILED: " + ", ".join(fails) if fails else "ALL CHECKS PASSED")
sys.exit(1 if fails else 0)
