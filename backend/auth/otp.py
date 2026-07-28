"""Shared secure OTP primitives for email verification gates."""
from __future__ import annotations

import hashlib
import hmac
import secrets
from datetime import datetime, timedelta

OTP_EXPIRY_MINUTES = 10
OTP_MAX_ATTEMPTS = 5


def generate_otp() -> tuple[str, str, datetime]:
    """Return plaintext code, SHA-256 hash and expiry timestamp."""
    code = f"{secrets.randbelow(1_000_000):06d}"
    return code, hash_otp(code), datetime.utcnow() + timedelta(minutes=OTP_EXPIRY_MINUTES)


def hash_otp(code: str) -> str:
    return hashlib.sha256(code.strip().encode("utf-8")).hexdigest()


def otp_matches(code: str, expected_hash: str | None) -> bool:
    if not expected_hash:
        return False
    return hmac.compare_digest(hash_otp(code), expected_hash)
