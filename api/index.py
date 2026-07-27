"""Hidden scheduler — Vercel serverless entrypoint.

The page HTML is rendered *by this function, behind the gate*, deliberately:
a static file at /s/index.html would be served to anyone who guessed the URL,
which would defeat the whole point of the page being hidden.
"""

import os
import sys
from datetime import date, datetime, time, timedelta

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from fastapi import Body, FastAPI, Form, HTTPException, Request, Response  # noqa: E402
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse  # noqa: E402

import _auth as auth  # noqa: E402
import _db as db  # noqa: E402
import _events as events  # noqa: E402
import _gemini as gemini  # noqa: E402
import _pages as pages  # noqa: E402
import _ui as ui  # noqa: E402

app = FastAPI(docs_url=None, redoc_url=None, openapi_url=None)

NOINDEX = {"X-Robots-Tag": "noindex, nofollow, noarchive"}


@app.middleware("http")
async def add_noindex(request: Request, call_next):
    response = await call_next(request)
    response.headers.update(NOINDEX)
    return response


def _is_authed(request: Request, scope: str) -> bool:
    return auth.verify_token(request.cookies.get(auth.cookie_name(scope), ""), scope)


def _detail_ok(request: Request) -> bool:
    """Either passcode may view event details; /s is the superset."""
    return _is_authed(request, "s") or _is_authed(request, "sprivate")


def _require_detail(request: Request) -> None:
    if not _detail_ok(request):
        raise HTTPException(status_code=401, detail="Not authorised.")


def _require_full(request: Request) -> None:
    if not _is_authed(request, "s"):
        raise HTTPException(status_code=401, detail="Not authorised.")


def _set_session(response: Response, scope: str) -> None:
    response.set_cookie(
        auth.cookie_name(scope),
        auth.issue_token(scope),
        max_age=auth.SESSION_TTL_DAYS * 86400,
        httponly=True,
        secure=True,
        samesite="lax",
        path="/",
    )


def _conn():
    try:
        return db.connect()
    except db.ConfigError as exc:
        raise HTTPException(status_code=500, detail=str(exc))


def _parse_day(value: str, fallback: date) -> date:
    try:
        return date.fromisoformat(value)
    except (TypeError, ValueError):
        return fallback


@app.get("/api/health")
def health():
    required = [
        "DATABASE_URL",
        "SESSION_SECRET",
        "SCHEDULER_PASSWORD",
        "SPRIVATE_PASSWORD",
    ]
    return {"ok": True, "configured": {n: bool(os.environ.get(n)) for n in required}}


# --- pages ---------------------------------------------------------------


@app.get("/s", response_class=HTMLResponse)
def s_page(request: Request):
    if not _is_authed(request, "s"):
        return HTMLResponse(pages.login_page("s", "/s"))
    return HTMLResponse(ui.scheduler_page())


@app.get("/sprivate", response_class=HTMLResponse)
def sprivate_page(request: Request):
    if not _detail_ok(request):
        return HTMLResponse(pages.login_page("sprivate", "/sprivate"))
    return HTMLResponse(ui.private_page())


@app.get("/spublic", response_class=HTMLResponse)
def spublic_page():
    # Availability only — intentionally unauthenticated.
    return HTMLResponse(ui.public_page())


# --- login ---------------------------------------------------------------


@app.post("/api/login")
def login(request: Request, scope: str = Form(...), password: str = Form(...)):
    if scope not in auth.SCOPES:
        return HTMLResponse(pages.login_page("s", "/s", error="Unknown page."), status_code=400)

    target = "/s" if scope == "s" else "/sprivate"
    caller = auth.client_id(request)

    try:
        conn = db.connect()
    except db.ConfigError as exc:
        return HTMLResponse(
            pages.login_page(scope, target, error=f"Server not configured: {exc}"),
            status_code=500,
        )

    try:
        try:
            auth.check_lockout(conn, scope, caller)
        except auth.LockedOut as exc:
            minutes = max(1, exc.seconds_remaining // 60)
            return HTMLResponse(
                pages.login_page(scope, target, error=f"Too many attempts. Try again in {minutes} min."),
                status_code=429,
            )

        if not auth.verify_password(scope, password):
            remaining = auth.record_failure(conn, scope, caller)
            if remaining <= 0:
                message, status = f"Incorrect. Locked for {auth.LOCKOUT_MINUTES} minutes.", 429
            else:
                plural = "try" if remaining == 1 else "tries"
                message, status = f"Incorrect. {remaining} {plural} left.", 401
            return HTMLResponse(pages.login_page(scope, target, error=message), status_code=status)

        auth.clear_failures(conn, scope, caller)
    finally:
        conn.close()

    response = RedirectResponse(target, status_code=303)
    _set_session(response, scope)
    return response


@app.post("/api/logout")
def logout(scope: str = Form("s")):
    target = "/s" if scope == "s" else "/sprivate"
    response = RedirectResponse(target, status_code=303)
    response.delete_cookie(auth.cookie_name(scope), path="/")
    return response


# --- calendar data -------------------------------------------------------


@app.get("/api/calendar")
def calendar(request: Request, start: str = "", end: str = ""):
    """Events plus availability. Requires a passcode — this exposes details."""
    _require_detail(request)
    today = events.now().date()
    start_day = _parse_day(start, today)
    end_day = _parse_day(end, today + timedelta(days=41))
    conn = _conn()
    try:
        events.archive_passed(conn)
        window_start = datetime.combine(start_day, time.min, events.TZ)
        window_end = datetime.combine(end_day + timedelta(days=1), time.min, events.TZ)
        return {
            "events": events.list_events(conn, window_start, window_end),
            "availability": events.availability_map(conn, start_day, end_day),
        }
    finally:
        conn.close()


@app.get("/api/availability")
def availability(start: str = "", end: str = ""):
    """Public: busy/free flags only. Deliberately returns no event details."""
    today = events.now().date()
    start_day = _parse_day(start, today)
    end_day = _parse_day(end, today + timedelta(days=41))
    conn = _conn()
    try:
        return {"events": [], "availability": events.availability_map(conn, start_day, end_day)}
    finally:
        conn.close()


@app.get("/api/availability/find")
def availability_find(day_type: str = "any", band: str = "morning"):
    """Public helper: soonest opening. No Gemini involved."""
    conn = _conn()
    try:
        return events.find_availability(conn, day_type, band)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    finally:
        conn.close()


# --- event CRUD ----------------------------------------------------------


def _dt(value: str):
    parsed = datetime.fromisoformat(value)
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=events.TZ)
    return parsed.astimezone(events.TZ)


@app.post("/api/events")
def create_event(request: Request, payload: dict = Body(...)):
    _require_full(request)
    conn = _conn()
    try:
        start = _dt(payload["start"])
        end = _dt(payload["end"]) if payload.get("end") else start + timedelta(hours=1)
        return events.create_event(
            conn,
            title=payload["title"],
            starts_at=start,
            ends_at=end,
            importance=payload.get("importance", "mid"),
            notes=payload.get("notes", ""),
        )
    except (KeyError, ValueError) as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    finally:
        conn.close()


@app.patch("/api/events/{event_id}")
def patch_event(event_id: int, request: Request, payload: dict = Body(...)):
    _require_full(request)
    conn = _conn()
    try:
        fields = {}
        if payload.get("title"):
            fields["title"] = payload["title"]
        if payload.get("start"):
            fields["starts_at"] = _dt(payload["start"])
        if payload.get("end"):
            fields["ends_at"] = _dt(payload["end"])
        if payload.get("importance"):
            fields["importance"] = payload["importance"]
        if payload.get("notes") is not None:
            fields["notes"] = payload["notes"]
        updated = events.update_event(conn, event_id, **fields)
        if not updated:
            raise HTTPException(status_code=404, detail="No such event.")
        return updated
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    finally:
        conn.close()


@app.delete("/api/events/{event_id}")
def remove_event(event_id: int, request: Request):
    _require_full(request)
    conn = _conn()
    try:
        if not events.delete_event(conn, event_id):
            raise HTTPException(status_code=404, detail="No such event.")
        return {"ok": True}
    finally:
        conn.close()


# --- settings & Gemini ---------------------------------------------------


@app.get("/api/settings")
def get_settings(request: Request):
    _require_full(request)
    conn = _conn()
    try:
        # Reports presence only. The key itself never leaves the server.
        return {
            "gemini_key_set": bool(gemini.get_key(conn)),
            "model": gemini.get_model(conn),
            "models": gemini.MODEL_CHOICES,
        }
    finally:
        conn.close()


@app.get("/api/settings/models/probe")
def probe_models(request: Request):
    """Ask the key which models it can actually call.

    Free-tier quota is granted per model per project, so the model list alone
    cannot tell us what will work — only the key can.
    """
    _require_full(request)
    conn = _conn()
    try:
        key = gemini.get_key(conn)
        if not key:
            raise HTTPException(status_code=428, detail="No Gemini API key saved yet.")
        try:
            return {"results": gemini.probe_models(key), "current": gemini.get_model(conn)}
        except gemini.InvalidKey as exc:
            raise HTTPException(status_code=428, detail=str(exc))
    finally:
        conn.close()


@app.post("/api/settings/model")
def set_model(request: Request, payload: dict = Body(...)):
    _require_full(request)
    model = (payload.get("model") or "").strip()
    if model not in gemini.MODEL_CHOICES:
        raise HTTPException(status_code=400, detail="Unknown model.")
    conn = _conn()
    try:
        gemini.set_model(conn, model)
        return {"ok": True, "model": model}
    finally:
        conn.close()


@app.post("/api/settings/gemini-key")
def set_gemini_key(request: Request, payload: dict = Body(...)):
    _require_full(request)
    key = (payload.get("key") or "").strip()
    if not key:
        raise HTTPException(status_code=400, detail="Key required.")
    conn = _conn()
    try:
        # Verify before storing. A bad paste previously sat in the database
        # and surfaced later as every model looking quota-blocked, which is a
        # deeply misleading way to learn the key was wrong.
        try:
            gemini.validate_key(key)
        except gemini.InvalidKey as exc:
            raise HTTPException(status_code=400, detail=str(exc))
        except gemini.GeminiError as exc:
            raise HTTPException(status_code=502, detail=str(exc))
        gemini.save_key(conn, key)
        return {"ok": True}
    finally:
        conn.close()


@app.post("/api/gemini/chat")
def gemini_chat(request: Request, payload: dict = Body(...)):
    _require_full(request)
    message = (payload.get("message") or "").strip()
    if not message:
        raise HTTPException(status_code=400, detail="Message required.")
    conn = _conn()
    try:
        if not gemini.get_key(conn):
            # 428 tells the UI to prompt for a key rather than show an error.
            raise HTTPException(status_code=428, detail="No Gemini API key saved yet.")
        return gemini.chat(conn, message, payload.get("history") or [])
    except gemini.QuotaExceeded:
        # The key is valid — do NOT clear it. This is a free-tier limit.
        model = gemini.get_model(conn)
        raise HTTPException(
            status_code=429,
            detail=(
                f"Free-tier quota hit on {model}. Daily quotas reset at midnight "
                "Pacific. Wait a minute for the per-minute limit, or pick another "
                "model above."
            ),
        )
    except gemini.InvalidKey:
        gemini.clear_key(conn)
        raise HTTPException(status_code=428, detail="Gemini rejected the key. Enter a new one.")
    except gemini.GeminiError as exc:
        raise HTTPException(status_code=502, detail=str(exc))
    finally:
        conn.close()


@app.exception_handler(HTTPException)
def http_error(request: Request, exc: HTTPException):
    return JSONResponse({"detail": exc.detail}, status_code=exc.status_code, headers=NOINDEX)
