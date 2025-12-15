from __future__ import annotations

import json
from datetime import date, datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

from fastapi import Depends, FastAPI, HTTPException, Query
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from zoneinfo import ZoneInfo

from . import settings
from .database import get_connection, init_db

app = FastAPI(title="Sleep Inference API", version="0.1.0")

BASE_DIR = Path(__file__).resolve().parent
FRONTEND_DIR = BASE_DIR / "frontend"

if FRONTEND_DIR.exists():
    app.mount("/ui", StaticFiles(directory=FRONTEND_DIR, html=True), name="ui")


@app.get("/", include_in_schema=False, response_model=None)
def serve_root():
    if FRONTEND_DIR.exists():
        return FileResponse(FRONTEND_DIR / "index.html")
    return {"message": "UI not built; FRONTEND_DIR missing"}


def get_db():
    conn = get_connection()
    init_db(conn)
    try:
        yield conn
    finally:
        conn.close()


@app.get("/users")
def list_users(conn=Depends(get_db)) -> List[Dict[str, Any]]:
    rows = conn.execute(
        "SELECT user_id, username, full_name, timezone FROM users ORDER BY user_id"
    ).fetchall()
    return [
        {
            "user_id": r["user_id"],
            "username": r["username"],
            "full_name": r["full_name"],
            "timezone": r["timezone"],
        }
        for r in rows
    ]


@app.get("/users/{user_id}/sleep")
def get_sleep_windows(
    user_id: int,
    from_date: Optional[date] = Query(None, alias="from"),
    to_date: Optional[date] = Query(None, alias="to"),
    conn=Depends(get_db),
) -> Dict[str, Any]:
    user = conn.execute("SELECT timezone FROM users WHERE user_id=?", (user_id,)).fetchone()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    tz = ZoneInfo(user["timezone"])
    windows = conn.execute(
        "SELECT sleep_start_local, sleep_end_local, duration_minutes, confidence FROM sleep_windows WHERE user_id=? ORDER BY sleep_start_local",
        (user_id,),
    ).fetchall()
    anomalies = conn.execute(
        "SELECT type, timestamp_local, metadata_json FROM anomalies WHERE user_id=? ORDER BY timestamp_local",
        (user_id,),
    ).fetchall()

    def _filter_by_date(dt_str: str) -> bool:
        dt = datetime.fromisoformat(dt_str).astimezone(tz)
        if from_date and dt.date() < from_date:
            return False
        if to_date and dt.date() > to_date:
            return False
        return True

    windows_payload = [
        {
            "start": w["sleep_start_local"],
            "end": w["sleep_end_local"],
            "durationMinutes": w["duration_minutes"],
            "confidence": w["confidence"],
        }
        for w in windows
        if _filter_by_date(w["sleep_start_local"])
    ]
    anomalies_payload = [
        {
            "type": a["type"],
            "timestamp": a["timestamp_local"],
            "metadata": json.loads(a["metadata_json"]) if a["metadata_json"] else {},
        }
        for a in anomalies
        if _filter_by_date(a["timestamp_local"])
    ]
    return {"windows": windows_payload, "anomalies": anomalies_payload}


@app.get("/users/{user_id}/presence")
def get_presence(
    user_id: int,
    from_ts: Optional[str] = Query(None, alias="from"),
    to_ts: Optional[str] = Query(None, alias="to"),
    status: Optional[str] = Query(None, description="Filter by normalized status (e.g., online)"),
    limit: int = Query(1000, ge=1, le=5000),
    conn=Depends(get_db),
) -> List[Dict[str, Any]]:
    params: list[Any] = [user_id]
    clause = ""
    if from_ts:
        clause += " AND timestamp_utc >= ?"
        params.append(from_ts)
    if to_ts:
        clause += " AND timestamp_utc <= ?"
        params.append(to_ts)
    if status:
        clause += " AND normalized_status = ?"
        params.append(status)
    params.append(limit)
    rows = conn.execute(
        f"""
        SELECT timestamp_utc, raw_status, normalized_status
        FROM presence_events
        WHERE user_id=? {clause}
        ORDER BY timestamp_utc DESC
        LIMIT ?
        """,
        params,
    ).fetchall()
    return [
        {
            "timestamp": r["timestamp_utc"],
            "rawStatus": r["raw_status"],
            "normalizedStatus": r["normalized_status"],
        }
        for r in reversed(rows)
    ]


@app.get("/presence/online")
def get_recent_online(
    limit: int = Query(100, ge=1, le=2000),
    conn=Depends(get_db),
) -> List[Dict[str, Any]]:
    rows = conn.execute(
        """
        SELECT user_id, timestamp_utc, raw_status, normalized_status
        FROM presence_events
        WHERE normalized_status = 'online'
        ORDER BY timestamp_utc DESC
        LIMIT ?
        """,
        (limit,),
    ).fetchall()
    return [
        {
            "userId": r["user_id"],
            "timestamp": r["timestamp_utc"],
            "rawStatus": r["raw_status"],
            "normalizedStatus": r["normalized_status"],
        }
        for r in rows
    ]


def main() -> None:
    import uvicorn

    uvicorn.run(
        "unhinged_spyware.api:app",
        host=settings.FASTAPI_HOST,
        port=settings.FASTAPI_PORT,
        reload=False,
    )


if __name__ == "__main__":
    main()
