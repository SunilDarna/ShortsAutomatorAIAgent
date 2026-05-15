"""
database.py — Phase 1: SQLite Persistence & Analytics Engine
Replaces stateless processed_videos.json with a fully relational database.
Tracks asset lineage, performance data, and hook-efficiency scoring.
"""
import sqlite3
import os
import datetime

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
    """)

    conn.commit()
    conn.close()
    print("DB: Schema initialized successfully.")

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
                hook_type: str = "", hook_text: str = "", title: str = "") -> bool:
    """Stage a new clip. Returns False if it would overlap with existing clips."""
    if is_segment_overlapping(parent_url, start, end):
        return False
    conn = _connect()
    conn.execute("""
        INSERT INTO Shorts_Clips (Clip_ID, Parent_URL, Start_Time, End_Time,
                                  Hook_Type, Hook_Text, Title, Status)
        VALUES (?, ?, ?, ?, ?, ?, ?, 'pending')
    """, (clip_id, parent_url, start, end, hook_type, hook_text, title))
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

def get_pending_clips():
    """Return all clips in 'pending' status."""
    conn = _connect()
    rows = conn.execute(
        "SELECT * FROM Shorts_Clips WHERE Status = 'pending' ORDER BY Clip_ID ASC"
    ).fetchall()
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
        HAVING avg_apv < (
            SELECT PERCENTILE_CONT(?) WITHIN GROUP (ORDER BY APV_Percentage)
            FROM Performance_Log
        )
        ORDER BY avg_apv ASC
    """, (threshold_pct / 100.0,)).fetchall()
    conn.close()
    return [dict(r) for r in rows]

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
