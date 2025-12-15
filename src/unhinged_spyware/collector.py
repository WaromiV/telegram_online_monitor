from __future__ import annotations

from datetime import datetime, timezone

from pyrogram import Client, idle, raw
from pyrogram.enums import UserStatus
from pyrogram.handlers import RawUpdateHandler

from . import settings
from .database import ensure_users, get_connection, init_db


def _valid_session_string(raw_value: str | None) -> str | None:
    if not raw_value:
        return None
    cleaned = raw_value.strip()
    if cleaned.lower() in {"session_string_here", "changeme", "placeholder"}:
        return None
    if len(cleaned) < 50:
        return None
    return cleaned


def _valid_bot_token(raw_value: str | None) -> str | None:
    if not raw_value:
        return None
    cleaned = raw_value.strip()
    if cleaned.lower() in {"bot_token_optional", "changeme", "placeholder"}:
        return None
    if ":" not in cleaned or len(cleaned) < 20:
        return None
    return cleaned


def _normalize_raw_status(status_obj: raw.types.UserStatus | None) -> tuple[str, str]:
    if isinstance(status_obj, UserStatus):
        raw_status = status_obj.name
        if status_obj == UserStatus.ONLINE:
            return raw_status, "online"
        if status_obj == UserStatus.OFFLINE:
            return raw_status, "offline"
        return raw_status, "unknown"
    if isinstance(status_obj, raw.types.UserStatusOnline):
        return "ONLINE", "online"
    if isinstance(status_obj, raw.types.UserStatusOffline):
        return "OFFLINE", "offline"
    if status_obj is None:
        return "None", "unknown"
    return type(status_obj).__name__, "unknown"


async def run_collector() -> None:
    if not settings.TELEGRAM_API_ID or not settings.TELEGRAM_API_HASH:
        raise SystemExit("TELEGRAM_API_ID/TELEGRAM_API_HASH missing. Populate .env first.")
    if not settings.USER_TIMEZONES:
        raise SystemExit("USER_TIMEZONES missing (format: user_id:tz,user_id:tz)")

    session_string = _valid_session_string(settings.TELEGRAM_SESSION_STRING)
    bot_token = _valid_bot_token(settings.TELEGRAM_BOT_TOKEN)
    if not session_string and not bot_token:
        raise SystemExit(
            "Provide a valid TELEGRAM_SESSION_STRING (preferred for user presence access) or TELEGRAM_BOT_TOKEN."
        )

    conn = get_connection()
    init_db(conn)
    ensure_users(conn, settings.USER_TIMEZONES)

    client_kwargs = dict(
        name="unhinged-spyware",
        api_id=int(settings.TELEGRAM_API_ID),
        api_hash=settings.TELEGRAM_API_HASH,
        workdir=str(settings.DATA_DIR),
        in_memory=False,
    )
    if session_string:
        client_kwargs["session_string"] = session_string
    if bot_token:
        client_kwargs["bot_token"] = bot_token

    async with Client(**client_kwargs) as app:
        async def ensure_user_row(user_id: int) -> None:
            row = conn.execute("SELECT 1 FROM users WHERE user_id=?", (user_id,)).fetchone()
            if not row:
                tz = settings.USER_TIMEZONES.get(user_id, "UTC")
                conn.execute(
                    "INSERT OR IGNORE INTO users (user_id, username, full_name, timezone) VALUES (?, ?, ?, ?)",
                    (user_id, None, None, tz),
                )
                conn.commit()

            # Try to refresh username/full_name when available.
            try:
                user = await app.get_users(user_id)
                full_name_parts = [p for p in [user.first_name, user.last_name] if p]
                full_name = " ".join(full_name_parts) if full_name_parts else None
                conn.execute(
                    "UPDATE users SET username=?, full_name=? WHERE user_id=?",
                    (user.username or None, full_name, user_id),
                )
                conn.commit()
            except Exception as exc:  # noqa: BLE001
                print(f"[collector] failed to refresh user profile for {user_id}: {exc}")

        async def handle_status_update(_, update, __, ___):
            # unwrap UpdateShort if needed
            print(update)
            if isinstance(update, raw.types.UpdateShort):
                update = update.update
            if not isinstance(update, raw.types.UpdateUserStatus):
                return
            await ensure_user_row(update.user_id)
            raw_status, normalized = _normalize_raw_status(update.status)
            ts = datetime.now(timezone.utc).isoformat()
            try:
                conn.execute(
                    """
                    INSERT INTO presence_events (user_id, timestamp_utc, raw_status, normalized_status)
                    VALUES (?, ?, ?, ?)
                    """,
                    (update.user_id, ts, raw_status, normalized),
                )
                conn.commit()
            except Exception as exc:  # noqa: BLE001
                print(f"[collector] failed to write status update: {exc}")

        app.add_handler(RawUpdateHandler(handle_status_update))
        print("[collector] listening for Telegram status updates (event-driven; no polling)")
        await idle()


def main() -> None:
    import asyncio

    asyncio.run(run_collector())


if __name__ == "__main__":
    main()
