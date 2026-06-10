# AUGMENT PROMPT — Portal 12: CB Planner Signing Queue

## Context
Certiva — FastAPI backend + Next.js 14 App Router frontend.
**DO NOT BREAK THE EXISTING PORTAL. All changes are additive.**

The platform role system: admin, planner, officer, executive, auditor, client.
"CB_ROLES" = admin, planner, officer, executive.

## What this builds

When a CB planner releases a Quotation (FR.220) or Agreement (FR.221), the document must be
signed by the planner on behalf of IFC Global **before** the client can see it.
This is the standard practice: CB signs first, then the client receives and countersigns.

This prompt adds:
1. `AuditDocumentSignature` table — the backbone for all future multi-party signing
2. Modified `release_document` — quotation/agreement land in `"pending_cb_signature"` state
3. New `signatures_router.py` — OTP request + verify for CB staff
4. On CB sign → document flips to `"released"` → workflow advances → client email fires
5. Frontend: "Pending Signatures" widget on CB dashboard + status badges in SharedDocumentsSection
6. Client portal: hides `pending_cb_signature` documents (client only sees after CB signs)

---

## Backend

### 1. New model `AuditDocumentSignature` in `backend/audit_set/db_models.py`

Add after the `AuditSetSharedDocument` class:

```python
# ---------------------------------------------------------------------------
# Table 6 — audit_document_signatures
# Multi-party signature tracking for all document types.
# CB planner signs FR.220/FR.221; future prompts add committee, auditor, guest.
# ---------------------------------------------------------------------------

class AuditDocumentSignature(Base):
    __tablename__ = "audit_document_signatures"

    id               = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    audit_set_id     = Column(String, ForeignKey("audit_sets.id", ondelete="CASCADE"), nullable=False)
    document_id      = Column(String, nullable=True)   # soft FK → audit_set_shared_documents.id
    document_type    = Column(String, nullable=False)   # "quotation" | "agreement" | "FR218" | etc.
    signer_role_label= Column(String, nullable=False)   # "cb_planner" | "cb_cert_manager" | "lead_auditor" | "guest"
    signer_user_id   = Column(String, nullable=True)    # PlatformUser.id; null for guests
    signer_name      = Column(String, nullable=True)    # denormalized
    signer_email     = Column(String, nullable=True)    # for OTP delivery
    required         = Column(Boolean, default=True, nullable=False)
    order_index      = Column(Integer, default=0, nullable=False)
    signed_at        = Column(DateTime, nullable=True)
    signed_ip        = Column(String, nullable=True)
    otp_hash         = Column(String, nullable=True)
    otp_expires_at   = Column(DateTime, nullable=True)
    signing_token    = Column(String, nullable=True)    # for future guest token links
    token_expires_at = Column(DateTime, nullable=True)
    created_at       = Column(DateTime, default=datetime.utcnow, nullable=False)
```

No `_safe_add_column` needed — `Base.metadata.create_all()` creates the new table on boot.

Also add `Integer` to the existing SQLAlchemy import at the top of `db_models.py` if it's not already there.

---

### 2. New file `backend/audit_set/signatures_router.py`

```python
"""
BATUHAN — Document CB signing (Prompt 12).

CB staff sign documents via OTP before they are released to the client portal.
Prompt 12 covers: cb_planner signs quotation + agreement.
Future prompts extend this to cb_cert_manager, lead_auditor, committee, guests.
"""
from __future__ import annotations
import hashlib, os, secrets
from datetime import datetime, timedelta

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.orm import Session

from audit_set.db_models import (
    AuditDocumentSignature, AuditSetSharedDocument, AuditSet,
    AuditSetStatusEvent, get_db,
)
from auth.db_models import PlatformUser, get_db as get_auth_db
from auth.dependencies import get_current_user
from email_service import send_document_released, send_otp_code

router = APIRouter(prefix="/audit-sets", tags=["signatures"])

CB_ROLES      = {"admin", "planner", "officer", "executive"}
OTP_EXPIRY    = 10  # minutes


def _hash_otp(otp: str) -> str:
    return hashlib.sha256(otp.encode()).hexdigest()


def _sig_to_dict(s: AuditDocumentSignature, doc_label: str = "", company_name: str = "", plan_number: int | None = None) -> dict:
    return {
        "id":               s.id,
        "audit_set_id":     s.audit_set_id,
        "document_id":      s.document_id,
        "document_type":    s.document_type,
        "document_label":   doc_label or s.document_type.title(),
        "signer_role_label": s.signer_role_label,
        "signer_name":      s.signer_name,
        "company_name":     company_name,
        "plan_number":      plan_number,
        "required":         s.required,
        "order_index":      s.order_index,
        "signed_at":        s.signed_at.isoformat() if s.signed_at else None,
        "is_signed":        s.signed_at is not None,
        "created_at":       s.created_at.isoformat() if s.created_at else None,
    }


@router.get("/my-pending-signatures")
def get_my_pending_signatures(
    db: Session = Depends(get_db),
    current_user: PlatformUser = Depends(get_current_user),
):
    """All unsigned signature slots assigned to the current user. Powers the dashboard widget."""
    if current_user.role not in CB_ROLES:
        raise HTTPException(403, "Not authorized")

    sigs = (
        db.query(AuditDocumentSignature)
        .filter_by(signer_user_id=current_user.id)
        .filter(AuditDocumentSignature.signed_at.is_(None))
        .order_by(AuditDocumentSignature.created_at)
        .all()
    )

    results = []
    for s in sigs:
        audit_set = db.query(AuditSet).filter_by(id=s.audit_set_id).first()
        doc_label = s.document_type.title()
        if s.document_id:
            doc = db.query(AuditSetSharedDocument).filter_by(id=s.document_id).first()
            if doc:
                doc_label = doc.label
        results.append(_sig_to_dict(
            s,
            doc_label=doc_label,
            company_name=audit_set.company_name if audit_set else "",
            plan_number=audit_set.plan_number if audit_set else None,
        ))
    return results


@router.post("/{audit_set_id}/signatures/{sig_id}/request-otp")
def request_cb_signature_otp(
    audit_set_id: str,
    sig_id: str,
    db: Session = Depends(get_db),
    current_user: PlatformUser = Depends(get_current_user),
):
    if current_user.role not in CB_ROLES:
        raise HTTPException(403, "Not authorized")

    sig = db.query(AuditDocumentSignature).filter_by(
        id=sig_id, audit_set_id=audit_set_id
    ).first()
    if not sig:
        raise HTTPException(404, "Signature request not found")
    if sig.signer_user_id != current_user.id:
        raise HTTPException(403, "This signature is not assigned to you")
    if sig.signed_at:
        raise HTTPException(400, "Already signed")

    otp = f"{secrets.randbelow(900000) + 100000}"
    sig.otp_hash = _hash_otp(otp)
    sig.otp_expires_at = datetime.utcnow() + timedelta(minutes=OTP_EXPIRY)
    db.commit()

    doc_label = sig.document_type.title()
    if sig.document_id:
        doc = db.query(AuditSetSharedDocument).filter_by(id=sig.document_id).first()
        if doc:
            doc_label = doc.label

    try:
        send_otp_code(
            to=current_user.email,
            full_name=current_user.full_name,
            otp=otp,
            document_label=doc_label,
        )
    except Exception:
        pass

    return {"message": f"OTP sent to {current_user.email}. Valid for {OTP_EXPIRY} minutes."}


@router.post("/{audit_set_id}/signatures/{sig_id}/verify")
def verify_cb_signature(
    audit_set_id: str,
    sig_id: str,
    otp: str,
    request: Request,
    db: Session = Depends(get_db),
    auth_db: Session = Depends(get_auth_db),
    current_user: PlatformUser = Depends(get_current_user),
):
    if current_user.role not in CB_ROLES:
        raise HTTPException(403, "Not authorized")

    sig = db.query(AuditDocumentSignature).filter_by(
        id=sig_id, audit_set_id=audit_set_id
    ).first()
    if not sig:
        raise HTTPException(404, "Signature request not found")
    if sig.signer_user_id != current_user.id:
        raise HTTPException(403, "This signature is not assigned to you")
    if sig.signed_at:
        raise HTTPException(400, "Already signed")
    if not sig.otp_hash or not sig.otp_expires_at:
        raise HTTPException(400, "No pending OTP. Request one first.")
    if datetime.utcnow() > sig.otp_expires_at:
        raise HTTPException(400, "OTP expired. Please request a new one.")
    if _hash_otp(otp.strip()) != sig.otp_hash:
        raise HTTPException(400, "Invalid OTP code.")

    # Mark signature complete
    sig.signed_at = datetime.utcnow()
    sig.signed_ip = request.client.host if request.client else None
    sig.otp_hash = None
    sig.otp_expires_at = None
    db.commit()

    # Check if all required signatures on this document are now complete
    if sig.document_id:
        doc = db.query(AuditSetSharedDocument).filter_by(id=sig.document_id).first()
        if doc and doc.status == "pending_cb_signature":
            remaining = (
                db.query(AuditDocumentSignature)
                .filter_by(document_id=sig.document_id, required=True)
                .filter(AuditDocumentSignature.signed_at.is_(None))
                .count()
            )
            if remaining == 0:
                # All required CB signatures collected — release to client
                doc.status = "released"
                audit_set = db.query(AuditSet).filter_by(id=audit_set_id).first()

                if audit_set and doc.document_type == "quotation":
                    if audit_set.workflow_status == "in_planning":
                        audit_set.workflow_status = "quotation_sent"
                        db.add(AuditSetStatusEvent(
                            audit_set_id=audit_set_id,
                            from_status="in_planning",
                            to_status="quotation_sent",
                            triggered_by=current_user.id,
                            notes="Quotation signed by CB planner and released to client",
                        ))

                db.commit()

                # Email client
                client_user = auth_db.query(PlatformUser).filter_by(
                    audit_set_id=audit_set_id, role="client"
                ).first()
                if client_user:
                    try:
                        send_document_released(
                            to=client_user.email,
                            full_name=client_user.full_name,
                            document_label=doc.label,
                        )
                    except Exception:
                        pass

    return {"signed": True, "signed_at": sig.signed_at.isoformat()}
```

---

### 3. Modified `release_document` in `backend/audit_set/documents_router.py`

Replace the current `release_document` function body with:

```python
@router.post("/{audit_set_id}/documents/release")
async def release_document(
    audit_set_id: str,
    label: str = Form(...),
    document_type: str = Form(...),
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
    auth_db: Session = Depends(get_auth_db),
    current_user: PlatformUser = Depends(get_current_user),
):
    if current_user.role not in CB_ROLES:
        raise HTTPException(403, "Not authorized")
    if document_type not in ALLOWED_DOC_TYPES:
        raise HTTPException(400, f"Invalid document_type. Expected one of: {sorted(ALLOWED_DOC_TYPES)}")
    audit_set = db.query(AuditSet).filter_by(id=audit_set_id).first()
    if not audit_set:
        raise HTTPException(404, "Audit set not found")

    # Save file
    settings = get_settings()
    upload_dir = os.path.join(settings.storage_base_path, "shared_docs", audit_set_id)
    os.makedirs(upload_dir, exist_ok=True)
    safe_name = f"{secrets.token_hex(6)}_{file.filename}"
    file_path = os.path.join(upload_dir, safe_name)
    content = await file.read()
    with open(file_path, "wb") as f:
        f.write(content)

    # Quotation and Agreement need CB signature before the client can see them.
    # Certificate is released immediately (no CB countersignature required on the portal).
    requires_cb_sig = document_type in ("quotation", "agreement")
    initial_status = "pending_cb_signature" if requires_cb_sig else "released"

    doc = AuditSetSharedDocument(
        audit_set_id=audit_set_id,
        label=label,
        document_type=document_type,
        file_path=file_path,
        direction="cb_to_client",
        status=initial_status,
        released_by=current_user.id,
        released_at=datetime.utcnow(),
    )
    db.add(doc)
    db.flush()  # populate doc.id before creating the signature record

    if requires_cb_sig:
        from audit_set.db_models import AuditDocumentSignature
        sig = AuditDocumentSignature(
            audit_set_id=audit_set_id,
            document_id=doc.id,
            document_type=document_type,
            signer_role_label="cb_planner",
            signer_user_id=current_user.id,
            signer_name=current_user.full_name,
            signer_email=current_user.email,
            required=True,
            order_index=0,
        )
        db.add(sig)
        db.commit()
        db.refresh(doc)
        # Do NOT advance workflow or email client yet — that happens in verify_cb_signature
        return {"id": doc.id, "status": "pending_cb_signature", "signature_id": sig.id}

    # Non-contract doc (e.g. certificate): release immediately
    db.commit()
    db.refresh(doc)
    client_user = auth_db.query(PlatformUser).filter_by(
        audit_set_id=audit_set_id, role="client"
    ).first()
    if client_user:
        try:
            send_document_released(
                to=client_user.email,
                full_name=client_user.full_name,
                document_label=label,
            )
        except Exception:
            pass
    return {"id": doc.id, "status": "released"}
```

Also add `AuditDocumentSignature` to the import at the top of `documents_router.py`:
```python
from audit_set.db_models import AuditSet, AuditSetSharedDocument, AuditSetStatusEvent, AuditDocumentSignature, get_db
```

Update `_doc_to_dict` to include CB signature info (pass `db` to it):

```python
def _doc_to_dict(d: AuditSetSharedDocument, db: Session | None = None) -> dict:
    result = {
        "id":            d.id,
        "label":         d.label,
        "document_type": d.document_type,
        "direction":     d.direction,
        "status":        d.status,
        "released_at":   d.released_at.isoformat() if d.released_at else None,
        "signed_at":     d.signed_at.isoformat()   if d.signed_at   else None,
        "signed_by":     d.signed_by,
        "cb_sig_status": None,
        "cb_sig_id":     None,
    }
    if db and d.document_type in ("quotation", "agreement"):
        cb_sig = (
            db.query(AuditDocumentSignature)
            .filter_by(document_id=d.id, signer_role_label="cb_planner")
            .first()
        )
        if cb_sig:
            result["cb_sig_status"] = "signed" if cb_sig.signed_at else "pending"
            result["cb_sig_id"] = cb_sig.id
    return result
```

Update all callers of `_doc_to_dict` in `documents_router.py` to pass `db`:
- `list_documents`: change `return [_doc_to_dict(d) for d in docs]` → `return [_doc_to_dict(d, db) for d in docs]`

**Also remove the auto-advance block from `release_document`** (the old Prompt 09 block that advanced workflow on quotation release). Auto-advance now happens in `verify_cb_signature` when CB signs. The block to remove looks like:
```python
# Auto-advance: releasing the quotation moves planning → quotation_sent
if payload.document_type == "quotation":
    _auto_advance_workflow(...)
```
This logic is now handled in `signatures_router.py`.

---

### 4. Update `client_router.py` — hide pending_cb_signature documents from client

In `get_my_documents`, add a status filter so clients never see documents before CB signs:

```python
@router.get("/my-audit-set/documents")
def get_my_documents(
    db: Session = Depends(get_db),
    current_user: PlatformUser = Depends(get_current_user),
):
    audit_set = _get_client_audit_set(current_user, db)
    docs = (
        db.query(AuditSetSharedDocument)
        .filter_by(audit_set_id=audit_set.id, direction="cb_to_client")
        .filter(AuditSetSharedDocument.status != "pending_cb_signature")  # ← NEW
        .order_by(AuditSetSharedDocument.created_at)
        .all()
    )
    return [
        {
            "id":            d.id,
            "label":         d.label,
            "document_type": d.document_type,
            "status":        d.status,
            "released_at":   d.released_at.isoformat() if d.released_at else None,
            "signed_at":     d.signed_at.isoformat()   if d.signed_at   else None,
        }
        for d in docs
    ]
```

---

### 5. Register `signatures_router` in `backend/main.py`

Add before the existing audit_set routers:
```python
from audit_set.signatures_router import router as signatures_router
app.include_router(signatures_router)
```

---

## Frontend

### 1. New file `frontend/src/components/ui/PendingSignaturesWidget.tsx`

```tsx
'use client'

import { useEffect, useState } from 'react'
import api from '@/lib/api'

interface PendingSig {
  id: string
  audit_set_id: string
  plan_number: number | null
  company_name: string
  document_label: string
  document_type: string
}

export function PendingSignaturesWidget() {
  const [sigs, setSigs]           = useState<PendingSig[]>([])
  const [loading, setLoading]     = useState(true)
  const [signingId, setSigningId] = useState<string | null>(null)
  const [otpSent, setOtpSent]     = useState(false)
  const [otpValue, setOtpValue]   = useState('')
  const [error, setError]         = useState('')
  const [busy, setBusy]           = useState(false)

  async function load() {
    try {
      const r = await api.get<PendingSig[]>('/audit-sets/my-pending-signatures')
      setSigs(r.data)
    } catch {
      // Not CB user or network error — fail silently
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => { load() }, [])

  async function requestOtp(sig: PendingSig) {
    setSigningId(sig.id)
    setOtpSent(false)
    setError('')
    setBusy(true)
    try {
      await api.post(`/audit-sets/${sig.audit_set_id}/signatures/${sig.id}/request-otp`)
      setOtpSent(true)
    } catch (e: unknown) {
      const detail = (e as { response?: { data?: { detail?: string } } })?.response?.data?.detail
      setError(detail || 'Failed to send code')
    } finally {
      setBusy(false)
    }
  }

  async function verifyOtp(sig: PendingSig) {
    setBusy(true)
    setError('')
    try {
      await api.post(
        `/audit-sets/${sig.audit_set_id}/signatures/${sig.id}/verify?otp=${otpValue}`,
      )
      setSigningId(null)
      setOtpValue('')
      setOtpSent(false)
      await load()
    } catch (e: unknown) {
      const detail = (e as { response?: { data?: { detail?: string } } })?.response?.data?.detail
      setError(detail || 'Invalid code')
    } finally {
      setBusy(false)
    }
  }

  if (loading || sigs.length === 0) return null

  return (
    <div className="rounded-lg border border-amber-200 bg-amber-50 p-5">
      <h2 className="mb-3 text-sm font-semibold text-amber-900">
        ✍ Pending Signatures ({sigs.length})
      </h2>
      <div className="space-y-3">
        {sigs.map((sig) => (
          <div key={sig.id} className="rounded-lg border border-amber-100 bg-white p-4">
            <div className="flex items-center justify-between">
              <div>
                <p className="text-sm font-medium text-gray-900">{sig.document_label}</p>
                <p className="mt-0.5 text-xs text-gray-400">
                  {sig.plan_number ? `#${sig.plan_number} · ` : ''}{sig.company_name}
                </p>
              </div>
              {signingId !== sig.id && (
                <button
                  type="button"
                  onClick={() => requestOtp(sig)}
                  disabled={busy}
                  className="rounded-lg bg-[#1A4731] px-3 py-1.5 text-xs font-medium text-white disabled:opacity-40"
                >
                  Sign
                </button>
              )}
            </div>

            {signingId === sig.id && (
              <div className="mt-3 rounded-lg border bg-gray-50 p-3">
                {!otpSent ? (
                  <p className="text-xs text-gray-500">
                    {busy ? 'Sending code…' : 'Sending a 6-digit code to your email…'}
                  </p>
                ) : (
                  <div className="flex items-center gap-2">
                    <input
                      className="w-32 rounded border px-2 py-1.5 text-center font-mono text-sm tracking-widest focus:outline-none focus:ring-2 focus:ring-[#1A4731]/30"
                      placeholder="000000"
                      maxLength={6}
                      value={otpValue}
                      onChange={(e) => setOtpValue(e.target.value.replace(/\D/g, ''))}
                    />
                    <button
                      type="button"
                      onClick={() => verifyOtp(sig)}
                      disabled={otpValue.length !== 6 || busy}
                      className="rounded bg-[#1A4731] px-3 py-1.5 text-xs text-white disabled:opacity-40"
                    >
                      {busy ? '…' : 'Confirm'}
                    </button>
                    <button
                      type="button"
                      onClick={() => { setSigningId(null); setOtpSent(false); setOtpValue('') }}
                      className="text-xs text-gray-400"
                    >
                      Cancel
                    </button>
                    <button
                      type="button"
                      onClick={() => requestOtp(sig)}
                      className="text-xs text-gray-400 underline"
                    >
                      Resend
                    </button>
                  </div>
                )}
                {error && <p className="mt-1 text-xs text-red-500">{error}</p>}
              </div>
            )}
          </div>
        ))}
      </div>
    </div>
  )
}
```

### 2. Wire `PendingSignaturesWidget` into `frontend/src/app/(app)/dashboard/page.tsx`

Add import at top:
```tsx
import { PendingSignaturesWidget } from '@/components/ui/PendingSignaturesWidget'
```

In `DashboardPage` return, add between `<StatCards>` and `<ClientTable>`:
```tsx
<div className="flex flex-col gap-6">
  <StatCards stats={stats} isLoading={statsLoading} />
  <PendingSignaturesWidget />
  <ClientTable />
</div>
```

### 3. Update `frontend/src/components/ui/SharedDocumentsSection.tsx`

**Update `SharedDoc` interface** to include CB sig fields:
```typescript
interface SharedDoc {
  id: string
  label: string
  document_type: string
  direction: 'cb_to_client' | 'auditor_to_cb'
  status: 'pending_cb_signature' | 'released' | 'signed' | 'uploaded'
  released_at: string | null
  signed_at: string | null
  signed_by: string | null
  cb_sig_status: 'pending' | 'signed' | null
  cb_sig_id: string | null
}
```

**Update the status badges section** in the document list item (replace the existing single badge):
```tsx
<div className="flex items-center gap-2">
  {/* CB signature badge — only for quotation / agreement */}
  {doc.cb_sig_status && (
    <span className={`rounded-full px-2 py-0.5 text-xs font-semibold ${
      doc.cb_sig_status === 'signed'
        ? 'bg-blue-100 text-blue-700'
        : 'bg-amber-100 text-amber-800'
    }`}>
      {doc.cb_sig_status === 'signed' ? 'CB ✓' : 'CB Signing…'}
    </span>
  )}
  {/* Client / document status badge */}
  <span className={`rounded-full px-2 py-0.5 text-xs font-semibold ${
    doc.status === 'signed'               ? 'bg-green-100 text-green-700'
    : doc.status === 'uploaded'           ? 'bg-blue-100 text-blue-700'
    : doc.status === 'pending_cb_signature' ? 'bg-gray-100 text-gray-500'
    : 'bg-amber-100 text-amber-700'
  }`}>
    {doc.status === 'signed'
      ? '✓ Signed'
      : doc.status === 'uploaded'
      ? 'Uploaded'
      : doc.status === 'pending_cb_signature'
      ? 'Pending release'
      : 'Awaiting Signature'}
  </span>
  <button
    type="button"
    onClick={() => downloadDoc(doc.id, doc.label)}
    className="rounded-lg border border-gray-300 px-2.5 py-1 text-xs text-gray-700 hover:bg-gray-50"
  >
    Download
  </button>
</div>
```

---

## Verification

1. `python3 -m py_compile backend/audit_set/signatures_router.py backend/audit_set/documents_router.py backend/audit_set/db_models.py backend/audit_set/client_router.py`
2. `cd frontend && npx tsc --noEmit`
3. Manual flow test:
   - CB releases a Quotation → document appears in SharedDocumentsSection with "CB Signing…" + "Pending release" badges
   - Dashboard shows "Pending Signatures (1)" amber widget
   - CB clicks Sign → enters OTP → document flips to "CB ✓" + "Awaiting Signature", WorkflowStatusBar advances to quotation_sent, client email fires
   - Client portal `/client/documents` shows the quotation only AFTER CB has signed it
   - Client signs → status → "✓ Signed", workflow advances to agreement_signed
   - Repeat for Agreement type
4. Confirm `GET /audit-sets/my-pending-signatures` appears in `/docs` and returns empty list for non-planner users
5. Commit and push to main

## Constraint
DO NOT modify any other endpoint, component, or page beyond what is listed.

New files: `backend/audit_set/signatures_router.py`, `frontend/src/components/ui/PendingSignaturesWidget.tsx`

Modified files:
- `backend/audit_set/db_models.py` — new `AuditDocumentSignature` model
- `backend/audit_set/documents_router.py` — modified `release_document` + updated `_doc_to_dict`
- `backend/audit_set/client_router.py` — filter `pending_cb_signature` from client document list
- `backend/main.py` — register `signatures_router`
- `frontend/src/app/(app)/dashboard/page.tsx` — add `PendingSignaturesWidget`
- `frontend/src/components/ui/SharedDocumentsSection.tsx` — updated badges + interface
