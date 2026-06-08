# Portal Build — Prompt 7 of 8: Document Sharing + OTP Signing

## ⚠️ CRITICAL: DO NOT BREAK THE EXISTING PORTAL
Purely additive. The existing document generation (audit set download, packager) is untouched.
This prompt adds a separate "release to client" layer on top of existing documents.

---

## Context

After generating the audit package, the CB coordinator releases specific documents (quotation
FR.220, agreement FR.221) to the client's portal. The client sees them, reads them, and signs
them with an OTP-verified click. Both sides see the signed status.

Release order: Quotation (FR.220) first → client signs → Agreement (FR.221) → client signs.
After both are signed, the audit package itself is internal only (auditor uploads later).

The `audit_set_shared_documents` table was created in Prompt 1.

---

## Task

### Backend: Document sharing API

#### New file: `backend/audit_set/documents_router.py`

```python
"""
BATUHAN — Audit set document sharing + OTP signing.
CB releases documents to client portal; client signs with OTP.
"""
from __future__ import annotations
import hashlib
import os
import secrets
from datetime import datetime, timedelta

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import FileResponse
from pydantic import BaseModel
from sqlalchemy.orm import Session

from audit_set.db_models import AuditSet, AuditSetSharedDocument, get_db
from auth.db_models import PlatformUser, get_db as get_auth_db
from auth.router import get_current_user
from email_service import send_document_released, send_otp_code

router = APIRouter(prefix="/audit-sets", tags=["documents"])

CB_ROLES = {"admin", "planner", "officer", "executive"}

OTP_EXPIRY_MINUTES = 10


def _hash_otp(otp: str) -> str:
    return hashlib.sha256(otp.encode()).hexdigest()


# ── CB: release a document to client ────────────────────────────────────────

class DocumentReleaseSchema(BaseModel):
    label: str          # e.g. "Quotation (FR.220)"
    document_type: str  # "quotation" | "agreement" | "certificate"
    file_path: str      # server-side path to the already-generated file


@router.post("/{audit_set_id}/documents/release")
def release_document(
    audit_set_id: str,
    payload: DocumentReleaseSchema,
    db: Session = Depends(get_db),
    auth_db: Session = Depends(get_auth_db),
    current_user: PlatformUser = Depends(get_current_user),
):
    if current_user.role not in CB_ROLES:
        raise HTTPException(403, "Not authorized")

    audit_set = db.query(AuditSet).filter_by(id=audit_set_id).first()
    if not audit_set:
        raise HTTPException(404, "Audit set not found")

    # Validate file exists
    if not os.path.exists(payload.file_path):
        raise HTTPException(400, f"File not found: {payload.file_path}")

    doc = AuditSetSharedDocument(
        audit_set_id=audit_set_id,
        label=payload.label,
        document_type=payload.document_type,
        file_path=payload.file_path,
        direction="cb_to_client",
        status="released",
        released_by=current_user.id,
        released_at=datetime.utcnow(),
    )
    db.add(doc)
    db.commit()
    db.refresh(doc)

    # Notify client
    client_user = auth_db.query(PlatformUser).filter_by(
        audit_set_id=audit_set_id, role="client"
    ).first()
    if client_user:
        send_document_released(
            to=client_user.email,
            full_name=client_user.full_name,
            document_label=payload.label,
        )

    return {"id": doc.id, "status": "released"}


@router.get("/{audit_set_id}/documents")
def list_documents(
    audit_set_id: str,
    db: Session = Depends(get_db),
    current_user: PlatformUser = Depends(get_current_user),
):
    """List all shared documents for an audit set. Accessible by CB roles."""
    if current_user.role not in CB_ROLES:
        raise HTTPException(403, "Not authorized")
    docs = (
        db.query(AuditSetSharedDocument)
        .filter_by(audit_set_id=audit_set_id)
        .order_by(AuditSetSharedDocument.created_at)
        .all()
    )
    return [_doc_to_dict(d) for d in docs]


@router.get("/{audit_set_id}/documents/{doc_id}/download")
def download_document(
    audit_set_id: str,
    doc_id: str,
    db: Session = Depends(get_db),
    current_user: PlatformUser = Depends(get_current_user),
):
    """Download the file. Accessible by CB and the linked client."""
    doc = db.query(AuditSetSharedDocument).filter_by(
        id=doc_id, audit_set_id=audit_set_id
    ).first()
    if not doc:
        raise HTTPException(404, "Document not found")

    # Client can only download documents directed at them
    if current_user.role == "client":
        if current_user.audit_set_id != audit_set_id:
            raise HTTPException(403, "Not your document")
        if doc.direction != "cb_to_client":
            raise HTTPException(403, "Not authorized")

    if not doc.file_path or not os.path.exists(doc.file_path):
        raise HTTPException(404, "File not found on server")

    filename = os.path.basename(doc.file_path)
    return FileResponse(doc.file_path, filename=filename,
                        media_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document")


# ── Client: request OTP to sign ─────────────────────────────────────────────

@router.post("/{audit_set_id}/documents/{doc_id}/sign/request-otp")
def request_sign_otp(
    audit_set_id: str,
    doc_id: str,
    db: Session = Depends(get_db),
    auth_db: Session = Depends(get_auth_db),
    current_user: PlatformUser = Depends(get_current_user),
):
    if current_user.role != "client":
        raise HTTPException(403, "Signing is for clients only")
    if current_user.audit_set_id != audit_set_id:
        raise HTTPException(403, "Not your document")

    doc = db.query(AuditSetSharedDocument).filter_by(
        id=doc_id, audit_set_id=audit_set_id, direction="cb_to_client"
    ).first()
    if not doc:
        raise HTTPException(404, "Document not found")
    if doc.status == "signed":
        raise HTTPException(400, "Document already signed")

    otp = f"{secrets.randbelow(900000) + 100000}"  # 6-digit
    doc.otp_hash = _hash_otp(otp)
    doc.otp_expires_at = datetime.utcnow() + timedelta(minutes=OTP_EXPIRY_MINUTES)
    db.commit()

    send_otp_code(
        to=current_user.email,
        full_name=current_user.full_name,
        otp=otp,
        document_label=doc.label,
    )
    return {"message": f"OTP sent to {current_user.email}. Valid for {OTP_EXPIRY_MINUTES} minutes."}


@router.post("/{audit_set_id}/documents/{doc_id}/sign/verify")
def verify_sign_otp(
    audit_set_id: str,
    doc_id: str,
    request: Request,
    otp: str,
    db: Session = Depends(get_db),
    current_user: PlatformUser = Depends(get_current_user),
):
    if current_user.role != "client":
        raise HTTPException(403, "Signing is for clients only")
    if current_user.audit_set_id != audit_set_id:
        raise HTTPException(403, "Not your document")

    doc = db.query(AuditSetSharedDocument).filter_by(
        id=doc_id, audit_set_id=audit_set_id
    ).first()
    if not doc:
        raise HTTPException(404, "Document not found")
    if doc.status == "signed":
        raise HTTPException(400, "Already signed")
    if not doc.otp_hash or not doc.otp_expires_at:
        raise HTTPException(400, "No pending OTP. Request one first.")
    if datetime.utcnow() > doc.otp_expires_at:
        raise HTTPException(400, "OTP expired. Please request a new one.")
    if _hash_otp(otp.strip()) != doc.otp_hash:
        raise HTTPException(400, "Invalid OTP code.")

    doc.status = "signed"
    doc.signed_by = current_user.id
    doc.signed_at = datetime.utcnow()
    doc.signed_ip = request.client.host if request.client else None
    doc.otp_hash = None  # clear OTP after use
    doc.otp_expires_at = None
    db.commit()

    return {"signed": True, "signed_at": doc.signed_at.isoformat()}


# ── Auditor: upload completed audit documents ────────────────────────────────

from fastapi import UploadFile, File
from config.settings import get_settings

@router.post("/{audit_set_id}/documents/upload")
async def upload_audit_document(
    audit_set_id: str,
    label: str,
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
    current_user: PlatformUser = Depends(get_current_user),
):
    """Auditor uploads completed audit documents back to CB."""
    if current_user.role not in {"auditor", "admin", "planner"}:
        raise HTTPException(403, "Not authorized to upload audit documents")

    settings = get_settings()
    upload_dir = os.path.join(settings.storage_base_path, "audit_uploads", audit_set_id)
    os.makedirs(upload_dir, exist_ok=True)

    safe_name = f"{secrets.token_hex(6)}_{file.filename}"
    file_path = os.path.join(upload_dir, safe_name)

    content = await file.read()
    with open(file_path, "wb") as f:
        f.write(content)

    doc = AuditSetSharedDocument(
        audit_set_id=audit_set_id,
        label=label or file.filename,
        document_type="audit_upload",
        file_path=file_path,
        direction="auditor_to_cb",
        status="uploaded",
        released_by=current_user.id,
        released_at=datetime.utcnow(),
    )
    db.add(doc)
    db.commit()
    return {"id": doc.id, "label": doc.label, "status": "uploaded"}


def _doc_to_dict(d: AuditSetSharedDocument) -> dict:
    return {
        "id": d.id,
        "label": d.label,
        "document_type": d.document_type,
        "direction": d.direction,
        "status": d.status,
        "released_at": d.released_at.isoformat() if d.released_at else None,
        "signed_at":   d.signed_at.isoformat()   if d.signed_at   else None,
        "signed_by":   d.signed_by,
    }
```

Register in `backend/main.py`:
```python
from audit_set.documents_router import router as documents_router
app.include_router(documents_router)
```

### Frontend: Client Documents page

Replace `frontend/src/app/(client)/client/documents/page.tsx`:

```tsx
'use client'
import { useEffect, useState } from 'react'
import api from '@/lib/api'

type DocStatus = 'released' | 'signed'

interface SharedDoc {
  id: string
  label: string
  document_type: string
  status: DocStatus
  released_at: string | null
  signed_at: string | null
}

export default function ClientDocumentsPage() {
  const [docs, setDocs]     = useState<SharedDoc[]>([])
  const [loading, setLoading] = useState(true)

  // Signing state
  const [signingDoc, setSigningDoc] = useState<string | null>(null)
  const [otpSent, setOtpSent]       = useState(false)
  const [otpValue, setOtpValue]     = useState('')
  const [signError, setSignError]   = useState('')
  const [signLoading, setSignLoading] = useState(false)

  async function loadDocs() {
    try {
      // Client uses the client router (my-audit-set endpoint)
      const r = await api.get<SharedDoc[]>('/client/my-audit-set/documents')
      setDocs(r.data)
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => { loadDocs() }, [])

  async function requestOtp(docId: string) {
    setSigningDoc(docId)
    setOtpSent(false)
    setSignError('')
    setSignLoading(true)
    try {
      // We need the audit_set_id — get it from the URL or from a context
      // For simplicity, the client router exposes a shorthand route:
      await api.post(`/client/my-audit-set/documents/${docId}/sign/request-otp`)
      setOtpSent(true)
    } catch (err: any) {
      setSignError(err?.response?.data?.detail || 'Failed to send OTP')
    } finally {
      setSignLoading(false)
    }
  }

  async function submitOtp(docId: string) {
    setSignLoading(true)
    setSignError('')
    try {
      await api.post(`/client/my-audit-set/documents/${docId}/sign/verify?otp=${otpValue}`)
      setSigningDoc(null)
      setOtpValue('')
      setOtpSent(false)
      await loadDocs()
    } catch (err: any) {
      setSignError(err?.response?.data?.detail || 'Invalid code')
    } finally {
      setSignLoading(false)
    }
  }

  if (loading) return <div className="p-8 text-gray-400">Loading documents...</div>

  return (
    <div className="p-6 max-w-2xl mx-auto">
      <div className="mb-6">
        <h1 className="text-xl font-bold text-gray-900">Documents</h1>
        <p className="text-sm text-gray-400 mt-0.5">Documents shared with you by IFC Global</p>
      </div>

      {docs.length === 0 ? (
        <div className="text-center py-16 text-gray-400 text-sm">
          No documents have been shared yet. You will be notified by email when documents are ready.
        </div>
      ) : (
        <div className="space-y-3">
          {docs.map(doc => (
            <div key={doc.id} className="bg-white rounded-xl border p-5">
              <div className="flex items-center justify-between">
                <div>
                  <p className="font-semibold text-gray-900 text-sm">{doc.label}</p>
                  <p className="text-xs text-gray-400 mt-0.5">
                    {doc.released_at
                      ? `Received ${new Date(doc.released_at).toLocaleDateString('en-GB', {day:'numeric',month:'long',year:'numeric'})}`
                      : ''}
                  </p>
                </div>
                <span className={`text-xs font-semibold px-2.5 py-1 rounded-full
                  ${doc.status === 'signed' ? 'bg-green-100 text-green-700' : 'bg-amber-100 text-amber-700'}`}>
                  {doc.status === 'signed' ? '✓ Signed' : 'Awaiting Signature'}
                </span>
              </div>

              <div className="flex items-center gap-2 mt-4">
                <a
                  href={`/client/my-audit-set/documents/${doc.id}/download`}
                  target="_blank"
                  className="text-sm text-[#1A4731] border border-[#1A4731] px-3 py-1.5 rounded-lg hover:bg-green-50 transition-colors"
                >
                  Download
                </a>
                {doc.status !== 'signed' && (
                  <button
                    onClick={() => requestOtp(doc.id)}
                    className="text-sm bg-[#1A4731] text-white px-3 py-1.5 rounded-lg hover:bg-[#143828] transition-colors"
                  >
                    Sign Document
                  </button>
                )}
                {doc.status === 'signed' && doc.signed_at && (
                  <span className="text-xs text-gray-400">
                    Signed on {new Date(doc.signed_at).toLocaleDateString('en-GB', {day:'numeric',month:'long',year:'numeric'})}
                  </span>
                )}
              </div>

              {/* OTP modal inline */}
              {signingDoc === doc.id && (
                <div className="mt-4 bg-gray-50 rounded-lg p-4 border">
                  {!otpSent ? (
                    <div>
                      {signLoading
                        ? <p className="text-sm text-gray-500">Sending code...</p>
                        : <p className="text-sm text-gray-600">Sending a 6-digit code to your email...</p>
                      }
                    </div>
                  ) : (
                    <div>
                      <p className="text-sm font-medium text-gray-700 mb-2">Enter the 6-digit code sent to your email:</p>
                      <div className="flex gap-2">
                        <input
                          className="border rounded-lg px-3 py-2 text-sm w-36 text-center font-mono tracking-widest focus:outline-none focus:ring-2 focus:ring-[#1A4731]/30"
                          placeholder="000000"
                          maxLength={6}
                          value={otpValue}
                          onChange={e => setOtpValue(e.target.value.replace(/\D/g, ''))}
                        />
                        <button
                          onClick={() => submitOtp(doc.id)}
                          disabled={otpValue.length !== 6 || signLoading}
                          className="bg-[#1A4731] text-white px-4 py-2 rounded-lg text-sm disabled:opacity-40"
                        >
                          {signLoading ? '...' : 'Confirm'}
                        </button>
                        <button
                          onClick={() => { setSigningDoc(null); setOtpSent(false); setOtpValue('') }}
                          className="text-gray-400 text-sm px-2"
                        >
                          Cancel
                        </button>
                      </div>
                      <button onClick={() => requestOtp(doc.id)} className="text-xs text-gray-400 mt-2 underline">
                        Resend code
                      </button>
                    </div>
                  )}
                  {signError && <p className="text-xs text-red-500 mt-2">{signError}</p>}
                </div>
              )}
            </div>
          ))}
        </div>
      )}
    </div>
  )
}
```

#### Add client document shorthand routes to `backend/audit_set/client_router.py`

The client documents page needs client-scoped routes (so the client can't access other audit sets' documents):

```python
from audit_set.db_models import AuditSetSharedDocument

@router.get("/my-audit-set/documents")
def get_my_documents(
    db: Session = Depends(get_db),
    current_user: PlatformUser = Depends(get_current_user),
):
    audit_set = _get_client_audit_set(current_user, db)
    docs = (
        db.query(AuditSetSharedDocument)
        .filter_by(audit_set_id=audit_set.id, direction="cb_to_client")
        .order_by(AuditSetSharedDocument.created_at)
        .all()
    )
    return [
        {
            "id": d.id, "label": d.label, "document_type": d.document_type,
            "status": d.status,
            "released_at": d.released_at.isoformat() if d.released_at else None,
            "signed_at":   d.signed_at.isoformat()   if d.signed_at   else None,
        }
        for d in docs
    ]

@router.get("/my-audit-set/documents/{doc_id}/download")
def download_my_document(
    doc_id: str,
    db: Session = Depends(get_db),
    current_user: PlatformUser = Depends(get_current_user),
):
    from fastapi.responses import FileResponse
    import os
    audit_set = _get_client_audit_set(current_user, db)
    doc = db.query(AuditSetSharedDocument).filter_by(
        id=doc_id, audit_set_id=audit_set.id, direction="cb_to_client"
    ).first()
    if not doc or not doc.file_path or not os.path.exists(doc.file_path):
        raise HTTPException(404, "Document not found")
    filename = os.path.basename(doc.file_path)
    return FileResponse(doc.file_path, filename=filename,
                        media_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document")

@router.post("/my-audit-set/documents/{doc_id}/sign/request-otp")
def client_request_otp(doc_id: str, db=Depends(get_db), auth_db=Depends(get_auth_db), current_user=Depends(get_current_user)):
    # Delegate to documents_router logic
    from audit_set.documents_router import request_sign_otp
    audit_set = _get_client_audit_set(current_user, db)
    # Call the main implementation
    return request_sign_otp(audit_set.id, doc_id, db, auth_db, current_user)

@router.post("/my-audit-set/documents/{doc_id}/sign/verify")
def client_verify_otp(doc_id: str, otp: str, request: Request, db=Depends(get_db), current_user=Depends(get_current_user)):
    from audit_set.documents_router import verify_sign_otp
    audit_set = _get_client_audit_set(current_user, db)
    return verify_sign_otp(audit_set.id, doc_id, request, otp, db, current_user)
```

#### Add "Release to Client" button to CB audit set detail page

In `frontend/src/app/(app)/clients/[id]/page.tsx`, add a "Shared Documents" section
(after the Messages section added in Prompt 6):

```tsx
// Show documents already released, and a "Release Document" button
// The button opens a small modal: select which generated document to release
// (list comes from the already-generated audit package files if they exist)
// For now, a simple form: label + file path input (CB can paste the server path)
```

This can be a simple admin UI — a modal with:
- Label field (e.g. "Quotation (FR.220)")
- Document type selector (quotation / agreement / certificate)
- File path (server path — CB pastes the path from the generated package)
- "Release to Client" button → calls POST `/audit-sets/{id}/documents/release`

And below it, a list of already-released documents with their status (released / signed).

### Verify

1. CB releases a document → client gets email notification
2. Client sees document in portal, clicks Sign → gets OTP email
3. Client enters OTP → document shows as "✓ Signed"
4. CB sees the signed status in the documents list
5. Download works for both CB and client
6. Existing document generation (packager/filler) is completely untouched

### Commit and push

Commit: `feat(portal): document sharing + OTP signing`
Push to main.

## Files to create/edit
- `backend/audit_set/documents_router.py` — new
- `backend/audit_set/client_router.py` — add document endpoints (additive)
- `backend/main.py` — register documents_router
- `frontend/src/app/(client)/client/documents/page.tsx` — replace placeholder
- `frontend/src/app/(app)/clients/[id]/page.tsx` — add shared documents section (additive)
