# AUGMENT PROMPT — Portal 11: Release Document via File Upload

## Context

Certiva — FastAPI backend + Next.js 14 App Router frontend.
DO NOT BREAK THE EXISTING PORTAL. This is a targeted replacement of one endpoint and one component.

## Problem

The "Release Document" form on `/clients/[id]` (SharedDocumentsSection) asks for a
"Server file path" — a raw text field expecting a server-side path like `/path/to/generated.docx`.
This is unusable: the CB downloads the audit package to their laptop, not the server.

## Fix

Replace the `file_path` JSON field with a real file upload — same pattern as the existing
`POST /audit-sets/{id}/documents/upload` (auditor upload endpoint in documents_router.py).

---

## Backend — `backend/audit_set/documents_router.py`

### 1. Change the `release_document` endpoint signature

The current endpoint is:
```
@router.post("/{audit_set_id}/documents/release")
def release_document(audit_set_id, payload: DocumentReleaseSchema, ...)
```

Change it to accept a multipart upload:

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

    # Save file to persistent storage
    settings = get_settings()
    upload_dir = os.path.join(settings.storage_base_path, "shared_docs", audit_set_id)
    os.makedirs(upload_dir, exist_ok=True)
    safe_name = f"{secrets.token_hex(6)}_{file.filename}"
    file_path = os.path.join(upload_dir, safe_name)
    content = await file.read()
    with open(file_path, "wb") as f:
        f.write(content)

    doc = AuditSetSharedDocument(
        audit_set_id=audit_set_id,
        label=label,
        document_type=document_type,
        file_path=file_path,
        direction="cb_to_client",
        status="released",
        released_by=current_user.id,
        released_at=datetime.utcnow(),
    )
    db.add(doc)
    db.commit()
    db.refresh(doc)

    # Auto-advance workflow + notify client
    _auto_advance_workflow(audit_set_id, "in_planning", "quotation_sent",
                           current_user.id, "Quotation document released", db, auth_db)

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

### 2. Remove the `DocumentReleaseSchema` class

It is no longer needed (the fields now come as `Form(...)` parameters). Delete:
```python
class DocumentReleaseSchema(BaseModel):
    label: str
    document_type: str
    file_path: str
```

### 3. Add missing imports if not already present

```python
from fastapi import Form, UploadFile, File
import secrets
```
`secrets` and `UploadFile`/`File` are already used by `upload_audit_document` — just confirm
they're imported at the top of the file and add any that are missing.

---

## Frontend — `frontend/src/components/ui/SharedDocumentsSection.tsx`

Replace the entire component with the updated version below. The only changes are:
- Remove `filePath` / `setFilePath` state
- Add `file` / `setFile` state (`File | null`)
- Replace the "Server file path" text input with `<input type="file" accept=".docx,.pdf">`
- Change `release()` to use `FormData` + `api.post(..., formData, { headers: { 'Content-Type': 'multipart/form-data' } })`
- Validation: require `file` instead of `filePath`

```tsx
'use client'

import { useEffect, useRef, useState } from 'react'
import api from '@/lib/api'

interface SharedDoc {
  id: string
  label: string
  document_type: string
  direction: 'cb_to_client' | 'auditor_to_cb'
  status: 'released' | 'signed' | 'uploaded'
  released_at: string | null
  signed_at: string | null
  signed_by: string | null
}

const DOC_TYPES = [
  { value: 'quotation',   label: 'Quotation' },
  { value: 'agreement',   label: 'Agreement' },
  { value: 'certificate', label: 'Certificate' },
]

function fmtDate(iso: string | null): string {
  if (!iso) return '—'
  return new Date(iso).toLocaleDateString('en-GB', {
    day: 'numeric', month: 'short', year: 'numeric',
  })
}

export function SharedDocumentsSection({ auditSetId }: { auditSetId: string }) {
  const [docs, setDocs]         = useState<SharedDoc[]>([])
  const [loading, setLoading]   = useState(true)
  const [showForm, setShowForm] = useState(false)
  const [label, setLabel]       = useState('')
  const [docType, setDocType]   = useState('quotation')
  const [file, setFile]         = useState<File | null>(null)
  const [submitting, setSubmitting] = useState(false)
  const [error, setError]       = useState('')
  const fileRef = useRef<HTMLInputElement>(null)

  async function load() {
    try {
      const r = await api.get<SharedDoc[]>(`/audit-sets/${auditSetId}/documents`)
      setDocs(r.data)
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => { load() }, [auditSetId])

  async function release() {
    setError('')
    if (!label.trim()) { setError('Label is required.'); return }
    if (!file)         { setError('Please select a file to upload.'); return }
    setSubmitting(true)
    try {
      const fd = new FormData()
      fd.append('label', label.trim())
      fd.append('document_type', docType)
      fd.append('file', file)
      await api.post(`/audit-sets/${auditSetId}/documents/release`, fd, {
        headers: { 'Content-Type': 'multipart/form-data' },
      })
      setLabel(''); setFile(null); setDocType('quotation')
      if (fileRef.current) fileRef.current.value = ''
      setShowForm(false)
      await load()
    } catch (err: unknown) {
      const detail = (err as { response?: { data?: { detail?: string } } })
        ?.response?.data?.detail
      setError(detail || 'Failed to release document.')
    } finally {
      setSubmitting(false)
    }
  }

  async function downloadDoc(docId: string, docLabel: string) {
    try {
      const r = await api.get(
        `/audit-sets/${auditSetId}/documents/${docId}/download`,
        { responseType: 'blob' },
      )
      const url = window.URL.createObjectURL(r.data as Blob)
      const a = document.createElement('a')
      a.href = url
      a.download = docLabel
      document.body.appendChild(a)
      a.click()
      a.remove()
      window.URL.revokeObjectURL(url)
    } catch {
      alert('Could not download document.')
    }
  }

  return (
    <div className="mt-8">
      <div className="mb-3 flex items-center justify-between">
        <h2 className="text-sm font-semibold uppercase tracking-wide text-gray-700">
          Shared Documents
        </h2>
        <button
          type="button"
          onClick={() => setShowForm((s) => !s)}
          className="rounded-lg bg-[#1A4731] px-3 py-1.5 text-xs font-medium text-white hover:bg-[#143828]"
        >
          {showForm ? 'Cancel' : '+ Release Document'}
        </button>
      </div>

      {showForm && (
        <div className="mb-4 rounded-xl border bg-white p-4">
          <div className="grid grid-cols-1 gap-3 md:grid-cols-3">
            <div>
              <label className="block text-xs font-medium text-gray-500">Label</label>
              <input
                value={label}
                onChange={(e) => setLabel(e.target.value)}
                placeholder="Quotation (FR.220)"
                className="mt-1 w-full rounded-lg border px-3 py-1.5 text-sm focus:outline-none focus:ring-2 focus:ring-[#1A4731]/30"
              />
            </div>
            <div>
              <label className="block text-xs font-medium text-gray-500">Type</label>
              <select
                value={docType}
                onChange={(e) => setDocType(e.target.value)}
                className="mt-1 w-full rounded-lg border px-3 py-1.5 text-sm focus:outline-none focus:ring-2 focus:ring-[#1A4731]/30"
              >
                {DOC_TYPES.map((t) => (
                  <option key={t.value} value={t.value}>{t.label}</option>
                ))}
              </select>
            </div>
            <div>
              <label className="block text-xs font-medium text-gray-500">File</label>
              <input
                ref={fileRef}
                type="file"
                accept=".docx,.pdf"
                onChange={(e) => setFile(e.target.files?.[0] ?? null)}
                className="mt-1 w-full rounded-lg border px-3 py-1.5 text-sm text-gray-700 file:mr-2 file:rounded file:border-0 file:bg-gray-100 file:px-2 file:py-0.5 file:text-xs focus:outline-none"
              />
            </div>
          </div>
          {error && <p className="mt-2 text-xs text-red-500">{error}</p>}
          <button
            type="button"
            onClick={release}
            disabled={submitting}
            className="mt-3 rounded-lg bg-[#1A4731] px-4 py-1.5 text-sm font-medium text-white disabled:opacity-40"
          >
            {submitting ? 'Uploading…' : 'Release to Client'}
          </button>
        </div>
      )}

      <div className="rounded-xl border bg-white">
        {loading ? (
          <p className="p-6 text-sm text-gray-400">Loading…</p>
        ) : docs.length === 0 ? (
          <p className="p-6 text-sm text-gray-400">No documents released yet.</p>
        ) : (
          <ul className="divide-y">
            {docs.map((d) => (
              <li key={d.id} className="flex items-center justify-between px-4 py-3">
                <div>
                  <p className="text-sm font-medium text-gray-800">{d.label}</p>
                  <p className="mt-0.5 text-xs text-gray-400">
                    {d.direction === 'auditor_to_cb' ? 'Auditor upload' : 'Released'}
                    {' · '}{fmtDate(d.released_at)}
                    {d.signed_at && ` · Signed ${fmtDate(d.signed_at)}`}
                  </p>
                </div>
                <div className="flex items-center gap-2">
                  <span
                    className={`rounded-full px-2 py-0.5 text-xs font-semibold ${
                      d.status === 'signed'    ? 'bg-green-100 text-green-700'
                      : d.status === 'uploaded' ? 'bg-blue-100 text-blue-700'
                      : 'bg-amber-100 text-amber-700'
                    }`}
                  >
                    {d.status === 'signed' ? '✓ Signed' : d.status === 'uploaded' ? 'Uploaded' : 'Awaiting Signature'}
                  </span>
                  <button
                    type="button"
                    onClick={() => downloadDoc(d.id, d.label)}
                    className="rounded-lg border border-gray-300 px-2.5 py-1 text-xs text-gray-700 hover:bg-gray-50"
                  >
                    Download
                  </button>
                </div>
              </li>
            ))}
          </ul>
        )}
      </div>
    </div>
  )
}
```

---

## Verification

1. `python3 -m py_compile backend/audit_set/documents_router.py`
2. `cd frontend && npx tsc --noEmit`
3. Confirm `/docs` shows `POST /audit-sets/{id}/documents/release` accepts `multipart/form-data`
4. Test: click "+ Release Document" → pick a .docx file → click "Release to Client" → confirm it appears in the document list and the client can download it
5. Commit and push to main

---

## Bug fix — `backend/audit_set/client_router.py`

The `client_verify_otp` wrapper route is missing `auth_db`. The core `verify_sign_otp`
function needs it for the auto-advance workflow step. Without it, the document IS signed
(committed before the crash) but the client sees a 500 error anyway.

Find this function in `client_router.py`:

```python
@router.post("/my-audit-set/documents/{doc_id}/sign/verify")
def client_verify_otp(
    doc_id: str,
    otp: str,
    request: Request,
    db: Session = Depends(get_db),
    current_user: PlatformUser = Depends(get_current_user),
):
    from audit_set.documents_router import verify_sign_otp
    audit_set = _get_client_audit_set(current_user, db)
    return verify_sign_otp(audit_set.id, doc_id, request, otp, db, current_user)
```

Replace with:

```python
@router.post("/my-audit-set/documents/{doc_id}/sign/verify")
def client_verify_otp(
    doc_id: str,
    otp: str,
    request: Request,
    db: Session = Depends(get_db),
    auth_db: Session = Depends(get_auth_db),
    current_user: PlatformUser = Depends(get_current_user),
):
    from audit_set.documents_router import verify_sign_otp
    audit_set = _get_client_audit_set(current_user, db)
    return verify_sign_otp(audit_set.id, doc_id, request, otp, db, auth_db, current_user)
```

`get_auth_db` is already imported at the top of `client_router.py` — just add it to the
function signature and pass it through.

---

## Constraint
Do not change any other endpoint, component, or page. Only these three files are modified:
- `backend/audit_set/documents_router.py` — `release_document` endpoint to file upload
- `frontend/src/components/ui/SharedDocumentsSection.tsx` — file picker UI
- `backend/audit_set/client_router.py` — `client_verify_otp` auth_db fix
