from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Iterable

from . import settings


def get_connection(path: Path | None = None) -> sqlite3.Connection:
    db_path = path or settings.DB_PATH
    conn = sqlite3.connect(db_path, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    # Reduce lock contention between writer (collector) and periodic aggregations.
    conn.execute("PRAGMA busy_timeout = 5000")
    conn.execute("PRAGMA journal_mode = WAL")
    return conn


def init_db(conn: sqlite3.Connection) -> None:
    conn.executescript(
        """
        PRAGMA foreign_keys = ON;

        CREATE TABLE IF NOT EXISTS users (
            user_id INTEGER PRIMARY KEY,
            username TEXT,
            full_name TEXT,
            timezone TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS presence_events (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            timestamp_utc DATETIME NOT NULL,
            raw_status TEXT NOT NULL,
            normalized_status TEXT NOT NULL,
            FOREIGN KEY (user_id) REFERENCES users(user_id)
        );

        CREATE INDEX IF NOT EXISTS idx_presence_user_time
            ON presence_events(user_id, timestamp_utc);

        CREATE TABLE IF NOT EXISTS offline_intervals (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            start_utc DATETIME NOT NULL,
            end_utc DATETIME NOT NULL,
            duration_seconds INTEGER NOT NULL,
            FOREIGN KEY (user_id) REFERENCES users(user_id)
        );

        CREATE TABLE IF NOT EXISTS sleep_windows (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            sleep_start_local DATETIME NOT NULL,
            sleep_end_local DATETIME NOT NULL,
            duration_minutes INTEGER NOT NULL,
            confidence REAL NOT NULL,
            FOREIGN KEY (user_id) REFERENCES users(user_id)
        );

        CREATE TABLE IF NOT EXISTS anomalies (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            type TEXT NOT NULL,
            timestamp_local DATETIME NOT NULL,
            metadata_json TEXT,
            FOREIGN KEY (user_id) REFERENCES users(user_id)
        );
        """
    )
    # Backfill new columns for existing installs; ignore if they already exist.
    try:
        conn.execute("ALTER TABLE users ADD COLUMN full_name TEXT")
    except sqlite3.OperationalError:
        pass

    conn.commit()


def ensure_users(conn: sqlite3.Connection, user_timezones: dict[int, str]) -> None:
    if not user_timezones:
        return
    rows: Iterable[sqlite3.Row] = conn.execute("SELECT user_id FROM users").fetchall()
    existing_ids = {row["user_id"] for row in rows}
    for user_id, tz in user_timezones.items():
        if user_id in existing_ids:
            continue
        conn.execute(
            "INSERT INTO users (user_id, username, full_name, timezone) VALUES (?, ?, ?, ?)",
            (user_id, None, None, tz),
        )
    conn.commit()
