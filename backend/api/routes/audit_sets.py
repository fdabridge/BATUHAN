"""
BATUHAN — Audit Set API Routes.
POST   /audit-sets/              → create a new audit set (201)
GET    /audit-sets/              → list all audit sets (?status=)
GET    /audit-sets/{id}          → get one audit set (404 if not found)
PUT    /audit-sets/{id}/planning → update EA, fees, stage assignments
GET    /audit-sets/{id}/download → ZIP of all filled DOCX templates
DELETE /audit-sets/{id}          → soft-delete: status = "archived" (204)
"""
from __future__ import annotations
import io
import logging

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session

from audit_set.db_models import get_db
from audit_set.packager import build_audit_set_zip
from audit_set.schemas import (
    AuditSetCreateSchema,
    AuditSetUpdatePlanningSchema,
    AuditSetResponse,
    AuditSetSummarySchema,
)
from audit_set.service import (
    create_audit_set,
    get_audit_set,
    list_audit_sets,
    update_planning,
)
from auth.db_models import PlatformUser
from auth.dependencies import require_admin, require_planner, require_any

router = APIRouter()
logger = logging.getLogger(__name__)


@router.post("/", response_model=AuditSetResponse, status_code=201)
def create(payload: AuditSetCreateSchema, db: Session = Depends(get_db), _: PlatformUser = Depends(require_planner)):
    """Create a new audit set, run man-day calculation, auto-generate stage rows."""
    audit_set = create_audit_set(db, payload)
    return audit_set


@router.get("/", response_model=list[AuditSetSummarySchema])
def list_all(status: str | None = None, db: Session = Depends(get_db), _: PlatformUser = Depends(require_any)):
    """
    List all audit sets, newest first.
    Pass ?status=draft|planning|complete|archived to filter.
    """
    return list_audit_sets(db, status=status)


@router.get("/{audit_set_id}", response_model=AuditSetResponse)
def get_one(audit_set_id: str, db: Session = Depends(get_db), _: PlatformUser = Depends(require_any)):
    """Return full audit set by ID, including all stage rows."""
    audit_set = get_audit_set(db, audit_set_id)
    if not audit_set:
        raise HTTPException(status_code=404, detail=f"Audit set '{audit_set_id}' not found.")
    return audit_set


@router.put("/{audit_set_id}/planning", response_model=AuditSetResponse)
def planning(
    audit_set_id: str,
    payload: AuditSetUpdatePlanningSchema,
    db: Session = Depends(get_db),
    _: PlatformUser = Depends(require_planner),
):
    """
    Update EA classification, fees, and stage auditor/date assignments.
    Creates missing stage rows; advances status from 'draft' to 'planning'.
    """
    audit_set = update_planning(db, audit_set_id, payload)
    if not audit_set:
        raise HTTPException(status_code=404, detail=f"Audit set '{audit_set_id}' not found.")
    return audit_set


@router.get("/{audit_set_id}/download")
def download_zip(audit_set_id: str, db: Session = Depends(get_db), _: PlatformUser = Depends(require_any)):
    """Return a ZIP of all filled IFC DOCX templates for this audit set."""
    audit_set = get_audit_set(db, audit_set_id)
    if not audit_set:
        raise HTTPException(status_code=404, detail=f"Audit set '{audit_set_id}' not found.")
    try:
        zip_bytes = build_audit_set_zip(audit_set, db)
    except Exception as exc:
        logger.exception("[AuditSet] ZIP build failed id=%s", audit_set_id)
        raise HTTPException(status_code=500, detail=f"Failed to build audit set ZIP: {exc}")

    filename = f"audit_set_{audit_set.plan_number}.zip"
    return StreamingResponse(
        io.BytesIO(zip_bytes),
        media_type="application/zip",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.delete("/{audit_set_id}", status_code=204)
def soft_delete(audit_set_id: str, db: Session = Depends(get_db), _: PlatformUser = Depends(require_admin)):
    """Soft-delete: set status to 'archived'. Returns 204 No Content."""
    audit_set = get_audit_set(db, audit_set_id)
    if not audit_set:
        raise HTTPException(status_code=404, detail=f"Audit set '{audit_set_id}' not found.")
    audit_set.status = "archived"
    db.commit()
    logger.info("[AuditSet] Archived id=%s", audit_set_id)
