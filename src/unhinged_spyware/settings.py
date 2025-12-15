from __future__ import annotations

import os
from pathlib import Path
from typing import Dict

from dotenv import load_dotenv

load_dotenv()


def _parse_user_timezones(raw: str) -> Dict[int, str]:
    """
    Parse a comma-separated list of user_id:tz entries into a mapping.
    Example: "12345:Europe/Berlin,67890:America/New_York"
    """
    mapping: Dict[int, str] = {}
    for part in raw.split(","):
        part = part.strip()
        if not part:
            continue
        if ":" not in part:
            continue
        user_id_str, tz = part.split(":", 1)
        try:
            mapping[int(user_id_str)] = tz
        except ValueError:
            continue
    return mapping


DATA_DIR = Path(os.environ.get("DATA_DIR", "data"))
DB_PATH = Path(os.environ.get("DB_PATH", DATA_DIR / "presence.db"))
DATA_DIR.mkdir(parents=True, exist_ok=True)

TELEGRAM_API_ID = os.environ.get("TELEGRAM_API_ID")
TELEGRAM_API_HASH = os.environ.get("TELEGRAM_API_HASH")
TELEGRAM_SESSION_STRING = os.environ.get("TELEGRAM_SESSION_STRING")
TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN")

USER_TIMEZONES = _parse_user_timezones(os.environ.get("USER_TIMEZONES", ""))
POLL_INTERVAL_SECONDS = int(os.environ.get("POLL_INTERVAL_SECONDS", "30"))

FASTAPI_HOST = os.environ.get("FASTAPI_HOST", "0.0.0.0")
FASTAPI_PORT = int(os.environ.get("FASTAPI_PORT", "18080"))
