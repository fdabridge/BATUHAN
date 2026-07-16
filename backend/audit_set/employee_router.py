"""
BATUHAN — Client Organisation Employee roster (Portal 49a).

Endpoints under /org/employees. Client-role only. Each employee is owned by
the calling user (client_user_id = current_user.id). Signature images follow
the UserSignature pattern: base64 PNG data URLs stored on the row itself.
"""
from __future__ import annotations
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from audit_set.db_models import ClientOrgEmployee, get_db
from audit_set.signature_image import normalize_signature_data_url
from auth.db_models import PlatformUser
from auth.dependencies import get_current_user

router = APIRouter(prefix="/org/employees", tags=["client-employees"])

_MAX_DATA_LEN = 2_000_000   # ~1.5 MB base64 PNG, same ceiling as UserSignature


def _require_client(current_user: PlatformUser) -> None:
    if current_user.role != "client":
        raise HTTPException(403, "Client role required")


# ── Schemas ───────────────────────────────────────────────────────────────────

class EmployeeCreate(BaseModel):
    full_name:  str
    role_title: str


class EmployeeUpdate(BaseModel):
    full_name:  Optional[str] = None
    role_title: Optional[str] = None
    is_active:  Optional[bool] = None


class SignatureIn(BaseModel):
    image_data: str   # data:image/png;base64,...
    source:     str   # "drawn" | "uploaded"


def _serialize(e: ClientOrgEmployee) -> dict:
    return {
        "id":              e.id,
        "full_name":       e.full_name,
        "role_title":      e.role_title,
        "is_active":       e.is_active,
        "has_signature":   bool(e.signature_data),
        "signature_source": e.signature_source,
        "created_at":      e.created_at.isoformat(),
        "updated_at":      e.updated_at.isoformat(),
    }


def _get_owned(employee_id: str, current_user: PlatformUser, db: Session) -> ClientOrgEmployee:
    emp = db.query(ClientOrgEmployee).filter_by(id=employee_id).first()
    if not emp or emp.client_user_id != current_user.id:
        raise HTTPException(404, "Employee not found")
    return emp


# ── List ──────────────────────────────────────────────────────────────────────

@router.get("")
def list_employees(
    include_inactive: bool = False,
    db: Session                = Depends(get_db),
    current_user: PlatformUser = Depends(get_current_user),
):
    _require_client(current_user)
    q = db.query(ClientOrgEmployee).filter_by(client_user_id=current_user.id)
    if not include_inactive:
        q = q.filter_by(is_active=True)
    return [_serialize(e) for e in q.order_by(ClientOrgEmployee.created_at).all()]


# ── Create ────────────────────────────────────────────────────────────────────

@router.post("")
def create_employee(
    body: EmployeeCreate,
    db: Session                = Depends(get_db),
    current_user: PlatformUser = Depends(get_current_user),
):
    _require_client(current_user)
    if not body.full_name.strip() or not body.role_title.strip():
        raise HTTPException(400, "full_name and role_title are required")
    emp = ClientOrgEmployee(
        client_user_id=current_user.id,
        full_name=body.full_name.strip(),
        role_title=body.role_title.strip(),
    )
    db.add(emp); db.commit(); db.refresh(emp)
    return _serialize(emp)


# ── Update ────────────────────────────────────────────────────────────────────

@router.patch("/{employee_id}")
def update_employee(
    employee_id: str,
    body: EmployeeUpdate,
    db: Session                = Depends(get_db),
    current_user: PlatformUser = Depends(get_current_user),
):
    _require_client(current_user)
    emp = _get_owned(employee_id, current_user, db)
    if body.full_name is not None:
        if not body.full_name.strip():
            raise HTTPException(400, "full_name cannot be empty")
        emp.full_name = body.full_name.strip()
    if body.role_title is not None:
        if not body.role_title.strip():
            raise HTTPException(400, "role_title cannot be empty")
        emp.role_title = body.role_title.strip()
    if body.is_active is not None:
        emp.is_active = body.is_active
    db.commit(); db.refresh(emp)
    return _serialize(emp)


# ── Soft delete ───────────────────────────────────────────────────────────────

@router.delete("/{employee_id}")
def delete_employee(
    employee_id: str,
    db: Session                = Depends(get_db),
    current_user: PlatformUser = Depends(get_current_user),
):
    _require_client(current_user)
    emp = _get_owned(employee_id, current_user, db)
    emp.is_active = False
    db.commit()
    return {"deleted": True}



# ── Signature: upsert ─────────────────────────────────────────────────────────

@router.post("/{employee_id}/signature")
def save_employee_signature(
    employee_id: str,
    body: SignatureIn,
    db: Session                = Depends(get_db),
    current_user: PlatformUser = Depends(get_current_user),
):
    _require_client(current_user)
    emp = _get_owned(employee_id, current_user, db)
    if not body.image_data.startswith("data:image/png;base64,"):
        raise HTTPException(400, "image_data must be a PNG data URL (data:image/png;base64,...)")
    if len(body.image_data) > _MAX_DATA_LEN:
        raise HTTPException(400, "Signature image is too large. Maximum is ~1.5 MB.")
    if body.source not in ("drawn", "uploaded"):
        raise HTTPException(400, "source must be 'drawn' or 'uploaded'")
    try:
        image_data = normalize_signature_data_url(body.image_data)
    except Exception:
        raise HTTPException(400, "Signature image could not be processed as a PNG.")

    emp.signature_data   = image_data
    emp.signature_source = body.source
    db.commit(); db.refresh(emp)
    return _serialize(emp)


# ── Signature: get (full data URL) ────────────────────────────────────────────

@router.get("/{employee_id}/signature")
def get_employee_signature(
    employee_id: str,
    db: Session                = Depends(get_db),
    current_user: PlatformUser = Depends(get_current_user),
):
    _require_client(current_user)
    emp = _get_owned(employee_id, current_user, db)
    if not emp.signature_data:
        return None
    return {
        "has_signature": True,
        "image_data":    emp.signature_data,
        "source":        emp.signature_source,
        "updated_at":    emp.updated_at.isoformat(),
    }
