"""Password gate, signed sessions, and lockout for the hidden scheduler.

Passwords are never hardcoded; they are read from the environment and compared
in constant time. Sessions are HMAC-signed tokens carried in an HTTP-only
cookie, so a stolen page render cannot be replayed without the secret.
"""

import base64
import hashlib
import hmac
import json
import os
import time
from datetime import datetime, timedelta, timezone

import _db as db

# Scopes map a page to the env var holding its password.
SCOPES = {
    "s": "SCHEDULER_PASSWORD",
    "sprivate": "SPRIVATE_PASSWORD",
}

MAX_FAILURES = 3
LOCKOUT_MINUTES = 15
SESSION_TTL_DAYS = 30
COOKIE_PREFIX = "sched_"


class AuthError(RuntimeError):
    pass


class LockedOut(AuthError):
    def __init__(self, seconds_remaining: int):
        self.seconds_remaining = seconds_remaining
        super().__init__(f"Locked out for {seconds_remaining}s")


def _session_secret() -> bytes:
    secret = os.environ.get("SESSION_SECRET")
    if not secret:
        raise db.ConfigError("SESSION_SECRET is not set")
    return secret.encode()


def expected_password(scope: str) -> str:
    env_var = SCOPES.get(scope)
    if not env_var:
        raise AuthError(f"Unknown scope: {scope}")
    value = os.environ.get(env_var)
    if not value:
        raise db.ConfigError(f"{env_var} is not set")
    return value


# --- lockout -------------------------------------------------------------


def _now() -> datetime:
    return datetime.now(timezone.utc)


def check_lockout(conn, scope: str, client_id: str) -> None:
    """Raise LockedOut if this client is currently barred."""
    with conn.cursor() as cur:
        cur.execute(
            "SELECT locked_until FROM login_attempts "
            "WHERE scope = %s AND client_id = %s",
            (scope, client_id),
        )
        row = cur.fetchone()
    if not row or not row["locked_until"]:
        return
    remaining = (row["locked_until"] - _now()).total_seconds()
    if remaining > 0:
        raise LockedOut(int(remaining) + 1)


def record_failure(conn, scope: str, client_id: str) -> int:
    """Count a failed attempt; lock the client once MAX_FAILURES is hit.

    Returns how many attempts remain before lockout (0 once locked).
    """
    locked_until = _now() + timedelta(minutes=LOCKOUT_MINUTES)
    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO login_attempts (scope, client_id, failures, updated_at)
            VALUES (%s, %s, 1, now())
            ON CONFLICT (scope, client_id) DO UPDATE
                SET failures = login_attempts.failures + 1,
                    updated_at = now(),
                    locked_until = CASE
                        WHEN login_attempts.failures + 1 >= %s THEN %s
                        ELSE login_attempts.locked_until
                    END
            RETURNING failures
            """,
            (scope, client_id, MAX_FAILURES, locked_until),
        )
        failures = cur.fetchone()["failures"]
    conn.commit()
    return max(0, MAX_FAILURES - failures)


def clear_failures(conn, scope: str, client_id: str) -> None:
    with conn.cursor() as cur:
        cur.execute(
            "DELETE FROM login_attempts WHERE scope = %s AND client_id = %s",
            (scope, client_id),
        )
    conn.commit()


# --- sessions ------------------------------------------------------------


def _b64e(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).decode().rstrip("=")


def _b64d(text: str) -> bytes:
    return base64.urlsafe_b64decode(text + "=" * (-len(text) % 4))


def issue_token(scope: str) -> str:
    payload = json.dumps(
        {"scope": scope, "exp": int(time.time()) + SESSION_TTL_DAYS * 86400},
        separators=(",", ":"),
    ).encode()
    body = _b64e(payload)
    sig = hmac.new(_session_secret(), body.encode(), hashlib.sha256).digest()
    return f"{body}.{_b64e(sig)}"


def verify_token(token: str, scope: str) -> bool:
    if not token or "." not in token:
        return False
    body, _, sig = token.partition(".")
    expected = hmac.new(_session_secret(), body.encode(), hashlib.sha256).digest()
    try:
        if not hmac.compare_digest(expected, _b64d(sig)):
            return False
        payload = json.loads(_b64d(body))
    except Exception:
        return False
    if payload.get("scope") != scope:
        return False
    return int(payload.get("exp", 0)) > time.time()


def verify_password(scope: str, supplied: str) -> bool:
    """Constant-time compare so response timing cannot leak the password."""
    return hmac.compare_digest(supplied or "", expected_password(scope))


def cookie_name(scope: str) -> str:
    return f"{COOKIE_PREFIX}{scope}"


def client_id(request) -> str:
    """Identify the caller for lockout purposes.

    Vercel terminates TLS upstream, so the real client IP arrives in
    X-Forwarded-For; request.client.host would be a proxy hop.
    """
    forwarded = request.headers.get("x-forwarded-for", "")
    if forwarded:
        return forwarded.split(",")[0].strip()
    return getattr(request.client, "host", "unknown") or "unknown"
