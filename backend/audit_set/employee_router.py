"""
BATUHAN — Client Organisation Employee roster (Portal 49a).

Endpoints under /org/employees. Client-role only. Each employee is owned by
the calling user (client_user_id = current_user.id). Signature images follow
the UserSignature pattern: base64 PNG data URLs stored on the row itself.
"""
from __future__ import annotations
from datetime import datetime
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel
from sqlalchemy.orm import Session

from audit_set.db_models import ClientOrgEmployee, get_db
from audit_set.signature_image import normalize_signature_data_url
from auth.db_models import PlatformUser, get_db as get_auth_db
from auth.dependencies import get_current_user
from auth.otp import OTP_MAX_ATTEMPTS, generate_otp, otp_matches
from auth.policy import EMPLOYEE_SIGNATURE_EMAIL_VERIFICATION, policy_enabled
from email_service import send_otp_code

router = APIRouter(prefix="/org/employees", tags=["client-employees"])

_MAX_DATA_LEN = 2_000_000   # ~1.5 MB base64 PNG, same ceiling as UserSignature


def _require_client(current_user: PlatformUser) -> None:
    if current_user.role != "client":
        raise HTTPException(403, "Client role required")


# ── Schemas ───────────────────────────────────────────────────────────────────

class EmployeeCreate(BaseModel):
    full_name:  str
    role_title: str
    email:      Optional[str] = None


class EmployeeUpdate(BaseModel):
    full_name:  Optional[str] = None
    role_title: Optional[str] = None
    email:      Optional[str] = None
    is_active:  Optional[bool] = None


class SignatureIn(BaseModel):
    image_data: str   # data:image/png;base64,...
    source:     str   # "drawn" | "uploaded"


class SignatureVerifyIn(BaseModel):
    code: str


def _serialize(e: ClientOrgEmployee) -> dict:
    return {
        "id":              e.id,
        "full_name":       e.full_name,
        "role_title":      e.role_title,
        "email":           e.email,
        "is_active":       e.is_active,
        "has_signature":   bool(e.signature_data),
        "signature_source": e.signature_source,
        "signature_verified_at": e.signature_verified_at.isoformat() if e.signature_verified_at else None,
        "signature_verification_pending": bool(e.pending_signature_data),
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
        email=body.email.strip().lower() if body.email and body.email.strip() else None,
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
    if body.email is not None:
        emp.email = body.email.strip().lower() or None
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
    auth_db: Session           = Depends(get_auth_db),
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

    if policy_enabled(auth_db, EMPLOYEE_SIGNATURE_EMAIL_VERIFICATION):
        if not emp.email:
            raise HTTPException(400, "Add the employee's email address before enrolling a signature.")
        otp, otp_hash, expires_at = generate_otp()
        if not send_otp_code(
            to=emp.email,
            full_name=emp.full_name,
            otp=otp,
            document_label="employee signature enrollment",
        ):
            raise HTTPException(503, "Verification email could not be delivered. The signature was not changed.")
        emp.pending_signature_data = image_data
        emp.pending_signature_source = body.source
        emp.enroll_otp_hash = otp_hash
        emp.enroll_otp_email = emp.email
        emp.enroll_otp_expires_at = expires_at
        emp.enroll_otp_attempts = 0
        db.commit()
        db.refresh(emp)
        result = _serialize(emp)
        result["verification_required"] = True
        result["verification_email"] = emp.email
        return result

    emp.signature_data = image_data
    emp.signature_source = body.source
    emp.signature_verified_at = datetime.utcnow()
    emp.signature_verified_email = emp.email
    emp.pending_signature_data = None
    emp.pending_signature_source = None
    emp.enroll_otp_hash = None
    emp.enroll_otp_email = None
    emp.enroll_otp_expires_at = None
    emp.enroll_otp_attempts = 0
    db.commit(); db.refresh(emp)
    return _serialize(emp)


@router.post("/{employee_id}/signature/verify")
def verify_employee_signature(
    employee_id: str,
    body: SignatureVerifyIn,
    request: Request,
    db: Session = Depends(get_db),
    auth_db: Session = Depends(get_auth_db),
    current_user: PlatformUser = Depends(get_current_user),
):
    _require_client(current_user)
    emp = _get_owned(employee_id, current_user, db)
    if not policy_enabled(auth_db, EMPLOYEE_SIGNATURE_EMAIL_VERIFICATION):
        raise HTTPException(400, "Employee signature verification is currently disabled.")
    if not emp.pending_signature_data or not emp.enroll_otp_hash:
        raise HTTPException(400, "No employee signature is awaiting verification.")
    if not emp.email or emp.email != emp.enroll_otp_email:
        raise HTTPException(
            400,
            "The employee email changed after the code was sent. Save the signature again for a new code.",
        )
    if not emp.enroll_otp_expires_at or emp.enroll_otp_expires_at < datetime.utcnow():
        raise HTTPException(400, "Verification code has expired. Save the signature again for a new code.")
    if (emp.enroll_otp_attempts or 0) >= OTP_MAX_ATTEMPTS:
        raise HTTPException(429, "Too many verification attempts. Save the signature again for a new code.")
    if not otp_matches(body.code, emp.enroll_otp_hash):
        emp.enroll_otp_attempts = (emp.enroll_otp_attempts or 0) + 1
        db.commit()
        raise HTTPException(400, "Invalid verification code.")

    emp.signature_data = emp.pending_signature_data
    emp.signature_source = emp.pending_signature_source
    emp.signature_verified_at = datetime.utcnow()
    emp.signature_verified_email = emp.email
    emp.signature_verified_ip = request.client.host if request.client else None
    emp.pending_signature_data = None
    emp.pending_signature_source = None
    emp.enroll_otp_hash = None
    emp.enroll_otp_email = None
    emp.enroll_otp_expires_at = None
    emp.enroll_otp_attempts = 0
    db.commit()
    db.refresh(emp)
    return {**_serialize(emp), "verified": True}


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
