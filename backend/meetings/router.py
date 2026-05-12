"""
BATUHAN — Meetings Module: FastAPI Router.
Registered in main.py at prefix="/meetings".

Routes (all relative to /meetings):
  GET  /ui        — serve the web UI
  POST /          — create a meeting
  GET  /          — list upcoming meetings
  GET  /today     — today's meetings (TRT date)
  GET  /tomorrow  — tomorrow's meetings (TRT date)
  DELETE /{id}    — delete a meeting
"""

from __future__ import annotations
import logging
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import HTMLResponse
from sqlalchemy.orm import Session

from meetings.models import Meeting, get_db
from meetings.schemas import MeetingCreate, MeetingOut
from meetings.service import (
    format_meeting_out,
    get_meetings_for_trt_date,
    parse_input_time,
    trt_today,
    trt_tomorrow,
)

logger = logging.getLogger(__name__)
router = APIRouter()

_UI_PATH = Path(__file__).parent / "ui" / "index.html"


# ---------------------------------------------------------------------------
# Web UI
# ---------------------------------------------------------------------------

@router.get("/ui", response_class=HTMLResponse, include_in_schema=False)
def meetings_ui():
    if not _UI_PATH.exists():
        raise HTTPException(status_code=404, detail="Meetings UI not found.")
    return HTMLResponse(content=_UI_PATH.read_text(encoding="utf-8"))


# ---------------------------------------------------------------------------
# CRUD
# ---------------------------------------------------------------------------

@router.post("/", response_model=MeetingOut, status_code=201)
def create_meeting(payload: MeetingCreate, db: Session = Depends(get_db)):
    try:
        start_utc = parse_input_time(payload.start_time, payload.timezone)
    except (ValueError, TypeError) as exc:
        raise HTTPException(status_code=422, detail=f"Invalid start_time: {exc}")

    meeting = Meeting(
        title=payload.title,
        description=payload.description,
        start_utc=start_utc,
        duration_minutes=payload.duration_minutes,
    )
    db.add(meeting)
    db.commit()
    db.refresh(meeting)
    logger.info("[Meetings] Created id=%d title='%s'", meeting.id, meeting.title)
    return format_meeting_out(meeting)


@router.get("/today", response_model=list[MeetingOut])
def get_today(db: Session = Depends(get_db)):
    return [format_meeting_out(m) for m in get_meetings_for_trt_date(db, trt_today())]


@router.get("/tomorrow", response_model=list[MeetingOut])
def get_tomorrow(db: Session = Depends(get_db)):
    return [format_meeting_out(m) for m in get_meetings_for_trt_date(db, trt_tomorrow())]


@router.get("/", response_model=list[MeetingOut])
def list_meetings(db: Session = Depends(get_db)):
    from datetime import datetime
    now = datetime.utcnow()
    meetings = (
        db.query(Meeting)
        .filter(Meeting.start_utc >= now)
        .order_by(Meeting.start_utc)
        .all()
    )
    return [format_meeting_out(m) for m in meetings]


@router.delete("/{meeting_id}", status_code=204)
def delete_meeting(meeting_id: int, db: Session = Depends(get_db)):
    m = db.query(Meeting).filter(Meeting.id == meeting_id).first()
    if not m:
        raise HTTPException(status_code=404, detail=f"Meeting {meeting_id} not found.")
    db.delete(m)
    db.commit()
    logger.info("[Meetings] Deleted id=%d", meeting_id)
