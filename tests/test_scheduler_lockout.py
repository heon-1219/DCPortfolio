"""Verify the 3-strike lockout against a real database.

Counters live in Postgres because serverless memory does not persist between
invocations; an in-process counter would silently reset and defeat the lock.
"""
import os, sys
for line in open(os.path.join(os.path.dirname(__file__), "..", ".env.local")):
    k, _, v = line.strip().partition("=")
    if k: os.environ[k] = v
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "api"))

from fastapi.testclient import TestClient
import index, _auth as auth, _db as db

TEST_IP = "203.0.113.77"          # TEST-NET-3, never a real client
HDR = {"x-forwarded-for": TEST_IP}
c = TestClient(index.app, follow_redirects=False)

fails = []
def check(name, cond):
    print(("PASS  " if cond else "FAIL  ") + name)
    if not cond: fails.append(name)

def reset():
    conn = db.connect()
    auth.clear_failures(conn, "s", TEST_IP)
    conn.close()

reset()

# Three wrong attempts, counting down.
r1 = c.post("/api/login", data={"scope": "s", "password": "0000"}, headers=HDR)
check("1st wrong attempt -> 401", r1.status_code == 401)
check("1st says 2 tries left", "2 tries left" in r1.text)

r2 = c.post("/api/login", data={"scope": "s", "password": "0000"}, headers=HDR)
check("2nd says 1 try left", "1 try left" in r2.text)

r3 = c.post("/api/login", data={"scope": "s", "password": "0000"}, headers=HDR)
check("3rd attempt locks out (429)", r3.status_code == 429)
check("3rd reports the lock", "Locked" in r3.text)

# The critical property: the CORRECT password must be refused while locked.
r4 = c.post("/api/login", data={"scope": "s", "password": "1219"}, headers=HDR)
check("correct password REFUSED while locked", r4.status_code == 429)
check("no session cookie issued while locked",
      not any("sched_s" in v for v in r4.headers.get_list("set-cookie")))

# A different IP must not inherit the lock.
r5 = c.post("/api/login", data={"scope": "s", "password": "1219"},
            headers={"x-forwarded-for": "203.0.113.99"})
check("different IP unaffected by lock (303 redirect)", r5.status_code == 303)
check("correct password issues session",
      any("sched_s" in v for v in r5.headers.get_list("set-cookie")))

# Clearing failures restores access.
reset()
r6 = c.post("/api/login", data={"scope": "s", "password": "1219"}, headers=HDR)
check("access restored after lock cleared", r6.status_code == 303)

# Wrong scope password must not cross over.
reset()
r7 = c.post("/api/login", data={"scope": "sprivate", "password": "1219"}, headers=HDR)
check("/s password rejected on /sprivate", r7.status_code == 401)

# Cleanup so real logins start clean.
reset()
conn = db.connect()
auth.clear_failures(conn, "s", "203.0.113.99")
auth.clear_failures(conn, "sprivate", TEST_IP)
conn.close()

print()
print("FAILED: " + ", ".join(fails) if fails else "ALL CHECKS PASSED")
sys.exit(1 if fails else 0)
