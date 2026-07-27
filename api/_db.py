"""Neon Postgres access for the hidden scheduler.

Connections are opened per request rather than pooled: Vercel functions are
short-lived and Neon's pooled endpoint already fronts the database.
"""

import os
import threading

import psycopg
from psycopg.rows import dict_row

_schema_ready = False
_schema_lock = threading.Lock()


class ConfigError(RuntimeError):
    """Raised when required environment configuration is missing."""


def database_url() -> str:
    url = os.environ.get("DATABASE_URL")
    if not url:
        raise ConfigError("DATABASE_URL is not set")
    return url


SCHEMA = """
CREATE TABLE IF NOT EXISTS events (
    id           BIGSERIAL PRIMARY KEY,
    title        TEXT        NOT NULL,
    starts_at    TIMESTAMPTZ NOT NULL,
    ends_at      TIMESTAMPTZ NOT NULL,
    importance   TEXT        NOT NULL DEFAULT 'mid',
    notes        TEXT,
    created_at   TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at   TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT events_time_order CHECK (ends_at > starts_at),
    CONSTRAINT events_importance CHECK (importance IN ('critical', 'mid', 'low'))
);

CREATE INDEX IF NOT EXISTS events_starts_at_idx ON events (starts_at);

-- Append-only history. Passed events leave Gemini's active context but are
-- never destroyed; every mutation lands here too.
CREATE TABLE IF NOT EXISTS event_log (
    id          BIGSERIAL PRIMARY KEY,
    event_id    BIGINT,
    action      TEXT        NOT NULL,
    snapshot    JSONB,
    actor       TEXT        NOT NULL DEFAULT 'user',
    logged_at   TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS event_log_logged_at_idx ON event_log (logged_at);

-- Reminders drained by the systemd loop on the always-on server.
CREATE TABLE IF NOT EXISTS reminders (
    id          BIGSERIAL PRIMARY KEY,
    event_id    BIGINT      NOT NULL REFERENCES events (id) ON DELETE CASCADE,
    remind_at   TIMESTAMPTZ NOT NULL,
    sent_at     TIMESTAMPTZ,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS reminders_pending_idx
    ON reminders (remind_at) WHERE sent_at IS NULL;

-- Server-side secrets (the Gemini key). Never returned to the browser.
CREATE TABLE IF NOT EXISTS app_settings (
    key         TEXT PRIMARY KEY,
    value       TEXT        NOT NULL,
    updated_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- Failed-login tracking. Must be in Postgres: serverless memory does not
-- survive between invocations, so an in-process counter would reset and
-- silently defeat the lockout.
CREATE TABLE IF NOT EXISTS login_attempts (
    scope         TEXT        NOT NULL,
    client_id     TEXT        NOT NULL,
    failures      INT         NOT NULL DEFAULT 0,
    locked_until  TIMESTAMPTZ,
    updated_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (scope, client_id)
);
"""


def connect():
    conn = psycopg.connect(database_url(), row_factory=dict_row)
    ensure_schema(conn)
    return conn


def ensure_schema(conn) -> None:
    """Create tables once per warm function instance."""
    global _schema_ready
    if _schema_ready:
        return
    with _schema_lock:
        if _schema_ready:
            return
        with conn.cursor() as cur:
            cur.execute(SCHEMA)
        conn.commit()
        _schema_ready = True
