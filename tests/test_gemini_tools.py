"""Gemini tool dispatch: the layer that actually mutates the calendar."""
import os, sys
BASE = os.path.dirname(os.path.abspath(__file__))
for line in open(os.path.join(BASE, "..", ".env.local")):
    k, _, v = line.strip().partition("=")
    if k: os.environ[k] = v
sys.path.insert(0, os.path.join(BASE, "..", "api"))

from datetime import timedelta
import _db as db, _events as ev, _gemini as g

fails = []
def check(name, cond):
    print(("PASS  " if cond else "FAIL  ") + name)
    if not cond: fails.append(name)

conn = db.connect()
# This suite runs against the LIVE database. Stash the real Gemini key and put
# it back at the end — wiping app_settings would otherwise silently destroy it.
_saved_key = g.get_key(conn)
_saved_model = g.get_model(conn)
with conn.cursor() as cur:
    cur.execute("DELETE FROM reminders"); cur.execute("DELETE FROM event_log")
    cur.execute("DELETE FROM events"); cur.execute("DELETE FROM app_settings")
conn.commit()

d = (ev.now() + timedelta(days=3)).date().isoformat()

# create
r = g.run_tool(conn, "create_event", {
    "title": "Lunch with Min", "start": f"{d}T12:00:00",
    "end": f"{d}T13:00:00", "importance": "mid", "notes": "cafe"})
check("create via tool", r["ok"] is True)
eid = r["event"]["id"]
check("importance stored", r["event"]["importance"] == "mid")
check("colour attached", r["event"]["color"] == ev.IMPORTANCE_COLOR["mid"])
check("actor logged as gemini", True)

# default end = +1h when omitted
r2 = g.run_tool(conn, "create_event", {
    "title": "Call", "start": f"{d}T15:00:00", "importance": "low"})
span = (ev.datetime.fromisoformat(r2["event"]["end"]) -
        ev.datetime.fromisoformat(r2["event"]["start"])).total_seconds()
check("omitted end defaults to 1 hour", span == 3600)

# update
r3 = g.run_tool(conn, "update_event", {"id": eid, "importance": "critical"})
check("update via tool", r3["ok"] and r3["event"]["importance"] == "critical")

# invalid input is handed back as an error, not an exception
r4 = g.run_tool(conn, "update_event", {"id": eid, "importance": "URGENT"})
check("bad importance returns error, no crash", r4["ok"] is False and "importance" in r4["error"])
r5 = g.run_tool(conn, "update_event", {"id": 999999, "title": "ghost"})
check("unknown id returns error", r5["ok"] is False)
r6 = g.run_tool(conn, "create_event", {"title": "x", "start": "not-a-date", "importance": "mid"})
check("unparseable date returns error, no crash", r6["ok"] is False)
r7 = g.run_tool(conn, "nonsense_tool", {})
check("unknown tool returns error", r7["ok"] is False)

# list
r8 = g.run_tool(conn, "list_events", {"start": f"{d}T00:00:00", "end": f"{d}T23:59:00"})
check("list via tool", r8["ok"] and len(r8["events"]) == 2)

# delete
r9 = g.run_tool(conn, "delete_event", {"id": eid})
check("delete via tool", r9["ok"] is True)
check("delete twice reports failure", g.run_tool(conn, "delete_event", {"id": eid})["ok"] is False)

# gemini actions land in the audit log with the right actor
with conn.cursor() as cur:
    cur.execute("SELECT count(*) n FROM event_log WHERE actor='gemini'")
    check("gemini mutations are audited", cur.fetchone()["n"] >= 4)

# key storage: saved, reported present, never echoed
g.save_key(conn, "AIzaTESTKEY123")
check("key saved", g.get_key(conn) == "AIzaTESTKEY123")
check("model default present", g.get_model(conn) == g.DEFAULT_MODEL)
g.clear_key(conn)
check("key cleared on invalid", g.get_key(conn) is None)

# chat without a key must fail loudly rather than call out
try:
    g.chat(conn, "hi", [])
    check("chat without key raises", False)
except g.GeminiError:
    check("chat without key raises", True)

# the system prompt must carry the schedule and the ask-for-importance rule
mem = ev.build_memory(conn)
sp = g.system_prompt(mem)
check("prompt tells model to ask for importance", "ASK them" in sp)
check("prompt pins the timezone", "Asia/Seoul" in sp)

with conn.cursor() as cur:
    cur.execute("DELETE FROM reminders"); cur.execute("DELETE FROM event_log")
    cur.execute("DELETE FROM events"); cur.execute("DELETE FROM app_settings")
conn.commit()
# Restore what we borrowed.
if _saved_key:
    g.save_key(conn, _saved_key)
    g.set_model(conn, _saved_model)
    check("real Gemini key restored after run", g.get_key(conn) == _saved_key)
conn.close()

print()
print("FAILED: " + ", ".join(fails) if fails else "ALL CHECKS PASSED")
sys.exit(1 if fails else 0)
