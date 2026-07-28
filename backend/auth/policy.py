"""Runtime platform policy stored in the auth database.

Policy reads happen at request time so an admin change applies to the next
action without a process restart. Defaults intentionally preserve the
configured Try Certiva behaviour described by the policy specification.
"""
from __future__ import annotations

from datetime import date, datetime
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from sqlalchemy.orm import Session

CLIENT_EMAIL_VERIFICATION = "client_email_verification"
EMPLOYEE_SIGNATURE_EMAIL_VERIFICATION = "employee_signature_email_verification"
RETROACTIVE_SIGNING_DATES = "retroactive_signing_dates"

DEFAULT_POLICY: dict[str, bool] = {
    CLIENT_EMAIL_VERIFICATION: True,
    EMPLOYEE_SIGNATURE_EMAIL_VERIFICATION: True,
    RETROACTIVE_SIGNING_DATES: True,
}


def get_policy(db: Session) -> dict[str, bool]:
    """Return all policy values, creating any newly introduced defaults."""
    from auth.db_models import PlatformPolicy
    rows = {row.key: row for row in db.query(PlatformPolicy).all()}
    changed = False
    for key, default in DEFAULT_POLICY.items():
        if key not in rows:
            row = PlatformPolicy(key=key, enabled=default)
            db.add(row)
            rows[key] = row
            changed = True
    if changed:
        db.commit()
    return {key: bool(rows[key].enabled) for key in DEFAULT_POLICY}


def policy_enabled(db: Session, key: str) -> bool:
    """Read one current policy value."""
    from auth.db_models import PlatformPolicy
    if key not in DEFAULT_POLICY:
        raise KeyError(f"Unknown platform policy: {key}")
    row = db.query(PlatformPolicy).filter_by(key=key).first()
    if row is None:
        row = PlatformPolicy(key=key, enabled=DEFAULT_POLICY[key])
        db.add(row)
        db.commit()
        db.refresh(row)
    return bool(row.enabled)


def update_policy(
    db: Session,
    values: dict[str, bool],
    *,
    updated_by: str | None,
) -> dict[str, bool]:
    """Persist a complete or partial policy update."""
    from auth.db_models import PlatformPolicy
    unknown = set(values) - set(DEFAULT_POLICY)
    if unknown:
        raise KeyError(f"Unknown platform policies: {sorted(unknown)}")

    current = {
        row.key: row
        for row in db.query(PlatformPolicy)
        .filter(PlatformPolicy.key.in_(list(DEFAULT_POLICY)))
        .all()
    }
    now = datetime.utcnow()
    for key, default in DEFAULT_POLICY.items():
        row = current.get(key)
        if row is None:
            row = PlatformPolicy(key=key, enabled=default)
            db.add(row)
            current[key] = row
        if key in values:
            row.enabled = bool(values[key])
            row.updated_at = now
            row.updated_by = updated_by
    db.commit()
    return get_policy(db)


def resolve_realtime_action_datetime(
    db: Session,
    requested_date: date | datetime | None,
) -> datetime:
    """Resolve a real-time action timestamp under the current policy.

    This helper must not be used for audit scheduling, certification cycles,
    certificate validity, application dates, or other business/planning dates.
    """
    if policy_enabled(db, RETROACTIVE_SIGNING_DATES) and requested_date:
        if isinstance(requested_date, datetime):
            return requested_date
        return datetime.combine(requested_date, datetime.min.time())
    return datetime.utcnow()
