"""
store.py – Full SQLite implementation of all persistence functions.
Owned by Sreedhar.

Tables:
  meetings  – one row per meeting (meeting_id PK, title, summary, raw_transcript JSON)
  items     – one row per FeedbackItem (id PK, meeting_id FK, status, data JSON)
  settings  – one row per meeting (meeting_id PK, data JSON)
  videos    – one row per uploaded video (video_id PK)
  shots     – one row per detected shot (id PK, video_id FK)
  frames    – one row per sampled frame embedding (id PK, shot_id FK)
"""
import json
import sqlite3
import time as _time
from contextlib import contextmanager
from typing import Generator

from backend.app import config
from backend.app.models import FeedbackItem, ProjectSettings, Shot, Transcript, Video


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
                status       TEXT DEFAULT 'completed',
                video_id     TEXT
            );

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

            -- Video indexing tables (Phase 2)

            CREATE TABLE IF NOT EXISTS videos (
                video_id     TEXT PRIMARY KEY,
                filename     TEXT NOT NULL,
                path         TEXT NOT NULL,
                fps          REAL,
                duration_sec REAL,
                width        INTEGER,
                height       INTEGER,
                index_status TEXT DEFAULT 'pending',
                index_pct    REAL DEFAULT 0.0,
                created_at   REAL,
                updated_at   REAL
            );

            CREATE TABLE IF NOT EXISTS shots (
                id            TEXT PRIMARY KEY,
                video_id      TEXT NOT NULL,
                shot_index    INTEGER NOT NULL,
                start_sec     REAL NOT NULL,
                end_sec       REAL NOT NULL,
                keyframe_path TEXT,
                caption       TEXT,
                FOREIGN KEY (video_id) REFERENCES videos(video_id)
            );
            CREATE INDEX IF NOT EXISTS idx_shots_video ON shots(video_id);

            CREATE TABLE IF NOT EXISTS frames (
                id        TEXT PRIMARY KEY,
                shot_id   TEXT NOT NULL,
                time_sec  REAL NOT NULL,
                embedding BLOB,
                FOREIGN KEY (shot_id) REFERENCES shots(id)
            );
            CREATE INDEX IF NOT EXISTS idx_frames_shot ON frames(shot_id);
        """)
        # Backward-compat: add columns to pre-existing DB files
        for alter in [
            "ALTER TABLE meetings ADD COLUMN status TEXT DEFAULT 'completed'",
            "ALTER TABLE meetings ADD COLUMN video_id TEXT",
        ]:
            try:
                conn.execute(alter)
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
    """Return a lightweight list of meetings: meeting_id, title, summary, status, video_id."""
    with _get_conn() as conn:
        rows = conn.execute(
            "SELECT meeting_id, title, summary, status, video_id FROM meetings ORDER BY rowid DESC"
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


# ---------------------------------------------------------------------------
# Meeting ↔ Video link
# ---------------------------------------------------------------------------

def link_video_to_meeting(meeting_id: str, video_id: str) -> None:
    """Associate a video_id with a meeting."""
    with _get_conn() as conn:
        conn.execute(
            "UPDATE meetings SET video_id = ? WHERE meeting_id = ?",
            (video_id, meeting_id),
        )


def get_meeting_video_id(meeting_id: str) -> str | None:
    """Return the video_id linked to a meeting, or None."""
    with _get_conn() as conn:
        row = conn.execute(
            "SELECT video_id FROM meetings WHERE meeting_id = ?", (meeting_id,)
        ).fetchone()
    return row["video_id"] if row else None


def get_latest_indexed_video() -> str | None:
    """Return the video_id of the most recently indexed video, or None."""
    with _get_conn() as conn:
        row = conn.execute(
            "SELECT video_id FROM videos WHERE index_status = 'done' ORDER BY created_at DESC LIMIT 1"
        ).fetchone()
    return row["video_id"] if row else None


# ---------------------------------------------------------------------------
# Videos
# ---------------------------------------------------------------------------

def save_video(v: Video) -> None:
    """Upsert a video record."""
    with _get_conn() as conn:
        conn.execute(
            """
            INSERT INTO videos (video_id, filename, path, fps, duration_sec, width, height,
                                index_status, index_pct, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(video_id) DO UPDATE SET
                filename = excluded.filename,
                path = excluded.path,
                fps = excluded.fps,
                duration_sec = excluded.duration_sec,
                width = excluded.width,
                height = excluded.height,
                index_status = excluded.index_status,
                index_pct = excluded.index_pct,
                updated_at = excluded.updated_at
            """,
            (
                v.video_id, v.filename, v.path, v.fps, v.duration_sec,
                v.width, v.height, v.index_status, v.index_pct,
                v.created_at, v.updated_at,
            ),
        )


def get_video(video_id: str) -> Video | None:
    """Return a Video record or None."""
    with _get_conn() as conn:
        row = conn.execute(
            "SELECT * FROM videos WHERE video_id = ?", (video_id,)
        ).fetchone()
    return Video(**dict(row)) if row else None


def list_videos() -> list[Video]:
    """Return all videos ordered by creation time desc."""
    with _get_conn() as conn:
        rows = conn.execute(
            "SELECT * FROM videos ORDER BY created_at DESC"
        ).fetchall()
    return [Video(**dict(r)) for r in rows]


def update_video_status(video_id: str, status: str, pct: float) -> None:
    """Update indexing status and progress for a video."""
    with _get_conn() as conn:
        conn.execute(
            "UPDATE videos SET index_status = ?, index_pct = ?, updated_at = ? WHERE video_id = ?",
            (status, pct, _time.time(), video_id),
        )


def update_video_meta(
    video_id: str, fps: float, duration_sec: float, width: int, height: int
) -> None:
    """Update ffprobe-derived metadata for a video."""
    with _get_conn() as conn:
        conn.execute(
            """
            UPDATE videos SET fps = ?, duration_sec = ?, width = ?, height = ?, updated_at = ?
            WHERE video_id = ?
            """,
            (fps, duration_sec, width, height, _time.time(), video_id),
        )


# ---------------------------------------------------------------------------
# Shots
# ---------------------------------------------------------------------------

def save_shots(shots: list[Shot]) -> None:
    """Insert or replace shots (full upsert)."""
    with _get_conn() as conn:
        conn.executemany(
            """
            INSERT OR REPLACE INTO shots
                (id, video_id, shot_index, start_sec, end_sec, keyframe_path, caption)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            [
                (s.id, s.video_id, s.shot_index, s.start_sec, s.end_sec,
                 s.keyframe_path, s.caption)
                for s in shots
            ],
        )


def get_shots(video_id: str) -> list[Shot]:
    """Return all shots for a video, ordered by shot_index."""
    with _get_conn() as conn:
        rows = conn.execute(
            "SELECT * FROM shots WHERE video_id = ? ORDER BY shot_index",
            (video_id,),
        ).fetchall()
    return [Shot(**dict(r)) for r in rows]


def get_shot(shot_id: str) -> Shot | None:
    """Return a single shot by id."""
    with _get_conn() as conn:
        row = conn.execute(
            "SELECT * FROM shots WHERE id = ?", (shot_id,)
        ).fetchone()
    return Shot(**dict(row)) if row else None


def update_shot_caption(shot_id: str, caption: str) -> None:
    """Update the caption for a shot."""
    with _get_conn() as conn:
        conn.execute(
            "UPDATE shots SET caption = ? WHERE id = ?", (caption, shot_id)
        )


def delete_shots(video_id: str) -> None:
    """Delete all shots (and their frame embeddings) for a video."""
    with _get_conn() as conn:
        shot_ids = [
            r["id"]
            for r in conn.execute(
                "SELECT id FROM shots WHERE video_id = ?", (video_id,)
            ).fetchall()
        ]
        if shot_ids:
            placeholders = ",".join("?" * len(shot_ids))
            conn.execute(f"DELETE FROM frames WHERE shot_id IN ({placeholders})", shot_ids)
        conn.execute("DELETE FROM shots WHERE video_id = ?", (video_id,))


# ---------------------------------------------------------------------------
# Frame embeddings
# ---------------------------------------------------------------------------

def save_frame_embedding(
    frame_id: str, shot_id: str, time_sec: float, embedding_bytes: bytes
) -> None:
    """Insert or replace a frame embedding."""
    with _get_conn() as conn:
        conn.execute(
            """
            INSERT OR REPLACE INTO frames (id, shot_id, time_sec, embedding)
            VALUES (?, ?, ?, ?)
            """,
            (frame_id, shot_id, time_sec, embedding_bytes),
        )


def get_frame_embeddings(video_id: str) -> list[dict]:
    """
    Return all frame embeddings for a video.
    Result: list of {frame_id, shot_id, time_sec, embedding_bytes}
    Frames with NULL embeddings are excluded.
    """
    with _get_conn() as conn:
        rows = conn.execute(
            """
            SELECT f.id AS frame_id, f.shot_id, f.time_sec, f.embedding
            FROM frames f
            JOIN shots s ON f.shot_id = s.id
            WHERE s.video_id = ? AND f.embedding IS NOT NULL
            ORDER BY s.shot_index, f.time_sec
            """,
            (video_id,),
        ).fetchall()
    return [
        {
            "frame_id": r["frame_id"],
            "shot_id": r["shot_id"],
            "time_sec": r["time_sec"],
            "embedding_bytes": bytes(r["embedding"]),
        }
        for r in rows
    ]
