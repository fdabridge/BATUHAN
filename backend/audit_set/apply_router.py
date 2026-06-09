"""
BATUHAN — Public client application form router.
POST /apply — no authentication required.
"""
from __future__ import annotations
import secrets
import string

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session
from sqlalchemy import func
from passlib.context import CryptContext

from audit_set.db_models import AuditSet, AuditSetStage, AuditSetStatusEvent, get_db as get_audit_db
from audit_set.service import _create_auto_stages
from auth.db_models import PlatformUser, get_db as get_auth_db
from email_service import send_client_welcome

router = APIRouter(prefix="/apply", tags=["application"])
pwd_ctx = CryptContext(schemes=["bcrypt"], deprecated="auto")

ALLOWED_STANDARDS = {"QMS", "EMS", "OHSMS", "FSMS", "ISMS", "MDQMS", "ABMS", "ENMS"}
ALLOWED_AUDIT_TYPES = {"initial", "surveillance", "recertification"}


class ClientApplicationSchema(BaseModel):
    # Company info
    company_name: str
    company_address: str
    city: str = ""
    country: str = ""
    phone: str = ""
    website: str = ""
    # Contact person
    representative_name: str          # becomes representative + client account full_name
    representative_email: str         # becomes client account email
    # Certification request
    standards: list[str]              # subset of ALLOWED_STANDARDS
    audit_type: str                   # "initial" | "surveillance" | "recertification"
    # Scope (simplified — CB will rewrite)
    scope_description: str = ""       # free text, what the company does
    # Personnel (rough)
    total_employees: int = 0
    has_additional_sites: bool = False
    additional_site_count: int = 0


def _generate_password(length: int = 12) -> str:
    alphabet = string.ascii_letters + string.digits
    return ''.join(secrets.choice(alphabet) for _ in range(length))


@router.post("")
def submit_application(
    payload: ClientApplicationSchema,
    audit_db: Session = Depends(get_audit_db),
    auth_db: Session = Depends(get_auth_db),
):
    # Validate
    bad_standards = [s for s in payload.standards if s not in ALLOWED_STANDARDS]
    if bad_standards:
        raise HTTPException(400, f"Unknown standards: {bad_standards}")
    if payload.audit_type not in ALLOWED_AUDIT_TYPES:
        raise HTTPException(400, f"Invalid audit_type: {payload.audit_type}")
    if not payload.standards:
        raise HTTPException(400, "At least one standard is required")

    # Check email not already registered
    existing = auth_db.query(PlatformUser).filter_by(
        email=payload.representative_email
    ).first()
    if existing:
        # Allow re-application if the linked audit set has been deleted
        # (common during testing / cancelled applications). Otherwise block.
        if existing.audit_set_id:
            linked_set = audit_db.query(AuditSet).filter_by(id=existing.audit_set_id).first()
            if linked_set:
                raise HTTPException(
                    409,
                    "An account with this email already exists. "
                    "Please log in to your client portal, or contact IFC Global if you need help.",
                )
        # Stale user with no valid audit set — clean it up and proceed
        auth_db.delete(existing)
        auth_db.commit()

    # Compute next plan_number (matches service-layer convention: COALESCE(MAX, 1599) + 1)
    max_plan = audit_db.query(func.max(AuditSet.plan_number)).scalar() or 1599
    plan_number = max_plan + 1

    # Build sites list from has_additional_sites
    sites = []
    if payload.has_additional_sites and payload.additional_site_count > 0:
        for _ in range(payload.additional_site_count):
            sites.append({"address": "", "process": "", "employee_count": 0})

    # Create AuditSet
    audit_set = AuditSet(
        plan_number=plan_number,
        company_name=payload.company_name,
        company_address=payload.company_address,
        city=payload.city,
        country=payload.country,
        phone=payload.phone,
        website=payload.website,
        representative=payload.representative_name,
        email=payload.representative_email,
        standards=payload.standards,
        audit_type=payload.audit_type,
        scope_en=payload.scope_description,
        scope_tr="",
        accreditation_body="UAF",
        status="draft",
        workflow_status="pending_review",
        submitted_via_portal=True,
        personnel={
            "full_time": payload.total_employees,
            "part_time": 0, "subcontractors": 0,
            "seasonal": 0, "unskilled": 0,
            "shift_count": 1, "shift_same_process": False,
            "repetitive_roles": [],
        },
        sites=sites,
    )
    audit_db.add(audit_set)
    audit_db.flush()   # get audit_set.id

    # Auto-create stages so the CB stage-planning panel renders immediately
    _create_auto_stages(audit_db, audit_set, None)

    # Log status event
    event = AuditSetStatusEvent(
        audit_set_id=audit_set.id,
        from_status=None,
        to_status="pending_review",
        triggered_by="client_portal",
        notes="Application submitted via client portal",
    )
    audit_db.add(event)

    # Create client PlatformUser
    temp_password = _generate_password()
    user = PlatformUser(
        email=payload.representative_email,
        password_hash=pwd_ctx.hash(temp_password),
        full_name=payload.representative_name,
        role="client",
        is_active=True,
        audit_set_id=audit_set.id,
    )
    auth_db.add(user)

    # Commit both DBs
    audit_db.commit()
    audit_db.refresh(audit_set)
    auth_db.commit()

    # Send welcome email (non-blocking — failure doesn't roll back)
    send_client_welcome(
        to=payload.representative_email,
        full_name=payload.representative_name,
        temp_password=temp_password,
        audit_set_id=audit_set.id,
    )

    return {
        "success": True,
        "message": "Application submitted successfully. Check your email for login credentials.",
        "plan_number": plan_number,
    }
