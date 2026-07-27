"""End-to-end: CRUD, the busy rule, availability finder, and access control."""
import os, sys
BASE = os.path.dirname(os.path.abspath(__file__))
for line in open(os.path.join(BASE, "..", ".env.local")):
    k, _, v = line.strip().partition("=")
    if k: os.environ[k] = v
sys.path.insert(0, os.path.join(BASE, "..", "api"))

from datetime import timedelta
from fastapi.testclient import TestClient
import index, _auth as auth, _db as db, _events as ev

c = TestClient(index.app)
fails = []
def check(name, cond):
    print(("PASS  " if cond else "FAIL  ") + name)
    if not cond: fails.append(name)

conn = db.connect()
with conn.cursor() as cur:            # clean slate
    cur.execute("DELETE FROM event_log"); cur.execute("DELETE FROM events")
conn.commit()

# ---- access control -----------------------------------------------------
check("calendar blocked without auth", c.get("/api/calendar").status_code == 401)
check("create blocked without auth",
      c.post("/api/events", json={"title":"x","start":"2026-08-01T10:00"}).status_code == 401)
check("public availability open", c.get("/api/availability").status_code == 200)
check("public finder open", c.get("/api/availability/find").status_code == 200)

# /sprivate may READ details but must not WRITE.
c.cookies.set(auth.cookie_name("sprivate"), auth.issue_token("sprivate"))
check("sprivate can read calendar", c.get("/api/calendar").status_code == 200)
check("sprivate CANNOT create",
      c.post("/api/events", json={"title":"x","start":"2026-08-01T10:00"}).status_code == 401)
check("sprivate CANNOT use Gemini",
      c.post("/api/gemini/chat", json={"message":"hi"}).status_code == 401)
c.cookies.clear()

# ---- CRUD as /s ---------------------------------------------------------
c.cookies.set(auth.cookie_name("s"), auth.issue_token("s"))
base = (ev.now() + timedelta(days=10)).replace(hour=14, minute=0, second=0, microsecond=0)
day = base.date().isoformat()

r = c.post("/api/events", json={"title":"Dentist","start":base.isoformat(),
                                "end":(base+timedelta(hours=1)).isoformat(),
                                "importance":"critical","notes":"molar"})
check("create event", r.status_code == 200)
eid = r.json().get("id")
check("critical gets red colour", r.json().get("color") == ev.IMPORTANCE_COLOR["critical"])

r = c.get("/api/calendar?start=%s&end=%s" % (day, day))
check("event appears in calendar", any(e["id"] == eid for e in r.json()["events"]))
check("1 critical marks day busy", r.json()["availability"][day]["busy"] is True)

r = c.patch("/api/events/%d" % eid, json={"importance":"low"})
check("patch importance", r.status_code == 200 and r.json()["importance"] == "low")
r = c.get("/api/calendar?start=%s&end=%s" % (day, day))
check("1 low does NOT mark busy", r.json()["availability"][day]["busy"] is False)

check("bad importance rejected",
      c.patch("/api/events/%d" % eid, json={"importance":"urgent"}).status_code == 400)
check("end-before-start rejected",
      c.post("/api/events", json={"title":"bad","start":base.isoformat(),
             "end":(base-timedelta(hours=1)).isoformat(),"importance":"mid"}).status_code == 400)
check("patch missing event 404", c.patch("/api/events/999999", json={"title":"x"}).status_code == 404)

# ---- the 3-mid busy rule ------------------------------------------------
d2 = (ev.now() + timedelta(days=11)).replace(hour=9, minute=0, second=0, microsecond=0)
d2day = d2.date().isoformat()
ids = []
for i in range(3):
    s = d2 + timedelta(hours=i*2)
    rr = c.post("/api/events", json={"title":"m%d"%i,"start":s.isoformat(),
                "end":(s+timedelta(hours=1)).isoformat(),"importance":"mid"})
    ids.append(rr.json()["id"])
    got = c.get("/api/calendar?start=%s&end=%s"%(d2day,d2day)).json()["availability"][d2day]["busy"]
    check("%d mid -> busy=%s" % (i+1, i+1>=3), got == (i+1 >= 3))

# ---- public leak check --------------------------------------------------
c.cookies.clear()
pub = c.get("/api/availability?start=%s&end=%s" % (d2day, d2day)).json()
check("public returns no event objects", pub["events"] == [])
check("public still reports busy", pub["availability"][d2day]["busy"] is True)
check("public page HTML has no event titles", "Dentist" not in c.get("/spublic").text)

# ---- availability finder ------------------------------------------------
f = c.get("/api/availability/find?day_type=any&band=morning").json()
check("finder returns a slot", f.get("found") is True)
check("finder skips the busy day", f.get("date") != d2day)
check("finder rejects bad band",
      c.get("/api/availability/find?band=midnight").status_code == 400)

# ---- log + memory -------------------------------------------------------
with conn.cursor() as cur:
    cur.execute("SELECT action, count(*) n FROM event_log GROUP BY action")
    log = {r["action"]: r["n"] for r in cur.fetchall()}
check("creates logged", log.get("create") == 4)
check("update logged", log.get("update") == 1)

c.cookies.set(auth.cookie_name("s"), auth.issue_token("s"))
c.delete("/api/events/%d" % eid)
with conn.cursor() as cur:
    cur.execute("SELECT count(*) n FROM event_log WHERE action='delete'")
    check("delete logged (survives row removal)", cur.fetchone()["n"] == 1)
check("deleted event gone", c.get("/api/calendar?start=%s&end=%s"%(day,day)).json()["events"] == [])

mem = ev.build_memory(conn)
check("memory lists upcoming", "m0" in mem and "[id:" in mem)
check("memory excludes deleted", "Dentist" not in mem)

# Past events leave active memory but stay logged.
past = ev.now() - timedelta(days=3)
p = ev.create_event(conn, "OldThing", past, past+timedelta(hours=1), "mid")
check("past event excluded from memory", "OldThing" not in ev.build_memory(conn))
ev.archive_passed(conn)
with conn.cursor() as cur:
    cur.execute("SELECT count(*) n FROM event_log WHERE action='passed' AND event_id=%s",(p["id"],))
    check("passed event archived to log", cur.fetchone()["n"] == 1)
ev.archive_passed(conn)
with conn.cursor() as cur:
    cur.execute("SELECT count(*) n FROM event_log WHERE action='passed' AND event_id=%s",(p["id"],))
    check("archive is idempotent", cur.fetchone()["n"] == 1)

# cleanup
with conn.cursor() as cur:
    cur.execute("DELETE FROM event_log"); cur.execute("DELETE FROM events")
conn.commit(); conn.close()

print()
print("FAILED: " + ", ".join(fails) if fails else "ALL CHECKS PASSED")
sys.exit(1 if fails else 0)
