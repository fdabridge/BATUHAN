"""
BATUHAN — Auth API Routes
POST /auth/login            → exchange credentials for JWT
GET  /auth/me               → return current user profile
POST /auth/change-password  → authenticated user changes own password
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from auth.db_models import get_db
from auth.dependencies import get_current_user
from auth.schemas import (
    ChangePasswordRequest, LoginRequest, TokenResponse, UserResponse,
)
from auth.service import authenticate, change_password, create_token, verify_password

router = APIRouter()


@router.post("/login", response_model=TokenResponse)
def login(body: LoginRequest, db: Session = Depends(get_db)):
    """Exchange email + password for a signed JWT."""
    user = authenticate(db, body.email, body.password)
    if not user:
        raise HTTPException(status_code=401, detail="Invalid credentials")
    token = create_token(user.id, user.email, user.role)
    return TokenResponse(
        access_token=token,
        role=user.role,
        full_name=user.full_name,
        user_id=user.id,
    )


@router.get("/me", response_model=UserResponse)
def me(current_user=Depends(get_current_user)):
    """Return the profile of the currently authenticated user."""
    return current_user


@router.post("/change-password")
def change_own_password(
    body: ChangePasswordRequest,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    """Authenticated user changes their own password."""
    if not verify_password(body.current_password, current_user.password_hash):
        raise HTTPException(status_code=400, detail="Current password incorrect")
    change_password(db, current_user.id, body.new_password)
    return {"message": "Password updated"}
