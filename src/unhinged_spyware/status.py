from __future__ import annotations

from pyrogram.enums import UserStatus


def normalize_status(status: UserStatus | None) -> str:
    if status == UserStatus.ONLINE:
        return "online"
    if status == UserStatus.OFFLINE:
        return "offline"
    return "unknown"
