"""
BATUHAN — Public client application form router.
POST /apply — no authentication required.
"""
from __future__ import annotations
from dataclasses import dataclass
import mimetypes
from pathlib import Path
import re
import secrets
import string
import uuid

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from pydantic import BaseModel, ValidationError
from typing import Optional
from sqlalchemy.orm import Session
from sqlalchemy import func
from passlib.context import CryptContext

from audit_set.db_models import (
    AuditSet,
    AuditSetCompanyDocument,
    AuditSetStage,
    AuditSetStatusEvent,
    get_db as get_audit_db,
)
from audit_set.service import _create_auto_stages
from auth.db_models import PlatformUser, get_db as get_auth_db
from auth.policy import CLIENT_EMAIL_VERIFICATION, policy_enabled
from auth.otp import generate_otp
from email_service import send_client_welcome, send_otp_code
from storage.document_store import delete as store_delete, upload as store_upload

router = APIRouter(prefix="/apply", tags=["application"])
pwd_ctx = CryptContext(schemes=["bcrypt"], deprecated="auto")

ALLOWED_STANDARDS = {"QMS", "EMS", "OHSMS", "FSMS", "ISMS", "MDQMS", "ABMS", "ENMS"}
ALLOWED_AUDIT_TYPES = {"initial", "surveillance_1", "surveillance_2", "recertification"}
ALLOWED_COMPANY_DOCUMENT_EXTENSIONS = {
    ".pdf",
    ".doc",
    ".docx",
    ".xls",
    ".xlsx",
    ".ppt",
    ".pptx",
    ".png",
    ".jpg",
    ".jpeg",
    ".txt",
    ".csv",
}
MAX_COMPANY_DOCUMENTS = 20
MAX_COMPANY_DOCUMENT_BYTES = 25 * 1024 * 1024
MAX_COMPANY_DOCUMENT_TOTAL_BYTES = 100 * 1024 * 1024


@dataclass(frozen=True)
class CompanyDocumentUpload:
    file_name: str
    content_type: str
    content: bytes


class SiteDetailInput(BaseModel):
    name: str = ""
    address: str = ""
    employee_count: int = 0
    process: str = ""


class ClientApplicationSchema(BaseModel):
    # ── Company info ──────────────────────────────────────────────────────
    company_name: str
    company_address: str
    city: str = ""
    country: str = ""
    phone: str = ""
    website: str = ""

    # ── Contact person ────────────────────────────────────────────────────
    representative_name: str          # becomes representative + client account full_name
    representative_email: str         # becomes client account email

    # ── Certification request ─────────────────────────────────────────────
    standards: list[str]              # subset of ALLOWED_STANDARDS
    audit_type: str                   # "initial" | "surveillance_1" | "surveillance_2" | "recertification"
    is_transfer: bool = False

    # ── Scope ─────────────────────────────────────────────────────────────
    scope_description: str = ""

    # ── Personnel — IAF MD5 breakdown ─────────────────────────────────────
    full_time_employees: int = 0           # permanent full-time workforce
    part_time_employees: int = 0           # part-time employees (will be × 0.5 FTE)
    subcontractor_employees: int = 0       # subcontractors (in scope of certification)
    seasonal_employees: int = 0            # seasonal workforce at peak
    shift_count: int = 1                   # number of production shifts
    shift_same_process: bool = False       # same work repeated across shifts

    # Legacy field — still accepted; used if full_time_employees is 0
    total_employees: int = 0

    # ── Additional sites ──────────────────────────────────────────────────
    has_additional_sites: bool = False
    additional_site_count: int = 0
    site_details: list[SiteDetailInput] = []

    # ── ISO 50001 — EnMS energy profile ──────────────────────────────────
    enms_annual_energy_tj: Optional[float] = None
    enms_num_energy_types: Optional[int] = None
    enms_num_seus: Optional[int] = None

    # ── ISO 22000 / FSSC 22000 — FSMS ────────────────────────────────────
    fsms_food_chain_categories: list[str] = []
    fsms_haccp_studies: Optional[int] = None
    fsms_offsite_storage_count: int = 0
    fsms_separate_head_office: bool = False
    fsms_fssc22000: bool = False
    fsms_seasonal_production: bool = False

    # ── ISO 27001 — ISMS ─────────────────────────────────────────────────
    isms_technical_area: Optional[str] = None   # "A" | "B" | "C" | "D"
    isms_data_role: Optional[str] = None        # "Controller" | "Processor" | "Both"

    # ── ISO 13485 — MDQMS ────────────────────────────────────────────────
    mdqms_device_classes: list[str] = []

    # ── Consultant referral ───────────────────────────────────────────────────
    consultant_code: Optional[str] = None   # consultant's username; looked up on submit


def _generate_password(length: int = 12) -> str:
    alphabet = string.ascii_letters + string.digits
    return ''.join(secrets.choice(alphabet) for _ in range(length))


def _safe_storage_name(file_name: str) -> str:
    base_name = Path(file_name).name.strip()
    clean_name = re.sub(r"[^A-Za-z0-9._ -]", "_", base_name)
    return clean_name[:180] or "document"


async def _read_company_documents(
    uploads: list[UploadFile],
) -> list[CompanyDocumentUpload]:
    if len(uploads) > MAX_COMPANY_DOCUMENTS:
        raise HTTPException(
            400,
            f"A maximum of {MAX_COMPANY_DOCUMENTS} company documents can be uploaded.",
        )

    documents: list[CompanyDocumentUpload] = []
    total_bytes = 0
    for upload in uploads:
        file_name = Path((upload.filename or "").replace("\\", "/")).name.strip()
        if not file_name:
            raise HTTPException(400, "Every company document must have a file name.")
        extension = Path(file_name).suffix.lower()
        if extension not in ALLOWED_COMPANY_DOCUMENT_EXTENSIONS:
            raise HTTPException(
                400,
                f"Unsupported company document type for '{file_name}'.",
            )

        content = await upload.read(MAX_COMPANY_DOCUMENT_BYTES + 1)
        if not content:
            raise HTTPException(400, f"Company document '{file_name}' is empty.")
        if len(content) > MAX_COMPANY_DOCUMENT_BYTES:
            raise HTTPException(
                413,
                f"Company document '{file_name}' exceeds the 25 MB limit.",
            )
        total_bytes += len(content)
        if total_bytes > MAX_COMPANY_DOCUMENT_TOTAL_BYTES:
            raise HTTPException(
                413,
                "The combined company document upload exceeds the 100 MB limit.",
            )
        documents.append(
            CompanyDocumentUpload(
                file_name=file_name,
                # Derive the served type from the allowed extension instead of
                # trusting the caller-provided multipart Content-Type header.
                content_type=(
                    mimetypes.guess_type(file_name)[0]
                    or "application/octet-stream"
                ),
                content=content,
            )
        )
    return documents


def _submit_application(
    payload: ClientApplicationSchema,
    audit_db: Session,
    auth_db: Session,
    company_documents: list[CompanyDocumentUpload] | None = None,
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

    # Resolve consultant by username (case-insensitive) if a code was supplied
    consultant_id: str | None = None
    if payload.consultant_code:
        consultant_user = (
            auth_db.query(PlatformUser)
            .filter(
                PlatformUser.role == "consultant",
                PlatformUser.is_active == True,
                PlatformUser.username == payload.consultant_code.strip(),
            )
            .first()
        )
        if not consultant_user:
            raise HTTPException(400, f"Consultant code '{payload.consultant_code}' not recognised.")
        consultant_id = consultant_user.id

    # Compute next plan_number (matches service-layer convention: COALESCE(MAX, 1599) + 1)
    max_plan = audit_db.query(func.max(AuditSet.plan_number)).scalar() or 1599
    plan_number = max_plan + 1

    # Build sites list — prefer detailed entries, fall back to count-only stubs
    sites: list[dict] = []
    if payload.site_details:
        sites = [
            {
                "name":           s.name,
                "address":        s.address,
                "employee_count": s.employee_count,
                "process":        s.process,
            }
            for s in payload.site_details
        ]
    elif payload.has_additional_sites and payload.additional_site_count > 0:
        # Legacy fallback — old clients without per-site detail
        sites = [
            {"name": f"Site {i + 1}", "address": "", "employee_count": 0, "process": ""}
            for i in range(payload.additional_site_count)
        ]

    # Resolve effective full-time count (new fields take priority over legacy total_employees)
    ft = payload.full_time_employees or payload.total_employees
    pt = payload.part_time_employees
    sub = payload.subcontractor_employees
    seas = payload.seasonal_employees

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
        is_transfer=payload.is_transfer,
        scope_en=payload.scope_description,
        scope_tr="",
        accreditation_body="UAF",
        status="draft",
        workflow_status="pending_review",
        submitted_via_portal=True,
        consultant_id=consultant_id,
        personnel={
            "full_time":      ft,
            "part_time":      pt,
            "subcontractors": sub,
            "seasonal":       seas,
            "unskilled":      0,
            "shift_count":    payload.shift_count,
            "shift_same_process": payload.shift_same_process,
            "repetitive_roles": [],
        },
        sites=sites,
        application_data={
            "enms_annual_energy_tj":      payload.enms_annual_energy_tj,
            "enms_num_energy_types":      payload.enms_num_energy_types,
            "enms_num_seus":              payload.enms_num_seus,
            "fsms_food_chain_categories": payload.fsms_food_chain_categories,
            "fsms_haccp_studies":         payload.fsms_haccp_studies,
            "fsms_offsite_storage_count": payload.fsms_offsite_storage_count,
            "fsms_separate_head_office":  payload.fsms_separate_head_office,
            "fsms_fssc22000":             payload.fsms_fssc22000,
            "fsms_seasonal_production":   payload.fsms_seasonal_production,
            "isms_technical_area":        payload.isms_technical_area,
            "isms_data_role":             payload.isms_data_role,
            "mdqms_device_classes":       payload.mdqms_device_classes,
            "part_time_fte_factor":       0.5,
            "subcontractors_in_scope":    True,
        },
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
        username=payload.representative_email,
        password_hash=pwd_ctx.hash(temp_password),
        full_name=payload.representative_name,
        role="client",
        is_active=True,
        is_activated=not policy_enabled(auth_db, CLIENT_EMAIL_VERIFICATION),
        audit_set_id=audit_set.id,
    )
    auth_db.add(user)

    # Persist application evidence before the application becomes visible to
    # planners. The metadata row and audit-set row are committed together.
    stored_refs: list[str] = []
    try:
        auth_db.flush()  # assign the client user id for uploader traceability
        for document in company_documents or []:
            document_id = str(uuid.uuid4())
            relative_path = (
                f"company_documents/{audit_set.id}/{document_id}/"
                f"{_safe_storage_name(document.file_name)}"
            )
            storage_ref = store_upload(
                relative_path,
                document.content,
                content_type=document.content_type,
            )
            stored_refs.append(storage_ref)
            audit_db.add(
                AuditSetCompanyDocument(
                    id=document_id,
                    audit_set_id=audit_set.id,
                    file_path=storage_ref,
                    file_name=document.file_name,
                    file_type=document.content_type,
                    file_size=len(document.content),
                    uploader_user_id=user.id,
                    uploader_name=payload.representative_name,
                    uploader_role="client",
                )
            )
        audit_db.commit()
    except Exception as exc:
        audit_db.rollback()
        auth_db.rollback()
        for storage_ref in stored_refs:
            try:
                store_delete(storage_ref)
            except Exception:
                pass
        if isinstance(exc, HTTPException):
            raise
        raise HTTPException(
            500,
            "The application documents could not be stored. No application was submitted.",
        ) from exc

    audit_db.refresh(audit_set)
    auth_db.commit()

    # Send welcome email — best-effort; a Resend outage must not fail the submission.
    try:
        send_client_welcome(
            to=payload.representative_email,
            full_name=payload.representative_name,
            temp_password=temp_password,
            audit_set_id=audit_set.id,
        )
    except Exception:
        pass

    # New verified-mode accounts receive an activation code immediately. If
    # delivery is temporarily unavailable they can request a fresh code from
    # the activation screen after logging in.
    if not user.is_activated:
        try:
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
                auth_db.commit()
        except Exception:
            pass

    return {
        "success":      True,
        "message":      "Application submitted successfully.",
        "plan_number":  plan_number,
        "username":     payload.representative_email,
        "temp_password": temp_password,
    }


@router.post("")
def submit_application(
    payload: ClientApplicationSchema,
    audit_db: Session = Depends(get_audit_db),
    auth_db: Session = Depends(get_auth_db),
):
    """Backward-compatible JSON submission for applications without files."""
    return _submit_application(payload, audit_db, auth_db)


@router.post("/with-documents")
async def submit_application_with_documents(
    application: str = Form(...),
    company_documents: list[UploadFile] = File(default=[]),
    audit_db: Session = Depends(get_audit_db),
    auth_db: Session = Depends(get_auth_db),
):
    """Submit an application and its final, client-selected document set."""
    try:
        payload = ClientApplicationSchema.model_validate_json(application)
    except ValidationError as exc:
        raise HTTPException(422, detail=exc.errors()) from exc
    documents = await _read_company_documents(company_documents)
    return _submit_application(payload, audit_db, auth_db, documents)


@router.get("/consultants")
def list_consultants(auth_db: Session = Depends(get_auth_db)):
    """
    Public endpoint — returns active consultants so the apply form
    can populate a dropdown. Returns only id, full_name, username.
    No authentication required (apply form is public).
    """
    consultants = (
        auth_db.query(PlatformUser)
        .filter(PlatformUser.role == "consultant", PlatformUser.is_active == True)
        .order_by(PlatformUser.full_name)
        .all()
    )
    return [
        {"id": c.id, "full_name": c.full_name, "username": c.username}
        for c in consultants
    ]
