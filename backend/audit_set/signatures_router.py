"""
BATUHAN — Document CB signing (Prompt 12).

CB staff sign documents via OTP before they are released to the client portal.
Prompt 12 covers: cb_planner signs quotation + agreement.
Future prompts extend this to cb_cert_manager, lead_auditor, committee, guests.
"""
from __future__ import annotations
import hashlib
import secrets
from datetime import datetime, timedelta

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.orm import Session

from audit_set.db_models import (
    AuditDocumentSignature, AuditSetSharedDocument, AuditSet,
    AuditSetStatusEvent, get_db,
)
from auth.db_models import PlatformUser, get_db as get_auth_db
from auth.dependencies import get_current_user
from email_service import send_document_released, send_otp_code

router = APIRouter(prefix="/audit-sets", tags=["signatures"])

CB_ROLES   = {"admin", "planner", "officer", "executive"}
OTP_EXPIRY = 10  # minutes


def _hash_otp(otp: str) -> str:
    return hashlib.sha256(otp.encode()).hexdigest()


def _sig_to_dict(s: AuditDocumentSignature, doc_label: str = "",
                 company_name: str = "", plan_number: int | None = None) -> dict:
    return {
        "id":                s.id,
        "audit_set_id":      s.audit_set_id,
        "document_id":       s.document_id,
        "document_type":     s.document_type,
        "document_label":    doc_label or s.document_type.title(),
        "signer_role_label": s.signer_role_label,
        "signer_name":       s.signer_name,
        "company_name":      company_name,
        "plan_number":       plan_number,
        "required":          s.required,
        "order_index":       s.order_index,
        "signed_at":         s.signed_at.isoformat() if s.signed_at else None,
        "is_signed":         s.signed_at is not None,
        "created_at":        s.created_at.isoformat() if s.created_at else None,
    }


@router.get("/my-pending-signatures")
def get_my_pending_signatures(
    db: Session = Depends(get_db),
    current_user: PlatformUser = Depends(get_current_user),
):
    """Unsigned signature slots assigned to (or claimable by) the current user."""
    if current_user.role not in CB_ROLES:
        raise HTTPException(403, "Not authorized")

    # Slots explicitly assigned to me
    assigned = (
        db.query(AuditDocumentSignature)
        .filter_by(signer_user_id=current_user.id)
        .filter(AuditDocumentSignature.signed_at.is_(None))
        .all()
    )

    # Unassigned slots this user is eligible to claim
    eligible_labels: list[str] = []
    if current_user.role in ("admin", "executive"):
        eligible_labels.append("cb_cert_manager")
    # cb_reviewer eligibility (EA-code check added in Prompt 14)
    if current_user.role in ("admin", "executive", "auditor"):
        eligible_labels.append("cb_reviewer")

    unassigned: list[AuditDocumentSignature] = []
    if eligible_labels:
        unassigned = (
            db.query(AuditDocumentSignature)
            .filter(AuditDocumentSignature.signer_user_id.is_(None))
            .filter(AuditDocumentSignature.signer_role_label.in_(eligible_labels))
            .filter(AuditDocumentSignature.signed_at.is_(None))
            .all()
        )

    sigs = assigned + unassigned

    results = []
    for s in sigs:
        audit_set = db.query(AuditSet).filter_by(id=s.audit_set_id).first()
        doc_label = s.document_type.title()
        if s.document_id:
            doc = db.query(AuditSetSharedDocument).filter_by(id=s.document_id).first()
            if doc:
                doc_label = doc.label
        results.append(_sig_to_dict(
            s,
            doc_label=doc_label,
            company_name=audit_set.company_name if audit_set else "",
            plan_number=audit_set.plan_number if audit_set else None,
        ))
    return results


@router.post("/{audit_set_id}/signatures/{sig_id}/request-otp")
def request_cb_signature_otp(
    audit_set_id: str,
    sig_id: str,
    db: Session = Depends(get_db),
    current_user: PlatformUser = Depends(get_current_user),
):
    if current_user.role not in CB_ROLES:
        raise HTTPException(403, "Not authorized")

    sig = db.query(AuditDocumentSignature).filter_by(
        id=sig_id, audit_set_id=audit_set_id
    ).first()
    if not sig:
        raise HTTPException(404, "Signature request not found")

    # Self-assign if the slot is unassigned and the caller is eligible
    if sig.signer_user_id is None:
        eligible = False
        if sig.signer_role_label == "cb_cert_manager" and current_user.role in ("admin", "executive"):
            eligible = True
        if sig.signer_role_label == "cb_reviewer" and current_user.role in ("admin", "executive", "auditor"):
            eligible = True
        if not eligible:
            raise HTTPException(403, "You are not eligible to sign this slot")
        sig.signer_user_id = current_user.id
        sig.signer_name    = current_user.full_name
        sig.signer_email   = current_user.email
        db.commit()
    elif sig.signer_user_id != current_user.id:
        raise HTTPException(403, "This signature is not assigned to you")

    if sig.signed_at:
        raise HTTPException(400, "Already signed")

    otp = f"{secrets.randbelow(900000) + 100000}"
    sig.otp_hash = _hash_otp(otp)
    sig.otp_expires_at = datetime.utcnow() + timedelta(minutes=OTP_EXPIRY)
    db.commit()

    doc_label = sig.document_type.title()
    if sig.document_id:
        doc = db.query(AuditSetSharedDocument).filter_by(id=sig.document_id).first()
        if doc:
            doc_label = doc.label

    try:
        send_otp_code(
            to=current_user.email,
            full_name=current_user.full_name,
            otp=otp,
            document_label=doc_label,
        )
    except Exception:
        pass

    return {"message": f"OTP sent to {current_user.email}. Valid for {OTP_EXPIRY} minutes."}


@router.post("/{audit_set_id}/signatures/{sig_id}/verify")
def verify_cb_signature(
    audit_set_id: str,
    sig_id: str,
    otp: str,
    request: Request,
    db: Session = Depends(get_db),
    auth_db: Session = Depends(get_auth_db),
    current_user: PlatformUser = Depends(get_current_user),
):
    if current_user.role not in CB_ROLES:
        raise HTTPException(403, "Not authorized")

    sig = db.query(AuditDocumentSignature).filter_by(
        id=sig_id, audit_set_id=audit_set_id
    ).first()
    if not sig:
        raise HTTPException(404, "Signature request not found")

    # Self-assign if unassigned and caller is eligible
    if sig.signer_user_id is None:
        eligible = False
        if sig.signer_role_label == "cb_cert_manager" and current_user.role in ("admin", "executive"):
            eligible = True
        if sig.signer_role_label == "cb_reviewer" and current_user.role in ("admin", "executive", "auditor"):
            eligible = True
        if not eligible:
            raise HTTPException(403, "You are not eligible to sign this slot")
        sig.signer_user_id = current_user.id
        sig.signer_name    = current_user.full_name
        sig.signer_email   = current_user.email
    elif sig.signer_user_id != current_user.id:
        raise HTTPException(403, "This signature is not assigned to you")

    if sig.signed_at:
        raise HTTPException(400, "Already signed")
    if not sig.otp_hash or not sig.otp_expires_at:
        raise HTTPException(400, "No pending OTP. Request one first.")
    if datetime.utcnow() > sig.otp_expires_at:
        raise HTTPException(400, "OTP expired. Please request a new one.")
    if _hash_otp(otp.strip()) != sig.otp_hash:
        raise HTTPException(400, "Invalid OTP code.")

    sig.signed_at = datetime.utcnow()
    sig.signed_ip = request.client.host if request.client else None
    sig.otp_hash = None
    sig.otp_expires_at = None
    db.commit()

    # If all required signatures on the underlying document are now collected,
    # flip the document to "released" and advance the workflow + notify client.
    if sig.document_id:
        doc = db.query(AuditSetSharedDocument).filter_by(id=sig.document_id).first()
        if doc and doc.status == "pending_cb_signature":
            remaining = (
                db.query(AuditDocumentSignature)
                .filter_by(document_id=sig.document_id, required=True)
                .filter(AuditDocumentSignature.signed_at.is_(None))
                .count()
            )
            if remaining == 0:
                doc.status = "released"
                audit_set = db.query(AuditSet).filter_by(id=audit_set_id).first()

                if audit_set and doc.document_type == "quotation":
                    if audit_set.workflow_status == "in_planning":
                        audit_set.workflow_status = "quotation_sent"
                        db.add(AuditSetStatusEvent(
                            audit_set_id=audit_set_id,
                            from_status="in_planning",
                            to_status="quotation_sent",
                            triggered_by=current_user.id,
                            notes="Quotation signed by CB planner and released to client",
                        ))

                db.commit()

                client_user = auth_db.query(PlatformUser).filter_by(
                    audit_set_id=audit_set_id, role="client"
                ).first()
                if client_user:
                    try:
                        send_document_released(
                            to=client_user.email,
                            full_name=client_user.full_name,
                            document_label=doc.label,
                        )
                    except Exception:
                        pass

    return {"signed": True, "signed_at": sig.signed_at.isoformat()}



@router.get("/{audit_set_id}/internal-signatures")
def get_internal_signatures(
    audit_set_id: str,
    db: Session = Depends(get_db),
    current_user: PlatformUser = Depends(get_current_user),
):
    """
    Returns all internal-document signature slots (FR218, FR222) for this audit set.
    CB only. Powers the InternalApprovalsSection on the client detail page.
    """
    if current_user.role not in CB_ROLES:
        raise HTTPException(403, "Not authorized")

    sigs = (
        db.query(AuditDocumentSignature)
        .filter_by(audit_set_id=audit_set_id)
        .filter(AuditDocumentSignature.document_type.in_(["FR218", "FR222"]))
        .order_by(AuditDocumentSignature.document_type, AuditDocumentSignature.order_index)
        .all()
    )

    eligible_labels: set[str] = set()
    if current_user.role in ("admin", "executive"):
        eligible_labels.add("cb_cert_manager")
    if current_user.role in ("admin", "executive", "auditor"):
        eligible_labels.add("cb_reviewer")

    return [
        {
            "id":                  s.id,
            "document_type":       s.document_type,
            "signer_role_label":   s.signer_role_label,
            "signer_name":         s.signer_name,
            "signer_user_id":      s.signer_user_id,
            "is_signed":           s.signed_at is not None,
            "signed_at":           s.signed_at.isoformat() if s.signed_at else None,
            "is_mine":             s.signer_user_id == current_user.id,
            "can_claim":           s.signer_user_id is None
                                   and s.signer_role_label in eligible_labels
                                   and s.signed_at is None,
            "pending_appointment": s.signer_role_label == "cb_reviewer" and s.signer_user_id is None,
            "required":            s.required,
            "order_index":         s.order_index,
        }
        for s in sigs
    ]


@router.post("/{audit_set_id}/signatures/create-fr222")
def create_fr222_signatures(
    audit_set_id: str,
    db: Session = Depends(get_db),
    current_user: PlatformUser = Depends(get_current_user),
):
    """
    Planner triggers creation of FR.222 Audit Programme signature slots.
    Idempotent — if slots already exist, returns without creating duplicates.
    """
    if current_user.role not in {"admin", "planner"}:
        raise HTTPException(403, "Only planners can create the audit programme signature")

    existing = (
        db.query(AuditDocumentSignature)
        .filter_by(audit_set_id=audit_set_id, document_type="FR222")
        .first()
    )
    if existing:
        return {"created": False, "message": "FR.222 signature slots already exist"}

    db.add(AuditDocumentSignature(
        audit_set_id=audit_set_id,
        document_id=None,
        document_type="FR222",
        signer_role_label="cb_planner",
        signer_user_id=current_user.id,
        signer_name=current_user.full_name,
        signer_email=current_user.email,
        required=True,
        order_index=0,
    ))
    db.add(AuditDocumentSignature(
        audit_set_id=audit_set_id,
        document_id=None,
        document_type="FR222",
        signer_role_label="cb_cert_manager",
        signer_user_id=None,
        signer_name=None,
        signer_email=None,
        required=True,
        order_index=1,
    ))
    db.commit()
    return {"created": True}
