"""
BATUHAN — Auth: password hashing, JWT creation/decoding, user CRUD.
"""
from __future__ import annotations
from datetime import datetime, timedelta

from jose import jwt, JWTError  # noqa: F401 — JWTError re-exported for callers
from passlib.context import CryptContext
from sqlalchemy.orm import Session

from auth.db_models import PlatformUser
from config.settings import get_settings

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")

# ---------------------------------------------------------------------------
# Password helpers
# ---------------------------------------------------------------------------

def hash_password(plain: str) -> str:
    return pwd_context.hash(plain)


def verify_password(plain: str, hashed: str) -> bool:
    return pwd_context.verify(plain, hashed)


# ---------------------------------------------------------------------------
# JWT helpers
# ---------------------------------------------------------------------------

def create_token(user_id: str, email: str, role: str) -> str:
    s = get_settings()
    expire = datetime.utcnow() + timedelta(hours=s.jwt_expiry_hours)
    payload = {
        "sub":   user_id,
        "email": email,
        "role":  role,
        "exp":   expire,
    }
    return jwt.encode(payload, s.secret_key, algorithm=s.jwt_algorithm)


def decode_token(token: str) -> dict:
    """Return the decoded payload dict. Raises JWTError on any failure."""
    s = get_settings()
    return jwt.decode(token, s.secret_key, algorithms=[s.jwt_algorithm])


# ---------------------------------------------------------------------------
# User CRUD
# ---------------------------------------------------------------------------

def get_user_by_email(db: Session, email: str) -> PlatformUser | None:
    return db.query(PlatformUser).filter(PlatformUser.email == email).first()


def get_user_by_username(db: Session, username: str) -> PlatformUser | None:
    return db.query(PlatformUser).filter(PlatformUser.username == username).first()


def get_user_by_id(db: Session, user_id: str) -> PlatformUser | None:
    return db.query(PlatformUser).filter(PlatformUser.id == user_id).first()


def list_users(db: Session, include_inactive: bool = False) -> list[PlatformUser]:
    q = db.query(PlatformUser)
    if not include_inactive:
        q = q.filter(PlatformUser.is_active == True)  # noqa: E712
    return q.order_by(PlatformUser.created_at).all()


def create_user(
    db: Session,
    email: str,
    password: str,
    full_name: str,
    role: str,
    auditor_id: str | None = None,
    username: str | None = None,
) -> PlatformUser:
    is_activated = True
    if role == "client":
        from auth.policy import CLIENT_EMAIL_VERIFICATION, policy_enabled
        is_activated = not policy_enabled(db, CLIENT_EMAIL_VERIFICATION)
    user = PlatformUser(
        email=email,
        password_hash=hash_password(password),
        full_name=full_name,
        role=role,
        auditor_id=auditor_id,
        username=username,
        is_activated=is_activated,
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    if role == "client" and not user.is_activated:
        # Best-effort initial activation email; the client can request a fresh
        # code after login if delivery is unavailable during account creation.
        try:
            from auth.otp import generate_otp
            from email_service import send_otp_code
            code, code_hash, expires_at = generate_otp()
            if send_otp_code(
                to=user.email,
                full_name=user.full_name,
                otp=code,
                document_label="client account activation",
            ):
                user.activation_email = user.email
                user.activation_otp_hash = code_hash
                user.activation_otp_expires_at = expires_at
                user.activation_otp_attempts = 0
                db.commit()
                db.refresh(user)
        except Exception:
            pass
    return user


_UPDATABLE = {"full_name", "role", "is_active", "auditor_id", "username"}


def update_user(db: Session, user_id: str, **fields) -> PlatformUser | None:
    user = get_user_by_id(db, user_id)
    if not user:
        return None
    for key, value in fields.items():
        if key in _UPDATABLE and value is not None:
            setattr(user, key, value)
    user.updated_at = datetime.utcnow()
    db.commit()
    db.refresh(user)
    return user


def change_password(db: Session, user_id: str, new_password: str) -> bool:
    user = get_user_by_id(db, user_id)
    if not user:
        return False
    user.password_hash = hash_password(new_password)
    user.updated_at = datetime.utcnow()
    db.commit()
    return True


def authenticate(db: Session, identifier: str, password: str) -> PlatformUser | None:
    """Return user if credentials are valid and account is active, else None.
    Accepts username or email as identifier."""
    user = get_user_by_username(db, identifier) or get_user_by_email(db, identifier)
    if not user or not user.is_active:
        return None
    if not verify_password(password, user.password_hash):
        return None
    user.last_login = datetime.utcnow()
    db.commit()
    db.refresh(user)
    return user
