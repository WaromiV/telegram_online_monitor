from __future__ import annotations

import json
from datetime import datetime, time, timedelta, timezone
from typing import List, Optional, Sequence, Tuple
from zoneinfo import ZoneInfo

from .database import get_connection, init_db

# =========================
# Tunables
# =========================

MIN_SLEEP_DURATION = timedelta(hours=3)
MAX_SLEEP_GAP = timedelta(minutes=5)

SLEEP_HOURS_START = time(21, 0)
SLEEP_HOURS_END = time(10, 0)

DOOM_START = time(3, 30)
DOOM_END = time(6, 0)
DOOM_MAX_DURATION = timedelta(minutes=20)


# =========================
# Helpers
# =========================

def _parse_utc(ts: str) -> datetime:
    dt = datetime.fromisoformat(ts)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def _overlaps_sleep_window(start_local: datetime, end_local: datetime) -> bool:
    # Anchor sleep window: 21:00 → 10:00
    anchor_date = (
        start_local.date()
        if start_local.time() >= SLEEP_HOURS_END
        else start_local.date() - timedelta(days=1)
    )

    window_start = datetime.combine(anchor_date, SLEEP_HOURS_START, tzinfo=start_local.tzinfo)
    window_end = datetime.combine(anchor_date + timedelta(days=1), SLEEP_HOURS_END, tzinfo=start_local.tzinfo)

    return max(start_local, window_start) < min(end_local, window_end)


def _merge_intervals(
    intervals: Sequence[Tuple[datetime, datetime]]
) -> List[Tuple[datetime, datetime]]:
    merged: List[Tuple[datetime, datetime]] = []

    for start, end in sorted(intervals, key=lambda x: x[0]):
        if not merged:
            merged.append((start, end))
            continue

        last_start, last_end = merged[-1]
        if start - last_end <= MAX_SLEEP_GAP:
            merged[-1] = (last_start, max(last_end, end))
        else:
            merged.append((start, end))

    return merged


# =========================
# Core aggregation
# =========================

def recompute_offline_intervals(conn) -> None:
    """
    Offline interval = OFFLINE event → next ONLINE event

    We explicitly do NOT:
    - extend intervals to 'now'
    - create intervals from repeated OFFLINE events
    """

    conn.execute("DELETE FROM offline_intervals")

    users = conn.execute("SELECT user_id FROM users").fetchall()

    for user in users:
        user_id = user["user_id"]

        events = conn.execute(
            """
            SELECT timestamp_utc, normalized_status
            FROM presence_events
            WHERE user_id=?
            ORDER BY timestamp_utc ASC
            """,
            (user_id,),
        ).fetchall()

        offline_start: Optional[datetime] = None

        for ev in events:
            ts = _parse_utc(ev["timestamp_utc"])
            status = ev["normalized_status"]

            if status == "offline":
                # Start offline interval if not already offline
                if offline_start is None:
                    offline_start = ts

            elif status == "online":
                # Close offline interval
                if offline_start is not None:
                    duration = int((ts - offline_start).total_seconds())
                    if duration > 0:
                        conn.execute(
                            """
                            INSERT INTO offline_intervals
                            (user_id, start_utc, end_utc, duration_seconds)
                            VALUES (?, ?, ?, ?)
                            """,
                            (
                                user_id,
                                offline_start.isoformat(),
                                ts.isoformat(),
                                duration,
                            ),
                        )
                    offline_start = None

        # NOTE:
        # If user is still offline at end of data, we intentionally discard
        # the open interval. Sleep is inferred only once user wakes up.

    conn.commit()


def _intervals_for_user(conn, user_id: int) -> List[Tuple[datetime, datetime]]:
    rows = conn.execute(
        """
        SELECT start_utc, end_utc
        FROM offline_intervals
        WHERE user_id=?
        ORDER BY start_utc ASC
        """,
        (user_id,),
    ).fetchall()

    return [(_parse_utc(r["start_utc"]), _parse_utc(r["end_utc"])) for r in rows]


def recompute_sleep_windows(conn) -> None:
    conn.execute("DELETE FROM sleep_windows")

    users = conn.execute("SELECT user_id, timezone FROM users").fetchall()

    for user in users:
        user_id = user["user_id"]
        tz = ZoneInfo(user["timezone"])

        intervals = _intervals_for_user(conn, user_id)
        candidates: List[Tuple[datetime, datetime]] = []

        for start_utc, end_utc in intervals:
            start_local = start_utc.astimezone(tz)
            end_local = end_utc.astimezone(tz)

            if end_local - start_local < MIN_SLEEP_DURATION:
                continue

            if not _overlaps_sleep_window(start_local, end_local):
                continue

            candidates.append((start_local, end_local))

        merged = _merge_intervals(candidates)

        for start_local, end_local in merged:
            duration_minutes = int((end_local - start_local).total_seconds() // 60)
            confidence = _compute_confidence(conn, user_id, start_local, end_local, tz)

            conn.execute(
                """
                INSERT INTO sleep_windows
                (user_id, sleep_start_local, sleep_end_local, duration_minutes, confidence)
                VALUES (?, ?, ?, ?, ?)
                """,
                (
                    user_id,
                    start_local.isoformat(),
                    end_local.isoformat(),
                    duration_minutes,
                    confidence,
                ),
            )

    conn.commit()


def _compute_confidence(
    conn,
    user_id: int,
    start_local: datetime,
    end_local: datetime,
    tz: ZoneInfo,
) -> float:
    start_utc = start_local.astimezone(timezone.utc)
    end_utc = end_local.astimezone(timezone.utc)

    events = conn.execute(
        """
        SELECT normalized_status
        FROM presence_events
        WHERE user_id=? AND timestamp_utc BETWEEN ? AND ?
        """,
        (user_id, start_utc.isoformat(), end_utc.isoformat()),
    ).fetchall()

    statuses = [r["normalized_status"] for r in events]

    score = 0.6

    if not any(s == "online" for s in statuses):
        score += 0.2

    if (end_local - start_local) >= timedelta(hours=6):
        score += 0.1

    if any(s == "unknown" for s in statuses):
        score -= 0.2

    return max(0.0, min(1.0, score))


def recompute_anomalies(conn) -> None:
    conn.execute("DELETE FROM anomalies")

    users = conn.execute("SELECT user_id, timezone FROM users").fetchall()

    for user in users:
        user_id = user["user_id"]
        tz = ZoneInfo(user["timezone"])

        windows = conn.execute(
            """
            SELECT sleep_start_local, sleep_end_local
            FROM sleep_windows
            WHERE user_id=?
            """,
            (user_id,),
        ).fetchall()

        for w in windows:
            start_local = datetime.fromisoformat(w["sleep_start_local"])
            end_local = datetime.fromisoformat(w["sleep_end_local"])
            _detect_doomscroll(conn, user_id, start_local, end_local, tz)

    conn.commit()


def _detect_doomscroll(
    conn,
    user_id: int,
    start_local: datetime,
    end_local: datetime,
    tz: ZoneInfo,
) -> None:
    start_utc = start_local.astimezone(timezone.utc)
    end_utc = end_local.astimezone(timezone.utc)

    events = conn.execute(
        """
        SELECT timestamp_utc, normalized_status
        FROM presence_events
        WHERE user_id=? AND timestamp_utc BETWEEN ? AND ?
        ORDER BY timestamp_utc ASC
        """,
        (user_id, start_utc.isoformat(), end_utc.isoformat()),
    ).fetchall()

    i = 0
    while i < len(events) - 1:
        cur = events[i]
        nxt = events[i + 1]

        if cur["normalized_status"] == "offline" and nxt["normalized_status"] == "online":
            online_start = _parse_utc(nxt["timestamp_utc"])

            j = i + 2
            while j < len(events):
                if events[j]["normalized_status"] == "offline":
                    online_end = _parse_utc(events[j]["timestamp_utc"])
                    duration = online_end - online_start
                    online_start_local = online_start.astimezone(tz)

                    if (
                        DOOM_START <= online_start_local.time() <= DOOM_END
                        and duration <= DOOM_MAX_DURATION
                    ):
                        conn.execute(
                            """
                            INSERT INTO anomalies
                            (user_id, type, timestamp_local, metadata_json)
                            VALUES (?, ?, ?, ?)
                            """,
                            (
                                user_id,
                                "doomscroll",
                                online_start_local.isoformat(),
                                json.dumps(
                                    {
                                        "online_duration_minutes": int(duration.total_seconds() // 60),
                                        "wake_time": online_start_local.strftime("%H:%M"),
                                        "return_to_sleep": True,
                                    }
                                ),
                            ),
                        )

                    i = j
                    break
                j += 1
        i += 1


def recompute_all(conn=None) -> None:
    conn = conn or get_connection()
    init_db(conn)
    recompute_offline_intervals(conn)
    recompute_sleep_windows(conn)
    recompute_anomalies(conn)


def main() -> None:
    conn = get_connection()
    init_db(conn)
    recompute_all(conn)
    print("Aggregation complete.")


if __name__ == "__main__":
    main()

