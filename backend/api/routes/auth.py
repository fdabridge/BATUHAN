"""
BATUHAN — Auth API Routes
POST /auth/login            → exchange credentials for JWT
GET  /auth/me               → return current user profile
POST /auth/change-password  → authenticated user changes own password
GET  /auth/bootstrap        → one-time admin creation (requires internal API key)
"""
from __future__ import annotations

from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel
from sqlalchemy.orm import Session

from auth.db_models import PlatformUser, get_db
from auth.dependencies import get_current_user
from auth.otp import OTP_MAX_ATTEMPTS, generate_otp, otp_matches
from auth.policy import CLIENT_EMAIL_VERIFICATION, policy_enabled
from auth.schemas import (
    ChangePasswordRequest, LoginRequest, TokenResponse, UserResponse,
)
from auth.service import authenticate, change_password, create_token, create_user, get_user_by_email, verify_password
from config.settings import get_settings
from email_service import send_otp_code

router = APIRouter()


@router.post("/login", response_model=TokenResponse)
def login(body: LoginRequest, db: Session = Depends(get_db)):
    """Exchange email + password for a signed JWT."""
    user = authenticate(db, body.email, body.password)
    if not user:
        raise HTTPException(status_code=401, detail="Invalid credentials")
    token = create_token(user.id, user.email, user.role)
    activation_required = (
        user.role == "client"
        and not user.is_activated
        and policy_enabled(db, CLIENT_EMAIL_VERIFICATION)
    )
    return TokenResponse(
        access_token=token,
        role=user.role,
        full_name=user.full_name,
        user_id=user.id,
        activation_required=activation_required,
    )


@router.get("/me", response_model=UserResponse)
def me(
    current_user: PlatformUser = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Return the profile of the currently authenticated user."""
    return {
        "id": current_user.id,
        "email": current_user.email,
        "username": current_user.username,
        "full_name": current_user.full_name,
        "role": current_user.role,
        "is_active": current_user.is_active,
        "auditor_id": current_user.auditor_id,
        "is_activated": current_user.is_activated,
        "activation_required": (
            current_user.role == "client"
            and not current_user.is_activated
            and policy_enabled(db, CLIENT_EMAIL_VERIFICATION)
        ),
        "last_login": current_user.last_login,
        "created_at": current_user.created_at,
    }


class ActivationCodeBody(BaseModel):
    code: str


@router.post("/client-activation/request")
def request_client_activation(
    current_user: PlatformUser = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    if current_user.role != "client":
        raise HTTPException(403, "Client role required")
    if not policy_enabled(db, CLIENT_EMAIL_VERIFICATION):
        return {"verification_required": False}
    if current_user.is_activated:
        return {"verification_required": False, "already_verified": True}

    code, code_hash, expires_at = generate_otp()
    if not send_otp_code(
        to=current_user.email,
        full_name=current_user.full_name,
        otp=code,
        document_label="client account activation",
    ):
        raise HTTPException(503, "Couldn't send your code. Please try again.")

    current_user.activation_email = current_user.email
    current_user.activation_otp_hash = code_hash
    current_user.activation_otp_expires_at = expires_at
    current_user.activation_otp_attempts = 0
    db.commit()
    return {
        "verification_required": True,
        "email": current_user.email,
        "expires_in_minutes": 10,
    }


@router.post("/client-activation/verify")
def verify_client_activation(
    body: ActivationCodeBody,
    request: Request,
    current_user: PlatformUser = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    if current_user.role != "client":
        raise HTTPException(403, "Client role required")
    if not policy_enabled(db, CLIENT_EMAIL_VERIFICATION):
        return {"verified": True, "verification_required": False}
    if current_user.is_activated:
        return {"verified": True, "already_verified": True}
    if (
        not current_user.activation_otp_hash
        or not current_user.activation_otp_expires_at
    ):
        raise HTTPException(400, "Request a verification code first.")
    if datetime.utcnow() > current_user.activation_otp_expires_at:
        raise HTTPException(400, "Verification code expired. Request a new code.")

    current_user.activation_otp_attempts = (
        current_user.activation_otp_attempts or 0
    ) + 1
    if current_user.activation_otp_attempts > OTP_MAX_ATTEMPTS:
        current_user.activation_otp_hash = None
        current_user.activation_otp_expires_at = None
        db.commit()
        raise HTTPException(400, "Too many attempts. Request a new code.")
    if not otp_matches(body.code, current_user.activation_otp_hash):
        db.commit()
        raise HTTPException(400, "Incorrect verification code.")

    current_user.is_activated = True
    current_user.activation_verified_at = datetime.utcnow()
    current_user.activation_verified_ip = (
        request.client.host if request.client else None
    )
    current_user.activation_otp_hash = None
    current_user.activation_otp_expires_at = None
    current_user.activation_otp_attempts = 0
    db.commit()
    return {"verified": True, "activation_verified_at": current_user.activation_verified_at}


@router.get("/bootstrap")
def bootstrap_admin(
    key: str = Query(...),
    email: str = Query(...),
    password: str = Query(...),
    db: Session = Depends(get_db),
):
    """
    One-time endpoint to force-create an admin user.
    Protected by INTERNAL_API_KEY (default: change-me-in-production).
    """
    s = get_settings()
    if key != s.internal_api_key:
        raise HTTPException(status_code=403, detail="Forbidden")
    existing = get_user_by_email(db, email)
    if existing:
        # Reset password in case user exists with wrong hash
        from auth.service import hash_password
        existing.password_hash = hash_password(password)
        db.commit()
        return {"status": "password_reset", "email": existing.email, "role": existing.role}
    user = create_user(db, email, password, "Administrator", "admin")
    return {"status": "created", "email": user.email, "id": user.id}


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
