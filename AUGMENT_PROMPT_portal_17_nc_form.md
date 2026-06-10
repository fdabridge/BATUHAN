# AUGMENT PROMPT — Portal 17: FR.230 NC Form (Two-Party Signing) + FR.223 Backend Fix

## Context
Certiva — FastAPI backend + Next.js 14 App Router frontend.
**DO NOT BREAK THE EXISTING PORTAL. All changes are additive unless explicitly listed.**

Two things in this prompt:

**Fix (required):** FR.223 backend allowlist is missing `audit_plan`.
`documents_router.py` currently has `ALLOWED_DOC_TYPES = {"quotation", "agreement", "certificate"}`.
Releasing an audit_plan document returns HTTP 400. Add `"audit_plan"` to this set and remove `"nc_form"` from the frontend dropdown (NC form has its own dedicated flow below).

**Main feature:** FR.230 — Nonconformity Notification Form.
Two-party, strict order:
1. Lead Auditor signs first (from auditor portal)
2. Client counter-signs (from client portal, only visible after LA signs)

NC form is a file uploaded by CB staff. It is NOT part of the SharedDocument release flow —
it has its own upload endpoint and its own table.

---

## What this builds

**Backend:**
1. `AuditSetNCForm` table in `db_models.py`
2. New `nc_router.py` — CB upload + CB view + auditor signing + client signing + download
3. Two new email functions in `email_service.py`
4. One-line fix in `documents_router.py` (ALLOWED_DOC_TYPES)
5. Register `nc_router` in `main.py`

**Frontend:**
6. Remove `nc_form` from DOC_TYPES in `SharedDocumentsSection.tsx`
7. New `NCFormManagementSection.tsx` (CB portal `/clients/[id]`)
8. New "NC Forms" tab in auditor portal `/auditor/audit/[id]/page.tsx`
9. New `NCFormClientSection` component added to client portal `/client/documents/page.tsx`
10. Wire `NCFormManagementSection` into `(app)/clients/[id]/page.tsx`

---

## Backend

### 1. `backend/audit_set/db_models.py` — add `AuditSetNCForm`

Add after `AuditSetAuditorAssessment` (or at the end of the file):

```python
# ---------------------------------------------------------------------------
# Table 10 — audit_set_nc_forms
# FR.230 — Nonconformity Notification Form.
# Two-party signing: Lead Auditor signs first, then client counter-signs.
# ---------------------------------------------------------------------------

class AuditSetNCForm(Base):
    __tablename__ = "audit_set_nc_forms"

    id           = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    audit_set_id = Column(String, ForeignKey("audit_sets.id", ondelete="CASCADE"), nullable=False)
    stage_type   = Column(String, nullable=False)   # "stage_1" | "stage_2" | "surveillance" etc.
    label        = Column(String, nullable=False)   # NC reference / short description
    file_path    = Column(String, nullable=False)   # disk path, same storage_base_path convention
    file_name    = Column(String, nullable=True)    # original filename for Content-Disposition

    # ── Lead Auditor signature (party 1) ───────────────────────────────────
    la_user_id      = Column(String, nullable=True)  # PlatformUser.id (resolved at sign time)
    la_signed_at    = Column(DateTime, nullable=True)
    la_signed_ip    = Column(String, nullable=True)
    la_otp_hash     = Column(String, nullable=True)
    la_otp_expires  = Column(DateTime, nullable=True)

    # ── Client signature (party 2) ─────────────────────────────────────────
    client_user_id  = Column(String, nullable=True)
    client_signed_at  = Column(DateTime, nullable=True)
    client_signed_ip  = Column(String, nullable=True)
    client_otp_hash   = Column(String, nullable=True)
    client_otp_expires = Column(DateTime, nullable=True)

    # ── Status ─────────────────────────────────────────────────────────────
    # "pending_la"     → awaiting Lead Auditor signature
    # "pending_client" → LA signed; awaiting client counter-signature
    # "complete"       → both signed
    status       = Column(String, default="pending_la", nullable=False)

    created_by   = Column(String, nullable=True)   # CB user who uploaded
    created_at   = Column(DateTime, default=datetime.utcnow, nullable=False)
```

No `_safe_add_column` needed — created by `Base.metadata.create_all` on boot.

---

### 2. New file `backend/audit_set/nc_router.py`

```python
"""
BATUHAN — FR.230 NC Form Two-Party Signing (Prompt 17).

Upload:  CB uploads the NC form file → status=pending_la
Sign 1:  Lead Auditor signs via OTP (auditor portal) → status=pending_client
Sign 2:  Client counter-signs via OTP (client portal) → status=complete

Routes:
  POST /audit-sets/{id}/nc-forms/upload          (CB admin/planner — multipart)
  GET  /audit-sets/{id}/nc-forms                 (CB + auditor — list all for this audit set)
  GET  /audit-sets/{id}/nc-forms/{nid}/download  (CB + auditor + client after pending_client)
  POST /audit-sets/{id}/nc-forms/{nid}/sign/la/request-otp  (auditor only)
  POST /audit-sets/{id}/nc-forms/{nid}/sign/la/verify       (auditor only)
  GET  /client/my-audit-set/nc-forms             (client only)
  GET  /client/my-audit-set/nc-forms/{nid}/download  (client only, pending_client+)
  POST /client/my-audit-set/nc-forms/{nid}/sign/request-otp  (client only)
  POST /client/my-audit-set/nc-forms/{nid}/sign/verify       (client only)
"""
from __future__ import annotations
import hashlib
import os
import secrets
from datetime import datetime, timedelta

from fastapi import APIRouter, Depends, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session

from audit_set.db_models import AuditSet, AuditSetNCForm, AuditSetStage, get_db
from auth.db_models import PlatformUser, get_db as get_auth_db
from auth.dependencies import get_current_user
from config.settings import get_settings
from email_service import (
    send_nc_form_la_request,
    send_nc_form_client_ready,
    send_otp_code,
)

router = APIRouter(tags=["nc_forms"])

CB_ROLES     = {"admin", "planner", "officer", "executive"}
OTP_EXPIRY   = 10  # minutes


def _hash(val: str) -> str:
    return hashlib.sha256(val.encode()).hexdigest()


def _nc_dict(n: AuditSetNCForm, include_paths: bool = False) -> dict:
    return {
        "id":              n.id,
        "audit_set_id":    n.audit_set_id,
        "stage_type":      n.stage_type,
        "label":           n.label,
        "file_name":       n.file_name,
        "status":          n.status,
        "la_signed_at":    n.la_signed_at.isoformat() if n.la_signed_at else None,
        "client_signed_at":n.client_signed_at.isoformat() if n.client_signed_at else None,
        "created_at":      n.created_at.isoformat() if n.created_at else None,
    }


def _get_lead_auditor_user(
    db: Session,
    auth_db: Session,
    audit_set_id: str,
    stage_type: str,
) -> PlatformUser | None:
    """Look up the PlatformUser who is the Lead Auditor for this stage."""
    stage = (
        db.query(AuditSetStage)
        .filter_by(audit_set_id=audit_set_id, stage_type=stage_type)
        .order_by(AuditSetStage.stage_order)
        .first()
    )
    if not stage or not stage.lead_auditor_id:
        return None
    return auth_db.query(PlatformUser).filter_by(auditor_id=stage.lead_auditor_id).first()


# ── CB: upload NC form ────────────────────────────────────────────────────────

@router.post("/audit-sets/{audit_set_id}/nc-forms/upload")
async def upload_nc_form(
    audit_set_id: str,
    stage_type: str = Form(...),
    label:      str = Form(...),
    file: UploadFile = File(...),
    db:       Session = Depends(get_db),
    auth_db:  Session = Depends(get_auth_db),
    current_user: PlatformUser = Depends(get_current_user),
):
    """CB uploads the NC form file. Notifies the Lead Auditor by email."""
    if current_user.role not in {"admin", "planner"}:
        raise HTTPException(403, "Not authorized")

    audit_set = db.query(AuditSet).filter_by(id=audit_set_id).first()
    if not audit_set:
        raise HTTPException(404, "Audit set not found")

    settings = get_settings()
    upload_dir = os.path.join(settings.storage_base_path, "nc_forms", audit_set_id)
    os.makedirs(upload_dir, exist_ok=True)

    safe_name = f"{secrets.token_hex(6)}_{file.filename or 'nc_form'}"
    file_path = os.path.join(upload_dir, safe_name)
    content   = await file.read()
    with open(file_path, "wb") as fh:
        fh.write(content)

    nc = AuditSetNCForm(
        audit_set_id=audit_set_id,
        stage_type=stage_type,
        label=label.strip(),
        file_path=file_path,
        file_name=file.filename or safe_name,
        status="pending_la",
        created_by=current_user.id,
    )
    db.add(nc)
    db.commit()
    db.refresh(nc)

    # Notify Lead Auditor
    la_user = _get_lead_auditor_user(db, auth_db, audit_set_id, stage_type)
    if la_user:
        try:
            send_nc_form_la_request(
                to=la_user.email,
                full_name=la_user.full_name,
                company_name=audit_set.company_name,
                stage_label=stage_type.replace("_", " ").title(),
                nc_label=label,
            )
        except Exception:
            pass

    return _nc_dict(nc)


# ── CB + Auditor: list and download ──────────────────────────────────────────

@router.get("/audit-sets/{audit_set_id}/nc-forms")
def list_nc_forms(
    audit_set_id: str,
    db: Session = Depends(get_db),
    current_user: PlatformUser = Depends(get_current_user),
):
    if current_user.role not in CB_ROLES | {"auditor"}:
        raise HTTPException(403, "Not authorized")
    rows = (
        db.query(AuditSetNCForm)
        .filter_by(audit_set_id=audit_set_id)
        .order_by(AuditSetNCForm.created_at)
        .all()
    )
    return [_nc_dict(r) for r in rows]


@router.get("/audit-sets/{audit_set_id}/nc-forms/{nid}/download")
def download_nc_form(
    audit_set_id: str,
    nid: str,
    db: Session = Depends(get_db),
    current_user: PlatformUser = Depends(get_current_user),
):
    nc = db.query(AuditSetNCForm).filter_by(id=nid, audit_set_id=audit_set_id).first()
    if not nc:
        raise HTTPException(404, "NC form not found")

    if current_user.role not in CB_ROLES | {"auditor"}:
        raise HTTPException(403, "Not authorized")

    if not nc.file_path or not os.path.exists(nc.file_path):
        raise HTTPException(404, "File not found on server")

    return FileResponse(
        nc.file_path,
        filename=nc.file_name or "nc_form.docx",
        media_type="application/octet-stream",
    )


# ── Auditor (Lead Auditor): sign party 1 ─────────────────────────────────────

def _check_la_authorization(
    nc: AuditSetNCForm,
    current_user: PlatformUser,
    db: Session,
) -> None:
    """Raise 403 if current_user is not the Lead Auditor for nc.stage_type."""
    if current_user.role != "auditor":
        raise HTTPException(403, "Auditor access only")
    if not current_user.auditor_id:
        raise HTTPException(403, "No auditor profile linked to your account")
    stage = (
        db.query(AuditSetStage)
        .filter_by(audit_set_id=nc.audit_set_id, stage_type=nc.stage_type)
        .order_by(AuditSetStage.stage_order)
        .first()
    )
    if not stage:
        raise HTTPException(404, "Stage not found")
    if stage.lead_auditor_id != current_user.auditor_id:
        raise HTTPException(403, "Only the Lead Auditor for this stage may sign the NC form")


@router.post("/audit-sets/{audit_set_id}/nc-forms/{nid}/sign/la/request-otp")
def la_request_otp(
    audit_set_id: str,
    nid: str,
    db:       Session = Depends(get_db),
    auth_db:  Session = Depends(get_auth_db),
    current_user: PlatformUser = Depends(get_current_user),
):
    nc = db.query(AuditSetNCForm).filter_by(id=nid, audit_set_id=audit_set_id).first()
    if not nc:
        raise HTTPException(404, "NC form not found")
    _check_la_authorization(nc, current_user, db)
    if nc.la_signed_at:
        raise HTTPException(400, "Already signed")

    otp            = f"{secrets.randbelow(900000) + 100000}"
    nc.la_otp_hash    = _hash(otp)
    nc.la_otp_expires = datetime.utcnow() + timedelta(minutes=OTP_EXPIRY)
    db.commit()

    try:
        send_otp_code(
            to=current_user.email,
            full_name=current_user.full_name,
            otp=otp,
            document_label=f"NC Form — {nc.label}",
        )
    except Exception:
        pass

    return {"message": f"Code sent to {current_user.email}. Valid for {OTP_EXPIRY} minutes."}


@router.post("/audit-sets/{audit_set_id}/nc-forms/{nid}/sign/la/verify")
def la_verify_otp(
    audit_set_id: str,
    nid: str,
    otp: str,
    request: Request,
    db:       Session = Depends(get_db),
    auth_db:  Session = Depends(get_auth_db),
    current_user: PlatformUser = Depends(get_current_user),
):
    nc = db.query(AuditSetNCForm).filter_by(id=nid, audit_set_id=audit_set_id).first()
    if not nc:
        raise HTTPException(404, "NC form not found")
    _check_la_authorization(nc, current_user, db)
    if nc.la_signed_at:
        raise HTTPException(400, "Already signed")
    if not nc.la_otp_hash or not nc.la_otp_expires:
        raise HTTPException(400, "No pending OTP. Request one first.")
    if datetime.utcnow() > nc.la_otp_expires:
        raise HTTPException(400, "OTP expired. Please request a new one.")
    if _hash(otp.strip()) != nc.la_otp_hash:
        raise HTTPException(400, "Invalid code.")

    nc.la_user_id   = current_user.id
    nc.la_signed_at = datetime.utcnow()
    nc.la_signed_ip = request.client.host if request.client else None
    nc.la_otp_hash  = None
    nc.la_otp_expires = None
    nc.status       = "pending_client"
    db.commit()

    # Notify client that NC form is ready for counter-signature
    audit_set = db.query(AuditSet).filter_by(id=audit_set_id).first()
    client_user = auth_db.query(PlatformUser).filter_by(
        audit_set_id=audit_set_id, role="client"
    ).first()
    if audit_set and client_user:
        try:
            send_nc_form_client_ready(
                to=client_user.email,
                full_name=client_user.full_name,
                company_name=audit_set.company_name,
                nc_label=nc.label,
            )
        except Exception:
            pass

    return {"signed": True, "status": "pending_client", "la_signed_at": nc.la_signed_at.isoformat()}


# ── Client: view, download, counter-sign ─────────────────────────────────────

def _get_client_nc(
    nid: str,
    current_user: PlatformUser,
    db: Session,
) -> AuditSetNCForm:
    if current_user.role != "client" or not current_user.audit_set_id:
        raise HTTPException(403, "Client access only")
    nc = db.query(AuditSetNCForm).filter_by(
        id=nid, audit_set_id=current_user.audit_set_id
    ).first()
    if not nc:
        raise HTTPException(404, "NC form not found")
    if nc.status == "pending_la":
        raise HTTPException(403, "Not yet available — awaiting auditor signature")
    return nc


@router.get("/client/my-audit-set/nc-forms")
def client_list_nc_forms(
    db: Session = Depends(get_db),
    current_user: PlatformUser = Depends(get_current_user),
):
    """Client sees NC forms once the Lead Auditor has signed (pending_client or complete)."""
    if current_user.role != "client" or not current_user.audit_set_id:
        raise HTTPException(403, "Client access only")
    rows = (
        db.query(AuditSetNCForm)
        .filter(
            AuditSetNCForm.audit_set_id == current_user.audit_set_id,
            AuditSetNCForm.status != "pending_la",
        )
        .order_by(AuditSetNCForm.created_at)
        .all()
    )
    return [_nc_dict(r) for r in rows]


@router.get("/client/my-audit-set/nc-forms/{nid}/download")
def client_download_nc_form(
    nid: str,
    db: Session = Depends(get_db),
    current_user: PlatformUser = Depends(get_current_user),
):
    nc = _get_client_nc(nid, current_user, db)
    if not nc.file_path or not os.path.exists(nc.file_path):
        raise HTTPException(404, "File not found on server")
    return FileResponse(
        nc.file_path,
        filename=nc.file_name or "nc_form.docx",
        media_type="application/octet-stream",
    )


@router.post("/client/my-audit-set/nc-forms/{nid}/sign/request-otp")
def client_nc_request_otp(
    nid: str,
    db:      Session = Depends(get_db),
    auth_db: Session = Depends(get_auth_db),
    current_user: PlatformUser = Depends(get_current_user),
):
    nc = _get_client_nc(nid, current_user, db)
    if nc.client_signed_at:
        raise HTTPException(400, "Already signed")

    otp = f"{secrets.randbelow(900000) + 100000}"
    nc.client_otp_hash    = _hash(otp)
    nc.client_otp_expires = datetime.utcnow() + timedelta(minutes=OTP_EXPIRY)
    db.commit()

    try:
        send_otp_code(
            to=current_user.email,
            full_name=current_user.full_name,
            otp=otp,
            document_label=f"NC Form — {nc.label}",
        )
    except Exception:
        pass

    return {"message": f"Code sent to {current_user.email}. Valid for {OTP_EXPIRY} minutes."}


@router.post("/client/my-audit-set/nc-forms/{nid}/sign/verify")
def client_nc_verify_otp(
    nid: str,
    otp: str,
    request: Request,
    db:      Session = Depends(get_db),
    current_user: PlatformUser = Depends(get_current_user),
):
    nc = _get_client_nc(nid, current_user, db)
    if nc.client_signed_at:
        raise HTTPException(400, "Already signed")
    if not nc.client_otp_hash or not nc.client_otp_expires:
        raise HTTPException(400, "No pending OTP. Request one first.")
    if datetime.utcnow() > nc.client_otp_expires:
        raise HTTPException(400, "OTP expired. Please request a new one.")
    if _hash(otp.strip()) != nc.client_otp_hash:
        raise HTTPException(400, "Invalid code.")

    nc.client_user_id    = current_user.id
    nc.client_signed_at  = datetime.utcnow()
    nc.client_signed_ip  = request.client.host if request.client else None
    nc.client_otp_hash   = None
    nc.client_otp_expires = None
    nc.status            = "complete"
    db.commit()

    return {"signed": True, "status": "complete", "client_signed_at": nc.client_signed_at.isoformat()}
```

---

### 3. `backend/email_service.py` — add two functions

Append before the final blank line:

```python
def send_nc_form_la_request(
    to: str,
    full_name: str,
    company_name: str,
    stage_label: str,
    nc_label: str,
) -> bool:
    """Sent to Lead Auditor when CB uploads an NC form requiring their signature."""
    settings = get_settings()
    html = f"""
    <div style="font-family:Arial,sans-serif;max-width:600px;margin:0 auto">
      <h2 style="color:#1A4731">IFC Global LLC — NC Form Signature Required</h2>
      <p>Dear {full_name},</p>
      <p>An NC Form has been uploaded for your signature for the audit of
         <strong>{company_name}</strong> ({stage_label}):</p>
      <div style="background:#f5f5f5;padding:16px;border-radius:6px;margin:16px 0">
        <strong>{nc_label}</strong>
      </div>
      <p>Please log in to the portal and navigate to the NC Forms tab in your audit
         assignment to review and sign.</p>
      <p><a href="{settings.email_base_url}/auditor/dashboard"
            style="background:#1A4731;color:white;padding:10px 20px;border-radius:4px;
                   text-decoration:none">Go to Portal</a></p>
      <p style="color:#666;font-size:12px">IFC Global LLC · application@ifcglobal.us</p>
    </div>
    """
    return _send(to, f"IFC Global — NC Form Signature Required: {company_name}", html)


def send_nc_form_client_ready(
    to: str,
    full_name: str,
    company_name: str,
    nc_label: str,
) -> bool:
    """Sent to client after Lead Auditor signs — NC form ready for counter-signature."""
    settings = get_settings()
    portal_url = f"{settings.email_base_url}/client/documents"
    html = f"""
    <div style="font-family:Arial,sans-serif;max-width:600px;margin:0 auto">
      <h2 style="color:#1A4731">IFC Global LLC — NC Form Ready for Your Signature</h2>
      <p>Dear {full_name},</p>
      <p>An NC Form related to your certification audit has been signed by the Lead Auditor
         and is now ready for your counter-signature:</p>
      <div style="background:#FFF3E0;padding:16px;border-radius:6px;margin:16px 0;
                  border-left:4px solid #E65100">
        <strong>{nc_label}</strong>
      </div>
      <p>Please log in to review the form and provide your signature.</p>
      <p><a href="{portal_url}"
            style="background:#1A4731;color:white;padding:10px 20px;border-radius:4px;
                   text-decoration:none">Review &amp; Sign</a></p>
      <p style="color:#666;font-size:12px">IFC Global LLC · application@ifcglobal.us</p>
    </div>
    """
    return _send(to, f"IFC Global — NC Form Ready for Counter-Signature", html)
```

---

### 4. `backend/audit_set/documents_router.py` — fix ALLOWED_DOC_TYPES

Find line 33:
```python
ALLOWED_DOC_TYPES = {"quotation", "agreement", "certificate"}
```
Replace with:
```python
ALLOWED_DOC_TYPES = {"quotation", "agreement", "certificate", "audit_plan"}
```
No other changes to this file. NC form documents go through `nc_router`, not this router.

---

### 5. `backend/main.py` — register router

```python
from audit_set.nc_router import router as nc_router
app.include_router(nc_router)
```

Place alongside the other audit_set routers.

---

## Frontend

### 6. `frontend/src/components/ui/SharedDocumentsSection.tsx` — remove nc_form

Find the `nc_form` entry in `DOC_TYPES` and remove it. Final array should be:

```tsx
const DOC_TYPES = [
  { value: 'quotation',   label: 'Quotation (FR.220)' },
  { value: 'agreement',   label: 'Agreement (FR.221)' },
  { value: 'audit_plan',  label: 'Audit Plan (FR.223)' },
  { value: 'certificate', label: 'Certificate' },
]
```

---

### 7. New file `frontend/src/components/ui/NCFormManagementSection.tsx`

CB portal view — upload and status tracking for NC forms.

```tsx
'use client'

import { useEffect, useRef, useState } from 'react'
import api from '@/lib/api'

interface NCForm {
  id:               string
  stage_type:       string
  label:            string
  file_name:        string | null
  status:           string
  la_signed_at:     string | null
  client_signed_at: string | null
  created_at:       string
}

const STAGE_OPTS = [
  { value: 'stage_1',         label: 'Stage 1' },
  { value: 'stage_2',         label: 'Stage 2' },
  { value: 'surveillance',    label: 'Surveillance' },
  { value: 'recertification', label: 'Recertification' },
]

const STATUS_CONFIG: Record<string, { label: string; chip: string }> = {
  pending_la:     { label: 'Awaiting Lead Auditor',  chip: 'bg-amber-100 text-amber-700' },
  pending_client: { label: 'Awaiting Client',         chip: 'bg-blue-100 text-blue-700' },
  complete:       { label: 'Complete',                chip: 'bg-green-100 text-green-700' },
}

function fmtDate(iso: string | null) {
  if (!iso) return ''
  return new Date(iso).toLocaleDateString('en-GB', { day: 'numeric', month: 'short', year: 'numeric' })
}

export function NCFormManagementSection({
  auditSetId,
  workflowStatus,
}: {
  auditSetId: string
  workflowStatus: string | null
}) {
  const [forms, setForms]       = useState<NCForm[]>([])
  const [loading, setLoading]   = useState(true)
  const [uploading, setUploading] = useState(false)
  const [showUpload, setShowUpload] = useState(false)
  const [stage, setStage]       = useState('stage_1')
  const [label, setLabel]       = useState('')
  const [file, setFile]         = useState<File | null>(null)
  const [uploadMsg, setUploadMsg] = useState('')
  const fileRef = useRef<HTMLInputElement>(null)

  // Show from audit_in_progress onwards
  const relevantStatuses = new Set([
    'audit_scheduled', 'audit_in_progress', 'under_review', 'certified',
  ])
  if (!workflowStatus || !relevantStatuses.has(workflowStatus)) return null

  async function load() {
    try {
      const r = await api.get<NCForm[]>(`/audit-sets/${auditSetId}/nc-forms`)
      setForms(r.data)
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => { load() }, [auditSetId])

  async function handleUpload(e: React.FormEvent) {
    e.preventDefault()
    if (!file || !label.trim()) return
    setUploading(true)
    setUploadMsg('')
    try {
      const form = new FormData()
      form.append('stage_type', stage)
      form.append('label', label.trim())
      form.append('file', file)
      await api.post(`/audit-sets/${auditSetId}/nc-forms/upload`, form, {
        headers: { 'Content-Type': 'multipart/form-data' },
      })
      setShowUpload(false)
      setLabel('')
      setFile(null)
      if (fileRef.current) fileRef.current.value = ''
      await load()
    } catch (err: unknown) {
      const detail = (err as { response?: { data?: { detail?: string } } })?.response?.data?.detail
      setUploadMsg(detail || 'Upload failed')
    } finally {
      setUploading(false)
    }
  }

  return (
    <div className="mt-6">
      <div className="mb-3 flex items-center justify-between">
        <h2 className="text-sm font-semibold uppercase tracking-wide text-gray-700">
          NC Forms (FR.230)
        </h2>
        <button
          type="button"
          onClick={() => { setShowUpload(!showUpload); setUploadMsg('') }}
          className="rounded-lg border border-[#1A4731] px-3 py-1.5 text-xs font-medium text-[#1A4731] hover:bg-green-50"
        >
          {showUpload ? 'Cancel' : '+ Upload NC Form'}
        </button>
      </div>

      {/* Upload form */}
      {showUpload && (
        <form
          onSubmit={handleUpload}
          className="mb-4 space-y-3 rounded-xl border border-amber-200 bg-amber-50 p-4"
        >
          <div className="grid grid-cols-2 gap-3">
            <div>
              <label className="mb-1 block text-xs font-medium text-gray-600">Stage</label>
              <select
                value={stage}
                onChange={e => setStage(e.target.value)}
                className="w-full rounded-lg border bg-white px-3 py-2 text-sm"
              >
                {STAGE_OPTS.map(s => (
                  <option key={s.value} value={s.value}>{s.label}</option>
                ))}
              </select>
            </div>
            <div>
              <label className="mb-1 block text-xs font-medium text-gray-600">NC Reference / Label</label>
              <input
                required
                value={label}
                onChange={e => setLabel(e.target.value)}
                placeholder="e.g. NC-001 Document Control"
                className="w-full rounded-lg border bg-white px-3 py-2 text-sm"
              />
            </div>
          </div>
          <div>
            <label className="mb-1 block text-xs font-medium text-gray-600">File</label>
            <input
              ref={fileRef}
              required
              type="file"
              onChange={e => setFile(e.target.files?.[0] || null)}
              className="text-sm"
            />
          </div>
          <button
            type="submit"
            disabled={uploading || !file || !label.trim()}
            className="rounded-lg bg-[#1A4731] px-4 py-2 text-sm text-white disabled:opacity-40"
          >
            {uploading ? 'Uploading…' : 'Upload & Notify Auditor'}
          </button>
          {uploadMsg && <p className="text-xs text-red-600">{uploadMsg}</p>}
        </form>
      )}

      {/* NC form list */}
      {loading ? (
        <p className="text-xs text-gray-400">Loading…</p>
      ) : forms.length === 0 ? (
        <div className="rounded-xl border bg-white px-4 py-6 text-center text-xs text-gray-400">
          No NC forms yet.
        </div>
      ) : (
        <div className="rounded-xl border bg-white divide-y divide-gray-50">
          {forms.map(f => {
            const cfg = STATUS_CONFIG[f.status] ?? { label: f.status, chip: 'bg-gray-100 text-gray-500' }
            return (
              <div key={f.id} className="flex items-center justify-between px-4 py-3">
                <div className="min-w-0">
                  <p className="text-sm font-medium text-gray-800 truncate">{f.label}</p>
                  <p className="mt-0.5 text-xs text-gray-400">
                    {STAGE_OPTS.find(s => s.value === f.stage_type)?.label ?? f.stage_type}
                    {f.la_signed_at && ` · LA signed ${fmtDate(f.la_signed_at)}`}
                    {f.client_signed_at && ` · Client signed ${fmtDate(f.client_signed_at)}`}
                  </p>
                </div>
                <span className={`ml-4 shrink-0 rounded-full px-2.5 py-0.5 text-xs font-semibold ${cfg.chip}`}>
                  {cfg.label}
                </span>
              </div>
            )
          })}
        </div>
      )}
    </div>
  )
}
```

---

### 8. `frontend/src/app/(auditor)/auditor/audit/[id]/page.tsx` — add "NC Forms" tab

**Step A — Add `'nc_forms'` to the Tab type:**

```tsx
type Tab = 'overview' | 'messages' | 'upload' | 'attendees' | 'nc_forms'
```

**Step B — Add `AuditorNCFormsView` component** (add above `export default function AuditorAuditDetail`):

```tsx
function AuditorNCFormsView({ auditSetId }: { auditSetId: string }) {
  const [forms, setForms]   = useState<{
    id: string; stage_type: string; label: string; file_name: string | null; status: string;
    la_signed_at: string | null;
  }[]>([])
  const [loading, setLoading] = useState(true)
  const [otpState, setOtpState] = useState<Record<string, 'idle' | 'otp_sent' | 'done'>>({})
  const [otpValues, setOtpValues] = useState<Record<string, string>>({})
  const [messages, setMessages]   = useState<Record<string, string>>({})
  const [busy, setBusy]           = useState<Record<string, boolean>>({})

  const STAGE_LABELS: Record<string, string> = {
    stage_1: 'Stage 1', stage_2: 'Stage 2', surveillance: 'Surveillance',
    recertification: 'Recertification',
  }

  useEffect(() => {
    api.get(`/audit-sets/${auditSetId}/nc-forms`)
      .then(r => setForms(r.data as typeof forms))
      .finally(() => setLoading(false))
  }, [auditSetId])

  async function download(id: string, fileName: string | null) {
    const r = await api.get(`/audit-sets/${auditSetId}/nc-forms/${id}/download`, {
      responseType: 'blob',
    })
    const url = window.URL.createObjectURL(new Blob([r.data]))
    const a   = document.createElement('a')
    a.href = url; a.download = fileName || 'nc_form.docx'
    document.body.appendChild(a); a.click(); a.remove()
    window.URL.revokeObjectURL(url)
  }

  async function requestOtp(id: string) {
    setBusy(b => ({ ...b, [id]: true }))
    setMessages(m => ({ ...m, [id]: '' }))
    try {
      await api.post(`/audit-sets/${auditSetId}/nc-forms/${id}/sign/la/request-otp`)
      setOtpState(s => ({ ...s, [id]: 'otp_sent' }))
    } catch (err: unknown) {
      const detail = (err as { response?: { data?: { detail?: string } } })?.response?.data?.detail
      setMessages(m => ({ ...m, [id]: detail || 'Failed to send code' }))
    } finally {
      setBusy(b => ({ ...b, [id]: false }))
    }
  }

  async function verifyOtp(id: string) {
    setBusy(b => ({ ...b, [id]: true }))
    setMessages(m => ({ ...m, [id]: '' }))
    try {
      await api.post(
        `/audit-sets/${auditSetId}/nc-forms/${id}/sign/la/verify?otp=${otpValues[id] ?? ''}`,
      )
      setOtpState(s => ({ ...s, [id]: 'done' }))
      setForms(prev => prev.map(f => f.id === id
        ? { ...f, status: 'pending_client', la_signed_at: new Date().toISOString() }
        : f
      ))
    } catch (err: unknown) {
      const detail = (err as { response?: { data?: { detail?: string } } })?.response?.data?.detail
      setMessages(m => ({ ...m, [id]: detail || 'Invalid code' }))
    } finally {
      setBusy(b => ({ ...b, [id]: false }))
    }
  }

  if (loading) return <p className="text-sm text-gray-400">Loading…</p>

  const pending = forms.filter(f => f.status === 'pending_la')
  const completed = forms.filter(f => f.status !== 'pending_la')

  return (
    <div className="space-y-4">
      {forms.length === 0 && (
        <p className="py-8 text-center text-sm text-gray-400">No NC forms for your stages.</p>
      )}

      {pending.length > 0 && (
        <div>
          <p className="mb-2 text-xs font-semibold uppercase tracking-wide text-amber-600">
            Awaiting Your Signature
          </p>
          <div className="space-y-3">
            {pending.map(f => {
              const state = otpState[f.id] || 'idle'
              return (
                <div key={f.id} className="rounded-xl border border-amber-200 bg-amber-50 p-4">
                  <div className="mb-3 flex items-start justify-between">
                    <div>
                      <p className="font-medium text-gray-800">{f.label}</p>
                      <p className="text-xs text-gray-400">
                        {STAGE_LABELS[f.stage_type] ?? f.stage_type}
                      </p>
                    </div>
                    <button
                      type="button"
                      onClick={() => download(f.id, f.file_name)}
                      className="text-xs text-[#1A4731] underline"
                    >
                      Download
                    </button>
                  </div>
                  {state === 'idle' && (
                    <button
                      type="button"
                      onClick={() => requestOtp(f.id)}
                      disabled={busy[f.id]}
                      className="rounded-lg bg-[#1A4731] px-4 py-2 text-sm text-white disabled:opacity-40"
                    >
                      {busy[f.id] ? 'Sending…' : 'Sign NC Form'}
                    </button>
                  )}
                  {state === 'otp_sent' && (
                    <div className="flex items-center gap-3">
                      <input
                        className="w-36 rounded-lg border px-3 py-2 text-center font-mono text-lg tracking-widest"
                        placeholder="000000" maxLength={6}
                        value={otpValues[f.id] ?? ''}
                        onChange={e => setOtpValues(v => ({
                          ...v, [f.id]: e.target.value.replace(/\D/g, ''),
                        }))}
                      />
                      <button
                        type="button"
                        onClick={() => verifyOtp(f.id)}
                        disabled={(otpValues[f.id] ?? '').length !== 6 || busy[f.id]}
                        className="rounded-lg bg-[#1A4731] px-4 py-2 text-sm text-white disabled:opacity-40"
                      >
                        {busy[f.id] ? '…' : 'Confirm'}
                      </button>
                      <button
                        type="button"
                        onClick={() => requestOtp(f.id)}
                        className="text-xs text-gray-400 underline"
                      >
                        Resend
                      </button>
                    </div>
                  )}
                  {state === 'done' && (
                    <p className="text-sm text-green-600 font-medium">Signed ✓ — client has been notified.</p>
                  )}
                  {messages[f.id] && (
                    <p className="mt-1 text-xs text-red-500">{messages[f.id]}</p>
                  )}
                </div>
              )
            })}
          </div>
        </div>
      )}

      {completed.length > 0 && (
        <div>
          <p className="mb-2 text-xs font-semibold uppercase tracking-wide text-gray-400">
            Signed
          </p>
          <div className="rounded-xl border bg-white divide-y divide-gray-50">
            {completed.map(f => (
              <div key={f.id} className="flex items-center justify-between px-4 py-3">
                <div>
                  <p className="text-sm font-medium text-gray-800">{f.label}</p>
                  <p className="text-xs text-gray-400">
                    {STAGE_LABELS[f.stage_type] ?? f.stage_type} ·{' '}
                    {f.status === 'complete' ? 'Both parties signed' : 'Awaiting client'}
                  </p>
                </div>
                <button
                  type="button"
                  onClick={() => download(f.id, f.file_name)}
                  className="text-xs text-[#1A4731] underline"
                >
                  Download
                </button>
              </div>
            ))}
          </div>
        </div>
      )}
    </div>
  )
}
```

**Step C — Add tab button** in the tabs row (after 'attendees'):

```tsx
{(['overview', 'messages', 'upload', 'attendees', 'nc_forms'] as const).map((t) => (
  <button ...>
    {t === 'upload' ? 'Upload Documents' 
     : t === 'attendees' ? 'Attendees' 
     : t === 'nc_forms' ? 'NC Forms'
     : t}
  </button>
))}
```

**Step D — Add tab panel** after the `{tab === 'attendees' && ...}` block:

```tsx
{tab === 'nc_forms' && (
  <AuditorNCFormsView auditSetId={id} />
)}
```

---

### 9. New file `frontend/src/components/ui/NCFormClientSection.tsx`

Client portal — shows NC forms awaiting counter-signature or already complete.

```tsx
'use client'

import { useEffect, useState } from 'react'
import api from '@/lib/api'

interface NCForm {
  id:               string
  stage_type:       string
  label:            string
  file_name:        string | null
  status:           string
  la_signed_at:     string | null
  client_signed_at: string | null
}

const STAGE_LABELS: Record<string, string> = {
  stage_1: 'Stage 1', stage_2: 'Stage 2',
  surveillance: 'Surveillance', recertification: 'Recertification',
}

function fmtDate(iso: string | null) {
  if (!iso) return ''
  return new Date(iso).toLocaleDateString('en-GB', {
    day: 'numeric', month: 'short', year: 'numeric',
  })
}

export function NCFormClientSection() {
  const [forms, setForms]   = useState<NCForm[]>([])
  const [loading, setLoading] = useState(true)
  const [otpState, setOtpState]   = useState<Record<string, 'idle' | 'otp_sent' | 'done'>>({})
  const [otpValues, setOtpValues] = useState<Record<string, string>>({})
  const [messages, setMessages]   = useState<Record<string, string>>({})
  const [busy, setBusy]           = useState<Record<string, boolean>>({})

  async function load() {
    try {
      const r = await api.get<NCForm[]>('/client/my-audit-set/nc-forms')
      setForms(r.data)
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => { load() }, [])

  async function download(id: string, fileName: string | null) {
    const r = await api.get(`/client/my-audit-set/nc-forms/${id}/download`, {
      responseType: 'blob',
    })
    const url = window.URL.createObjectURL(new Blob([r.data]))
    const a   = document.createElement('a')
    a.href = url; a.download = fileName || 'nc_form.docx'
    document.body.appendChild(a); a.click(); a.remove()
    window.URL.revokeObjectURL(url)
  }

  async function requestOtp(id: string) {
    setBusy(b => ({ ...b, [id]: true }))
    setMessages(m => ({ ...m, [id]: '' }))
    try {
      await api.post(`/client/my-audit-set/nc-forms/${id}/sign/request-otp`)
      setOtpState(s => ({ ...s, [id]: 'otp_sent' }))
    } catch (err: unknown) {
      const detail = (err as { response?: { data?: { detail?: string } } })?.response?.data?.detail
      setMessages(m => ({ ...m, [id]: detail || 'Failed to send code' }))
    } finally {
      setBusy(b => ({ ...b, [id]: false }))
    }
  }

  async function verifyOtp(id: string) {
    setBusy(b => ({ ...b, [id]: true }))
    setMessages(m => ({ ...m, [id]: '' }))
    try {
      await api.post(`/client/my-audit-set/nc-forms/${id}/sign/verify?otp=${otpValues[id] ?? ''}`)
      setOtpState(s => ({ ...s, [id]: 'done' }))
      setForms(prev => prev.map(f => f.id === id
        ? { ...f, status: 'complete', client_signed_at: new Date().toISOString() }
        : f
      ))
    } catch (err: unknown) {
      const detail = (err as { response?: { data?: { detail?: string } } })?.response?.data?.detail
      setMessages(m => ({ ...m, [id]: detail || 'Invalid code' }))
    } finally {
      setBusy(b => ({ ...b, [id]: false }))
    }
  }

  if (loading) return null  // silent load — section only renders when forms exist

  if (forms.length === 0) return null  // hide section entirely until CB uploads an NC form

  return (
    <div className="mt-8">
      <h2 className="mb-3 text-base font-semibold text-gray-900">
        Nonconformity Forms (FR.230)
      </h2>
      <div className="space-y-3">
        {forms.map(f => {
          const isSigned = f.status === 'complete'
          const state    = otpState[f.id] || 'idle'

          if (isSigned) {
            return (
              <div key={f.id} className="flex items-center justify-between rounded-xl border border-green-200 bg-green-50 px-4 py-3">
                <div>
                  <p className="font-medium text-gray-800">{f.label}</p>
                  <p className="mt-0.5 text-xs text-gray-400">
                    {STAGE_LABELS[f.stage_type] ?? f.stage_type} · Signed {fmtDate(f.client_signed_at)}
                  </p>
                </div>
                <div className="flex items-center gap-3">
                  <span className="rounded-full bg-green-100 px-2.5 py-0.5 text-xs font-semibold text-green-700">
                    ✓ Signed
                  </span>
                  <button
                    type="button"
                    onClick={() => download(f.id, f.file_name)}
                    className="text-xs text-[#1A4731] underline"
                  >
                    Download
                  </button>
                </div>
              </div>
            )
          }

          // pending_client — awaiting client signature
          return (
            <div key={f.id} className="rounded-xl border bg-white p-4">
              <div className="mb-3 flex items-start justify-between">
                <div>
                  <p className="font-medium text-gray-800">{f.label}</p>
                  <p className="mt-0.5 text-xs text-gray-500">
                    {STAGE_LABELS[f.stage_type] ?? f.stage_type}
                    {f.la_signed_at && ` · Auditor signed ${fmtDate(f.la_signed_at)}`}
                  </p>
                </div>
                <button
                  type="button"
                  onClick={() => download(f.id, f.file_name)}
                  className="text-xs text-[#1A4731] underline"
                >
                  Download
                </button>
              </div>

              {state === 'idle' && (
                <button
                  type="button"
                  onClick={() => requestOtp(f.id)}
                  disabled={busy[f.id]}
                  className="rounded-lg bg-[#1A4731] px-4 py-2 text-sm text-white disabled:opacity-40 hover:bg-[#143828]"
                >
                  {busy[f.id] ? 'Sending code…' : 'Sign NC Form'}
                </button>
              )}

              {state === 'otp_sent' && (
                <div className="flex items-center gap-3">
                  <input
                    className="w-36 rounded-lg border px-3 py-2 text-center font-mono text-lg tracking-widest focus:outline-none focus:ring-2 focus:ring-[#1A4731]/30"
                    placeholder="000000" maxLength={6}
                    value={otpValues[f.id] ?? ''}
                    onChange={e => setOtpValues(v => ({
                      ...v, [f.id]: e.target.value.replace(/\D/g, ''),
                    }))}
                  />
                  <button
                    type="button"
                    onClick={() => verifyOtp(f.id)}
                    disabled={(otpValues[f.id] ?? '').length !== 6 || busy[f.id]}
                    className="rounded-lg bg-[#1A4731] px-4 py-2 text-sm text-white disabled:opacity-40"
                  >
                    {busy[f.id] ? '…' : 'Confirm Signature'}
                  </button>
                  <button
                    type="button"
                    onClick={() => requestOtp(f.id)}
                    className="text-xs text-gray-400 underline"
                  >
                    Resend
                  </button>
                </div>
              )}

              {state === 'done' && (
                <p className="text-sm font-medium text-green-600">NC Form signed ✓</p>
              )}

              {messages[f.id] && (
                <p className="mt-1 text-xs text-red-500">{messages[f.id]}</p>
              )}
            </div>
          )
        })}
      </div>
    </div>
  )
}
```

---

### 10. `frontend/src/app/(client)/client/documents/page.tsx` — add NCFormClientSection

Add import at the top:
```tsx
import { NCFormClientSection } from '@/components/ui/NCFormClientSection'
```

Add at the **bottom** of the returned JSX (after the existing SharedDocuments list, before the closing `</div>`):
```tsx
<NCFormClientSection />
```

---

### 11. `frontend/src/app/(app)/clients/[id]/page.tsx` — wire NCFormManagementSection

Add import:
```tsx
import { NCFormManagementSection } from '@/components/ui/NCFormManagementSection'
```

Add **after** `<AssessmentManagementSection …/>`:
```tsx
<NCFormManagementSection
  auditSetId={id}
  workflowStatus={data.workflow_status ?? null}
/>
```

---

## Verification

1. `python3 -m py_compile backend/audit_set/nc_router.py backend/audit_set/db_models.py backend/email_service.py`
2. `cd frontend && npx tsc --noEmit`
3. FR.223 backend fix:
   a. CB → Release Document → Audit Plan (FR.223) → upload file → status should be "released" (no CB signing queue)
   b. Client Documents page → shows the audit plan → Sign Document → OTP flow works
4. FR.230 upload + LA sign:
   a. CB → `/clients/{id}` → "NC Forms (FR.230)" section appears
   b. `+ Upload NC Form` → Stage 1 + label + file → "Upload & Notify Auditor" → form appears with status "Awaiting Lead Auditor"
   c. Lead Auditor logs in → Audit detail page → "NC Forms" tab → form appears under "Awaiting Your Signature" → Download works → "Sign NC Form" → OTP → Confirm → status changes to "pending_client", green "Signed ✓ — client has been notified"
5. FR.230 client counter-sign:
   a. Client logs in → Documents page → "Nonconformity Forms" section appears at bottom (hidden when no forms exist)
   b. Form shows as pending with "Sign NC Form" button → OTP → Confirm → green "✓ Signed"
   c. CB portal → NC form status changes to "Complete"
6. Authorization guards:
   a. Non-lead-auditor trying to sign an NC form → 403 "Only the Lead Auditor for this stage may sign"
   b. Client trying to access NC form still in pending_la → 403 "Not yet available"
   c. Client seeing NC form for a different audit set → 404
7. Commit and push to main

## Constraints
DO NOT modify any other file beyond what is listed.

New files:
- `backend/audit_set/nc_router.py`
- `frontend/src/components/ui/NCFormManagementSection.tsx`
- `frontend/src/components/ui/NCFormClientSection.tsx`

Modified files:
- `backend/audit_set/db_models.py` — add `AuditSetNCForm`
- `backend/email_service.py` — add two functions
- `backend/audit_set/documents_router.py` — ALLOWED_DOC_TYPES one-line fix
- `backend/main.py` — register nc_router
- `frontend/src/components/ui/SharedDocumentsSection.tsx` — remove nc_form from DOC_TYPES
- `frontend/src/app/(auditor)/auditor/audit/[id]/page.tsx` — add NC Forms tab
- `frontend/src/app/(client)/client/documents/page.tsx` — import + add NCFormClientSection
- `frontend/src/app/(app)/clients/[id]/page.tsx` — wire NCFormManagementSection
