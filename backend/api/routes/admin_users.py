"""
BATUHAN — Admin User Management Routes
All endpoints require the "admin" role.

POST   /admin/users/                    → create user (201)
GET    /admin/users/                    → list users
GET    /admin/users/{id}               → get user (404 if not found)
PUT    /admin/users/{id}               → update user (404 if not found)
POST   /admin/users/{id}/reset-password → admin resets password directly
DELETE /admin/users/{id}               → soft-delete / deactivate (204)
"""
from __future__ import annotations

import csv
import io

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from pydantic import BaseModel
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from auditors.models import Auditor, AuditorStandardQualification, get_db as get_auditors_db
from auth.db_models import PlatformUser, get_db
from auth.dependencies import get_current_user, require_admin
from auth.schemas import (
    UserCreateSchema, UserResponse, UserUpdateSchema, VALID_ROLES,
)
from auth.service import (
    create_user, get_user_by_email, get_user_by_id, get_user_by_username, list_users, update_user, change_password,
)

router = APIRouter()


class ResetPasswordRequest(BaseModel):
    new_password: str


@router.post("/users/", response_model=UserResponse, status_code=201)
def admin_create_user(
    body: UserCreateSchema,
    db: Session = Depends(get_db),
    _admin: PlatformUser = Depends(require_admin),
):
    full_name = body.full_name.strip()
    email = body.email.strip()
    username = body.username.strip() if body.username else None
    role = body.role.strip().lower()

    if not full_name or not email or not body.password or not username:
        raise HTTPException(status_code=400, detail="Full name, username, email, and password are required.")
    if role not in VALID_ROLES:
        raise HTTPException(status_code=400, detail=f"Invalid role. Must be one of {sorted(VALID_ROLES)}")
    if get_user_by_email(db, email):
        raise HTTPException(status_code=409, detail="Email already exists.")
    if username and get_user_by_username(db, username):
        raise HTTPException(status_code=409, detail="Username already exists.")

    auditor_id = body.auditor_id if role == "auditor" else None
    try:
        return create_user(db, email, body.password, full_name, role, auditor_id, username)
    except IntegrityError:
        db.rollback()
        raise HTTPException(status_code=409, detail="A user with this email or username already exists.")


@router.get("/users/", response_model=list[UserResponse])
def admin_list_users(
    include_inactive: bool = False,
    db: Session = Depends(get_db),
    _admin: PlatformUser = Depends(require_admin),
):
    return list_users(db, include_inactive=include_inactive)


@router.get("/users/{user_id}", response_model=UserResponse)
def admin_get_user(
    user_id: str,
    db: Session = Depends(get_db),
    _admin: PlatformUser = Depends(require_admin),
):
    user = get_user_by_id(db, user_id)
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    return user


@router.put("/users/{user_id}", response_model=UserResponse)
def admin_update_user(
    user_id: str,
    body: UserUpdateSchema,
    db: Session = Depends(get_db),
    _admin: PlatformUser = Depends(require_admin),
):
    if body.role and body.role not in VALID_ROLES:
        raise HTTPException(status_code=400, detail=f"Invalid role. Must be one of {sorted(VALID_ROLES)}")
    user = update_user(db, user_id, **body.model_dump(exclude_none=True))
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    return user


@router.post("/users/{user_id}/reset-password")
def admin_reset_password(
    user_id: str,
    body: ResetPasswordRequest,
    db: Session = Depends(get_db),
    _admin: PlatformUser = Depends(require_admin),
):
    ok = change_password(db, user_id, body.new_password)
    if not ok:
        raise HTTPException(status_code=404, detail="User not found")
    return {"message": "Password reset"}


@router.delete("/users/{user_id}", status_code=204)
def admin_deactivate_user(
    user_id: str,
    db: Session = Depends(get_db),
    current_admin: PlatformUser = Depends(get_current_user),
    _admin: PlatformUser = Depends(require_admin),
):
    if user_id == current_admin.id:
        raise HTTPException(status_code=400, detail="Cannot deactivate your own account")
    ok = update_user(db, user_id, is_active=False)
    if not ok:
        raise HTTPException(status_code=404, detail="User not found")


@router.post("/users/bulk-import")
async def admin_bulk_import(
    file:        UploadFile  = File(...),
    db:          Session     = Depends(get_db),
    auditors_db: Session     = Depends(get_auditors_db),
    _admin:      PlatformUser = Depends(require_admin),
):
    """
    CSV bulk import for CB staff and auditor accounts.
    Idempotent: rows whose username already exists in platform_users are skipped.
    Returns a summary of what was created, skipped, and any row-level errors.
    """
    contents = await file.read()
    try:
        text = contents.decode("utf-8-sig")   # utf-8-sig strips BOM if present
    except UnicodeDecodeError:
        text = contents.decode("latin-1")

    reader = csv.DictReader(io.StringIO(text))

    created: list[dict] = []
    skipped: list[dict] = []
    errors:  list[dict] = []

    for i, row in enumerate(reader, start=2):   # row 1 = header
        full_name      = (row.get("full_name")             or "").strip()
        username       = (row.get("username")              or "").strip()
        email          = (row.get("email")                 or "").strip()
        password       = (row.get("password")              or "").strip()
        role           = (row.get("role")                  or "").strip().lower()
        standards_raw  = (row.get("standards")             or "").strip()
        ea_codes_raw   = (row.get("ea_codes")              or "").strip()
        accred_raw     = (row.get("accreditation_bodies")  or "").strip()
        tech_depth     = (row.get("technical_depth")       or "").strip()

        # ── Validate required fields ──────────────────────────────────────────
        if not full_name or not username or not password or not role:
            errors.append({"row": i, "username": username or "?",
                           "reason": "Missing required field (full_name / username / password / role)"})
            continue

        if role not in VALID_ROLES:
            errors.append({"row": i, "username": username,
                           "reason": f"Invalid role '{role}'. Must be one of {sorted(VALID_ROLES)}"})
            continue

        # ── Check for duplicate username ──────────────────────────────────────
        if get_user_by_username(db, username):
            skipped.append({"row": i, "username": username, "reason": "Username already exists"})
            continue

        # ── Auditor path: create Auditor profile first ────────────────────────
        auditor_id = None
        if role == "auditor":
            standards = [s.strip() for s in standards_raw.split("|") if s.strip()]
            ea_codes  = [c.strip() for c in ea_codes_raw.split("|")  if c.strip()]
            accred    = [a.strip() for a in accred_raw.split("|")     if a.strip()]

            auditor = Auditor(
                name=full_name,
                email=email or None,
                role=tech_depth or "Lead Auditor",
                ea_codes=ea_codes if ea_codes else None,
                accreditation_bodies=accred if accred else None,
                is_active=True,
            )
            auditors_db.add(auditor)
            auditors_db.flush()   # get auditor.id before committing

            for std in standards:
                auditors_db.add(AuditorStandardQualification(
                    auditor_id=auditor.id,
                    standard_code=std,
                    accreditation_body=accred[0] if accred else None,
                    ea_codes=ea_codes if ea_codes else None,
                    technical_depth=tech_depth or "Lead Auditor",
                    is_qualified=True,
                ))
            auditors_db.commit()
            auditor_id = auditor.id

        # ── Create platform_users account ─────────────────────────────────────
        try:
            user = create_user(
                db=db,
                email=email or f"{username}@certiva.internal",
                password=password,
                full_name=full_name,
                role=role,
                auditor_id=auditor_id,
                username=username,
            )
            created.append({
                "row":        i,
                "username":   username,
                "full_name":  full_name,
                "role":       role,
                "user_id":    user.id,
                "auditor_id": auditor_id,
            })
        except Exception as exc:
            # Roll back auditor record if user creation failed
            if auditor_id:
                try:
                    a = auditors_db.query(Auditor).filter_by(id=auditor_id).first()
                    if a:
                        auditors_db.delete(a)
                        auditors_db.commit()
                except Exception:
                    pass
            errors.append({"row": i, "username": username, "reason": str(exc)})

    return {
        "summary": {
            "total_rows": len(created) + len(skipped) + len(errors),
            "created":    len(created),
            "skipped":    len(skipped),
            "errors":     len(errors),
        },
        "created": created,
        "skipped": skipped,
        "errors":  errors,
    }
