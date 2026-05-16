"""
database.py — Phase 1: SQLite Persistence & Analytics Engine
Replaces stateless processed_videos.json with a fully relational database.
Tracks asset lineage, performance data, and hook-efficiency scoring.
"""
import sqlite3
import os
import datetime
import json

DB_PATH = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "pipeline.db")

def _connect():
    """Returns a connection with native datetime type parsing enabled."""
    conn = sqlite3.connect(
        DB_PATH,
        detect_types=sqlite3.PARSE_DECLTYPES | sqlite3.PARSE_COLNAMES
    )
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    """Initialize all tables if they do not exist. Safe to call on every startup."""
    conn = _connect()
    cur = conn.cursor()

    cur.executescript("""
        CREATE TABLE IF NOT EXISTS Source_Media (
            Original_URL    TEXT PRIMARY KEY,
            Title           TEXT NOT NULL,
            Duration        INTEGER,
            Channel_ID      TEXT,
            Scraped_Date    TIMESTAMP DEFAULT (datetime('now'))
        );

        CREATE TABLE IF NOT EXISTS Shorts_Clips (
            Clip_ID         TEXT PRIMARY KEY,
            Parent_URL      TEXT NOT NULL,
            Start_Time      REAL NOT NULL,
            End_Time        REAL NOT NULL,
            Hook_Type       TEXT,
            Hook_Text       TEXT,
            Title           TEXT,
            Publish_Date    TIMESTAMP,
            YouTube_ID      TEXT,
            Status          TEXT DEFAULT 'pending',
            FOREIGN KEY (Parent_URL) REFERENCES Source_Media(Original_URL)
        );

        CREATE TABLE IF NOT EXISTS Performance_Log (
            Log_ID          INTEGER PRIMARY KEY AUTOINCREMENT,
            Clip_ID         TEXT NOT NULL,
            Recorded_At     TIMESTAMP DEFAULT (datetime('now')),
            Views_24h       INTEGER DEFAULT 0,
            Stayed_Rate     REAL DEFAULT 0.0,
            APV_Percentage  REAL DEFAULT 0.0,
            Replay_Rate     REAL DEFAULT 0.0,
            Subs_Gained     INTEGER DEFAULT 0,
            Hook_Efficiency REAL GENERATED ALWAYS AS (
                CASE WHEN (100.0 - Stayed_Rate) > 0
                     THEN Stayed_Rate / (100.0 - Stayed_Rate)
                     ELSE 0
                END
            ) STORED,
            FOREIGN KEY (Clip_ID) REFERENCES Shorts_Clips(Clip_ID)
        );

        CREATE TABLE IF NOT EXISTS Prompts_Repo (
            Prompt_ID       INTEGER PRIMARY KEY AUTOINCREMENT,
            Prompt_Text     TEXT NOT NULL,
            Model_Used      TEXT,
            Hook_Type       TEXT,
            Avg_Stayed_Rate REAL DEFAULT 0.0,
            Usage_Count     INTEGER DEFAULT 0,
            Created_At      TIMESTAMP DEFAULT (datetime('now'))
        );

        CREATE INDEX IF NOT EXISTS idx_clips_parent ON Shorts_Clips(Parent_URL);
        CREATE INDEX IF NOT EXISTS idx_clips_status ON Shorts_Clips(Status);
        CREATE INDEX IF NOT EXISTS idx_perf_clip ON Performance_Log(Clip_ID);

        CREATE TABLE IF NOT EXISTS Source_Intelligence (
            Original_URL       TEXT PRIMARY KEY,
            Channel_ID         TEXT,
            Source_Title       TEXT,
            Duration           REAL DEFAULT 0.0,
            View_Count         INTEGER DEFAULT 0,
            Like_Count         INTEGER DEFAULT 0,
            Comment_Count      INTEGER DEFAULT 0,
            Age_Hours          REAL DEFAULT 0.0,
            Velocity_Score     REAL DEFAULT 0.0,
            Authority_Score    REAL DEFAULT 0.0,
            Raw_Metadata_JSON  TEXT,
            Recorded_At        TIMESTAMP DEFAULT (datetime('now'))
        );

        CREATE TABLE IF NOT EXISTS Candidate_Segments (
            Candidate_ID       TEXT PRIMARY KEY,
            Parent_URL         TEXT NOT NULL,
            Start_Time         REAL NOT NULL,
            End_Time           REAL NOT NULL,
            Topic              TEXT,
            Virality_Score     REAL DEFAULT 0.0,
            Transcript_Score   REAL DEFAULT 0.0,
            Source_Score       REAL DEFAULT 0.0,
            Novelty_Score      REAL DEFAULT 0.0,
            Feature_JSON       TEXT,
            Status             TEXT DEFAULT 'ranked',
            Created_At         TIMESTAMP DEFAULT (datetime('now')),
            FOREIGN KEY (Parent_URL) REFERENCES Source_Media(Original_URL)
        );

        CREATE TABLE IF NOT EXISTS Render_QA (
            Clip_ID            TEXT PRIMARY KEY,
            Width              INTEGER DEFAULT 0,
            Height             INTEGER DEFAULT 0,
            Duration           REAL DEFAULT 0.0,
            Has_Audio          INTEGER DEFAULT 0,
            Burned_In_Captions INTEGER DEFAULT 0,
            Caption_Zone       TEXT,
            Passed             INTEGER DEFAULT 0,
            Warnings_JSON      TEXT,
            Checked_At         TIMESTAMP DEFAULT (datetime('now')),
            FOREIGN KEY (Clip_ID) REFERENCES Shorts_Clips(Clip_ID)
        );

        CREATE TABLE IF NOT EXISTS Schedule_Performance (
            Slot_ID             INTEGER PRIMARY KEY AUTOINCREMENT,
            Clip_ID             TEXT,
            Geography           TEXT,
            Local_Hour          INTEGER,
            Weekday             INTEGER,
            Topic               TEXT,
            Publish_At_UTC      TEXT,
            Views_24h           INTEGER DEFAULT 0,
            Avg_View_Percentage REAL DEFAULT 0.0,
            Subscribers_Gained  INTEGER DEFAULT 0,
            Score               REAL DEFAULT 0.0,
            Recorded_At         TIMESTAMP DEFAULT (datetime('now')),
            FOREIGN KEY (Clip_ID) REFERENCES Shorts_Clips(Clip_ID)
        );

        CREATE INDEX IF NOT EXISTS idx_candidate_parent ON Candidate_Segments(Parent_URL);
        CREATE INDEX IF NOT EXISTS idx_candidate_score ON Candidate_Segments(Virality_Score);
        CREATE INDEX IF NOT EXISTS idx_schedule_geo_hour ON Schedule_Performance(Geography, Local_Hour);
    """)

    _ensure_clip_columns(conn)

    conn.commit()
    conn.close()
    print("DB: Schema initialized successfully.")


def _column_exists(conn, table: str, column: str) -> bool:
    rows = conn.execute(f"PRAGMA table_info({table})").fetchall()
    return any(row["name"] == column for row in rows)


def _ensure_column(conn, table: str, column: str, ddl: str):
    if not _column_exists(conn, table, column):
        conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {ddl}")


def _ensure_clip_columns(conn):
    """Add new intelligence columns without rebuilding existing user data."""
    _ensure_column(conn, "Shorts_Clips", "Candidate_ID", "TEXT")
    _ensure_column(conn, "Shorts_Clips", "Candidate_Score", "REAL DEFAULT 0.0")
    _ensure_column(conn, "Shorts_Clips", "Source_Score", "REAL DEFAULT 0.0")
    _ensure_column(conn, "Shorts_Clips", "Topic", "TEXT")
    _ensure_column(conn, "Shorts_Clips", "Geography", "TEXT")
    _ensure_column(conn, "Shorts_Clips", "Schedule_Slot_UTC", "TEXT")
    _ensure_column(conn, "Shorts_Clips", "Render_QA_Status", "TEXT")
    _ensure_column(conn, "Shorts_Clips", "Failure_Reason", "TEXT")

# ─────────────────────────── Source Media ────────────────────────────────────

def upsert_source_media(url: str, title: str, duration: int = 0, channel_id: str = ""):
    """Insert or update a source video record."""
    conn = _connect()
    conn.execute("""
        INSERT INTO Source_Media (Original_URL, Title, Duration, Channel_ID)
        VALUES (?, ?, ?, ?)
        ON CONFLICT(Original_URL) DO UPDATE SET
            Title = excluded.Title,
            Duration = excluded.Duration
    """, (url, title, duration, channel_id))
    conn.commit()
    conn.close()

# ─────────────────────────── Shorts Clips ────────────────────────────────────

def is_segment_overlapping(parent_url: str, new_start: float, new_end: float) -> bool:
    """
    Core agentic rule: returns True if the proposed [new_start, new_end] window
    overlaps with ANY previously extracted clip from the same parent video.
    Overlap condition: (StartA < EndB) AND (EndA > StartB)
    """
    conn = _connect()
    cur = conn.cursor()
    cur.execute("""
        SELECT COUNT(*) as cnt FROM Shorts_Clips
        WHERE Parent_URL = ?
          AND Start_Time < ?
          AND End_Time   > ?
          AND Status != 'failed'
    """, (parent_url, new_end, new_start))
    row = cur.fetchone()
    conn.close()
    return row["cnt"] > 0

def insert_clip(clip_id: str, parent_url: str, start: float, end: float,
                hook_type: str = "", hook_text: str = "", title: str = "",
                candidate_id: str = "", candidate_score: float = 0.0,
                source_score: float = 0.0, topic: str = "",
                geography: str = "", schedule_slot_utc: str = "") -> bool:
    """Stage a new clip. Returns False if it would overlap with existing clips."""
    if is_segment_overlapping(parent_url, start, end):
        return False
    conn = _connect()
    conn.execute("""
        INSERT INTO Shorts_Clips (Clip_ID, Parent_URL, Start_Time, End_Time,
                                  Hook_Type, Hook_Text, Title, Status,
                                  Candidate_ID, Candidate_Score, Source_Score,
                                  Topic, Geography, Schedule_Slot_UTC)
        VALUES (?, ?, ?, ?, ?, ?, ?, 'pending', ?, ?, ?, ?, ?, ?)
    """, (
        clip_id, parent_url, start, end, hook_type, hook_text, title,
        candidate_id, candidate_score, source_score, topic, geography,
        schedule_slot_utc,
    ))
    conn.commit()
    conn.close()
    return True

def update_clip_status(clip_id: str, status: str, youtube_id: str = None):
    """Update the status of a clip (pending → published / failed)."""
    conn = _connect()
    if youtube_id:
        conn.execute("""
            UPDATE Shorts_Clips
            SET Status = ?, YouTube_ID = ?, Publish_Date = datetime('now')
            WHERE Clip_ID = ?
        """, (status, youtube_id, clip_id))
    else:
        conn.execute("UPDATE Shorts_Clips SET Status = ? WHERE Clip_ID = ?",
                     (status, clip_id))
    conn.commit()
    conn.close()


def update_clip_schedule(clip_id: str, publish_at_utc: str = "", geography: str = ""):
    conn = _connect()
    conn.execute("""
        UPDATE Shorts_Clips
        SET Schedule_Slot_UTC = COALESCE(NULLIF(?, ''), Schedule_Slot_UTC),
            Geography = COALESCE(NULLIF(?, ''), Geography)
        WHERE Clip_ID = ?
    """, (publish_at_utc, geography, clip_id))
    conn.commit()
    conn.close()


def update_clip_failure(clip_id: str, reason: str):
    conn = _connect()
    conn.execute("""
        UPDATE Shorts_Clips
        SET Status = 'failed', Failure_Reason = ?
        WHERE Clip_ID = ?
    """, (reason, clip_id))
    conn.commit()
    conn.close()

def get_pending_clips():
    """Return all clips in 'pending' status."""
    conn = _connect()
    rows = conn.execute(
        "SELECT * FROM Shorts_Clips WHERE Status = 'pending' ORDER BY Clip_ID ASC"
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def get_published_clips(limit: int = 50):
    conn = _connect()
    rows = conn.execute("""
        SELECT * FROM Shorts_Clips
        WHERE Status = 'published' AND YouTube_ID IS NOT NULL
        ORDER BY Publish_Date DESC, Clip_ID DESC
        LIMIT ?
    """, (limit,)).fetchall()
    conn.close()
    return [dict(r) for r in rows]

# ─────────────────────────── Performance Log ─────────────────────────────────

def log_performance(clip_id: str, views_24h: int = 0, stayed_rate: float = 0.0,
                    apv: float = 0.0, replay_rate: float = 0.0, subs_gained: int = 0):
    """Log a performance snapshot for a published clip."""
    conn = _connect()
    conn.execute("""
        INSERT INTO Performance_Log
            (Clip_ID, Views_24h, Stayed_Rate, APV_Percentage, Replay_Rate, Subs_Gained)
        VALUES (?, ?, ?, ?, ?, ?)
    """, (clip_id, views_24h, stayed_rate, apv, replay_rate, subs_gained))
    conn.commit()
    conn.close()


def upsert_source_intelligence(parent_url: str, metadata: dict):
    """Store source-level ranking signals collected before clip selection."""
    conn = _connect()
    conn.execute("""
        INSERT INTO Source_Intelligence (
            Original_URL, Channel_ID, Source_Title, Duration, View_Count,
            Like_Count, Comment_Count, Age_Hours, Velocity_Score,
            Authority_Score, Raw_Metadata_JSON, Recorded_At
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, datetime('now'))
        ON CONFLICT(Original_URL) DO UPDATE SET
            Channel_ID = excluded.Channel_ID,
            Source_Title = excluded.Source_Title,
            Duration = excluded.Duration,
            View_Count = excluded.View_Count,
            Like_Count = excluded.Like_Count,
            Comment_Count = excluded.Comment_Count,
            Age_Hours = excluded.Age_Hours,
            Velocity_Score = excluded.Velocity_Score,
            Authority_Score = excluded.Authority_Score,
            Raw_Metadata_JSON = excluded.Raw_Metadata_JSON,
            Recorded_At = datetime('now')
    """, (
        parent_url,
        metadata.get("channel_id", ""),
        metadata.get("title", ""),
        float(metadata.get("duration", 0) or 0),
        int(metadata.get("view_count", 0) or 0),
        int(metadata.get("like_count", 0) or 0),
        int(metadata.get("comment_count", 0) or 0),
        float(metadata.get("age_hours", 0) or 0),
        float(metadata.get("velocity_score", 0) or 0),
        float(metadata.get("authority_score", 0) or 0),
        json.dumps(metadata, default=str),
    ))
    conn.commit()
    conn.close()


def insert_candidate_segments(parent_url: str, candidates: list):
    """Replace ranked candidate rows for a parent video with the latest scoring run."""
    conn = _connect()
    conn.execute("DELETE FROM Candidate_Segments WHERE Parent_URL = ?", (parent_url,))
    for candidate in candidates:
        conn.execute("""
            INSERT INTO Candidate_Segments (
                Candidate_ID, Parent_URL, Start_Time, End_Time, Topic,
                Virality_Score, Transcript_Score, Source_Score, Novelty_Score,
                Feature_JSON, Status
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            candidate.get("candidate_id"),
            parent_url,
            float(candidate.get("start", 0) or 0),
            float(candidate.get("end", 0) or 0),
            candidate.get("topic", ""),
            float(candidate.get("virality_score", 0) or 0),
            float(candidate.get("transcript_score", 0) or 0),
            float(candidate.get("source_score", 0) or 0),
            float(candidate.get("novelty_score", 0) or 0),
            json.dumps(candidate.get("features", {}), default=str),
            candidate.get("status", "ranked"),
        ))
    conn.commit()
    conn.close()


def log_render_qa(clip_id: str, qa: dict):
    conn = _connect()
    conn.execute("""
        INSERT INTO Render_QA (
            Clip_ID, Width, Height, Duration, Has_Audio,
            Burned_In_Captions, Caption_Zone, Passed, Warnings_JSON, Checked_At
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, datetime('now'))
        ON CONFLICT(Clip_ID) DO UPDATE SET
            Width = excluded.Width,
            Height = excluded.Height,
            Duration = excluded.Duration,
            Has_Audio = excluded.Has_Audio,
            Burned_In_Captions = excluded.Burned_In_Captions,
            Caption_Zone = excluded.Caption_Zone,
            Passed = excluded.Passed,
            Warnings_JSON = excluded.Warnings_JSON,
            Checked_At = datetime('now')
    """, (
        clip_id,
        int(qa.get("width", 0) or 0),
        int(qa.get("height", 0) or 0),
        float(qa.get("duration", 0) or 0),
        1 if qa.get("has_audio") else 0,
        1 if qa.get("burned_in_captions") else 0,
        qa.get("caption_zone", ""),
        1 if qa.get("passed") else 0,
        json.dumps(qa.get("warnings", []), default=str),
    ))
    status = "passed" if qa.get("passed") else "failed"
    conn.execute("""
        UPDATE Shorts_Clips
        SET Render_QA_Status = ?
        WHERE Clip_ID = ?
    """, (status, clip_id))
    conn.commit()
    conn.close()


def log_schedule_performance(clip_id: str, geography: str, local_hour: int,
                             weekday: int, topic: str, publish_at_utc: str,
                             views_24h: int = 0, avg_view_percentage: float = 0.0,
                             subscribers_gained: int = 0):
    score = (views_24h / 1000.0) + avg_view_percentage + (subscribers_gained * 5)
    conn = _connect()
    conn.execute("""
        INSERT INTO Schedule_Performance (
            Clip_ID, Geography, Local_Hour, Weekday, Topic, Publish_At_UTC,
            Views_24h, Avg_View_Percentage, Subscribers_Gained, Score
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, (
        clip_id, geography, local_hour, weekday, topic, publish_at_utc,
        views_24h, avg_view_percentage, subscribers_gained, score,
    ))
    conn.commit()
    conn.close()


def get_schedule_slot_report(geography: str = "", limit: int = 12) -> list:
    conn = _connect()
    params = []
    where = ""
    if geography:
        where = "WHERE Geography = ?"
        params.append(geography)
    rows = conn.execute(f"""
        SELECT Geography, Local_Hour, COUNT(*) AS sample_count,
               AVG(Views_24h) AS avg_views_24h,
               AVG(Avg_View_Percentage) AS avg_apv,
               AVG(Subscribers_Gained) AS avg_subs,
               AVG(Score) AS avg_score
        FROM Schedule_Performance
        {where}
        GROUP BY Geography, Local_Hour
        ORDER BY avg_score DESC, sample_count DESC
        LIMIT ?
    """, (*params, limit)).fetchall()
    conn.close()
    return [dict(r) for r in rows]

# ─────────────────────────── Analytics & Intelligence ────────────────────────

def get_hook_efficiency_report() -> list:
    """
    Weekly Review: Return bottom 20% performers by APV and identify
    high-performing hook types to weight future prompt selection.
    """
    conn = _connect()
    rows = conn.execute("""
        SELECT
            sc.Hook_Type,
            AVG(pl.Stayed_Rate)     AS avg_stayed,
            AVG(pl.APV_Percentage)  AS avg_apv,
            AVG(pl.Hook_Efficiency) AS avg_hes,
            COUNT(*)                AS sample_count
        FROM Performance_Log pl
        JOIN Shorts_Clips sc ON pl.Clip_ID = sc.Clip_ID
        GROUP BY sc.Hook_Type
        ORDER BY avg_hes DESC
    """).fetchall()
    conn.close()
    return [dict(r) for r in rows]

def get_best_hook_type() -> str:
    """Return the hook type with the highest Hook Efficiency Score."""
    report = get_hook_efficiency_report()
    if report:
        best = report[0]
        print(f"DB Intelligence: Best hook type → '{best['Hook_Type']}' "
              f"(HES={best['avg_hes']:.2f}, Stayed={best['avg_stayed']:.1f}%)")
        return best["Hook_Type"]
    return "Counter-Intuitive"  # Default strategy

def get_bottom_performers(threshold_pct: float = 20.0) -> list:
    """Return clips in the bottom N% by APV for hook review."""
    conn = _connect()
    rows = conn.execute("""
        SELECT sc.Clip_ID, sc.Hook_Type, sc.Hook_Text, sc.Title,
               AVG(pl.APV_Percentage) AS avg_apv
        FROM Performance_Log pl
        JOIN Shorts_Clips sc ON pl.Clip_ID = sc.Clip_ID
        GROUP BY sc.Clip_ID
        ORDER BY avg_apv ASC
    """).fetchall()
    conn.close()
    data = [dict(r) for r in rows]
    if not data:
        return []
    cutoff_count = max(1, int(len(data) * (threshold_pct / 100.0)))
    return data[:cutoff_count]

def get_all_used_segments(parent_url: str) -> list:
    """Return all extracted segments for a given source video (for overlap checks)."""
    conn = _connect()
    rows = conn.execute("""
        SELECT Start_Time, End_Time FROM Shorts_Clips
        WHERE Parent_URL = ? AND Status != 'failed'
        ORDER BY Start_Time
    """, (parent_url,)).fetchall()
    conn.close()
    return [dict(r) for r in rows]

# ─────────────────────────── Startup ─────────────────────────────────────────

if __name__ == "__main__":
    init_db()
    print(f"Database ready at: {DB_PATH}")
