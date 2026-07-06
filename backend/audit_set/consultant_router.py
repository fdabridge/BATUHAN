"""
BATUHAN — Consultant Portal Router (Portal 106)

Read-only endpoints for consultant-role users.
A consultant can only see audit sets where consultant_id = their own user id.
No write actions — purely a status tracker.
"""
from __future__ import annotations
import logging
from datetime import date
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from audit_set.db_models import AuditSet, get_db
from auth.db_models import PlatformUser, get_db as get_auth_db
from auth.dependencies import get_current_user

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/consultant", tags=["consultant"])

SIMPLE_STATUS: dict[str | None, str] = {
    None:                    "Application Received",
    "pending_review":        "Application Received",
    "in_planning":           "In Planning",
    "notification_sent":     "In Planning",
    "quotation_sent":        "Quotation Sent",
    "agreement_signed":      "Agreement Signed",
    "fr218_in_progress":     "Under Review",
    "fr218_complete":        "Under Review",
    "stage1_scheduled":      "Stage 1 Audit",
    "stage1_in_progress":    "Stage 1 Audit",
    "stage1_complete":       "Stage 1 Complete",
    "stage2_scheduled":      "Stage 2 Audit",
    "stage2_in_progress":    "Stage 2 Audit",
    "under_review":          "Under Review",
    "committee_review":      "Committee Review",
    "certified":             "Certified",
    "audit_scheduled":       "Surveillance Audit",
    "audit_in_progress":     "Surveillance Audit",
    "surveillance_complete": "Surveillance Complete",
}


class ConsultantClientRow(BaseModel):
    id:               str
    company_name:     str
    city:             Optional[str]
    standards:        list
    audit_type:       str
    simple_status:    str
    workflow_status:  Optional[str]
    cert_issued_date: Optional[str]
    cert_expiry_date: Optional[str]
    contact_name:     Optional[str]
    contact_email:    Optional[str]


@router.get("/clients", response_model=list[ConsultantClientRow])
def consultant_clients(
    db:           Session = Depends(get_db),
    auth_db:      Session = Depends(get_auth_db),
    current_user: PlatformUser = Depends(get_current_user),
):
    """Returns the consultant's own referred clients — read-only."""
    if current_user.role != "consultant":
        raise HTTPException(403, "Consultant portal access only.")

    try:
        audit_sets = (
            db.query(AuditSet)
            .filter_by(consultant_id=current_user.id)
            .order_by(AuditSet.company_name)
            .all()
        )
    except Exception as exc:
        logger.error("[Consultant] clients DB error: %s", exc)
        return []

    result: list[ConsultantClientRow] = []
    for a in audit_sets:
        try:
            client_user = (
                auth_db.query(PlatformUser)
                .filter_by(audit_set_id=a.id, role="client")
                .first()
            )
            result.append(ConsultantClientRow(
                id=a.id,
                company_name=a.company_name or "",
                city=a.city,
                standards=a.standards or [],
                audit_type=a.audit_type or "initial",
                simple_status=SIMPLE_STATUS.get(a.workflow_status, "In Progress"),
                workflow_status=a.workflow_status,
                cert_issued_date=a.cert_issued_date.isoformat() if a.cert_issued_date else None,
                cert_expiry_date=a.cert_expiry_date.isoformat() if a.cert_expiry_date else None,
                contact_name=client_user.full_name if client_user else a.representative,
                contact_email=client_user.email if client_user else a.email,
            ))
        except Exception as exc:
            logger.warning("[Consultant] skip audit_set %s: %s", a.id, exc)
    return result


@router.get("/me")
def consultant_profile(current_user: PlatformUser = Depends(get_current_user)):
    """Returns the consultant's own profile (username = their referral code)."""
    if current_user.role != "consultant":
        raise HTTPException(403, "Consultant portal access only.")
    return {
        "id":          current_user.id,
        "full_name":   current_user.full_name,
        "email":       current_user.email,
        "username":    current_user.username,   # this is their referral code
        "referral_code": current_user.username,
    }
