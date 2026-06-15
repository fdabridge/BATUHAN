"""
BATUHAN — Certification Committee appointment (Prompt 14).

Endpoints under /audit-sets:
  GET    /audit-sets/{id}/committee
  GET    /audit-sets/{id}/committee/eligible-users
  POST   /audit-sets/{id}/committee/appoint
  DELETE /audit-sets/{id}/committee/{member_id}
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from pydantic import BaseModel
from sqlalchemy import and_, or_
from sqlalchemy.orm import Session

from audit_set.db_models import (
    AuditSet, AuditSetCommitteeMember, AuditSetFR233Record, AuditSetSharedDocument,
    AuditSetStage, AuditDocumentSignature, VisualSignaturePlacement, get_db,
)
from auth.db_models import PlatformUser, get_db as get_auth_db
from auth.dependencies import get_current_user

router = APIRouter(prefix="/audit-sets", tags=["committee"])

CB_ROLES = {"admin", "planner", "officer", "executive", "gm"}
CM_ROLES = {"admin", "executive"}   # roles that act as Certification Manager


def _collect_stage_auditor_ids(stages: list) -> set[str]:
    """Return the set of auditors.auditors.id values assigned to any stage."""
    ids: set[str] = set()
    for s in stages:
        if s.lead_auditor_id:
            ids.add(s.lead_auditor_id)
        for group in (s.auditors or [], s.technical_experts or [],
                      s.observers or [], s.ik_experts or [], s.evaluators or []):
            for p in group:
                if isinstance(p, dict) and p.get("id"):
                    ids.add(p["id"])
    return ids


@router.get("/{audit_set_id}/committee")
def get_committee(
    audit_set_id: str,
    db: Session = Depends(get_db),
    current_user: PlatformUser = Depends(get_current_user),
):
    if current_user.role not in CB_ROLES:
        raise HTTPException(403, "Not authorized")

    members = (
        db.query(AuditSetCommitteeMember)
        .filter_by(audit_set_id=audit_set_id)
        .order_by(AuditSetCommitteeMember.appointed_at)
        .all()
    )
    reviewer_sigs = {
        s.signer_user_id: s
        for s in db.query(AuditDocumentSignature).filter_by(
            audit_set_id=audit_set_id,
            signer_role_label="cb_reviewer",
        ).all()
        if s.signer_user_id
    }
    return [
        {
            "id":                      m.id,
            "user_id":                 m.user_id,
            "user_name":               m.user_name,
            "user_email":              m.user_email,
            "role":                    m.role,
            "appointed_by":            m.appointed_by,
            "ea_codes_at_appointment": m.ea_codes_at_appointment,
            "appointed_at":            m.appointed_at.isoformat() if m.appointed_at else None,
            "has_signed_fr218":        (
                reviewer_sigs.get(m.user_id) is not None
                and reviewer_sigs[m.user_id].signed_at is not None
            ),
        }
        for m in members
    ]


@router.get("/{audit_set_id}/committee/eligible-users")
def get_eligible_users(
    audit_set_id: str,
    db: Session = Depends(get_db),
    auth_db: Session = Depends(get_auth_db),
    current_user: PlatformUser = Depends(get_current_user),
):
    if current_user.role not in CB_ROLES:
        raise HTTPException(403, "Not authorized")

    audit_set = db.query(AuditSet).filter_by(id=audit_set_id).first()
    if not audit_set:
        raise HTTPException(404, "Audit set not found")

    stages = db.query(AuditSetStage).filter_by(audit_set_id=audit_set_id).all()
    stage_auditor_ids = _collect_stage_auditor_ids(stages)

    already_appointed_user_ids = {
        m.user_id for m in
        db.query(AuditSetCommitteeMember).filter_by(audit_set_id=audit_set_id).all()
    }

    # Portal 54 — eligible candidates are CB staff PLUS external auditors with
    # a linked auditor profile. Previously CB-only filtering excluded auditors
    # from the committee picker even when they covered the right EA codes.
    candidate_users = (
        auth_db.query(PlatformUser)
        .filter(
            PlatformUser.is_active == True,  # noqa: E712
            or_(
                PlatformUser.role.in_(CB_ROLES),
                and_(
                    PlatformUser.role == "auditor",
                    PlatformUser.auditor_id.isnot(None),
                ),
            ),
        )
        .all()
    )

    from auditors.models import Auditor as AuditorModel

    plan_ea_code = (audit_set.ea_code or "").strip()

    results = []
    for u in candidate_users:
        if u.id in already_appointed_user_ids:
            continue

        ea_codes: list[str] = []
        on_audit_team = False

        if u.auditor_id:
            if u.auditor_id in stage_auditor_ids:
                on_audit_team = True
            auditor = db.query(AuditorModel).filter_by(id=u.auditor_id).first()
            if auditor:
                ea_codes = auditor.ea_codes or []

        if on_audit_team:
            continue

        if ea_codes:
            ea_match = (not plan_ea_code) or (plan_ea_code in ea_codes)
        else:
            ea_match = True

        results.append({
            "user_id":              u.id,
            "full_name":            u.full_name,
            "email":                u.email,
            "role":                 u.role,
            "ea_codes":             ea_codes,
            "ea_match":             ea_match,
            "has_auditor_profile":  bool(u.auditor_id),
            "eligible_as_reviewer": ea_match,
        })

    results.sort(key=lambda x: (not x["eligible_as_reviewer"], x["full_name"]))
    return results


class AppointRequest(BaseModel):
    # Portal 61 — user_id optional for role="reviewer" (auto-resolves to the
    # system's certification_manager). Still required for decision_maker.
    user_id: str | None = None
    role: str  # "reviewer" | "decision_maker"


@router.get("/{audit_set_id}/committee/cert-manager")
def get_cert_manager(
    audit_set_id: str,
    db: Session = Depends(get_db),
    auth_db: Session = Depends(get_auth_db),
    current_user: PlatformUser = Depends(get_current_user),
):
    """Portal 61 — return the single active Certification Manager for display
    in the auto-assign reviewer confirmation UI."""
    if current_user.role not in CB_ROLES:
        raise HTTPException(403, "Not authorized")
    if not db.query(AuditSet).filter_by(id=audit_set_id).first():
        raise HTTPException(404, "Audit set not found")
    cm = auth_db.query(PlatformUser).filter_by(
        role="certification_manager", is_active=True,
    ).first()
    if not cm:
        return {"cert_manager": None}
    return {"cert_manager": {"user_id": cm.id, "full_name": cm.full_name, "email": cm.email}}


@router.post("/{audit_set_id}/committee/appoint")
def appoint_committee_member(
    audit_set_id: str,
    body: AppointRequest,
    db: Session = Depends(get_db),
    auth_db: Session = Depends(get_auth_db),
    current_user: PlatformUser = Depends(get_current_user),
):
    if current_user.role not in {"admin", "planner"}:
        raise HTTPException(403, "Only admin or planner can appoint committee members")

    if body.role not in ("reviewer", "decision_maker"):
        raise HTTPException(400, "role must be 'reviewer' or 'decision_maker'")

    audit_set = db.query(AuditSet).filter_by(id=audit_set_id).first()
    if not audit_set:
        raise HTTPException(404, "Audit set not found")

    # Portal 61 — reviewer role is auto-assigned to the system's single
    # Certification Manager; any caller-supplied user_id is ignored.
    if body.role == "reviewer":
        user = auth_db.query(PlatformUser).filter_by(
            role="certification_manager", is_active=True,
        ).first()
        if not user:
            raise HTTPException(
                400, "No active Certification Manager account found",
            )
    else:
        if not body.user_id:
            raise HTTPException(400, "user_id is required for decision_maker")
        user = auth_db.query(PlatformUser).filter_by(id=body.user_id).first()
        if not user or user.role not in CB_ROLES:
            raise HTTPException(400, "User not found or not a CB user")

    already = db.query(AuditSetCommitteeMember).filter_by(
        audit_set_id=audit_set_id, user_id=user.id
    ).first()
    if already:
        raise HTTPException(409, "User is already a committee member for this audit set")

    from auditors.models import Auditor as AuditorModel
    ea_codes_snapshot: list[str] = []
    if user.auditor_id:
        auditor = db.query(AuditorModel).filter_by(id=user.auditor_id).first()
        if auditor:
            ea_codes_snapshot = auditor.ea_codes or []

    member = AuditSetCommitteeMember(
        audit_set_id=audit_set_id,
        user_id=user.id,
        user_name=user.full_name,
        user_email=user.email,
        role=body.role,
        appointed_by=current_user.id,
        ea_codes_at_appointment=ea_codes_snapshot,
    )
    db.add(member)

    if body.role == "reviewer":
        sig = (
            db.query(AuditDocumentSignature)
            .filter_by(
                audit_set_id=audit_set_id,
                document_type="FR218",
                signer_role_label="cb_reviewer",
            )
            .first()
        )
        if sig and not sig.signed_at:
            sig.signer_user_id = user.id
            sig.signer_name    = user.full_name
            sig.signer_email   = user.email

    db.commit()
    return {
        "appointed": True,
        "user_id":   user.id,
        "user_name": user.full_name,
        "role":      body.role,
    }


@router.delete("/{audit_set_id}/committee/{member_id}")
def remove_committee_member(
    audit_set_id: str,
    member_id: str,
    db: Session = Depends(get_db),
    current_user: PlatformUser = Depends(get_current_user),
):
    if current_user.role not in {"admin", "planner"}:
        raise HTTPException(403, "Not authorized")

    member = db.query(AuditSetCommitteeMember).filter_by(
        id=member_id, audit_set_id=audit_set_id
    ).first()
    if not member:
        raise HTTPException(404, "Committee member not found")

    has_signed = (
        db.query(AuditDocumentSignature)
        .filter_by(audit_set_id=audit_set_id, signer_user_id=member.user_id)
        .filter(AuditDocumentSignature.signed_at.isnot(None))
        .count()
    ) > 0
    if has_signed:
        raise HTTPException(
            409, "Cannot remove a committee member who has already signed documents"
        )

    if member.role == "reviewer":
        sig = (
            db.query(AuditDocumentSignature)
            .filter_by(
                audit_set_id=audit_set_id,
                document_type="FR218",
                signer_role_label="cb_reviewer",
                signer_user_id=member.user_id,
            )
            .first()
        )
        if sig:
            sig.signer_user_id = None
            sig.signer_name    = None
            sig.signer_email   = None

    db.delete(member)
    db.commit()
    return {"removed": True}


# ── Portal 49a Part 3 — FR.233 Review & Decision Form ─────────────────────────

@router.post("/{audit_set_id}/fr233/generate")
def generate_fr233(
    audit_set_id: str,
    db: Session = Depends(get_db),
    current_user: PlatformUser = Depends(get_current_user),
):
    """Render FR.233 from the blank template, persist it as a SharedDocument and
    upsert the AuditSetFR233Record. Idempotent: re-running overwrites the file
    and resets status to ``signing``."""
    import os
    from datetime import datetime
    from audit_set.fr233_generator import render_fr233_bytes
    from config.settings import get_settings

    if current_user.role not in {"admin", "planner", "executive"}:
        raise HTTPException(403, "Only Planner or Certification Manager may generate FR.233")

    audit_set = db.query(AuditSet).filter_by(id=audit_set_id).first()
    if not audit_set:
        raise HTTPException(404, "Audit set not found")

    allowed_statuses = {
        "stage2_complete", "committee_review", "under_review",
        "stage2_in_progress",
    }
    if audit_set.workflow_status not in allowed_statuses:
        raise HTTPException(
            400,
            f"FR.233 cannot be generated while workflow_status='{audit_set.workflow_status}'. "
            "Complete Stage 2 first.",
        )

    members = db.query(AuditSetCommitteeMember).filter_by(audit_set_id=audit_set_id).count()
    if members < 1:
        raise HTTPException(400, "Appoint at least one committee member before generating FR.233")

    try:
        docx_bytes = render_fr233_bytes(audit_set, db)
    except Exception as exc:
        raise HTTPException(500, f"FR.233 render failed: {exc}")

    settings = get_settings()
    out_dir = os.path.join(settings.storage_base_path, "shared_docs", audit_set_id)
    os.makedirs(out_dir, exist_ok=True)
    out_path = os.path.join(out_dir, f"FR233_{audit_set.plan_number or audit_set_id}.docx")
    with open(out_path, "wb") as f:
        f.write(docx_bytes)

    record = db.query(AuditSetFR233Record).filter_by(audit_set_id=audit_set_id).first()
    doc = None
    if record and record.document_id:
        doc = db.query(AuditSetSharedDocument).filter_by(id=record.document_id).first()
    if doc is None:
        doc = AuditSetSharedDocument(
            audit_set_id=audit_set_id,
            label=f"FR.233 Review & Decision — {audit_set.plan_number or ''}".strip(" —"),
            document_type="fr233",
            file_path=out_path,
            direction="cb_to_client",
            status="released",
            released_by=current_user.id,
            released_at=datetime.utcnow(),
        )
        db.add(doc)
        db.flush()
    else:
        doc.file_path  = out_path
        doc.status     = "released"
        doc.released_by= current_user.id
        doc.released_at= datetime.utcnow()
        # Old PDF + extracted SIG fields are stale — drop them so the viewer
        # re-converts and re-extracts from the new DOCX on next open.
        pdf_path = os.path.splitext(out_path)[0] + ".pdf"
        if os.path.exists(pdf_path):
            try:    os.remove(pdf_path)
            except Exception: pass
        from audit_set.db_models import DocumentSignatureField
        db.query(DocumentSignatureField).filter_by(docx_path=os.path.abspath(out_path)).delete()

    if record is None:
        record = AuditSetFR233Record(
            audit_set_id=audit_set_id, document_id=doc.id, status="signing",
        )
        db.add(record)
    else:
        record.document_id = doc.id
        record.status      = "signing"

    if audit_set.workflow_status in {"stage2_complete", "stage2_in_progress"}:
        old = audit_set.workflow_status
        audit_set.workflow_status = "committee_review"
        from audit_set.db_models import AuditSetStatusEvent
        db.add(AuditSetStatusEvent(
            audit_set_id=audit_set_id, from_status=old, to_status="committee_review",
            triggered_by=current_user.id, notes="FR.233 generated; committee review opened",
        ))

    db.commit()
    return {
        "generated":    True,
        "document_id":  doc.id,
        "fr233_status": record.status,
    }


@router.post("/{audit_set_id}/fr233/upload")
async def upload_fr233(
    audit_set_id: str,
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
    current_user: PlatformUser = Depends(get_current_user),
):
    """Portal 57 — committee uploads the completed FR.233 Review & Decision Form
    (PDF or DOCX) prepared offline. Stored as a SharedDocument and tracked via
    AuditSetFR233Record; committee + CM sign it afterwards through the viewer.
    Mirrors the persistence path of /fr233/generate so the existing signing
    flow keeps working unchanged."""
    import os
    from datetime import datetime
    from config.settings import get_settings

    if current_user.role not in {"admin", "planner", "executive", "certification_manager"}:
        raise HTTPException(403, "Not authorized to upload FR.233")

    audit_set = db.query(AuditSet).filter_by(id=audit_set_id).first()
    if not audit_set:
        raise HTTPException(404, "Audit set not found")

    ext = os.path.splitext(file.filename or "")[1].lower()
    if ext not in {".pdf", ".docx"}:
        raise HTTPException(400, "Only PDF and DOCX files are accepted for FR.233")

    settings = get_settings()
    out_dir = os.path.join(settings.storage_base_path, "shared_docs", audit_set_id)
    os.makedirs(out_dir, exist_ok=True)
    out_path = os.path.join(out_dir, f"FR233_{audit_set.plan_number or audit_set_id}{ext}")

    contents = await file.read()
    with open(out_path, "wb") as f:
        f.write(contents)

    record = db.query(AuditSetFR233Record).filter_by(audit_set_id=audit_set_id).first()
    doc = None
    if record and record.document_id:
        doc = db.query(AuditSetSharedDocument).filter_by(id=record.document_id).first()
    if doc is None:
        doc = AuditSetSharedDocument(
            audit_set_id=audit_set_id,
            label=f"FR.233 Review & Decision — {audit_set.plan_number or ''}".strip(" —"),
            document_type="fr233",
            file_path=out_path,
            direction="cb_to_client",
            status="released",
            released_by=current_user.id,
            released_at=datetime.utcnow(),
        )
        db.add(doc)
        db.flush()
    else:
        # Replacing the file — drop any stale rendered PDF + extracted sig fields
        # so the viewer re-converts and re-extracts on next open.
        if doc.file_path and doc.file_path != out_path and os.path.exists(doc.file_path):
            try:    os.remove(doc.file_path)
            except Exception: pass
        old_pdf = os.path.splitext(doc.file_path or "")[0] + ".pdf"
        if old_pdf and os.path.exists(old_pdf):
            try:    os.remove(old_pdf)
            except Exception: pass
        doc.file_path   = out_path
        doc.status      = "released"
        doc.released_by = current_user.id
        doc.released_at = datetime.utcnow()
        from audit_set.db_models import DocumentSignatureField
        db.query(DocumentSignatureField).filter_by(docx_path=os.path.abspath(out_path)).delete()

    if record is None:
        record = AuditSetFR233Record(
            audit_set_id=audit_set_id, document_id=doc.id, status="signing",
        )
        db.add(record)
    else:
        record.document_id = doc.id
        record.status      = "signing"

    if audit_set.workflow_status in {"stage2_complete", "stage2_in_progress"}:
        old = audit_set.workflow_status
        audit_set.workflow_status = "committee_review"
        from audit_set.db_models import AuditSetStatusEvent
        db.add(AuditSetStatusEvent(
            audit_set_id=audit_set_id, from_status=old, to_status="committee_review",
            triggered_by=current_user.id, notes="FR.233 uploaded; committee review opened",
        ))

    db.commit()
    return {
        "uploaded":     True,
        "document_id":  doc.id,
        "fr233_status": record.status,
    }


@router.get("/{audit_set_id}/fr233")
def get_fr233_status(
    audit_set_id: str,
    db: Session = Depends(get_db),
    current_user: PlatformUser = Depends(get_current_user),
):
    if current_user.role not in CB_ROLES:
        raise HTTPException(403, "Not authorized")

    record = db.query(AuditSetFR233Record).filter_by(audit_set_id=audit_set_id).first()
    members = (
        db.query(AuditSetCommitteeMember)
        .filter_by(audit_set_id=audit_set_id)
        .order_by(AuditSetCommitteeMember.appointed_at)
        .all()
    )

    # Per-slot signed lookup from VisualSignaturePlacement (the source of truth
    # for committee signing — populated by /viewer/sign/confirm).
    placements = []
    if record and record.document_id:
        placements = (
            db.query(VisualSignaturePlacement)
            .filter_by(document_type="shared_doc", doc_id=record.document_id)
            .filter(VisualSignaturePlacement.signed_at.isnot(None))
            .all()
        )
    signed_keys = {p.sig_key for p in placements}

    chair = next((m for m in members if m.role == "decision_maker"), None)
    regulars = [m for m in members if m is not chair]
    slot_for_member = {}
    if chair: slot_for_member[chair.id] = "COMMITTEE_CHAIR"
    if len(regulars) > 0: slot_for_member[regulars[0].id] = "COMMITTEE_MEMBER_1"
    if len(regulars) > 1: slot_for_member[regulars[1].id] = "COMMITTEE_MEMBER_2"

    return {
        "status":             record.status if record else "pending",
        "document_id":        record.document_id if record else None,
        "members": [
            {
                "id":         m.id,
                "user_id":    m.user_id,
                "user_name":  m.user_name,
                "role":       m.role,
                "sig_key":    slot_for_member.get(m.id),
                "ea_codes":   m.ea_codes_at_appointment or [],
                "signed":     slot_for_member.get(m.id) in signed_keys,
            }
            for m in members
        ],
        "cert_manager_signed": "CERT_MANAGER_FR233" in signed_keys,
        "all_committee_signed": all(
            slot_for_member.get(m.id) in signed_keys for m in members if slot_for_member.get(m.id)
        ) and bool(members),
    }
