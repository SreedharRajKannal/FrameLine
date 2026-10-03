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

            CREATE TABLE IF NOT EXISTS detections (
                id          TEXT PRIMARY KEY,
                video_id    TEXT NOT NULL,
                frame_index INTEGER NOT NULL,
                time_sec    REAL NOT NULL,
                track_id    TEXT NOT NULL,
                class_name  TEXT NOT NULL,
                color       TEXT NOT NULL,
                confidence  REAL NOT NULL,
                bbox        TEXT NOT NULL,
                mask        TEXT,
                position    TEXT,
                FOREIGN KEY (video_id) REFERENCES videos(video_id)
            );
            CREATE INDEX IF NOT EXISTS idx_detections_video_time
                ON detections(video_id, time_sec);
            CREATE INDEX IF NOT EXISTS idx_detections_video_track
                ON detections(video_id, track_id);

            -- Phase 3 Vision Context & Edit Instruction tables
            CREATE TABLE IF NOT EXISTS frame_descriptions (
                id           TEXT PRIMARY KEY,
                video_id     TEXT NOT NULL,
                time_sec     REAL NOT NULL,
                data         TEXT NOT NULL,
                think_text   TEXT,
                latency_ms   REAL,
                reused       INTEGER DEFAULT 0,
                model        TEXT,
                FOREIGN KEY (video_id) REFERENCES videos(video_id)
            );
            CREATE INDEX IF NOT EXISTS idx_frame_desc_vid ON frame_descriptions(video_id);

            CREATE TABLE IF NOT EXISTS video_context (
                video_id     TEXT PRIMARY KEY,
                built_at     REAL NOT NULL,
                data         TEXT NOT NULL,
                FOREIGN KEY (video_id) REFERENCES videos(video_id)
            );

            CREATE TABLE IF NOT EXISTS entities (
                id           TEXT PRIMARY KEY,
                video_id     TEXT NOT NULL,
                key          TEXT NOT NULL,
                name         TEXT NOT NULL,
                color        TEXT,
                intervals    TEXT NOT NULL,
                data         TEXT,
                FOREIGN KEY (video_id) REFERENCES videos(video_id)
            );
            CREATE INDEX IF NOT EXISTS idx_entities_video ON entities(video_id);

            CREATE TABLE IF NOT EXISTS edit_instructions (
                id                  TEXT PRIMARY KEY,
                item_id             TEXT NOT NULL,
                meeting_id          TEXT NOT NULL,
                effect              TEXT NOT NULL,
                target_entity       TEXT,
                start_sec           REAL NOT NULL,
                end_sec             REAL NOT NULL,
                params              TEXT NOT NULL,
                confidence          REAL DEFAULT 1.0,
                reason              TEXT,
                ambiguous           INTEGER DEFAULT 0,
                candidate_intervals TEXT,
                status              TEXT DEFAULT 'pending', -- pending, approved, rejected
                filter_string       TEXT,
                preview_path        TEXT,
                created_at          REAL,
                FOREIGN KEY (meeting_id) REFERENCES meetings(meeting_id)
            );
            CREATE INDEX IF NOT EXISTS idx_edits_meeting ON edit_instructions(meeting_id);
            CREATE INDEX IF NOT EXISTS idx_edits_item ON edit_instructions(item_id);
        """)
        # Backward-compat: add columns to pre-existing DB files
        for alter in [
            "ALTER TABLE meetings ADD COLUMN status TEXT DEFAULT 'completed'",
            "ALTER TABLE meetings ADD COLUMN video_id TEXT",
            "ALTER TABLE detections ADD COLUMN position TEXT",
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


def get_meeting(meeting_id: str) -> dict | None:
    """Return meeting record dict (meeting_id, title, summary, status, video_id) or None."""
    with _get_conn() as conn:
        row = conn.execute(
            "SELECT meeting_id, title, summary, status, video_id FROM meetings WHERE meeting_id = ?",
            (meeting_id,),
        ).fetchone()
    return dict(row) if row else None


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


# ---------------------------------------------------------------------------
# Phase 3: Frame descriptions, video context, entities, edit instructions
# ---------------------------------------------------------------------------

def save_frame_description(
    video_id: str,
    time_sec: float,
    data: dict,
    think_text: str | None = None,
    latency_ms: float | None = None,
    reused: bool = False,
    model: str | None = None,
) -> str:
    """Save or update one frame description."""
    desc_id = f"fdesc-{video_id[:8]}-{time_sec:.1f}"
    with _get_conn() as conn:
        conn.execute(
            """
            INSERT OR REPLACE INTO frame_descriptions
                (id, video_id, time_sec, data, think_text, latency_ms, reused, model)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                desc_id,
                video_id,
                time_sec,
                json.dumps(data),
                think_text,
                latency_ms,
                1 if reused else 0,
                model,
            ),
        )
    return desc_id


def get_frame_descriptions(video_id: str) -> list[dict]:
    """Get all frame descriptions for a video, ordered by time_sec."""
    with _get_conn() as conn:
        rows = conn.execute(
            """
            SELECT * FROM frame_descriptions
            WHERE video_id = ?
            ORDER BY time_sec
            """,
            (video_id,),
        ).fetchall()
    result = []
    for r in rows:
        d = dict(r)
        d["data"] = json.loads(d["data"]) if d.get("data") else {}
        d["reused"] = bool(d.get("reused"))
        result.append(d)
    return result


def save_detections(video_id: str, detections: list[dict]) -> None:
    """Replace sampled detector observations for a video."""
    rows = []
    for detection in detections:
        rows.append((
            detection["id"], video_id, detection["frame_index"], detection["time_sec"],
            detection["track_id"], detection["class_name"], detection.get("color", "unknown"),
            detection["confidence"], json.dumps(detection["bbox"]),
            json.dumps(detection["mask"]) if detection.get("mask") is not None else None,
            detection.get("position"),
        ))
    with _get_conn() as conn:
        conn.execute("DELETE FROM detections WHERE video_id = ?", (video_id,))
        conn.executemany(
            """INSERT INTO detections
               (id, video_id, frame_index, time_sec, track_id, class_name,
                color, confidence, bbox, mask, position)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            rows,
        )


def get_detections(video_id: str) -> list[dict]:
    """Return sampled detector observations in video-time order."""
    with _get_conn() as conn:
        rows = conn.execute(
            "SELECT * FROM detections WHERE video_id = ? ORDER BY time_sec, frame_index, id",
            (video_id,),
        ).fetchall()
    result = []
    for row in rows:
        detection = dict(row)
        detection["bbox"] = json.loads(detection["bbox"])
        detection["mask"] = json.loads(detection["mask"]) if detection["mask"] else None
        result.append(detection)
    return result


def save_video_context(video_id: str, context_data: dict) -> None:
    """Save aggregated video context (scenes, entity index, summary)."""
    with _get_conn() as conn:
        conn.execute(
            """
            INSERT OR REPLACE INTO video_context (video_id, built_at, data)
            VALUES (?, ?, ?)
            """,
            (video_id, _time.time(), json.dumps(context_data)),
        )


def get_video_context(video_id: str) -> dict | None:
    """Get video context by video_id."""
    with _get_conn() as conn:
        row = conn.execute(
            "SELECT * FROM video_context WHERE video_id = ?", (video_id,)
        ).fetchone()
    if not row:
        return None
    d = dict(row)
    return json.loads(d["data"]) if d.get("data") else None


def save_entities(video_id: str, entities_list: list[dict]) -> None:
    """Save or replace entity index for a video."""
    with _get_conn() as conn:
        conn.execute("DELETE FROM entities WHERE video_id = ?", (video_id,))
        for ent in entities_list:
            ent_id = f"ent-{video_id[:8]}-{ent['key']}"
            conn.execute(
                """
                INSERT INTO entities (id, video_id, key, name, color, intervals, data)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    ent_id,
                    video_id,
                    ent["key"],
                    ent.get("name", ent["key"]),
                    ent.get("color"),
                    json.dumps(ent.get("intervals", [])),
                    json.dumps(ent),
                ),
            )


def get_entities(video_id: str) -> list[dict]:
    """Get entity index list for a video."""
    with _get_conn() as conn:
        rows = conn.execute(
            "SELECT * FROM entities WHERE video_id = ? ORDER BY key", (video_id,)
        ).fetchall()
    result = []
    for r in rows:
        d = dict(r)
        full_data = json.loads(d["data"]) if d.get("data") else {}
        full_data["key"] = d["key"]
        full_data["name"] = d["name"]
        full_data["color"] = d["color"]
        full_data["intervals"] = json.loads(d["intervals"]) if d.get("intervals") else []
        result.append(full_data)
    return result


def save_edit_instruction(inst: dict) -> None:
    """Save or replace an edit instruction."""
    meeting_id = inst["meeting_id"]
    if not get_transcript(meeting_id):
        save_transcript(Transcript(meeting_id=meeting_id, segments=[]))

    with _get_conn() as conn:

        conn.execute(
            """
            INSERT OR REPLACE INTO edit_instructions
                (id, item_id, meeting_id, effect, target_entity, start_sec, end_sec,
                 params, confidence, reason, ambiguous, candidate_intervals, status,
                 filter_string, preview_path, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                inst["id"],
                inst["item_id"],
                inst["meeting_id"],
                inst["effect"],
                inst.get("target_entity"),
                inst["start_sec"],
                inst["end_sec"],
                json.dumps(inst.get("params", {})),
                inst.get("confidence", 1.0),
                inst.get("reason"),
                1 if inst.get("ambiguous") else 0,
                json.dumps(inst.get("candidate_intervals", [])),
                inst.get("status", "pending"),
                inst.get("filter_string"),
                inst.get("preview_path"),
                inst.get("created_at", _time.time()),
            ),
        )


def get_edit_instructions(meeting_id: str) -> list[dict]:
    """Get all edit instructions for a meeting."""
    with _get_conn() as conn:
        rows = conn.execute(
            """
            SELECT * FROM edit_instructions
            WHERE meeting_id = ?
            ORDER BY start_sec
            """,
            (meeting_id,),
        ).fetchall()
    result = []
    for r in rows:
        d = dict(r)
        d["params"] = json.loads(d["params"]) if d.get("params") else {}
        d["candidate_intervals"] = (
            json.loads(d["candidate_intervals"]) if d.get("candidate_intervals") else []
        )
        d["ambiguous"] = bool(d.get("ambiguous"))
        result.append(d)
    return result


def get_edit_instruction(inst_id: str) -> dict | None:
    """Get a single edit instruction by id."""
    with _get_conn() as conn:
        row = conn.execute(
            "SELECT * FROM edit_instructions WHERE id = ?", (inst_id,)
        ).fetchone()
    if not row:
        return None
    d = dict(row)
    d["params"] = json.loads(d["params"]) if d.get("params") else {}
    d["candidate_intervals"] = (
        json.loads(d["candidate_intervals"]) if d.get("candidate_intervals") else []
    )
    d["ambiguous"] = bool(d.get("ambiguous"))
    return d


def update_edit_instruction(inst_id: str, patch: dict) -> dict | None:
    """Update fields of an edit instruction."""
    inst = get_edit_instruction(inst_id)
    if not inst:
        return None
    inst.update(patch)
    save_edit_instruction(inst)
    return get_edit_instruction(inst_id)

