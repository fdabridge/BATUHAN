"""
BATUHAN — Meetings Module: Celery Tasks
  check_upcoming_meetings — every 5 min: 30-min pre-meeting WhatsApp alert
  send_nightly_digest     — 21:00 TRT (18:00 UTC): tomorrow's agenda
  send_weekly_summary     — Sunday 21:00 TRT (18:00 UTC): full week ahead
"""

from __future__ import annotations
import logging
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from jobs.tasks import celery_app

logger = logging.getLogger(__name__)
TRT = ZoneInfo("Europe/Istanbul")


@celery_app.task(name="meetings.tasks.check_upcoming_meetings")
def check_upcoming_meetings() -> None:
    """Find meetings starting in ~30 min that haven't been notified yet and alert."""
    from meetings.models import Meeting, SessionLocal
    from meetings.service import to_trt, to_et
    from meetings.notifier import send_whatsapp

    db = SessionLocal()
    try:
        now = datetime.utcnow()
        window_start = now + timedelta(minutes=25)
        window_end   = now + timedelta(minutes=35)
        meetings = (
            db.query(Meeting)
            .filter(
                Meeting.start_utc >= window_start,
                Meeting.start_utc <= window_end,
                Meeting.notified_30min == False,  # noqa: E712
            )
            .all()
        )
        for m in meetings:
            trt = to_trt(m.start_utc)
            et  = to_et(m.start_utc)
            msg = (
                f"⏰ 30 dakika sonra: {m.title}\n"
                f"🕐 {trt.strftime('%H:%M')} TRT / {et.strftime('%H:%M')} ET"
            )
            send_whatsapp(msg)
            m.notified_30min = True
            db.commit()
            logger.info("[Meetings] 30-min alert sent: meeting_id=%d", m.id)
    except Exception as exc:
        logger.error("[Meetings] check_upcoming_meetings error: %s", exc, exc_info=True)
    finally:
        db.close()


@celery_app.task(name="meetings.tasks.send_nightly_digest")
def send_nightly_digest() -> None:
    """Send tomorrow's meeting agenda at 21:00 TRT."""
    from meetings.models import SessionLocal
    from meetings.service import trt_tomorrow, get_meetings_for_trt_date, to_trt, to_et
    from meetings.notifier import send_whatsapp

    db = SessionLocal()
    try:
        tomorrow = trt_tomorrow()
        meetings = get_meetings_for_trt_date(db, tomorrow)
        if not meetings:
            msg = f"🌙 Yarın ({tomorrow.strftime('%a %d %b')}) görüşme yok. 🎉"
        else:
            lines = [f"🌙 Yarın ({tomorrow.strftime('%a %d %b')}) görüşmeler:"]
            for m in meetings:
                trt = to_trt(m.start_utc)
                et  = to_et(m.start_utc)
                lines.append(
                    f"  • {m.title} — {trt.strftime('%H:%M')} TRT / {et.strftime('%H:%M')} ET"
                )
            msg = "\n".join(lines)
        send_whatsapp(msg)
        logger.info("[Meetings] Nightly digest sent: %d meeting(s).", len(meetings))
    except Exception as exc:
        logger.error("[Meetings] send_nightly_digest error: %s", exc, exc_info=True)
    finally:
        db.close()


@celery_app.task(name="meetings.tasks.send_weekly_summary")
def send_weekly_summary() -> None:
    """Send the full coming-week agenda every Sunday at 21:00 TRT."""
    from meetings.models import SessionLocal
    from meetings.service import get_meetings_for_trt_date, to_trt, to_et
    from meetings.notifier import send_whatsapp

    db = SessionLocal()
    try:
        today_trt = datetime.now(TRT).date()
        # Next Monday (day after Sunday = 1 day ahead when run on Sunday)
        days_to_monday = (7 - today_trt.weekday()) % 7 or 7
        monday = today_trt + timedelta(days=days_to_monday)

        lines = [f"📅 Haftalık özet ({monday.strftime('%d %b')} haftası):"]
        total = 0
        for i in range(7):
            d = monday + timedelta(days=i)
            day_meetings = get_meetings_for_trt_date(db, d)
            if day_meetings:
                lines.append(f"\n{d.strftime('%A %d %b')}:")
                for m in day_meetings:
                    trt = to_trt(m.start_utc)
                    et  = to_et(m.start_utc)
                    lines.append(
                        f"  • {m.title} — {trt.strftime('%H:%M')} TRT / {et.strftime('%H:%M')} ET"
                    )
                total += len(day_meetings)

        if total == 0:
            lines.append("  Önümüzdeki hafta görüşme yok. 🎉")
        send_whatsapp("\n".join(lines))
        logger.info("[Meetings] Weekly summary sent: %d meeting(s) next week.", total)
    except Exception as exc:
        logger.error("[Meetings] send_weekly_summary error: %s", exc, exc_info=True)
    finally:
        db.close()
