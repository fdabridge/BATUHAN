"""
BATUHAN — Auth: Pydantic request / response schemas.
"""
from __future__ import annotations
from datetime import datetime

from pydantic import BaseModel

VALID_ROLES = {"admin", "planner", "planner_us", "auditor", "officer", "executive", "client", "gm", "certification_manager", "crm", "consultant"}


class LoginRequest(BaseModel):
    email: str
    password: str


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    role: str
    full_name: str
    user_id: str


class UserCreateSchema(BaseModel):
    email: str
    password: str
    full_name: str
    role: str           # must be one of VALID_ROLES
    auditor_id: str | None = None
    username: str | None = None


class UserUpdateSchema(BaseModel):
    full_name: str | None = None
    role: str | None = None
    is_active: bool | None = None
    auditor_id: str | None = None
    username: str | None = None


class UserResponse(BaseModel):
    id: str
    email: str
    username: str | None
    full_name: str
    role: str
    is_active: bool
    auditor_id: str | None
    last_login: datetime | None
    created_at: datetime

    class Config:
        from_attributes = True


class ChangePasswordRequest(BaseModel):
    current_password: str
    new_password: str
