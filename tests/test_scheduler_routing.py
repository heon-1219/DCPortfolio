"""Routing: signing in on /s must land on /s, never /sprivate."""
import os, sys
BASE = os.path.dirname(os.path.abspath(__file__))
for line in open(os.path.join(BASE, "..", ".env.local")):
    k, _, v = line.strip().partition("=")
    if k: os.environ[k] = v
sys.path.insert(0, os.path.join(BASE, "..", "api"))

from fastapi.testclient import TestClient
import index, _auth as auth, _db as db, _ui as ui

c = TestClient(index.app, follow_redirects=False)
fails = []
def check(name, cond):
    print(("PASS  " if cond else "FAIL  ") + name)
    if not cond: fails.append(name)

conn = db.connect(); auth.clear_failures(conn, "s", "testclient")
auth.clear_failures(conn, "sprivate", "testclient"); conn.close()

# The /s login form must declare /s as its destination.
page = c.get("/s").text
check("/s login form targets /s", 'name="next" value="/s"' in page)
check("/s login form scope is s", 'name="scope" value="s"' in page)
priv = c.get("/sprivate").text
check("/sprivate form targets /sprivate", 'name="next" value="/sprivate"' in priv)

# Signing in on /s lands on /s.
r = c.post("/api/login", data={"scope": "s", "password": "1219", "next": "/s"})
check("login on /s redirects to /s", r.headers.get("location") == "/s")

# A stale/tampered `next` must not divert the user.
r2 = c.post("/api/login", data={"scope": "s", "password": "1219", "next": "/sprivate"})
check("mismatched next ignored -> still /s", r2.headers.get("location") == "/s")
r3 = c.post("/api/login", data={"scope": "s", "password": "1219", "next": "https://evil.example/x"})
check("external next ignored -> still /s", r3.headers.get("location") == "/s")
r4 = c.post("/api/login", data={"scope": "s", "password": "1219"})
check("absent next -> /s", r4.headers.get("location") == "/s")

# sprivate still works correctly.
r5 = c.post("/api/login", data={"scope": "sprivate", "password": "1111", "next": "/sprivate"})
check("login on /sprivate redirects to /sprivate", r5.headers.get("location") == "/sprivate")

# Authenticated HTML must not be cacheable by a CDN or shared proxy.
c.cookies.set(auth.cookie_name("s"), auth.issue_token("s"))
h = c.get("/s")
cc = h.headers.get("cache-control", "")
check("no-store on authenticated page", "no-store" in cc)
check("not publicly cacheable", "public" not in cc)

# Buttons must be explicitly typed; an untyped button submits by default.
for name, html in [("/s", ui.scheduler_page()), ("/sprivate", ui.private_page()),
                   ("/spublic", ui.public_page())]:
    import re
    untyped = re.findall(r'<button(?![^>]*\btype=)[^>]*>', html)
    check(f"{name} has no untyped buttons", not untyped)
    check(f"{name} contains no link to another scheduler page",
          'href="/sprivate"' not in html and 'href="/s"' not in html)

# --- month grid: neighbouring-month days stay usable ---------------------
for name, html in [("/s", ui.scheduler_page()), ("/spublic", ui.public_page())]:
    check(f"{name} does not fade out-of-month cells",
          ".cell.dim { opacity" not in html)
    check(f"{name} de-emphasises only the day number",
          ".cell.dim .num" in html)
    check(f"{name} binds a click on every cell",
          'querySelectorAll(".cell").forEach' in html)
    check(f"{name} supports swipe between periods", "bindSwipe" in html)
    # A spill-over tap must reload data for the month it belongs to.
    check(f"{name} reloads after selecting a day",
          'view = "day"; load();' in html)

conn = db.connect(); auth.clear_failures(conn, "s", "testclient")
auth.clear_failures(conn, "sprivate", "testclient"); conn.close()

print()
print("FAILED: " + ", ".join(fails) if fails else "ALL CHECKS PASSED")
sys.exit(1 if fails else 0)
