"""
BATUHAN — Auth: FastAPI dependency injection helpers.
"""
from __future__ import annotations

from fastapi import Depends, HTTPException, Request
from fastapi.security import OAuth2PasswordBearer
from jose import JWTError
from sqlalchemy.orm import Session

from auth.db_models import PlatformUser, get_db
from auth.service import decode_token, get_user_by_id

oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/auth/login")


def get_current_user(
    request: Request,
    token: str = Depends(oauth2_scheme),
    db: Session = Depends(get_db),
) -> PlatformUser:
    try:
        payload = decode_token(token)
        user = get_user_by_id(db, payload["sub"])
        if not user or not user.is_active:
            raise HTTPException(status_code=401, detail="Invalid or inactive user")
        if user.role == "client" and not user.is_activated:
            from auth.policy import CLIENT_EMAIL_VERIFICATION, policy_enabled
            activation_paths = {
                "/auth/me",
                "/auth/client-activation/request",
                "/auth/client-activation/verify",
            }
            if (
                policy_enabled(db, CLIENT_EMAIL_VERIFICATION)
                and request.url.path not in activation_paths
            ):
                raise HTTPException(
                    status_code=403,
                    detail="Client email verification is required.",
                )
        return user
    except JWTError:
        raise HTTPException(status_code=401, detail="Could not validate token")


def require_role(*roles: str):
    """Factory that returns a FastAPI dependency enforcing one of the given roles."""
    def checker(
        current_user: PlatformUser = Depends(get_current_user),
    ) -> PlatformUser:
        if current_user.role not in roles:
            raise HTTPException(
                status_code=403,
                detail=f"Access denied. Required role: {list(roles)}",
            )
        return current_user
    return checker


# Convenience shortcuts — use as Depends(require_admin) etc.
require_admin    = require_role("admin")
require_planner  = require_role("admin", "planner", "planner_us")
require_auditor  = require_role("admin", "planner", "planner_us", "auditor")
require_officer  = require_role("admin", "officer")
require_any      = require_role("admin", "planner", "planner_us", "auditor", "officer", "executive", "certification_manager")
require_training_officer = require_role("admin", "training_officer")
