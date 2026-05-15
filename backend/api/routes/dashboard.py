"""
BATUHAN — Dashboard API Routes
GET   /dashboard/stats                    → aggregate stats cards
GET   /dashboard/clients                  → paginated client list with cert info
PATCH /dashboard/clients/{id}/cert-dates  → update certificate issued/expiry dates
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from audit_set.db_models import AuditSet, get_db
from audit_set.schemas import (
    AuditSetCertUpdateSchema,
    ClientSummarySchema,
    DashboardStatsSchema,
)
from audit_set.service import (
    get_audit_set,
    get_dashboard_stats,
    list_clients,
    update_cert_dates,
)
from auth.db_models import PlatformUser
from auth.dependencies import require_any, require_planner

router = APIRouter()


# ---------------------------------------------------------------------------
# Internal helper — builds ClientSummarySchema from an AuditSet ORM row
# ---------------------------------------------------------------------------

def _to_client_summary(audit_set: AuditSet) -> ClientSummarySchema:
    stages = audit_set.stages or []

    stage_1_date = next(
        (s.audit_date_start for s in stages if s.stage_type == "stage_1"), None
    )
    stage_2_date = next(
        (s.audit_date_start for s in stages if s.stage_type == "stage_2"), None
    )

    # Prefer stage_2 lead auditor, fall back to stage_1
    lead_auditor_name: str | None = None
    for preferred in ("stage_2", "stage_1"):
        match = next(
            (s.lead_auditor_name for s in stages
             if s.stage_type == preferred and s.lead_auditor_name),
            None,
        )
        if match:
            lead_auditor_name = match
            break

    return ClientSummarySchema(
        id=audit_set.id,
        plan_number=audit_set.plan_number,
        company_name=audit_set.company_name or "",
        company_address=audit_set.company_address or "",
        standards=audit_set.standards or [],
        audit_type=audit_set.audit_type or "",
        status=audit_set.status,
        cert_issued_date=audit_set.cert_issued_date,
        cert_expiry_date=audit_set.cert_expiry_date,
        cert_status=audit_set.compute_cert_status(),
        stage_1_date=stage_1_date,
        stage_2_date=stage_2_date,
        lead_auditor_name=lead_auditor_name,
        created_at=audit_set.created_at,
    )


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------

@router.get("/stats", response_model=DashboardStatsSchema)
def dashboard_stats(
    db: Session = Depends(get_db),
    _: PlatformUser = Depends(require_any),
):
    """Return aggregate counts: total plans, active certs, approaching expiry, expired,
    open pipeline jobs, pending review jobs."""
    return get_dashboard_stats(db)


@router.get("/clients", response_model=list[ClientSummarySchema])
def dashboard_clients(
    search: str | None = None,
    standard: str | None = None,
    cert_status: str | None = None,
    audit_type: str | None = None,
    limit: int = 50,
    offset: int = 0,
    db: Session = Depends(get_db),
    _: PlatformUser = Depends(require_any),
):
    """Paginated client list. Supports filtering by search, standard, cert_status,
    audit_type. Returns ClientSummarySchema for each match."""
    audit_sets = list_clients(
        db,
        search=search,
        standard=standard,
        cert_status=cert_status,
        audit_type=audit_type,
        limit=limit,
        offset=offset,
    )
    return [_to_client_summary(a) for a in audit_sets]


@router.patch("/clients/{audit_set_id}/cert-dates", response_model=ClientSummarySchema)
def update_client_cert_dates(
    audit_set_id: str,
    body: AuditSetCertUpdateSchema,
    db: Session = Depends(get_db),
    _: PlatformUser = Depends(require_planner),
):
    """Set or update certificate issued/expiry dates for an audit set.
    Auto-computes expiry as issued + 3 years when only issued date is supplied."""
    audit_set = update_cert_dates(db, audit_set_id, body)
    if not audit_set:
        raise HTTPException(status_code=404, detail=f"Audit set '{audit_set_id}' not found.")
    return _to_client_summary(audit_set)
