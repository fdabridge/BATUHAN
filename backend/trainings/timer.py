"""Pure helpers for the server-authoritative training exam countdown."""
from __future__ import annotations

import math
from datetime import datetime


def utc_iso(value: datetime | None) -> str | None:
    """Serialize the module's naive UTC datetimes as unambiguous RFC 3339."""
    return f"{value.isoformat()}Z" if value else None


def remaining_exam_seconds(
    due_at: datetime | None,
    now: datetime,
) -> int | None:
    if due_at is None:
        return None
    return max(0, math.ceil((due_at - now).total_seconds()))
