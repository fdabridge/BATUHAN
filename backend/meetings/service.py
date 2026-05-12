"""
BATUHAN — Meetings Module: Timezone Logic & CRUD Helpers.

All datetimes are stored as naive UTC in the DB.
Display always shows both TRT (Europe/Istanbul, UTC+3) and ET (America/New_York, DST-aware).
"""

from __future__ import annotations
from datetime import date, datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from meetings.models import Meeting

TRT = ZoneInfo("Europe/Istanbul")   # UTC+3 (no DST)
ET  = ZoneInfo("America/New_York")  # UTC-4/-5 (DST-aware)


# ---------------------------------------------------------------------------
# Timezone converters
# ---------------------------------------------------------------------------

def to_trt(dt_utc: datetime) -> datetime:
    """Convert a naive UTC datetime to TRT-aware datetime."""
    return dt_utc.replace(tzinfo=timezone.utc).astimezone(TRT)


def to_et(dt_utc: datetime) -> datetime:
    """Convert a naive UTC datetime to ET-aware datetime."""
    return dt_utc.replace(tzinfo=timezone.utc).astimezone(ET)


def parse_input_time(time_str: str, tz_name: str) -> datetime:
    """
    Parse an ISO 8601 datetime string in the specified timezone and return
    a naive UTC datetime suitable for storing in the DB.
    """
    tz = TRT if tz_name.upper() == "TRT" else ET
    dt = datetime.fromisoformat(time_str)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=tz)
    return dt.astimezone(timezone.utc).replace(tzinfo=None)


# ---------------------------------------------------------------------------
# Date helpers (all TRT-relative)
# ---------------------------------------------------------------------------

def trt_today() -> date:
    return datetime.now(TRT).date()


def trt_tomorrow() -> date:
    return (datetime.now(TRT) + timedelta(days=1)).date()


# ---------------------------------------------------------------------------
# Output formatter
# ---------------------------------------------------------------------------

def format_meeting_out(m: Meeting) -> dict:
    """Return a dict matching MeetingOut schema, with formatted TRT and ET strings."""
    trt = to_trt(m.start_utc)
    et  = to_et(m.start_utc)
    return {
        "id":               m.id,
        "title":            m.title,
        "description":      m.description,
        "start_utc":        m.start_utc.isoformat(),
        "start_trt":        trt.strftime("%a %d %b %Y %H:%M TRT"),
        "start_et":         et.strftime("%H:%M ET"),
        "duration_minutes": m.duration_minutes,
        "notified_30min":   m.notified_30min,
        "created_at":       m.created_at.isoformat() if m.created_at else None,
    }


# ---------------------------------------------------------------------------
# Query helpers
# ---------------------------------------------------------------------------

def parse_nl_meeting(text: str) -> dict:
    """
    Parse a natural-language meeting description (Turkish/English) using Claude.
    Returns a dict with keys: title, start_date, start_time, duration_minutes, description.
    Raises ValueError if Claude returns unparseable output.
    """
    import json as _json
    import anthropic
    from config.settings import get_settings

    now_trt = datetime.now(TRT)
    today_str = now_trt.strftime("%Y-%m-%d")
    day_name = now_trt.strftime("%A")   # e.g. "Monday"

    prompt = f"""You are a meeting parser. Today is {today_str} ({day_name}). The user is in Istanbul (TRT, UTC+3).

Parse the following meeting description and return ONLY a JSON object — no markdown, no explanation:

Input: "{text}"

Required JSON format:
{{
  "title": "concise meeting title (Turkish or English, match input language)",
  "start_date": "YYYY-MM-DD",
  "start_time": "HH:MM",
  "duration_minutes": 60,
  "description": null
}}

Rules:
- yarın / yarin = tomorrow  |  bugün / bugun = today
- Day names: Pazartesi=Mon, Salı=Tue, Çarşamba=Wed, Perşembe=Thu, Cuma=Fri, Cumartesi=Sat, Pazar=Sun (next occurrence)
- Time: "15.00" or "15:00" → "15:00"  |  No time mentioned → "09:00"
- Duration: "1 saat"=60, "2 saat"=120, "30 dakika"/"30 dk"=30  |  Default=60
- Title: strip filler words (toplantı, meeting, görüşme are OK to keep if meaningful)
- description: any extra context not in the title, otherwise null"""

    settings = get_settings()
    client = anthropic.Anthropic(api_key=settings.anthropic_api_key)
    msg = client.messages.create(
        model=settings.claude_model,
        max_tokens=256,
        messages=[{"role": "user", "content": prompt}],
    )
    raw = msg.content[0].text.strip()
    # Strip markdown code fences if Claude wraps the JSON
    if raw.startswith("```"):
        raw = raw.split("```")[1]
        if raw.startswith("json"):
            raw = raw[4:]
        raw = raw.strip()
    return _json.loads(raw)


def get_meetings_for_trt_date(db, d: date) -> list[Meeting]:
    """Return all meetings whose start time falls on the given TRT calendar date."""
    day_start = (
        datetime(d.year, d.month, d.day, 0, 0, 0, tzinfo=TRT)
        .astimezone(timezone.utc).replace(tzinfo=None)
    )
    day_end = (
        datetime(d.year, d.month, d.day, 23, 59, 59, tzinfo=TRT)
        .astimezone(timezone.utc).replace(tzinfo=None)
    )
    return (
        db.query(Meeting)
        .filter(Meeting.start_utc >= day_start, Meeting.start_utc <= day_end)
        .order_by(Meeting.start_utc)
        .all()
    )
