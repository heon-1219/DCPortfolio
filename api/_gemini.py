"""Gemini integration: conversational CRUD via function calling.

The API key is held server-side only. It is stored in app_settings and never
returned to the browser — the client only ever learns whether a key is present.

Function calling is used rather than freeform text parsing because dates and
mutations must be unambiguous; a model improvising JSON in prose is not a
foundation for deleting someone's calendar entries.
"""

import json
import time
import urllib.error
import urllib.request
from datetime import datetime, timedelta

import _events as events

API_ROOT = "https://generativelanguage.googleapis.com/v1beta/models"
# Editable at runtime so a model rename or an exhausted quota does not require
# a code change. 2.0-flash was the original default; its free-tier daily quota
# runs out quickly, and 2.5-flash-lite is no longer offered to new keys.
DEFAULT_MODEL = "gemini-2.5-flash"

# Offered in the UI picker. Which of these a given key may actually call is not
# knowable from the name: Google allocates free-tier quota per model per
# project, and a retired model reports 429 on its very first request (it fails
# the per-minute limit, which usage alone cannot exhaust). So the UI probes the
# real key rather than trusting this list — see probe_models().
MODEL_CHOICES = [
    "gemini-2.5-flash",
    "gemini-2.5-pro",
    "gemini-2.0-flash",
    "gemini-2.0-flash-lite",
]

# Tried in order when the selected model turns out to be quota-blocked.
FALLBACK_ORDER = ["gemini-2.5-flash", "gemini-2.5-pro", "gemini-2.0-flash"]

SETTING_KEY = "gemini_api_key"
SETTING_MODEL = "gemini_model"


class GeminiError(RuntimeError):
    pass


class InvalidKey(GeminiError):
    """Raised when Gemini rejects the stored key, so the UI can re-prompt."""


class QuotaExceeded(GeminiError):
    """Free-tier quota or rate limit hit (HTTP 429).

    Distinct from InvalidKey: the key is fine, so it must NOT be cleared —
    wiping a working key over a temporary rate limit would be a nasty
    surprise. Surfaced separately so the UI can advise waiting or switching
    model instead of asking for a new key.
    """


# --- key storage ---------------------------------------------------------


def save_key(conn, key: str) -> None:
    with conn.cursor() as cur:
        cur.execute(
            "INSERT INTO app_settings (key, value, updated_at) VALUES (%s, %s, now()) "
            "ON CONFLICT (key) DO UPDATE SET value = EXCLUDED.value, updated_at = now()",
            (SETTING_KEY, key.strip()),
        )
    conn.commit()


def get_key(conn):
    with conn.cursor() as cur:
        cur.execute("SELECT value FROM app_settings WHERE key = %s", (SETTING_KEY,))
        row = cur.fetchone()
    return row["value"] if row else None


def clear_key(conn) -> None:
    with conn.cursor() as cur:
        cur.execute("DELETE FROM app_settings WHERE key = %s", (SETTING_KEY,))
    conn.commit()


def get_model(conn) -> str:
    with conn.cursor() as cur:
        cur.execute("SELECT value FROM app_settings WHERE key = %s", (SETTING_MODEL,))
        row = cur.fetchone()
    return row["value"] if row else DEFAULT_MODEL


def set_model(conn, model: str) -> None:
    with conn.cursor() as cur:
        cur.execute(
            "INSERT INTO app_settings (key, value, updated_at) VALUES (%s, %s, now()) "
            "ON CONFLICT (key) DO UPDATE SET value = EXCLUDED.value, updated_at = now()",
            (SETTING_MODEL, model.strip()),
        )
    conn.commit()


# --- tool schema ---------------------------------------------------------

TOOLS = [
    {
        "function_declarations": [
            {
                "name": "create_event",
                "description": (
                    "Create a calendar event. If the user has not stated the "
                    "importance, do NOT guess: ask them whether it is critical, "
                    "mid, or low before calling this."
                ),
                "parameters": {
                    "type": "object",
                    "properties": {
                        "title": {"type": "string"},
                        "start": {
                            "type": "string",
                            "description": "ISO 8601 local start, e.g. 2026-07-28T14:00:00",
                        },
                        "end": {
                            "type": "string",
                            "description": "ISO 8601 local end. Default 1h after start.",
                        },
                        "importance": {
                            "type": "string",
                            "enum": list(events.IMPORTANCE),
                        },
                        "notes": {"type": "string"},
                    },
                    "required": ["title", "start", "importance"],
                },
            },
            {
                "name": "update_event",
                "description": "Update an existing event by id.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "id": {"type": "integer"},
                        "title": {"type": "string"},
                        "start": {"type": "string"},
                        "end": {"type": "string"},
                        "importance": {"type": "string", "enum": list(events.IMPORTANCE)},
                        "notes": {"type": "string"},
                    },
                    "required": ["id"],
                },
            },
            {
                "name": "delete_event",
                "description": "Delete an event by id.",
                "parameters": {
                    "type": "object",
                    "properties": {"id": {"type": "integer"}},
                    "required": ["id"],
                },
            },
            {
                "name": "list_events",
                "description": "List events between two ISO dates.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "start": {"type": "string"},
                        "end": {"type": "string"},
                    },
                    "required": ["start", "end"],
                },
            },
        ]
    }
]


def system_prompt(memory: str) -> str:
    return f"""You manage the user's calendar. Timezone is Asia/Seoul.

Rules:
- Importance is one of: critical, mid, low. If the user does not say which,
  ASK them before creating the event. Never silently guess.
- Resolve relative dates ("tomorrow", "next Friday") against the current time
  given below.
- If no end time is given, default to one hour after the start.
- Be brief and concrete. After a change, confirm what you did in one sentence.
- Use the [id:N] markers in the schedule below to target updates and deletes.

Current schedule context:

{memory}
"""


# --- tool dispatch -------------------------------------------------------


def _parse_dt(value: str) -> datetime:
    text = (value or "").strip().replace("Z", "+00:00")
    parsed = datetime.fromisoformat(text)
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=events.TZ)
    return parsed.astimezone(events.TZ)


def run_tool(conn, name: str, args: dict) -> dict:
    try:
        if name == "create_event":
            start = _parse_dt(args["start"])
            end = _parse_dt(args["end"]) if args.get("end") else start + timedelta(hours=1)
            created = events.create_event(
                conn,
                title=args["title"],
                starts_at=start,
                ends_at=end,
                importance=args["importance"],
                notes=args.get("notes", ""),
                actor="gemini",
            )
            return {"ok": True, "event": created}

        if name == "update_event":
            fields = {}
            if args.get("title"):
                fields["title"] = args["title"]
            if args.get("start"):
                fields["starts_at"] = _parse_dt(args["start"])
            if args.get("end"):
                fields["ends_at"] = _parse_dt(args["end"])
            if args.get("importance"):
                fields["importance"] = args["importance"]
            if args.get("notes") is not None:
                fields["notes"] = args["notes"]
            updated = events.update_event(conn, int(args["id"]), actor="gemini", **fields)
            if not updated:
                return {"ok": False, "error": "No event with that id."}
            return {"ok": True, "event": updated}

        if name == "delete_event":
            ok = events.delete_event(conn, int(args["id"]), actor="gemini")
            return {"ok": ok, "error": None if ok else "No event with that id."}

        if name == "list_events":
            found = events.list_events(
                conn, _parse_dt(args["start"]), _parse_dt(args["end"])
            )
            return {"ok": True, "events": found}

        return {"ok": False, "error": f"Unknown tool {name}"}
    except (ValueError, KeyError) as exc:
        # Hand the failure back to the model so it can correct itself.
        return {"ok": False, "error": str(exc)}


# --- transport -----------------------------------------------------------


def _post(url: str, payload: dict) -> dict:
    request = urllib.request.Request(
        url,
        data=json.dumps(payload).encode(),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=45) as response:
            return json.loads(response.read())
    except urllib.error.HTTPError as exc:
        body = exc.read().decode(errors="replace")
        if exc.code == 429:
            raise QuotaExceeded(body[:300]) from exc
        if exc.code == 404 and "no longer available" in body:
            raise GeminiError(
                "That model is no longer available for this key. "
                "Pick a different one in the model selector."
            ) from exc
        if exc.code in (400, 401, 403) and (
            "API_KEY" in body or "API key" in body or exc.code == 403
        ):
            raise InvalidKey(body[:300]) from exc
        raise GeminiError(f"Gemini HTTP {exc.code}: {body[:300]}") from exc
    except urllib.error.URLError as exc:
        raise GeminiError(f"Could not reach Gemini: {exc.reason}") from exc


def validate_key(key: str) -> None:
    """Check a key before storing it, so a bad paste fails loudly and at once.

    Uses ListModels rather than generateContent: it proves the credential works
    without consuming any generation quota, so validating can never itself
    cause a rate-limit error.
    """
    url = f"{API_ROOT.rsplit('/', 1)[0]}/models?key={key}"
    request = urllib.request.Request(url, method="GET")
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            json.loads(response.read())
    except urllib.error.HTTPError as exc:
        body = exc.read().decode(errors="replace")
        if exc.code in (400, 401, 403):
            hint = ""
            if not key.startswith("AIza"):
                hint = (
                    " That does not look like an AI Studio API key — they begin "
                    "with 'AIza'. Check you copied the key itself and not an "
                    "OAuth client secret or project ID."
                )
            raise InvalidKey(f"Google rejected this key.{hint}") from exc
        raise GeminiError(f"Could not verify key (HTTP {exc.code}): {body[:150]}") from exc
    except urllib.error.URLError as exc:
        raise GeminiError(f"Could not reach Gemini: {exc.reason}") from exc


def probe_models(key: str) -> dict:
    """Ask the key itself which models it can call.

    Model names alone do not tell you this — free-tier quota is granted per
    model per project, so a name that works on one key 429s on another.
    A blocked model fails instantly and costs nothing; a working one spends a
    single tiny request, so this is only run on demand.
    """
    payload = {
        "contents": [{"role": "user", "parts": [{"text": "hi"}]}],
        "generationConfig": {"maxOutputTokens": 1},
    }
    # Verify the credential first. Without this, a bad key makes every model
    # look quota-blocked, which points the user at the wrong problem entirely.
    validate_key(key)

    results = {}
    for index, model in enumerate(MODEL_CHOICES):
        if index:
            # Pace the calls: firing the whole list back-to-back can trip the
            # per-minute limit and mislabel a working model as blocked.
            time.sleep(1.5)
        try:
            _post(f"{API_ROOT}/{model}:generateContent?key={key}", payload)
            results[model] = "ok"
        except QuotaExceeded:
            results[model] = "blocked"
        except GeminiError:
            results[model] = "unavailable"
    return results


def chat(conn, message: str, history: list) -> dict:
    """One conversational turn, resolving any tool calls Gemini requests."""
    key = get_key(conn)
    if not key:
        raise GeminiError("No Gemini API key saved yet.")

    model = get_model(conn)
    switched_from = None
    # A model can be quota-blocked from the very first call, so verify the
    # selection is usable before burning the (larger) real request on it.
    try:
        _post(
            f"{API_ROOT}/{model}:generateContent?key={key}",
            {
                "contents": [{"role": "user", "parts": [{"text": "hi"}]}],
                "generationConfig": {"maxOutputTokens": 1},
            },
        )
    except QuotaExceeded:
        for candidate in FALLBACK_ORDER:
            if candidate == model:
                continue
            try:
                _post(
                    f"{API_ROOT}/{candidate}:generateContent?key={key}",
                    {
                        "contents": [{"role": "user", "parts": [{"text": "hi"}]}],
                        "generationConfig": {"maxOutputTokens": 1},
                    },
                )
            except GeminiError:
                continue
            switched_from, model = model, candidate
            set_model(conn, candidate)
            break
        else:
            raise
    except GeminiError:
        pass  # Not a quota problem; let the real request surface it.

    url = f"{API_ROOT}/{model}:generateContent?key={key}"

    memory = events.build_memory(conn)
    contents = []
    for turn in history[-12:]:
        role = "model" if turn.get("role") == "model" else "user"
        contents.append({"role": role, "parts": [{"text": turn.get("text", "")}]})
    contents.append({"role": "user", "parts": [{"text": message}]})

    payload = {
        "systemInstruction": {"parts": [{"text": system_prompt(memory)}]},
        "contents": contents,
        "tools": TOOLS,
    }

    actions = []
    # Allow a few rounds so multi-step requests ("move X and delete Y") resolve.
    for _ in range(5):
        data = _post(url, payload)
        candidates = data.get("candidates") or []
        if not candidates:
            raise GeminiError("Gemini returned no response.")
        parts = candidates[0].get("content", {}).get("parts", []) or []

        calls = [p["functionCall"] for p in parts if "functionCall" in p]
        if not calls:
            text = "".join(p.get("text", "") for p in parts).strip()
            return {
                "reply": text or "(no reply)",
                "actions": actions,
                "model": model,
                "switched_from": switched_from,
            }

        contents.append({"role": "model", "parts": parts})
        responses = []
        for call in calls:
            name = call.get("name", "")
            args = call.get("args", {}) or {}
            result = run_tool(conn, name, args)
            actions.append({"tool": name, "args": args, "result": result})
            responses.append(
                {"functionResponse": {"name": name, "response": {"result": result}}}
            )
        contents.append({"role": "user", "parts": responses})
        payload["contents"] = contents

    return {
        "reply": "Stopped after too many tool steps.",
        "actions": actions,
        "model": model,
        "switched_from": switched_from,
    }
