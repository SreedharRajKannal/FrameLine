"""
store.py – Full SQLite implementation of all persistence functions.
Owned by Sreedhar.

Tables:
  meetings  – one row per meeting (meeting_id PK, title, summary, raw_transcript JSON)
  items     – one row per FeedbackItem (id PK, meeting_id FK, status, data JSON)
  settings  – one row per meeting (meeting_id PK, data JSON)
"""
import json
import sqlite3
from contextlib import contextmanager
from typing import Generator

from backend.app import config
from backend.app.models import FeedbackItem, ProjectSettings, Transcript


# ---------------------------------------------------------------------------
# Connection helper
# ---------------------------------------------------------------------------

@contextmanager
def _get_conn() -> Generator[sqlite3.Connection, None, None]:
    conn = sqlite3.connect(config.DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# Schema
# ---------------------------------------------------------------------------

def init_db() -> None:
    """Create tables if they don't exist. Safe to call multiple times."""
    with _get_conn() as conn:
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS meetings (
                meeting_id   TEXT PRIMARY KEY,
                title        TEXT,
                summary      TEXT,
                raw_json     TEXT NOT NULL,
                status       TEXT DEFAULT 'completed'
            );
            
            -- Attempt to add status column if it doesn't exist (SQLite < 3.25 doesn't have IF NOT EXISTS for ADD COLUMN)
            -- We'll just catch the exception in python if it fails


            CREATE TABLE IF NOT EXISTS items (
                id           TEXT PRIMARY KEY,
                meeting_id   TEXT NOT NULL,
                status       TEXT NOT NULL DEFAULT 'pending',
                data         TEXT NOT NULL,
                FOREIGN KEY (meeting_id) REFERENCES meetings(meeting_id)
            );

            CREATE INDEX IF NOT EXISTS idx_items_meeting ON items(meeting_id);
            CREATE INDEX IF NOT EXISTS idx_items_status  ON items(status);

            CREATE TABLE IF NOT EXISTS settings (
                meeting_id   TEXT PRIMARY KEY,
                data         TEXT NOT NULL,
                FOREIGN KEY (meeting_id) REFERENCES meetings(meeting_id)
            );
        """)
        try:
            conn.execute("ALTER TABLE meetings ADD COLUMN status TEXT DEFAULT 'completed'")
        except sqlite3.OperationalError:
            pass  # column already exists


# ---------------------------------------------------------------------------
# Meetings / transcripts
# ---------------------------------------------------------------------------

def save_transcript(t: Transcript, status: str = "completed") -> None:
    """Upsert a transcript for a meeting."""
    with _get_conn() as conn:
        conn.execute(
            """
            INSERT INTO meetings (meeting_id, title, summary, raw_json, status)
            VALUES (?, ?, ?, ?, ?)
            ON CONFLICT(meeting_id) DO UPDATE SET
                title   = excluded.title,
                summary = excluded.summary,
                raw_json = excluded.raw_json,
                status   = excluded.status
            """,
            (t.meeting_id, t.title, t.summary, t.model_dump_json(), status),
        )

def update_meeting_status(meeting_id: str, status: str) -> None:
    """Update the processing status of a meeting."""
    with _get_conn() as conn:
        conn.execute("UPDATE meetings SET status = ? WHERE meeting_id = ?", (status, meeting_id))

def update_meeting_title(meeting_id: str, title: str) -> None:
    """Update the title of a meeting."""
    with _get_conn() as conn:
        conn.execute("UPDATE meetings SET title = ? WHERE meeting_id = ?", (title, meeting_id))



def get_transcript(meeting_id: str) -> Transcript | None:
    """Return the Transcript for a meeting, or None if not found."""
    with _get_conn() as conn:
        row = conn.execute(
            "SELECT raw_json FROM meetings WHERE meeting_id = ?", (meeting_id,)
        ).fetchone()
    if row is None:
        return None
    return Transcript.model_validate_json(row["raw_json"])


def list_meetings() -> list[dict]:
    """Return a lightweight list of meetings: meeting_id, title, summary, status."""
    with _get_conn() as conn:
        rows = conn.execute(
            "SELECT meeting_id, title, summary, status FROM meetings ORDER BY rowid DESC"
        ).fetchall()
    return [dict(r) for r in rows]


def delete_meeting(meeting_id: str) -> None:
    """Delete a meeting and all associated items/settings."""
    with _get_conn() as conn:
        conn.execute("DELETE FROM settings WHERE meeting_id = ?", (meeting_id,))
        conn.execute("DELETE FROM items WHERE meeting_id = ?", (meeting_id,))
        conn.execute("DELETE FROM meetings WHERE meeting_id = ?", (meeting_id,))


# ---------------------------------------------------------------------------
# Items
# ---------------------------------------------------------------------------

def save_items(meeting_id: str, items: list[FeedbackItem]) -> None:
    """Replace all items for a meeting (full overwrite)."""
    with _get_conn() as conn:
        conn.execute("DELETE FROM items WHERE meeting_id = ?", (meeting_id,))
        conn.executemany(
            "INSERT INTO items (id, meeting_id, status, data) VALUES (?, ?, ?, ?)",
            [
                (item.id, meeting_id, item.status, item.model_dump_json())
                for item in items
            ],
        )


def get_items(meeting_id: str) -> list[FeedbackItem]:
    """Return all FeedbackItems for a meeting."""
    with _get_conn() as conn:
        rows = conn.execute(
            "SELECT data FROM items WHERE meeting_id = ? ORDER BY rowid",
            (meeting_id,),
        ).fetchall()
    return [FeedbackItem.model_validate_json(r["data"]) for r in rows]


def update_item(item_id: str, patch: dict) -> FeedbackItem | None:
    """
    Apply a partial patch dict to an item and persist it.
    Returns the updated FeedbackItem, or None if not found.
    """
    with _get_conn() as conn:
        row = conn.execute(
            "SELECT data FROM items WHERE id = ?", (item_id,)
        ).fetchone()
        if row is None:
            return None
        data = json.loads(row["data"])
        data.update(patch)
        updated = FeedbackItem.model_validate(data)
        conn.execute(
            "UPDATE items SET status = ?, data = ? WHERE id = ?",
            (updated.status, updated.model_dump_json(), item_id),
        )
    return updated


# ---------------------------------------------------------------------------
# Settings
# ---------------------------------------------------------------------------

def get_settings(meeting_id: str) -> ProjectSettings:
    """Return settings for a meeting; returns defaults if not set yet."""
    with _get_conn() as conn:
        row = conn.execute(
            "SELECT data FROM settings WHERE meeting_id = ?", (meeting_id,)
        ).fetchone()
    if row is None:
        return ProjectSettings()
    return ProjectSettings.model_validate_json(row["data"])


def save_settings(meeting_id: str, s: ProjectSettings) -> None:
    """Upsert settings for a meeting."""
    with _get_conn() as conn:
        conn.execute(
            """
            INSERT INTO settings (meeting_id, data)
            VALUES (?, ?)
            ON CONFLICT(meeting_id) DO UPDATE SET data = excluded.data
            """,
            (meeting_id, s.model_dump_json()),
        )
