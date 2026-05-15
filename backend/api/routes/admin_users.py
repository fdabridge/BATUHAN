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

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from auth.db_models import PlatformUser, get_db
from auth.dependencies import get_current_user, require_admin
from auth.schemas import (
    UserCreateSchema, UserResponse, UserUpdateSchema, VALID_ROLES,
)
from auth.service import (
    create_user, get_user_by_id, list_users, update_user, change_password,
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
    if body.role not in VALID_ROLES:
        raise HTTPException(status_code=400, detail=f"Invalid role. Must be one of {sorted(VALID_ROLES)}")
    user = create_user(db, body.email, body.password, body.full_name, body.role, body.auditor_id)
    return user


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
