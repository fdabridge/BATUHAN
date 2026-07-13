"""
BATUHAN — Document CB signing (Prompt 12).

CB staff sign documents via OTP before they are released to the client portal.
Prompt 12 covers: cb_planner signs quotation + agreement.
Future prompts extend this to cb_cert_manager, lead_auditor, committee, guests.
"""
from __future__ import annotations
from datetime import datetime, date
from typing import Optional

from fastapi import APIRouter, Body, Depends, HTTPException, Request
from pydantic import BaseModel
from sqlalchemy.orm import Session

from audit_set.db_models import (
    AuditDocumentSignature, AuditSet, AuditSetSharedDocument,
    AuditSetAuditReport, AuditSetNCForm, AuditSetStage, AuditSetStatusEvent,
    VisualSignaturePlacement, get_db,
)
from audit_set.committee_slots import (
    committee_member_auditor_id,
    committee_member_name,
    expected_committee_sig_keys,
    planned_committee_chair,
    planned_committee_slots,
)
from storage.document_store import resolve_docx_key
from auth.db_models import PlatformUser
from auth.dependencies import get_current_user

router = APIRouter(prefix="/audit-sets", tags=["signatures"])

CB_ROLES = {"admin", "planner", "planner_us", "officer", "executive", "gm", "certification_manager"}
FR233_CERT_MANAGER_KEYS = {"CB_CERT_MANAGER", "CERT_MANAGER_FR233", "CERT_MANAGER_REVIEW"}


def _stage_lead_for(
    db: Session,
    audit_set_id: str,
    stage_type: str | None,
) -> str | None:
    q = db.query(AuditSetStage).filter_by(audit_set_id=audit_set_id)
    if stage_type:
        stage = q.filter_by(stage_type=stage_type).order_by(AuditSetStage.stage_order).first()
        if stage:
            return stage.lead_auditor_id
    stage = q.order_by(AuditSetStage.stage_order).first()
    return stage.lead_auditor_id if stage else None


def _report_sig_document_type(report: AuditSetAuditReport) -> str:
    return "stage1_report" if report.stage_type == "stage_1" else "stage2_report"


def _add_unique(result: list[dict], seen: set[str], item: dict) -> None:
    key = item["id"]
    if key not in seen:
        seen.add(key)
        result.append(item)


def _virtual_sig(
    *,
    key: str,
    audit_set: AuditSet | None,
    document_id: str,
    document_type: str,
    document_label: str,
    signer_role_label: str,
    signer_name: str | None = None,
) -> dict:
    return {
        "id": key,
        "audit_set_id": audit_set.id if audit_set else "",
        "document_id": document_id,
        "document_type": document_type,
        "document_label": document_label,
        "signer_role_label": signer_role_label,
        "signer_name": signer_name,
        "company_name": audit_set.company_name if audit_set else "",
        "plan_number": audit_set.plan_number if audit_set else None,
        "required": True,
        "order_index": 0,
        "signed_at": None,
        "is_signed": False,
        "created_at": None,
    }


def _fr233_document_keys(doc: AuditSetSharedDocument, db: Session) -> set[str]:
    if not doc.file_path:
        return set()
    try:
        docx_key = resolve_docx_key(doc.file_path)
    except Exception:
        docx_key = doc.file_path
    try:
        from audit_set.db_models import DocumentSignatureField
        return {
            key for (key,) in
            db.query(DocumentSignatureField.sig_key)
            .filter_by(docx_path=docx_key)
            .all()
        }
    except Exception:
        return set()


def _vsp_signed(db: Session, document_type: str, doc_id: str, sig_key: str) -> bool:
    return (
        db.query(VisualSignaturePlacement.id)
        .filter_by(document_type=document_type, doc_id=doc_id, sig_key=sig_key)
        .filter(VisualSignaturePlacement.signed_at.isnot(None))
        .first()
        is not None
    )


def _append_report_and_nc_tasks(
    result: list[dict],
    seen: set[str],
    db: Session,
    current_user: PlatformUser,
) -> None:
    reports = db.query(AuditSetAuditReport).all()
    audit_sets = {
        a.id: a for a in db.query(AuditSet).filter(
            AuditSet.id.in_({r.audit_set_id for r in reports} or {""})
        ).all()
    } if reports else {}

    for report in reports:
        audit_set = audit_sets.get(report.audit_set_id)
        doc_type = _report_sig_document_type(report)
        if (
            current_user.role == "auditor"
            and current_user.auditor_id
            and not report.la_signed_at
            and _stage_lead_for(db, report.audit_set_id, report.stage_type) == current_user.auditor_id
        ):
            _add_unique(result, seen, _virtual_sig(
                key=f"virtual:audit-report-la:{report.id}",
                audit_set=audit_set,
                document_id=report.id,
                document_type=doc_type,
                document_label=report.label or report.report_form or "Audit Report",
                signer_role_label="lead_auditor",
            ))

        if (
            current_user.role == "auditor"
            and current_user.auditor_id
            and report.la_signed_at
            and not report.appointed_reviewer_signed_at
        ):
            chair = planned_committee_chair(audit_set) if audit_set else None
            if committee_member_auditor_id(chair) == current_user.auditor_id:
                _add_unique(result, seen, _virtual_sig(
                    key=f"virtual:audit-report-chair:{report.id}",
                    audit_set=audit_set,
                    document_id=report.id,
                    document_type=doc_type,
                    document_label=report.label or report.report_form or "Audit Report",
                    signer_role_label="appointed_reviewer",
                    signer_name=committee_member_name(chair),
                ))

        if (
            current_user.role in ("certification_manager", "admin")
            and report.la_signed_at
            and not report.reviewer_signed_at
        ):
            _add_unique(result, seen, _virtual_sig(
                key=f"virtual:audit-report-cm:{report.id}",
                audit_set=audit_set,
                document_id=report.id,
                document_type=doc_type,
                document_label=report.label or report.report_form or "Audit Report",
                signer_role_label="cb_cert_manager",
                signer_name=current_user.full_name,
            ))

    nc_forms = db.query(AuditSetNCForm).all()
    nc_audit_sets = {
        a.id: a for a in db.query(AuditSet).filter(
            AuditSet.id.in_({n.audit_set_id for n in nc_forms} or {""})
        ).all()
    } if nc_forms else {}
    for nc in nc_forms:
        audit_set = nc_audit_sets.get(nc.audit_set_id)
        if (
            current_user.role == "auditor"
            and current_user.auditor_id
            and not nc.la_signed_at
            and _stage_lead_for(db, nc.audit_set_id, nc.stage_type) == current_user.auditor_id
        ):
            _add_unique(result, seen, _virtual_sig(
                key=f"virtual:nc-la:{nc.id}",
                audit_set=audit_set,
                document_id=nc.id,
                document_type="nc_form",
                document_label=f"NC Form: {nc.label}",
                signer_role_label="lead_auditor",
            ))
        if (
            current_user.role == "client"
            and current_user.audit_set_id == nc.audit_set_id
            and nc.status == "pending_client"
            and nc.la_signed_at
            and not nc.client_signed_at
        ):
            _add_unique(result, seen, _virtual_sig(
                key=f"virtual:nc-client:{nc.id}",
                audit_set=audit_set,
                document_id=nc.id,
                document_type="nc_form",
                document_label=f"NC Form: {nc.label}",
                signer_role_label="client",
            ))


def _append_fr233_field_tasks(
    result: list[dict],
    seen: set[str],
    db: Session,
    current_user: PlatformUser,
) -> None:
    docs = db.query(AuditSetSharedDocument).filter_by(document_type="fr233").all()
    if not docs:
        return
    audit_sets = {
        a.id: a for a in db.query(AuditSet).filter(
            AuditSet.id.in_({d.audit_set_id for d in docs})
        ).all()
    }
    for doc in docs:
        audit_set = audit_sets.get(doc.audit_set_id)
        if not audit_set:
            continue
        document_keys = _fr233_document_keys(doc, db)
        expected_keys = expected_committee_sig_keys(audit_set, document_keys)

        if current_user.role == "auditor" and current_user.auditor_id:
            candidate_keys = {
                f"COMMITTEE_MEMBER_{current_user.auditor_id}",
                *[
                    key for key, member in planned_committee_slots(audit_set).items()
                    if committee_member_auditor_id(member) == current_user.auditor_id
                ],
            }
            for sig_key in sorted(candidate_keys & expected_keys):
                if not _vsp_signed(db, "shared_doc", doc.id, sig_key):
                    _add_unique(result, seen, _virtual_sig(
                        key=f"virtual:fr233:{doc.id}:{sig_key}",
                        audit_set=audit_set,
                        document_id=doc.id,
                        document_type="fr233",
                        document_label=doc.label or "FR.233 Review & Decision",
                        signer_role_label="committee_member",
                    ))

        if current_user.role in ("certification_manager", "admin", "executive"):
            cm_keys = FR233_CERT_MANAGER_KEYS & (document_keys or FR233_CERT_MANAGER_KEYS)
            if not cm_keys:
                cm_keys = {"CB_CERT_MANAGER"}
            committee_done = bool(expected_keys) and all(
                _vsp_signed(db, "shared_doc", doc.id, key) for key in expected_keys
            )
            for sig_key in sorted(cm_keys):
                if committee_done and not _vsp_signed(db, "shared_doc", doc.id, sig_key):
                    _add_unique(result, seen, _virtual_sig(
                        key=f"virtual:fr233:{doc.id}:{sig_key}",
                        audit_set=audit_set,
                        document_id=doc.id,
                        document_type="fr233",
                        document_label=doc.label or "FR.233 Review & Decision",
                        signer_role_label="cb_cert_manager",
                        signer_name=current_user.full_name,
                    ))


class SignDirectBody(BaseModel):
    signed_date: Optional[date] = None  # user-selected signing date; defaults to today


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
    """Unsigned signature slots assigned to (or claimable by) the current user.

    Serves both CB staff (role in CB_ROLES) and auditors (role == 'auditor').

    Auditor coverage — three slot types, all matched via auditor_id:
      1. cb_reviewer   → AuditSet.fr218_reviewer_id == current_user.auditor_id
      2. lead_auditor  → AuditSetStage.lead_auditor_id == current_user.auditor_id
                         (stage matched by document stage_type)
      3. assigned_auditor → AuditSetSharedDocument.assigned_auditor_id == current_user.auditor_id

    Also returns any slot with signer_user_id == current_user.id (direct assignment,
    covering future cases where slots are pre-assigned at appointment time).
    """

    seen_result_ids: set[str] = set()
    supplemental_results: list[dict] = []
    _append_report_and_nc_tasks(supplemental_results, seen_result_ids, db, current_user)
    _append_fr233_field_tasks(supplemental_results, seen_result_ids, db, current_user)

    # ── Auditor path ────────────────────────────────────────────────────────────
    if current_user.role == "auditor":
        if not current_user.auditor_id:
            return supplemental_results

        auditor_id = current_user.auditor_id
        seen_ids: set[str] = set()
        all_slots: list[AuditDocumentSignature] = []

        def _add(slot: AuditDocumentSignature) -> None:
            if slot.id not in seen_ids:
                seen_ids.add(slot.id)
                all_slots.append(slot)

        # ── 0. Directly assigned (signer_user_id already set) ──────────────────
        for s in (
            db.query(AuditDocumentSignature)
            .filter_by(signer_user_id=current_user.id)
            .filter(AuditDocumentSignature.signed_at.is_(None))
            .all()
        ):
            _add(s)

        # ── 1. cb_reviewer — FR.218 Application Review ─────────────────────────
        # Find all audit sets where this auditor is the appointed FR.218 reviewer.
        fr218_set_ids = {
            row.id
            for row in db.query(AuditSet.id)
            .filter_by(fr218_reviewer_id=auditor_id)
            .all()
        }
        if fr218_set_ids:
            for s in (
                db.query(AuditDocumentSignature)
                .filter(
                    AuditDocumentSignature.signer_role_label == "cb_reviewer",
                    AuditDocumentSignature.signed_at.is_(None),
                    AuditDocumentSignature.audit_set_id.in_(fr218_set_ids),
                )
                .all()
            ):
                _add(s)

        # ── 2. lead_auditor — stage reports and NC forms ────────────────────────
        # Find all (audit_set_id, stage_type) pairs where this auditor is lead.
        lead_pairs: set[tuple[str, str]] = {
            (row.audit_set_id, row.stage_type)
            for row in db.query(
                AuditSetStage.audit_set_id, AuditSetStage.stage_type
            )
            .filter_by(lead_auditor_id=auditor_id)
            .all()
        }
        if lead_pairs:
            # Collect audit_set_ids so we can pre-filter slots efficiently.
            lead_audit_set_ids = {p[0] for p in lead_pairs}
            candidate_slots = (
                db.query(AuditDocumentSignature)
                .filter(
                    AuditDocumentSignature.signer_role_label == "lead_auditor",
                    AuditDocumentSignature.signed_at.is_(None),
                    AuditDocumentSignature.audit_set_id.in_(lead_audit_set_ids),
                )
                .all()
            )
            for s in candidate_slots:
                # Derive stage_type: prefer AuditSetSharedDocument.stage_type;
                # fall back to inferring from document_type string.
                stage_type: str | None = None
                if s.document_id:
                    doc = db.query(AuditSetSharedDocument).filter_by(id=s.document_id).first()
                    if doc:
                        stage_type = doc.stage_type
                if not stage_type:
                    dt = s.document_type or ""
                    if "stage1" in dt:
                        stage_type = "stage_1"
                    elif "stage2" in dt:
                        stage_type = "stage_2"

                if stage_type:
                    if (s.audit_set_id, stage_type) in lead_pairs:
                        _add(s)
                else:
                    # nc_form without stage_type info — include if auditor leads
                    # any stage in this audit set (conservative: better to show than hide)
                    if any(p[0] == s.audit_set_id for p in lead_pairs):
                        _add(s)

        # ── 3. assigned_auditor — FR.224 team info ─────────────────────────────
        # Find all shared documents where this auditor is the assigned auditor.
        assigned_doc_ids = {
            row.id
            for row in db.query(AuditSetSharedDocument.id)
            .filter_by(assigned_auditor_id=auditor_id)
            .all()
        }
        if assigned_doc_ids:
            for s in (
                db.query(AuditDocumentSignature)
                .filter(
                    AuditDocumentSignature.signer_role_label == "assigned_auditor",
                    AuditDocumentSignature.signed_at.is_(None),
                    AuditDocumentSignature.document_id.in_(assigned_doc_ids),
                )
                .all()
            ):
                _add(s)

        # ── Serialize and return ────────────────────────────────────────────────
        results = []
        for s in all_slots:
            audit_set = db.query(AuditSet).filter_by(id=s.audit_set_id).first()
            doc_label = (s.document_type or "").replace("_", " ").title()
            if s.document_id:
                doc = db.query(AuditSetSharedDocument).filter_by(id=s.document_id).first()
                if doc and doc.label:
                    doc_label = doc.label
            results.append(_sig_to_dict(
                s,
                doc_label=doc_label,
                company_name=audit_set.company_name if audit_set else "",
                plan_number=audit_set.plan_number if audit_set else None,
            ))
        result_seen = {r["id"] for r in results}
        for item in supplemental_results:
            _add_unique(results, result_seen, item)
        return results

    # ── CB staff path (unchanged) ───────────────────────────────────────────────
    if current_user.role == "client":
        return supplemental_results

    if current_user.role not in CB_ROLES:
        raise HTTPException(403, "Not authorized")

    # Slots explicitly assigned to me
    assigned = (
        db.query(AuditDocumentSignature)
        .filter_by(signer_user_id=current_user.id)
        .filter(AuditDocumentSignature.signed_at.is_(None))
        .all()
    )

    # Unassigned slots this user is eligible to claim.
    # NOTE: cb_reviewer removed in Prompt 14 — assigned only via committee appointment.
    eligible_labels: list[str] = []
    if current_user.role in ("admin", "planner", "planner_us"):
        eligible_labels.append("cb_planner")
    if current_user.role in ("admin", "executive", "certification_manager"):
        eligible_labels.append("cb_cert_manager")
    if current_user.role == "gm":
        eligible_labels.append("gm")

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
    result_seen = {r["id"] for r in results}
    for item in supplemental_results:
        _add_unique(results, result_seen, item)
    return results


@router.post("/{audit_set_id}/signatures/{sig_id}/sign-direct")
def sign_direct(
    audit_set_id: str,
    sig_id:       str,
    request:      Request,
    body:         SignDirectBody = Body(default_factory=SignDirectBody),
    db:           Session      = Depends(get_db),
    current_user: PlatformUser = Depends(get_current_user),
):
    """Direct sign for FR218/FR222 internal slots — no OTP required."""
    if current_user.role not in CB_ROLES:
        raise HTTPException(403, "Not authorized")

    sig = db.query(AuditDocumentSignature).filter_by(
        id=sig_id, audit_set_id=audit_set_id
    ).first()
    if not sig:
        raise HTTPException(404, "Signature slot not found")

    # Self-assign if the slot is unassigned and the caller is eligible.
    if sig.signer_user_id is None:
        eligible = (
            (sig.signer_role_label == "cb_planner"      and current_user.role in ("admin", "planner", "planner_us"))
            or (sig.signer_role_label == "cb_cert_manager" and current_user.role in ("admin", "executive", "certification_manager"))
            or (sig.signer_role_label == "gm"              and current_user.role == "gm")
            or (sig.signer_role_label == "cb_reviewer"     and current_user.role in ("admin", "certification_manager"))
        )
        if not eligible:
            raise HTTPException(403, "You are not eligible to sign this slot")
        sig.signer_user_id = current_user.id
        sig.signer_name    = current_user.full_name
        sig.signer_email   = current_user.email
    elif sig.signer_user_id != current_user.id:
        raise HTTPException(403, "This signature slot is not assigned to you")

    if sig.signed_at:
        raise HTTPException(400, "Already signed")

    sig.signed_at      = (
        datetime.combine(body.signed_date, datetime.min.time())
        if body.signed_date else datetime.utcnow()
    )
    sig.signed_ip      = request.client.host if request.client else None
    sig.otp_hash       = None
    sig.otp_expires_at = None

    # Flush before count so the updated signed_at is visible.
    db.flush()

    # If this slot has a linked shared document, check whether all required
    # signatures are now collected and release the document if so.
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
                            notes="Quotation signed by CB planner and released (direct sign)",
                        ))

    db.commit()

    # Portal 47 — if this was an FR.218 slot, check whether the document is
    # now fully signed and auto-advance fr218_in_progress → fr218_complete.
    if sig.document_type == "FR218":
        from audit_set.pipeline_triggers import check_fr218_completion
        check_fr218_completion(
            audit_set_id=audit_set_id,
            triggered_by=current_user.id,
            db=db,
        )

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

    # NOTE: cb_reviewer removed in Prompt 14 — assigned only via committee appointment.
    eligible_labels: set[str] = set()
    if current_user.role in ("admin", "planner", "planner_us"):
        eligible_labels.add("cb_planner")
    if current_user.role in ("admin", "executive", "certification_manager"):
        eligible_labels.add("cb_cert_manager")
    if current_user.role == "gm":
        eligible_labels.add("gm")

    return [
        {
            "id":                  s.id,
            "document_type":       s.document_type,
            "document_id":         s.document_id,
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
    if current_user.role not in {"admin", "planner", "planner_us"}:
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
