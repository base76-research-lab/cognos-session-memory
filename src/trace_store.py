"""
Trace Store Module

SQLite-backed persistence for session traces.
Each trace records: decision, policy, trust_score, risk, metadata, envelope.

Used by /v1/plan to extract context from recent traces.
"""

from __future__ import annotations

import json
import os
import sqlite3
from typing import Any

DB_PATH = os.getenv("COGNOS_TRACE_DB", "data/traces.sqlite3")


# ── Initialization ─────────────────────────────────────────────────────────────


def init_db() -> None:
    """Initialize database schema."""
    os.makedirs(os.path.dirname(DB_PATH) or ".", exist_ok=True)
    with _conn() as c:
        c.execute("""
            CREATE TABLE IF NOT EXISTS traces (
                trace_id            TEXT PRIMARY KEY,
                created_at          TEXT NOT NULL,
                decision            TEXT,
                policy              TEXT,
                trust_score         REAL,
                risk                REAL,
                is_stream           INTEGER,
                status_code         INTEGER,
                model               TEXT,
                request_fingerprint TEXT,
                response_fingerprint TEXT,
                envelope            TEXT,
                metadata            TEXT
            )
        """)
        c.execute("""
            CREATE INDEX IF NOT EXISTS idx_created_at
            ON traces (created_at DESC)
        """)


# ── Write ──────────────────────────────────────────────────────────────────────


def save_trace(record: dict[str, Any]) -> None:
    """Save a trace record to the database."""
    with _conn() as c:
        c.execute("""
            INSERT OR REPLACE INTO traces (
                trace_id, created_at, decision, policy,
                trust_score, risk, is_stream, status_code, model,
                request_fingerprint, response_fingerprint,
                envelope, metadata
            ) VALUES (
                :trace_id, :created_at, :decision, :policy,
                :trust_score, :risk, :is_stream, :status_code, :model,
                :request_fingerprint, :response_fingerprint,
                :envelope, :metadata
            )
        """, {
            **record,
            "request_fingerprint": _dump(record.get("request_fingerprint")),
            "response_fingerprint": _dump(record.get("response_fingerprint")),
            "envelope": _dump(record.get("envelope")),
            "metadata": _dump(record.get("metadata")),
        })


# ── Read ───────────────────────────────────────────────────────────────────────


def get_trace(trace_id: str) -> dict[str, Any] | None:
    """Retrieve a single trace by ID."""
    with _conn() as c:
        row = c.execute(
            "SELECT * FROM traces WHERE trace_id = ?", (trace_id,)
        ).fetchone()
    return _deserialize(row) if row else None


def get_recent_traces(n: int = 5) -> list[dict[str, Any]]:
    """
    Retrieve the N most recent traces, newest first.
    Used by /v1/plan for context extraction.
    """
    n = max(1, min(n, 50))  # hard limit: never more than 50
    with _conn() as c:
        rows = c.execute(
            "SELECT * FROM traces ORDER BY created_at DESC LIMIT ?", (n,)
        ).fetchall()
    return [_deserialize(r) for r in rows]


def get_traces_by_ids(trace_ids: list[str]) -> list[dict[str, Any]]:
    """Retrieve multiple traces by their IDs."""
    if not trace_ids:
        return []
    placeholders = ",".join("?" * len(trace_ids))
    with _conn() as c:
        rows = c.execute(
            f"SELECT * FROM traces WHERE trace_id IN ({placeholders})"
            f" ORDER BY created_at DESC",
            trace_ids,
        ).fetchall()
    return [_deserialize(r) for r in rows]


def get_traces_since(iso_timestamp: str) -> list[dict[str, Any]]:
    """
    Retrieve all traces after given ISO timestamp.
    Useful for drift control and TVV sync.
    """
    with _conn() as c:
        rows = c.execute(
            "SELECT * FROM traces WHERE created_at > ? ORDER BY created_at DESC",
            (iso_timestamp,),
        ).fetchall()
    return [_deserialize(r) for r in rows]


def count_traces() -> int:
    """Count total traces in database."""
    with _conn() as c:
        return c.execute("SELECT COUNT(*) FROM traces").fetchone()[0]


# ── Delete ─────────────────────────────────────────────────────────────────────


def delete_trace(trace_id: str) -> bool:
    """Delete a single trace by ID."""
    with _conn() as c:
        affected = c.execute(
            "DELETE FROM traces WHERE trace_id = ?", (trace_id,)
        ).rowcount
    return affected > 0


def purge_older_than(iso_timestamp: str) -> int:
    """
    Delete traces older than given timestamp.
    Returns number of deleted rows.
    """
    with _conn() as c:
        affected = c.execute(
            "DELETE FROM traces WHERE created_at < ?", (iso_timestamp,)
        ).rowcount
    return affected


# ── Helpers ────────────────────────────────────────────────────────────────────


def _conn() -> sqlite3.Connection:
    """Get database connection with Row factory."""
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def _dump(v: Any) -> str | None:
    """Serialize value to JSON string."""
    if v is None:
        return None
    return json.dumps(v, separators=(",", ":")) if not isinstance(v, str) else v


def _load(v: str | None) -> Any:
    """Deserialize JSON string to value."""
    if v is None:
        return None
    try:
        return json.loads(v)
    except (json.JSONDecodeError, TypeError):
        return v


def _deserialize(row: sqlite3.Row) -> dict[str, Any]:
    """Convert Row to dict with proper deserialization."""
    d = dict(row)
    for field in ("request_fingerprint", "response_fingerprint", "envelope", "metadata"):
        d[field] = _load(d.get(field))
    d["is_stream"] = bool(d.get("is_stream"))
    return d
