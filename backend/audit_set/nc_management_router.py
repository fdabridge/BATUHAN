"""
Portal 103 — NC Management Router.

Nonconformity lifecycle:
  auditor submits decision → client uploads evidence → auditor reviews → closed/rejected

Routes:
  POST /audit-sets/{id}/nc-decision
  GET  /audit-sets/{id}/nc-decision
  POST /audit-sets/{id}/nc-items/{nc_id}/evidence
  POST /audit-sets/{id}/nc-items/{nc_id}/review
  GET  /client/my-audit-set/ncs
  GET  /client/my-audit-set/ncs/{nc_id}/evidence/{ev_id}/download
  GET  /audit-sets/{id}/nc-items/{nc_id}/evidence/{ev_id}/download
  GET  /nc-management/summary
"""
from __future__ import annotations
import os
import secrets
from datetime import date, timedelta, datetime
from typing import Optional

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, UploadFile
from fastapi.responses import FileResponse
from pydantic import BaseModel
from sqlalchemy.orm import Session

from audit_set.db_models import (
    AuditSet,
    AuditSetAuditReport,
    AuditSetNCDecision,
    AuditSetNCItem,
    AuditSetNCEvidence,
    AuditSetNCReview,
    AuditSetStage,
    NC_DUE_DAYS,
    get_db,
)
from auth.db_models import PlatformUser, get_db as get_auth_db
from auth.dependencies import get_current_user
from config.settings import get_settings
from storage.document_store import upload as store_upload, ensure_local

router = APIRouter(tags=["nc_management"])

CB_ROLES    = {"admin", "planner", "planner_us", "officer", "executive", "gm"}
AUDITOR_ROLES = {"auditor"}

NC_STAGE_TYPES = {"stage_1", "stage_2", "surveillance", "recertification"}
NC_STAGE_LABELS = {
    "stage_1": "Stage 1",
    "stage_2": "Stage 2",
    "surveillance": "Surveillance",
    "recertification": "Recertification",
}
REPORT_FORMS_BY_STAGE = {
    "stage_1": {"FR.231", "FR.231-1", "FR.229"},
    "stage_2": {"FR.232", "FR.229"},
    "surveillance": {"FR.232", "FR.229"},
    "recertification": {"FR.232", "FR.229"},
}


# ── Serialisers ───────────────────────────────────────────────────────────────

def _ev_dict(ev: AuditSetNCEvidence) -> dict:
    return {
        "id":           ev.id,
        "nc_item_id":   ev.nc_item_id,
        "file_name":    ev.file_name,
        "upload_type":  ev.upload_type,
        "uploaded_at":  ev.uploaded_at.isoformat() if ev.uploaded_at else None,
        "round_number": ev.round_number,
    }


def _review_dict(r: AuditSetNCReview) -> dict:
    return {
        "id":           r.id,
        "decision":     r.decision,
        "notes":        r.notes,
        "reviewed_at":  r.reviewed_at.isoformat() if r.reviewed_at else None,
        "round_number": r.round_number,
    }


def _item_dict(item: AuditSetNCItem, db: Session) -> dict:
    evidence = (
        db.query(AuditSetNCEvidence)
        .filter_by(nc_item_id=item.id)
        .order_by(AuditSetNCEvidence.uploaded_at)
        .all()
    )
    reviews = (
        db.query(AuditSetNCReview)
        .filter_by(nc_item_id=item.id)
        .order_by(AuditSetNCReview.reviewed_at)
        .all()
    )
    return {
        "id":          item.id,
        "stage_type":  item.stage_type,
        "stage_label": NC_STAGE_LABELS.get(item.stage_type or "", item.stage_type),
        "nc_index":    item.nc_index,
        "category":    item.category,
        "description": item.description,
        "status":      item.status,
        "due_date":    item.due_date.isoformat() if item.due_date else None,
        "created_at":  item.created_at.isoformat() if item.created_at else None,
        "evidence":    [_ev_dict(e) for e in evidence],
        "reviews":     [_review_dict(r) for r in reviews],
    }


def _decision_dict(dec: AuditSetNCDecision, db: Session) -> dict:
    q = db.query(AuditSetNCItem).filter_by(audit_set_id=dec.audit_set_id)
    if dec.stage_type:
        q = q.filter_by(stage_type=dec.stage_type)
    else:
        q = q.filter(AuditSetNCItem.stage_type.is_(None))
    items = q.order_by(AuditSetNCItem.nc_index).all()
    return {
        "id":          dec.id,
        "audit_set_id": dec.audit_set_id,
        "stage_type":  dec.stage_type,
        "stage_label": NC_STAGE_LABELS.get(dec.stage_type or "", dec.stage_type),
        "no_nc":       dec.no_nc,
        "notes":       dec.notes,
        "decided_at":  dec.decided_at.isoformat() if dec.decided_at else None,
        "items":       [_item_dict(i, db) for i in items],
    }


# ── Schemas ───────────────────────────────────────────────────────────────────

class NCItemIn(BaseModel):
    category:    str   # "minor" | "major" | "critical"
    description: str

class NCDecisionIn(BaseModel):
    stage_type: str
    no_nc: bool = False
    notes: Optional[str] = None
    items: list[NCItemIn] = []   # ignored when no_nc=True


class NCReviewIn(BaseModel):
    decision: str    # "approved" | "rejected"
    notes:    Optional[str] = None


# ── Helpers ───────────────────────────────────────────────────────────────────

def _get_audit_set(audit_set_id: str, db: Session) -> AuditSet:
    obj = db.query(AuditSet).filter_by(id=audit_set_id).first()
    if not obj:
        raise HTTPException(404, "Audit set not found")
    return obj


def _require_cb_or_auditor(current_user: PlatformUser) -> None:
    if current_user.role not in CB_ROLES | AUDITOR_ROLES:
        raise HTTPException(403, "Not authorized")


def _normalise_nc_stage(stage_type: str | None) -> str:
    if stage_type not in NC_STAGE_TYPES:
        raise HTTPException(422, "stage_type must be 'stage_1', 'stage_2', 'surveillance', or 'recertification'")
    return stage_type


def _get_stage(audit_set_id: str, stage_type: str, db: Session) -> AuditSetStage:
    stage = db.query(AuditSetStage).filter_by(
        audit_set_id=audit_set_id, stage_type=stage_type,
    ).first()
    if not stage:
        raise HTTPException(404, f"{NC_STAGE_LABELS.get(stage_type, stage_type)} not found")
    return stage


def _is_stage_lead(current_user: PlatformUser, stage: AuditSetStage) -> bool:
    return (
        current_user.role == "auditor"
        and current_user.auditor_id is not None
        and stage.lead_auditor_id == current_user.auditor_id
    )


def _require_stage_lead(current_user: PlatformUser, stage: AuditSetStage) -> None:
    if not _is_stage_lead(current_user, stage):
        raise HTTPException(
            403,
            f"Only the lead auditor assigned to {NC_STAGE_LABELS.get(stage.stage_type, stage.stage_type)} "
            "can manage NCs for that stage.",
        )


def _require_report_uploaded(audit_set_id: str, stage_type: str, db: Session) -> None:
    forms = REPORT_FORMS_BY_STAGE.get(stage_type, set())
    exists = (
        db.query(AuditSetAuditReport)
        .filter_by(audit_set_id=audit_set_id, stage_type=stage_type)
        .filter(AuditSetAuditReport.report_form.in_(forms))
        .first()
    )
    if not exists:
        raise HTTPException(
            409,
            f"{NC_STAGE_LABELS.get(stage_type, stage_type)} NCs can only be submitted after "
            "that stage's audit report has been uploaded.",
        )


# ── POST /audit-sets/{id}/nc-decision ────────────────────────────────────────

@router.post("/audit-sets/{audit_set_id}/nc-decision")
def submit_nc_decision(
    audit_set_id: str,
    payload: NCDecisionIn,
    db: Session = Depends(get_db),
    current_user: PlatformUser = Depends(get_current_user),
):
    _get_audit_set(audit_set_id, db)
    stage_type = _normalise_nc_stage(payload.stage_type)
    stage = _get_stage(audit_set_id, stage_type, db)
    _require_stage_lead(current_user, stage)
    _require_report_uploaded(audit_set_id, stage_type, db)

    if not payload.no_nc and not payload.items:
        raise HTTPException(422, "Must provide at least one NC item when no_nc=False")

    for item in payload.items:
        if item.category not in NC_DUE_DAYS:
            raise HTTPException(422, f"Invalid NC category '{item.category}'. Must be: minor, major, critical")
        if not item.description.strip():
            raise HTTPException(422, "NC description cannot be empty")

    existing = db.query(AuditSetNCDecision).filter_by(
        audit_set_id=audit_set_id, stage_type=stage_type,
    ).first()
    if existing:
        in_progress = (
            db.query(AuditSetNCItem)
            .filter_by(audit_set_id=audit_set_id, stage_type=stage_type)
            .filter(AuditSetNCItem.status.in_(["client_responded", "closed"]))
            .count()
        )
        if in_progress:
            raise HTTPException(
                409,
                f"{in_progress} NC item(s) are already in progress (client has responded or NC is closed). "
                "Cannot replace the NC decision once clients have begun responding."
            )
        db.query(AuditSetNCItem).filter_by(
            audit_set_id=audit_set_id, stage_type=stage_type,
        ).delete()
        existing.no_nc      = payload.no_nc
        existing.notes      = payload.notes
        existing.decided_by = current_user.id
        existing.decided_at = datetime.utcnow()
        decision = existing
    else:
        decision = AuditSetNCDecision(
            audit_set_id=audit_set_id,
            stage_type=stage_type,
            no_nc=payload.no_nc,
            notes=payload.notes,
            decided_by=current_user.id,
        )
        db.add(decision)
        db.flush()

    decided_date = decision.decided_at.date() if hasattr(decision.decided_at, 'date') else date.today()
    if not payload.no_nc:
        for idx, item_in in enumerate(payload.items, start=1):
            due = decided_date + timedelta(days=NC_DUE_DAYS[item_in.category])
            nc_item = AuditSetNCItem(
                audit_set_id=audit_set_id,
                stage_type=stage_type,
                nc_index=idx,
                category=item_in.category,
                description=item_in.description.strip(),
                status="open",
                due_date=due,
            )
            db.add(nc_item)

    db.commit()
    db.refresh(decision)
    return _decision_dict(decision, db)


# ── GET /audit-sets/{id}/nc-decision ─────────────────────────────────────────

@router.get("/audit-sets/{audit_set_id}/nc-decision")
def get_nc_decision(
    audit_set_id: str,
    stage_type: Optional[str] = Query(None),
    db: Session = Depends(get_db),
    current_user: PlatformUser = Depends(get_current_user),
):
    _require_cb_or_auditor(current_user)
    _get_audit_set(audit_set_id, db)
    if stage_type is None:
        raise HTTPException(422, "stage_type is required for audit-flow NC access")
    stage_type = _normalise_nc_stage(stage_type)
    stage = _get_stage(audit_set_id, stage_type, db)
    _require_stage_lead(current_user, stage)
    decision = db.query(AuditSetNCDecision).filter_by(
        audit_set_id=audit_set_id, stage_type=stage_type,
    ).first()
    if not decision:
        return None
    return _decision_dict(decision, db)


# ── POST evidence upload (client) ─────────────────────────────────────────────

@router.post("/audit-sets/{audit_set_id}/nc-items/{nc_id}/evidence")
async def upload_nc_evidence(
    audit_set_id: str,
    nc_id: str,
    upload_type: str = Form(...),
    files: list[UploadFile] = File(...),
    db: Session = Depends(get_db),
    current_user: PlatformUser = Depends(get_current_user),
):
    if current_user.role != "client":
        raise HTTPException(403, "Client access only")
    if not current_user.audit_set_id or current_user.audit_set_id != audit_set_id:
        raise HTTPException(403, "Not authorized for this audit set")

    if upload_type not in ("root_cause", "corrective_action"):
        raise HTTPException(422, "upload_type must be 'root_cause' or 'corrective_action'")

    item = db.query(AuditSetNCItem).filter_by(id=nc_id, audit_set_id=audit_set_id).first()
    if not item:
        raise HTTPException(404, "NC item not found")
    if item.status == "closed":
        raise HTTPException(409, "This NC has already been closed. No further evidence is needed.")

    last_review = (
        db.query(AuditSetNCReview)
        .filter_by(nc_item_id=nc_id)
        .order_by(AuditSetNCReview.reviewed_at.desc())
        .first()
    )
    round_num = (last_review.round_number + 1) if last_review else 1

    saved = []
    for file in files:
        safe_name = f"{secrets.token_hex(6)}_{file.filename or 'evidence'}"
        relative_path = f"nc_evidence/{audit_set_id}/{nc_id}/{safe_name}"
        content = await file.read()
        file_path = store_upload(relative_path, content)

        ev = AuditSetNCEvidence(
            nc_item_id=nc_id,
            file_path=file_path,
            file_name=file.filename or safe_name,
            upload_type=upload_type,
            uploaded_by=current_user.id,
            round_number=round_num,
        )
        db.add(ev)
        saved.append(ev)

    item.status = "client_responded"
    db.commit()

    return {"uploaded": len(saved), "round_number": round_num, "status": item.status}


# ── POST review (auditor/admin) ───────────────────────────────────────────────

@router.post("/audit-sets/{audit_set_id}/nc-items/{nc_id}/review")
def review_nc_item(
    audit_set_id: str,
    nc_id: str,
    payload: NCReviewIn,
    db: Session = Depends(get_db),
    current_user: PlatformUser = Depends(get_current_user),
):
    if current_user.role not in CB_ROLES | AUDITOR_ROLES:
        raise HTTPException(403, "Not authorized")

    if payload.decision not in ("approved", "rejected"):
        raise HTTPException(422, "decision must be 'approved' or 'rejected'")

    item = db.query(AuditSetNCItem).filter_by(id=nc_id, audit_set_id=audit_set_id).first()
    if not item:
        raise HTTPException(404, "NC item not found")
    if item.stage_type:
        stage = _get_stage(audit_set_id, item.stage_type, db)
        _require_stage_lead(current_user, stage)
    if item.status == "closed":
        raise HTTPException(409, "NC item is already closed")
    if item.status not in ("client_responded",):
        raise HTTPException(
            409,
            f"Cannot review an NC in status '{item.status}'. "
            "The client must upload evidence first."
        )

    last_round = (
        db.query(AuditSetNCEvidence)
        .filter_by(nc_item_id=nc_id)
        .order_by(AuditSetNCEvidence.round_number.desc())
        .first()
    )
    round_num = last_round.round_number if last_round else 1

    review = AuditSetNCReview(
        nc_item_id=nc_id,
        decision=payload.decision,
        notes=payload.notes,
        reviewed_by=current_user.id,
        round_number=round_num,
    )
    db.add(review)

    item.status = "closed" if payload.decision == "approved" else "rejected"
    db.commit()

    return {"nc_id": nc_id, "status": item.status, "decision": payload.decision}


# ── GET client NCs ────────────────────────────────────────────────────────────

@router.get("/client/my-audit-set/ncs")
def client_get_ncs(
    db: Session = Depends(get_db),
    current_user: PlatformUser = Depends(get_current_user),
):
    if current_user.role != "client" or not current_user.audit_set_id:
        raise HTTPException(403, "Client access only")
    decisions = db.query(AuditSetNCDecision).filter_by(
        audit_set_id=current_user.audit_set_id
    ).order_by(AuditSetNCDecision.stage_type, AuditSetNCDecision.decided_at).all()
    return [_decision_dict(decision, db) for decision in decisions]


# ── Download evidence ─────────────────────────────────────────────────────────

@router.get("/client/my-audit-set/ncs/{nc_id}/evidence/{ev_id}/download")
def client_download_evidence(
    nc_id: str,
    ev_id: str,
    db: Session = Depends(get_db),
    current_user: PlatformUser = Depends(get_current_user),
):
    if current_user.role != "client" or not current_user.audit_set_id:
        raise HTTPException(403, "Client access only")

    item = db.query(AuditSetNCItem).filter_by(
        id=nc_id, audit_set_id=current_user.audit_set_id
    ).first()
    if not item:
        raise HTTPException(404, "NC item not found")

    ev = db.query(AuditSetNCEvidence).filter_by(id=ev_id, nc_item_id=nc_id).first()
    if not ev:
        raise HTTPException(404, "Evidence file not found")
    if not ev.file_path:
        raise HTTPException(404, "File not on server")
    try:
        local_path = ensure_local(ev.file_path)
    except FileNotFoundError:
        raise HTTPException(404, "File not on server")
    return FileResponse(local_path, filename=ev.file_name or "evidence", media_type="application/octet-stream")


@router.get("/audit-sets/{audit_set_id}/nc-items/{nc_id}/evidence/{ev_id}/download")
def cb_download_evidence(
    audit_set_id: str,
    nc_id: str,
    ev_id: str,
    db: Session = Depends(get_db),
    current_user: PlatformUser = Depends(get_current_user),
):
    if current_user.role not in CB_ROLES | AUDITOR_ROLES:
        raise HTTPException(403, "Not authorized")

    item = db.query(AuditSetNCItem).filter_by(id=nc_id, audit_set_id=audit_set_id).first()
    if not item:
        raise HTTPException(404, "NC item not found")

    ev = db.query(AuditSetNCEvidence).filter_by(id=ev_id, nc_item_id=nc_id).first()
    if not ev:
        raise HTTPException(404, "Evidence file not found")
    if not ev.file_path:
        raise HTTPException(404, "File not on server")
    try:
        local_path = ensure_local(ev.file_path)
    except FileNotFoundError:
        raise HTTPException(404, "File not on server")
    return FileResponse(local_path, filename=ev.file_name or "evidence", media_type="application/octet-stream")


# ── GET /nc-management/summary (planner/admin cross-company view) ─────────────

@router.get("/nc-management/summary")
def nc_management_summary(
    db: Session = Depends(get_db),
    current_user: PlatformUser = Depends(get_current_user),
):
    if current_user.role not in CB_ROLES:
        raise HTTPException(403, "Not authorized")

    decisions = db.query(AuditSetNCDecision).order_by(AuditSetNCDecision.decided_at.desc()).all()

    rows = []
    today = date.today()
    for dec in decisions:
        audit_set = db.query(AuditSet).filter_by(id=dec.audit_set_id).first()
        if not audit_set:
            continue

        if dec.no_nc:
            rows.append({
                "audit_set_id": dec.audit_set_id,
                "stage_type":   dec.stage_type,
                "stage_label":  NC_STAGE_LABELS.get(dec.stage_type or "", dec.stage_type),
                "company_name": audit_set.company_name,
                "plan_number":  audit_set.plan_number,
                "no_nc":        True,
                "decided_at":   dec.decided_at.isoformat() if dec.decided_at else None,
                "open_count":   0,
                "closed_count": 0,
                "total_count":  0,
                "has_overdue":  False,
                "workflow_status": audit_set.workflow_status,
            })
            continue

        q = db.query(AuditSetNCItem).filter_by(audit_set_id=dec.audit_set_id)
        if dec.stage_type:
            q = q.filter_by(stage_type=dec.stage_type)
        else:
            q = q.filter(AuditSetNCItem.stage_type.is_(None))
        items = q.all()
        open_count   = sum(1 for i in items if i.status != "closed")
        closed_count = sum(1 for i in items if i.status == "closed")
        has_overdue  = any(
            i.due_date and i.due_date < today and i.status != "closed"
            for i in items
        )

        rows.append({
            "audit_set_id":    dec.audit_set_id,
            "stage_type":      dec.stage_type,
            "stage_label":     NC_STAGE_LABELS.get(dec.stage_type or "", dec.stage_type),
            "company_name":    audit_set.company_name,
            "plan_number":     audit_set.plan_number,
            "no_nc":           False,
            "decided_at":      dec.decided_at.isoformat() if dec.decided_at else None,
            "open_count":      open_count,
            "closed_count":    closed_count,
            "total_count":     len(items),
            "has_overdue":     has_overdue,
            "workflow_status": audit_set.workflow_status,
        })

    return rows
