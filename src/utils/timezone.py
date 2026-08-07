from __future__ import annotations

from datetime import datetime
from zoneinfo import ZoneInfo

BRASILIA_TZ = ZoneInfo("America/Sao_Paulo")


def brasilia_now() -> datetime:
    return datetime.now(BRASILIA_TZ).replace(tzinfo=None)


def brasilia_now_iso(timespec: str = "seconds") -> str:
    return brasilia_now().isoformat(timespec=timespec)
