"""
CRM Router — Portal 91

Read-only endpoints for non-technical staff (finance / operations).
Data is derived from the existing audit_set tables with no writes.

Accessible to roles: crm, admin
All endpoints return empty/zero responses on DB error — never 500.
"""
from __future__ import annotations

import logging
from datetime import date, timedelta
from typing import Optional

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy.orm import Session

from audit_set.db_models import AuditSet, AuditSetStage, get_db
from auth.db_models import PlatformUser, get_db as get_auth_db
from auth.dependencies import get_current_user
from auditors.models import Auditor, get_db as get_auditors_db

logger = logging.getLogger(__name__)
router = APIRouter(tags=["crm"])

CRM_ROLES = {"crm", "admin"}

# ── Simplified pipeline status map ───────────────────────────────────────────

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
    "audit_scheduled":       "Surveillance Audit",
    "audit_in_progress":     "Surveillance Audit",
    "surveillance_complete": "Surveillance Complete",
    "cert_complete":         "Certified",
    "certified":             "Certified",
}

PIPELINE_ORDER = [
    "Application Received", "In Planning", "Quotation Sent", "Agreement Signed",
    "Under Review", "Stage 1 Audit", "Stage 1 Complete", "Stage 2 Audit",
    "Committee Review", "Surveillance Audit", "Surveillance Complete", "Certified",
]

# ── Cycle date computation ────────────────────────────────────────────────────

def _add_years(d: date, years: int) -> date:
    try:
        return d.replace(year=d.year + years)
    except ValueError:
        return d.replace(year=d.year + years, day=28)


def _cycle_dates(issued: date) -> tuple[date, date, date]:
    surv1  = _add_years(issued, 1) - timedelta(days=1)
    surv2  = _add_years(issued, 2) - timedelta(days=1)
    recert = _add_years(issued, 3)
    return surv1, surv2, recert


# ── Contact lookup ────────────────────────────────────────────────────────────

def _get_contact(audit_set_id: str, audit_set: AuditSet, auth_db: Session) -> dict:
    try:
        client_user = (
            auth_db.query(PlatformUser)
            .filter_by(audit_set_id=audit_set_id, role="client")
            .first()
        )
        if client_user:
            return {
                "contact_name":  client_user.full_name,
                "contact_email": client_user.email,
                "contact_phone": audit_set.phone or "",
            }
    except Exception:
        pass
    return {
        "contact_name":  audit_set.representative or "",
        "contact_email": audit_set.email or "",
        "contact_phone": audit_set.phone or "",
    }


# ── Serialise one AuditSet row ────────────────────────────────────────────────

def _serialise(audit_set: AuditSet, auth_db: Session) -> dict:
    issued: Optional[date] = audit_set.cert_issued_date
    surv1_due = surv2_due = recert_due = None
    if issued:
        surv1_due, surv2_due, recert_due = _cycle_dates(issued)
    contact = _get_contact(audit_set.id, audit_set, auth_db)
    return {
        "id":                audit_set.id,
        "company_name":      audit_set.company_name or "",
        "city":              audit_set.city or "",
        "standards":         audit_set.standards or [],
        "audit_type":        audit_set.audit_type or "initial",
        "accreditation_body": audit_set.accreditation_body or "",
        "simple_status":     SIMPLE_STATUS.get(audit_set.workflow_status, "In Progress"),
        "workflow_status":   audit_set.workflow_status,
        "cert_issued_date":  issued.isoformat() if issued else None,
        "cert_expiry_date":  audit_set.cert_expiry_date.isoformat() if audit_set.cert_expiry_date else None,
        "surv1_due":         surv1_due.isoformat()  if surv1_due  else None,
        "surv2_due":         surv2_due.isoformat()  if surv2_due  else None,
        "recert_due":        recert_due.isoformat() if recert_due else None,
        "certification_fee": audit_set.certification_fee,
        "surveillance_fee":  audit_set.surveillance_fee,
        "currency":          audit_set.currency or "USD",
        **contact,
    }


# ── Pydantic response schemas ─────────────────────────────────────────────────

class CRMClientRow(BaseModel):
    id: str
    company_name: str
    city: str
    standards: list
    audit_type: str
    accreditation_body: str
    simple_status: str
    workflow_status: Optional[str]
    cert_issued_date: Optional[str]
    cert_expiry_date: Optional[str]
    surv1_due: Optional[str]
    surv2_due: Optional[str]
    recert_due: Optional[str]
    certification_fee: Optional[float]
    surveillance_fee: Optional[float]
    currency: str
    contact_name: str
    contact_email: str
    contact_phone: str

    class Config:
        from_attributes = True


class KPIs(BaseModel):
    active_certifications: int
    expiring_90_days: int
    overdue_renewals: int
    in_progress: int


class CRMDashboardResponse(BaseModel):
    kpis: KPIs
    upcoming_renewals: list[dict]
    pipeline: dict[str, int]


# ── Endpoints ─────────────────────────────────────────────────────────────────

@router.get("/crm/dashboard", response_model=CRMDashboardResponse)
def crm_dashboard(
    db:      Session = Depends(get_db),
    auth_db: Session = Depends(get_auth_db),
    current_user: PlatformUser = Depends(get_current_user),
):
    if current_user.role not in CRM_ROLES:
        from fastapi import HTTPException
        raise HTTPException(403, "Not authorized")

    today = date.today()
    in_90 = today + timedelta(days=90)

    try:
        all_sets = db.query(AuditSet).all()
    except Exception as exc:
        logger.error("[CRM] dashboard DB error: %s", exc)
        all_sets = []

    active_certs = expiring_90 = overdue_renewals = in_progress_cnt = 0
    pipeline: dict[str, int] = {s: 0 for s in PIPELINE_ORDER}
    upcoming: list[dict] = []

    for a in all_sets:
        label = SIMPLE_STATUS.get(a.workflow_status, "In Progress")
        if label in pipeline:
            pipeline[label] += 1
        if label not in ("Certified", "Application Received"):
            in_progress_cnt += 1
        if not a.cert_issued_date:
            continue

        active_certs += 1
        issued = a.cert_issued_date
        surv1, surv2, recert = _cycle_dates(issued)
        contact = _get_contact(a.id, a, auth_db)

        if a.cert_expiry_date and today <= a.cert_expiry_date <= in_90:
            expiring_90 += 1

        for milestone, due in [("surv1", surv1), ("surv2", surv2), ("recert", recert)]:
            days_until = (due - today).days
            if days_until < -30:
                overdue_renewals += 1
                continue
            if days_until > 548:
                continue
            upcoming.append({
                "audit_set_id":     a.id,
                "company_name":     a.company_name or "",
                "standards":        a.standards or [],
                "milestone":        milestone,
                "due_date":         due.isoformat(),
                "days_until":       days_until,
                "cert_issued_date": issued.isoformat(),
                **contact,
            })

    upcoming.sort(key=lambda r: r["due_date"])

    return CRMDashboardResponse(
        kpis=KPIs(
            active_certifications=active_certs,
            expiring_90_days=expiring_90,
            overdue_renewals=overdue_renewals,
            in_progress=in_progress_cnt,
        ),
        upcoming_renewals=upcoming,
        pipeline={k: v for k, v in pipeline.items() if v > 0},
    )


@router.get("/crm/clients", response_model=list[CRMClientRow])
def crm_clients(
    db:      Session = Depends(get_db),
    auth_db: Session = Depends(get_auth_db),
    current_user: PlatformUser = Depends(get_current_user),
):
    if current_user.role not in CRM_ROLES:
        from fastapi import HTTPException
        raise HTTPException(403, "Not authorized")

    try:
        all_sets = db.query(AuditSet).order_by(AuditSet.company_name).all()
    except Exception as exc:
        logger.error("[CRM] clients DB error: %s", exc)
        return []

    result = []
    for a in all_sets:
        try:
            result.append(CRMClientRow(**_serialise(a, auth_db)))
        except Exception as exc:
            logger.warning("[CRM] skip audit_set %s: %s", a.id, exc)
    return result


@router.get("/crm/clients/{audit_set_id}", response_model=CRMClientRow)
def crm_client_detail(
    audit_set_id: str,
    db:      Session = Depends(get_db),
    auth_db: Session = Depends(get_auth_db),
    current_user: PlatformUser = Depends(get_current_user),
):
    if current_user.role not in CRM_ROLES:
        from fastapi import HTTPException
        raise HTTPException(403, "Not authorized")

    try:
        a = db.query(AuditSet).filter_by(id=audit_set_id).first()
    except Exception as exc:
        logger.error("[CRM] client detail DB error: %s", exc)
        from fastapi import HTTPException
        raise HTTPException(500, "Database error")

    if not a:
        from fastapi import HTTPException
        raise HTTPException(404, "Audit set not found")

    return CRMClientRow(**_serialise(a, auth_db))


# ── Portal 92 — Auditor Calendar ──────────────────────────────────────────────

class CRMAuditorRow(BaseModel):
    id:    str
    name:  str
    email: Optional[str]
    role:  Optional[str]


class CRMCalendarEntry(BaseModel):
    audit_set_id:  str
    plan_number:   int
    company_name:  str
    stage_type:    str
    date_start:    str
    date_end:      str
    auditor_role:  str


@router.get("/crm/auditors", response_model=list[CRMAuditorRow])
def crm_auditors(
    auditors_db: Session = Depends(get_auditors_db),
    current_user: PlatformUser = Depends(get_current_user),
):
    if current_user.role not in CRM_ROLES:
        from fastapi import HTTPException
        raise HTTPException(403, "Not authorized")
    try:
        rows = (
            auditors_db.query(Auditor)
            .filter(Auditor.is_active == True)
            .order_by(Auditor.name)
            .all()
        )
        return [CRMAuditorRow(id=r.id, name=r.name, email=r.email, role=r.role) for r in rows]
    except Exception as exc:
        logger.error("[CRM] auditors DB error: %s", exc)
        return []


@router.get("/crm/auditors/{auditor_id}/calendar", response_model=list[CRMCalendarEntry])
def crm_auditor_calendar(
    auditor_id: str,
    db: Session = Depends(get_db),
    current_user: PlatformUser = Depends(get_current_user),
):
    if current_user.role not in CRM_ROLES:
        from fastapi import HTTPException
        raise HTTPException(403, "Not authorized")
    try:
        stages = (
            db.query(AuditSetStage)
            .join(AuditSet, AuditSetStage.audit_set_id == AuditSet.id)
            .filter(AuditSetStage.audit_date_start.isnot(None))
            .all()
        )
    except Exception as exc:
        logger.error("[CRM] calendar DB error: %s", exc)
        return []

    result: list[CRMCalendarEntry] = []
    for stage in stages:
        is_lead = stage.lead_auditor_id == auditor_id
        team: list[dict] = stage.auditors or []
        is_team = any(str(m.get("id", "")) == auditor_id for m in team if isinstance(m, dict))
        if not (is_lead or is_team):
            continue

        audit_set = stage.audit_set
        if not audit_set:
            continue

        date_start = stage.audit_date_start
        date_end   = stage.audit_date_end or date_start

        stype = (stage.stage_type or "").lower()
        if "stage_1" in stype or stype in ("stage1", "1"):
            label = "Stage 1"
        elif "stage_2" in stype or stype in ("stage2", "2"):
            label = "Stage 2"
        elif "surveillance" in stype:
            label = "Surveillance"
        elif "recert" in stype:
            label = "Recertification"
        else:
            label = stage.stage_type or "Audit"

        result.append(CRMCalendarEntry(
            audit_set_id = audit_set.id,
            plan_number  = audit_set.plan_number,
            company_name = audit_set.company_name or "",
            stage_type   = label,
            date_start   = date_start.isoformat(),
            date_end     = date_end.isoformat(),
            auditor_role = "Lead Auditor" if is_lead else "Team Auditor",
        ))

    result.sort(key=lambda r: r.date_start)
    return result
