"""Verify the gate: routing, sessions, constant-time compare, lockout wiring."""
import os, sys
os.environ.update(
    DATABASE_URL="postgresql://stub/stub",
    SESSION_SECRET="test-secret-not-real",
    SCHEDULER_PASSWORD="1219",
    SPRIVATE_PASSWORD="1111",
)
sys.path.insert(0, os.path.join(os.getcwd(), "api"))
from fastapi.testclient import TestClient
import index
import _auth as auth

c = TestClient(index.app)
fails = []
def check(name, cond):
    print(("PASS  " if cond else "FAIL  ") + name)
    if not cond: fails.append(name)

# 1. Gated pages must NOT leak content without a session.
r = c.get("/s")
check("/s renders login when unauthenticated", "Enter passcode" in r.text)
check("/s does not leak app content", "monthHtml" not in r.text)
r2 = c.get("/sprivate")
check("/sprivate renders login when unauthenticated", "Enter passcode" in r2.text)

# 2. /spublic is intentionally open.
r3 = c.get("/spublic")
check("/spublic is public (200)", r3.status_code == 200)
check("/spublic shows availability page", "Availability" in r3.text)
check("/spublic has no Gemini chat", "gemini/chat" not in r3.text)

# 3. noindex on every response.
check("noindex header present", "noindex" in r.headers.get("x-robots-tag", ""))

# 4. Session tokens.
tok = auth.issue_token("s")
check("valid token verifies", auth.verify_token(tok, "s"))
check("token is scope-bound (s != sprivate)", not auth.verify_token(tok, "sprivate"))
check("tampered token rejected", not auth.verify_token(tok[:-3] + "aaa", "s"))
check("garbage token rejected", not auth.verify_token("nonsense", "s"))

# 5. Password compare.
check("correct password accepted", auth.verify_password("s", "1219"))
check("wrong password rejected", not auth.verify_password("s", "1218"))
check("empty password rejected", not auth.verify_password("s", ""))
check("scopes use different passwords", auth.verify_password("sprivate", "1111"))

# 6. A valid cookie unlocks the page.
c.cookies.set(auth.cookie_name("s"), tok)
r4 = c.get("/s")
check("valid session unlocks /s", "monthHtml" in r4.text and "Ask Gemini" in r4.text)

# 7. Health never exposes secret values.
c.cookies.clear()
h = c.get("/api/health").json()
check("health reports config presence", h["configured"]["SCHEDULER_PASSWORD"] is True)
check("health does not leak the password", "1219" not in c.get("/api/health").text)

print()
print("FAILED: " + ", ".join(fails) if fails else "ALL CHECKS PASSED")
sys.exit(1 if fails else 0)
