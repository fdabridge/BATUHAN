"""
BATUHAN — FR.225 Meeting Attendees & guest token signing (Prompt 15).

Two routers:
  protected_router  — CB / auditor management (auth required)
  public_router     — guest signing flow (NO auth)
"""
from __future__ import annotations
import hashlib
import secrets
from datetime import datetime, timedelta

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel
from sqlalchemy.orm import Session

from audit_set.db_models import AuditSet, AuditSetMeetingAttendee, get_db
from auth.db_models import PlatformUser
from auth.dependencies import get_current_user
from email_service import send_meeting_signing_link, send_meeting_otp
from config.settings import get_settings

# ── Constants ─────────────────────────────────────────────────────────────────

STAGE_LABELS: dict[str, str] = {
    "stage_1":         "Stage 1",
    "stage_2":         "Stage 2",
    "surveillance":    "Surveillance",
    "recertification": "Recertification",
}
TOKEN_TTL_HOURS = 72
OTP_EXPIRY_MIN  = 10
CB_ROLES        = {"admin", "planner", "officer", "executive", "gm"}
ALLOWED_ROLES   = CB_ROLES | {"auditor"}


def _hash(val: str) -> str:
    return hashlib.sha256(val.encode()).hexdigest()


def _att_dict(a: AuditSetMeetingAttendee) -> dict:
    return {
        "id":                a.id,
        "audit_set_id":      a.audit_set_id,
        "stage_type":        a.stage_type,
        "stage_label":       STAGE_LABELS.get(a.stage_type, a.stage_type),
        "full_name":         a.full_name,
        "title":             a.title,
        "email":             a.email,
        "token_expires_at":  a.token_expires_at.isoformat() if a.token_expires_at else None,
        "opening_signed":    a.opening_signed_at is not None,
        "opening_signed_at": a.opening_signed_at.isoformat() if a.opening_signed_at else None,
        "closing_signed":    a.closing_signed_at is not None,
        "closing_signed_at": a.closing_signed_at.isoformat() if a.closing_signed_at else None,
        "created_at":        a.created_at.isoformat() if a.created_at else None,
    }


# ── Protected router (CB + auditor management) ────────────────────────────────

protected_router = APIRouter(prefix="/audit-sets", tags=["meeting-attendees"])


@protected_router.get("/{audit_set_id}/meeting-attendees")
def list_attendees(
    audit_set_id: str,
    db: Session = Depends(get_db),
    current_user: PlatformUser = Depends(get_current_user),
):
    if current_user.role not in ALLOWED_ROLES:
        raise HTTPException(403, "Not authorized")
    attendees = (
        db.query(AuditSetMeetingAttendee)
        .filter_by(audit_set_id=audit_set_id)
        .order_by(AuditSetMeetingAttendee.stage_type, AuditSetMeetingAttendee.created_at)
        .all()
    )
    return [_att_dict(a) for a in attendees]


class AddAttendeeSchema(BaseModel):
    stage_type: str
    full_name:  str
    title:      str | None = None
    email:      str


@protected_router.post("/{audit_set_id}/meeting-attendees")
def add_attendee(
    audit_set_id: str,
    body: AddAttendeeSchema,
    db: Session = Depends(get_db),
    current_user: PlatformUser = Depends(get_current_user),
):
    if current_user.role not in ALLOWED_ROLES:
        raise HTTPException(403, "Not authorized")

    if body.stage_type not in STAGE_LABELS:
        raise HTTPException(400, f"Invalid stage_type. Must be one of: {list(STAGE_LABELS)}")

    audit_set = db.query(AuditSet).filter_by(id=audit_set_id).first()
    if not audit_set:
        raise HTTPException(404, "Audit set not found")

    settings = get_settings()
    expires_at = datetime.utcnow() + timedelta(hours=TOKEN_TTL_HOURS)

    attendee = AuditSetMeetingAttendee(
        audit_set_id=audit_set_id,
        stage_type=body.stage_type,
        full_name=body.full_name.strip(),
        title=body.title,
        email=body.email.lower().strip(),
        token_expires_at=expires_at,
    )
    db.add(attendee)
    db.commit()
    db.refresh(attendee)

    sign_url = f"{settings.email_base_url}/sign/meeting/{attendee.token}"
    try:
        send_meeting_signing_link(
            to=attendee.email,
            full_name=attendee.full_name,
            company_name=audit_set.company_name or "",
            stage_label=STAGE_LABELS[body.stage_type],
            sign_url=sign_url,
        )
    except Exception:
        pass  # best-effort

    return _att_dict(attendee)


class DirectSignSchema(BaseModel):
    meeting_type: str  # "opening" | "closing"


@protected_router.post("/{audit_set_id}/meeting-attendees/{att_id}/sign-direct")
def sign_attendee_direct(
    audit_set_id: str,
    att_id: str,
    body: DirectSignSchema,
    db: Session = Depends(get_db),
    current_user: PlatformUser = Depends(get_current_user),
):
    if current_user.role not in ALLOWED_ROLES:
        raise HTTPException(403, "Not authorized")
    if body.meeting_type not in ("opening", "closing"):
        raise HTTPException(400, "meeting_type must be 'opening' or 'closing'")

    att = db.query(AuditSetMeetingAttendee).filter_by(
        id=att_id, audit_set_id=audit_set_id
    ).first()
    if not att:
        raise HTTPException(404, "Attendee not found")

    now = datetime.utcnow()
    if body.meeting_type == "opening":
        if att.opening_signed_at:
            raise HTTPException(400, "Opening meeting already marked as signed")
        att.opening_signed_at = now
    else:
        if att.closing_signed_at:
            raise HTTPException(400, "Closing meeting already marked as signed")
        att.closing_signed_at = now

    db.commit()
    db.refresh(att)
    return _att_dict(att)


@protected_router.delete("/{audit_set_id}/meeting-attendees/{att_id}")
def remove_attendee(
    audit_set_id: str,
    att_id: str,
    db: Session = Depends(get_db),
    current_user: PlatformUser = Depends(get_current_user),
):
    if current_user.role not in CB_ROLES:
        raise HTTPException(403, "Only CB staff can remove attendees")

    att = db.query(AuditSetMeetingAttendee).filter_by(
        id=att_id, audit_set_id=audit_set_id
    ).first()
    if not att:
        raise HTTPException(404, "Attendee not found")

    if att.opening_signed_at or att.closing_signed_at:
        raise HTTPException(409, "Cannot remove an attendee who has already signed")

    db.delete(att)
    db.commit()
    return {"removed": True}


@protected_router.post("/{audit_set_id}/meeting-attendees/{att_id}/resend")
def resend_invite(
    audit_set_id: str,
    att_id: str,
    db: Session = Depends(get_db),
    current_user: PlatformUser = Depends(get_current_user),
):
    if current_user.role not in ALLOWED_ROLES:
        raise HTTPException(403, "Not authorized")

    att = db.query(AuditSetMeetingAttendee).filter_by(
        id=att_id, audit_set_id=audit_set_id
    ).first()
    if not att:
        raise HTTPException(404, "Attendee not found")

    audit_set = db.query(AuditSet).filter_by(id=audit_set_id).first()
    settings = get_settings()

    att.token_expires_at = datetime.utcnow() + timedelta(hours=TOKEN_TTL_HOURS)
    db.commit()

    sign_url = f"{settings.email_base_url}/sign/meeting/{att.token}"
    try:
        send_meeting_signing_link(
            to=att.email,
            full_name=att.full_name,
            company_name=audit_set.company_name if audit_set else "",
            stage_label=STAGE_LABELS.get(att.stage_type, att.stage_type),
            sign_url=sign_url,
        )
    except Exception:
        pass

    return {"resent": True}


# ── Public router (guest signing — NO auth dependency) ────────────────────────

public_router = APIRouter(prefix="/sign/meeting", tags=["meeting-signing"])


def _get_attendee_by_token(token: str, db: Session) -> AuditSetMeetingAttendee:
    att = db.query(AuditSetMeetingAttendee).filter_by(token=token).first()
    if not att:
        raise HTTPException(404, "Signing link not found")
    if att.token_expires_at and datetime.utcnow() > att.token_expires_at:
        # Expired, but only block if neither event is signed yet
        if not att.opening_signed_at and not att.closing_signed_at:
            raise HTTPException(410, "This signing link has expired")
    return att


@public_router.get("/{token}")
def get_signing_info(token: str, db: Session = Depends(get_db)):
    """
    Public endpoint — returns attendee and audit info needed to render the
    signing page. No sensitive data (no email, no OTP hashes).
    """
    att = _get_attendee_by_token(token, db)
    audit_set = db.query(AuditSet).filter_by(id=att.audit_set_id).first()
    return {
        "full_name":         att.full_name,
        "title":             att.title,
        "company_name":      audit_set.company_name if audit_set else "",
        "stage_label":       STAGE_LABELS.get(att.stage_type, att.stage_type),
        "opening_signed":    att.opening_signed_at is not None,
        "opening_signed_at": att.opening_signed_at.isoformat() if att.opening_signed_at else None,
        "closing_signed":    att.closing_signed_at is not None,
        "closing_signed_at": att.closing_signed_at.isoformat() if att.closing_signed_at else None,
        "token_expires_at":  att.token_expires_at.isoformat() if att.token_expires_at else None,
    }


@public_router.post("/{token}/request-otp")
def request_meeting_otp(
    token: str,
    event_type: str,
    db: Session = Depends(get_db),
):
    if event_type not in ("opening", "closing"):
        raise HTTPException(400, "event_type must be 'opening' or 'closing'")

    att = _get_attendee_by_token(token, db)

    if event_type == "opening" and att.opening_signed_at:
        raise HTTPException(400, "Opening meeting already signed")
    if event_type == "closing" and att.closing_signed_at:
        raise HTTPException(400, "Closing meeting already signed")

    audit_set = db.query(AuditSet).filter_by(id=att.audit_set_id).first()

    otp = f"{secrets.randbelow(900000) + 100000}"
    otp_hash    = _hash(otp)
    otp_expires = datetime.utcnow() + timedelta(minutes=OTP_EXPIRY_MIN)

    if event_type == "opening":
        att.opening_otp_hash    = otp_hash
        att.opening_otp_expires = otp_expires
    else:
        att.closing_otp_hash    = otp_hash
        att.closing_otp_expires = otp_expires

    db.commit()

    try:
        send_meeting_otp(
            to=att.email,
            full_name=att.full_name,
            event_type=event_type,
            company_name=audit_set.company_name if audit_set else "",
            otp=otp,
        )
    except Exception:
        pass

    return {"message": f"Code sent to your registered email. Valid for {OTP_EXPIRY_MIN} minutes."}


@public_router.post("/{token}/verify")
def verify_meeting_signature(
    token: str,
    event_type: str,
    otp: str,
    request: Request,
    db: Session = Depends(get_db),
):
    if event_type not in ("opening", "closing"):
        raise HTTPException(400, "event_type must be 'opening' or 'closing'")

    att = _get_attendee_by_token(token, db)

    if event_type == "opening":
        if att.opening_signed_at:
            raise HTTPException(400, "Already signed")
        if not att.opening_otp_hash or not att.opening_otp_expires:
            raise HTTPException(400, "No pending OTP. Request one first.")
        if datetime.utcnow() > att.opening_otp_expires:
            raise HTTPException(400, "OTP expired. Please request a new one.")
        if _hash(otp.strip()) != att.opening_otp_hash:
            raise HTTPException(400, "Invalid code.")
        att.opening_signed_at   = datetime.utcnow()
        att.opening_signed_ip   = request.client.host if request.client else None
        att.opening_otp_hash    = None
        att.opening_otp_expires = None
    else:
        if att.closing_signed_at:
            raise HTTPException(400, "Already signed")
        if not att.closing_otp_hash or not att.closing_otp_expires:
            raise HTTPException(400, "No pending OTP. Request one first.")
        if datetime.utcnow() > att.closing_otp_expires:
            raise HTTPException(400, "OTP expired. Please request a new one.")
        if _hash(otp.strip()) != att.closing_otp_hash:
            raise HTTPException(400, "Invalid code.")
        att.closing_signed_at   = datetime.utcnow()
        att.closing_signed_ip   = request.client.host if request.client else None
        att.closing_otp_hash    = None
        att.closing_otp_expires = None

    db.commit()
    signed_at = (att.opening_signed_at if event_type == "opening" else att.closing_signed_at)
    return {"signed": True, "event_type": event_type, "signed_at": signed_at.isoformat()}
