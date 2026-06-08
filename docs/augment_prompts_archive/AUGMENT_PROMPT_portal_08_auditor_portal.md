# Portal Build — Prompt 8 of 8: Auditor Portal

## ⚠️ CRITICAL: DO NOT BREAK THE EXISTING PORTAL
- The `(app)` route group is untouched. Do NOT change any existing page.
- The existing `auditor` role in `platform_users` may already be used for internal access.
  Do NOT change how auditor-role users currently log in or what they currently see in `(app)`.
- This prompt adds a NEW `(auditor)` route group at `/auditor/*` as ADDITIONAL pages.
- Auditor users who log in will be redirected to `/auditor/dashboard` (added to the login redirect
  logic from Prompt 5). If that already redirects auditors to `/dashboard` (the internal portal),
  check with the existing behavior and only change the redirect for auditor-role users IF they
  currently land on an empty/incorrect state. If the existing audit portal works fine for auditors,
  leave the redirect alone and just add `/auditor/*` as supplemental pages they can navigate to.

---

## Context

Auditors have their own portal where they can:
1. See their assigned audit sets (where they are lead auditor or team member)
2. Download the pre-filled audit document package
3. Upload completed audit documents back to CB
4. Message the client

An auditor's `PlatformUser.auditor_id` links to their profile in `auditors.auditors`.
The audit set's `stage.lead_auditor_id` or `stage.auditors[].id` contains the auditor's profile ID.

---

## Task

### Backend: Auditor portal API

#### New file: `backend/audit_set/auditor_router.py`

```python
"""
BATUHAN — Auditor portal API.
Routes for auditor-role users to view their assigned audit sets.
"""
from __future__ import annotations
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from audit_set.db_models import AuditSet, AuditSetStage, AuditSetMessage, AuditSetSharedDocument, get_db
from auth.db_models import PlatformUser, get_db as get_auth_db
from auth.router import get_current_user

router = APIRouter(prefix="/auditor", tags=["auditor-portal"])


def _require_auditor(current_user: PlatformUser) -> PlatformUser:
    if current_user.role not in {"auditor", "admin"}:
        raise HTTPException(403, "Auditor portal access only")
    return current_user


def _get_auditor_assignments(current_user: PlatformUser, db: Session) -> list[AuditSet]:
    """
    Find all audit sets where this auditor is assigned.
    Checks stage.lead_auditor_id == auditor_id OR auditor appears in stage.auditors JSON.
    """
    if not current_user.auditor_id:
        return []

    auditor_id = current_user.auditor_id

    # Find stages where this auditor is lead or team member
    stages = db.query(AuditSetStage).all()
    matching_audit_set_ids: set[str] = set()

    for stage in stages:
        if stage.lead_auditor_id == auditor_id:
            matching_audit_set_ids.add(stage.audit_set_id)
            continue
        # Check auditors JSON array
        for a in (stage.auditors or []):
            if isinstance(a, dict) and a.get("id") == auditor_id:
                matching_audit_set_ids.add(stage.audit_set_id)
                break

    if not matching_audit_set_ids:
        return []

    return (
        db.query(AuditSet)
        .filter(AuditSet.id.in_(matching_audit_set_ids))
        .order_by(AuditSet.created_at.desc())
        .all()
    )


@router.get("/my-assignments")
def get_my_assignments(
    db: Session = Depends(get_db),
    current_user: PlatformUser = Depends(get_current_user),
):
    _require_auditor(current_user)
    audit_sets = _get_auditor_assignments(current_user, db)

    result = []
    for a in audit_sets:
        # Find the relevant stage(s) for this auditor
        my_stages = []
        for s in (a.stages or []):
            is_lead = s.lead_auditor_id == current_user.auditor_id
            is_team = any(
                isinstance(x, dict) and x.get("id") == current_user.auditor_id
                for x in (s.auditors or [])
            )
            if is_lead or is_team:
                my_stages.append({
                    "stage_type":       s.stage_type,
                    "audit_date_start": s.audit_date_start.isoformat() if s.audit_date_start else None,
                    "audit_date_end":   s.audit_date_end.isoformat()   if s.audit_date_end   else None,
                    "is_lead":          is_lead,
                    "status":           s.status,
                })
        result.append({
            "id":            a.id,
            "plan_number":   a.plan_number,
            "company_name":  a.company_name,
            "company_address": a.company_address,
            "standards":     a.standards,
            "audit_type":    a.audit_type,
            "scope_en":      a.scope_en,
            "workflow_status": a.workflow_status,
            "my_stages":     my_stages,
        })
    return result


@router.get("/my-assignments/{audit_set_id}")
def get_assignment_detail(
    audit_set_id: str,
    db: Session = Depends(get_db),
    current_user: PlatformUser = Depends(get_current_user),
):
    _require_auditor(current_user)
    # Verify this auditor is actually assigned
    assigned_ids = {a.id for a in _get_auditor_assignments(current_user, db)}
    if audit_set_id not in assigned_ids:
        raise HTTPException(403, "Not assigned to this audit set")

    audit_set = db.query(AuditSet).filter_by(id=audit_set_id).first()
    if not audit_set:
        raise HTTPException(404, "Not found")

    stages_out = []
    for s in (audit_set.stages or []):
        stages_out.append({
            "stage_type":        s.stage_type,
            "stage_order":       s.stage_order,
            "audit_date_start":  s.audit_date_start.isoformat() if s.audit_date_start else None,
            "audit_date_end":    s.audit_date_end.isoformat()   if s.audit_date_end   else None,
            "lead_auditor_name": s.lead_auditor_name,
            "audit_days":        s.audit_days,
            "status":            s.status,
        })

    return {
        "id":              audit_set.id,
        "plan_number":     audit_set.plan_number,
        "client_reference": audit_set.client_reference,
        "company_name":    audit_set.company_name,
        "company_address": audit_set.company_address,
        "email":           audit_set.email,
        "phone":           audit_set.phone,
        "representative":  audit_set.representative,
        "standards":       audit_set.standards,
        "audit_type":      audit_set.audit_type,
        "scope_en":        audit_set.scope_en,
        "non_applicable_clauses": audit_set.non_applicable_clauses,
        "ea_code":         audit_set.ea_code,
        "ea_category":     audit_set.ea_category,
        "accreditation_body": audit_set.accreditation_body,
        "workflow_status": audit_set.workflow_status,
        "stages":          stages_out,
    }


@router.get("/my-assignments/{audit_set_id}/messages")
def get_assignment_messages(
    audit_set_id: str,
    db: Session = Depends(get_db),
    current_user: PlatformUser = Depends(get_current_user),
):
    _require_auditor(current_user)
    assigned_ids = {a.id for a in _get_auditor_assignments(current_user, db)}
    if audit_set_id not in assigned_ids:
        raise HTTPException(403, "Not assigned")

    msgs = (
        db.query(AuditSetMessage)
        .filter_by(audit_set_id=audit_set_id)
        .order_by(AuditSetMessage.created_at)
        .all()
    )
    return [
        {
            "id": m.id,
            "sender_name": m.sender_name,
            "sender_role": m.sender_role,
            "body": m.body,
            "created_at": m.created_at.isoformat(),
            "is_mine": m.sender_user_id == current_user.id,
        }
        for m in msgs
    ]


@router.post("/my-assignments/{audit_set_id}/messages")
def post_assignment_message(
    audit_set_id: str,
    payload: dict,
    db: Session = Depends(get_db),
    current_user: PlatformUser = Depends(get_current_user),
):
    _require_auditor(current_user)
    assigned_ids = {a.id for a in _get_auditor_assignments(current_user, db)}
    if audit_set_id not in assigned_ids:
        raise HTTPException(403, "Not assigned")

    body = (payload.get("body") or "").strip()
    if not body:
        raise HTTPException(400, "Message body required")

    msg = AuditSetMessage(
        audit_set_id=audit_set_id,
        sender_user_id=current_user.id,
        sender_name=current_user.full_name,
        sender_role="auditor",
        body=body,
    )
    db.add(msg)
    db.commit()
    return {"id": msg.id}
```

Register in `backend/main.py`:
```python
from audit_set.auditor_router import router as auditor_router
app.include_router(auditor_router)
```

### Frontend: Auditor portal

#### New file: `frontend/src/app/(auditor)/layout.tsx`

```tsx
'use client'
import { useEffect } from 'react'
import { useRouter } from 'next/navigation'
import { useAuth } from '@/lib/auth'

export default function AuditorLayout({ children }: { children: React.ReactNode }) {
  const { user, isLoading } = useAuth()
  const router = useRouter()

  useEffect(() => {
    if (!isLoading && !user) router.push('/login')
    // Only auditor and admin can access this portal
    if (!isLoading && user && !['auditor', 'admin'].includes(user.role)) {
      router.push('/dashboard')
    }
  }, [user, isLoading])

  if (isLoading || !user) return null

  return (
    <div className="min-h-screen bg-gray-50 flex">
      <aside className="w-56 bg-white border-r shrink-0 flex flex-col">
        <div className="p-5 border-b">
          <p className="text-sm font-bold text-[#1A4731]">IFC Global</p>
          <p className="text-xs text-gray-400 mt-0.5 truncate">{user.full_name}</p>
          <span className="text-xs bg-orange-100 text-orange-700 px-1.5 py-0.5 rounded mt-1 inline-block">Auditor</span>
        </div>
        <nav className="p-4 space-y-1 flex-1">
          <a href="/auditor/dashboard" className="block px-3 py-2 rounded-lg text-sm text-gray-700 hover:bg-gray-100">My Audits</a>
        </nav>
        <div className="p-4 border-t">
          <button
            onClick={() => { localStorage.removeItem('certiva_token'); router.push('/login') }}
            className="text-xs text-gray-400 hover:text-gray-600"
          >
            Sign out
          </button>
        </div>
      </aside>
      <main className="flex-1 overflow-auto">{children}</main>
    </div>
  )
}
```

#### New file: `frontend/src/app/(auditor)/auditor/dashboard/page.tsx`

```tsx
'use client'
import { useEffect, useState } from 'react'
import { useRouter } from 'next/navigation'
import api from '@/lib/api'

const STANDARD_NAMES: Record<string, string> = {
  QMS: 'ISO 9001', EMS: 'ISO 14001', OHSMS: 'ISO 45001',
  FSMS: 'ISO 22000', ISMS: 'ISO 27001', ENMS: 'ISO 50001',
  MDQMS: 'ISO 13485', ABMS: 'ISO 37001',
}

export default function AuditorDashboard() {
  const router = useRouter()
  const [assignments, setAssignments] = useState<any[]>([])
  const [loading, setLoading] = useState(true)

  useEffect(() => {
    api.get('/auditor/my-assignments')
      .then(r => setAssignments(r.data))
      .finally(() => setLoading(false))
  }, [])

  if (loading) return <div className="p-8 text-gray-400">Loading your assignments...</div>

  return (
    <div className="p-6 max-w-4xl mx-auto">
      <div className="mb-6">
        <h1 className="text-xl font-bold text-gray-900">My Audit Assignments</h1>
        <p className="text-sm text-gray-400 mt-0.5">{assignments.length} audit{assignments.length !== 1 ? 's' : ''} assigned</p>
      </div>

      {assignments.length === 0 ? (
        <div className="text-center py-16 text-gray-400 text-sm">No assignments yet.</div>
      ) : (
        <div className="space-y-3">
          {assignments.map(a => {
            const nextStage = a.my_stages?.find((s: any) => s.status !== 'complete')
                           || a.my_stages?.[0]
            return (
              <div
                key={a.id}
                className="bg-white border rounded-xl p-5 hover:shadow-sm transition-shadow cursor-pointer"
                onClick={() => router.push(`/auditor/audit/${a.id}`)}
              >
                <div className="flex items-start justify-between">
                  <div className="flex-1 min-w-0">
                    <h3 className="font-semibold text-gray-900">{a.company_name}</h3>
                    <p className="text-xs text-gray-400 mt-0.5 truncate">{a.company_address}</p>
                    <div className="flex flex-wrap gap-1.5 mt-2">
                      {(a.standards || []).map((s: string) => (
                        <span key={s} className="text-xs bg-blue-50 text-blue-700 px-2 py-0.5 rounded">
                          {STANDARD_NAMES[s] || s}
                        </span>
                      ))}
                    </div>
                    {a.scope_en && (
                      <p className="text-xs text-gray-400 italic mt-1 truncate">"{a.scope_en}"</p>
                    )}
                  </div>
                  <div className="ml-4 text-right shrink-0">
                    {nextStage?.audit_date_start && (
                      <p className="text-sm font-semibold text-gray-800">
                        {new Date(nextStage.audit_date_start).toLocaleDateString('en-GB', {day:'numeric',month:'short',year:'numeric'})}
                      </p>
                    )}
                    {nextStage && (
                      <p className="text-xs text-gray-400 mt-0.5">
                        {nextStage.stage_type?.replace('_', ' ')} {nextStage.is_lead ? '· Lead' : ''}
                      </p>
                    )}
                  </div>
                </div>
              </div>
            )
          })}
        </div>
      )}
    </div>
  )
}
```

#### New file: `frontend/src/app/(auditor)/auditor/audit/[id]/page.tsx`

```tsx
'use client'
import { useEffect, useState } from 'react'
import { useParams } from 'next/navigation'
import api from '@/lib/api'
import { MessageThread } from '@/components/ui/MessageThread'

export default function AuditorAuditDetail() {
  const { id } = useParams<{ id: string }>()
  const [data, setData] = useState<any>(null)
  const [tab, setTab]   = useState<'overview' | 'messages' | 'upload'>('overview')
  const [uploading, setUploading] = useState(false)
  const [uploadLabel, setUploadLabel] = useState('')
  const [uploadFile, setUploadFile]   = useState<File | null>(null)
  const [uploadMsg, setUploadMsg]     = useState('')

  useEffect(() => {
    api.get(`/auditor/my-assignments/${id}`).then(r => setData(r.data))
  }, [id])

  async function handleUpload() {
    if (!uploadFile || !uploadLabel.trim()) return
    setUploading(true)
    setUploadMsg('')
    try {
      const form = new FormData()
      form.append('file', uploadFile)
      form.append('label', uploadLabel)
      await api.post(`/audit-sets/${id}/documents/upload?label=${encodeURIComponent(uploadLabel)}`, form, {
        headers: { 'Content-Type': 'multipart/form-data' },
      })
      setUploadMsg('Document uploaded successfully.')
      setUploadFile(null)
      setUploadLabel('')
    } catch (e: any) {
      setUploadMsg(e?.response?.data?.detail || 'Upload failed')
    } finally {
      setUploading(false)
    }
  }

  if (!data) return <div className="p-8 text-gray-400">Loading...</div>

  const STANDARD_NAMES: Record<string, string> = {
    QMS: 'ISO 9001:2015', EMS: 'ISO 14001:2015', OHSMS: 'ISO 45001:2018',
    FSMS: 'ISO 22000:2018', ISMS: 'ISO/IEC 27001:2022',
  }

  return (
    <div className="p-6 max-w-3xl mx-auto">
      {/* Header */}
      <div className="mb-6">
        <h1 className="text-xl font-bold text-gray-900">{data.company_name}</h1>
        <p className="text-sm text-gray-400 mt-0.5">{data.company_address}</p>
        <div className="flex gap-2 mt-2 flex-wrap">
          {(data.standards || []).map((s: string) => (
            <span key={s} className="text-xs bg-blue-50 text-blue-700 px-2 py-0.5 rounded">
              {STANDARD_NAMES[s] || s}
            </span>
          ))}
        </div>
      </div>

      {/* Tabs */}
      <div className="flex gap-1 bg-gray-100 p-1 rounded-lg mb-6 w-fit">
        {(['overview', 'messages', 'upload'] as const).map(t => (
          <button
            key={t}
            onClick={() => setTab(t)}
            className={`px-4 py-1.5 rounded-md text-sm font-medium transition-colors capitalize
              ${tab === t ? 'bg-white text-gray-900 shadow-sm' : 'text-gray-500 hover:text-gray-700'}`}
          >
            {t === 'upload' ? 'Upload Documents' : t.charAt(0).toUpperCase() + t.slice(1)}
          </button>
        ))}
      </div>

      {/* Overview tab */}
      {tab === 'overview' && (
        <div className="space-y-4">
          <div className="bg-white rounded-xl border p-5 grid grid-cols-2 gap-4 text-sm">
            <div>
              <p className="text-xs text-gray-400 uppercase tracking-wide mb-1">Contact</p>
              <p className="font-medium">{data.representative || '—'}</p>
              <p className="text-gray-500">{data.email}</p>
              <p className="text-gray-500">{data.phone}</p>
            </div>
            <div>
              <p className="text-xs text-gray-400 uppercase tracking-wide mb-1">Accreditation</p>
              <p className="font-medium">{data.accreditation_body}</p>
              <p className="text-gray-500">{data.audit_type?.replace('_', ' ')}</p>
            </div>
          </div>

          {data.scope_en && (
            <div className="bg-white rounded-xl border p-5">
              <p className="text-xs text-gray-400 uppercase tracking-wide mb-2">Scope</p>
              <p className="text-sm text-gray-700">{data.scope_en}</p>
            </div>
          )}

          {data.non_applicable_clauses && (
            <div className="bg-white rounded-xl border p-5">
              <p className="text-xs text-gray-400 uppercase tracking-wide mb-2">Non-Applicable Clauses</p>
              <p className="text-sm text-gray-700">{data.non_applicable_clauses}</p>
            </div>
          )}

          <div className="bg-white rounded-xl border p-5">
            <p className="text-xs text-gray-400 uppercase tracking-wide mb-3">Audit Stages</p>
            <div className="space-y-2">
              {(data.stages || []).map((s: any, i: number) => (
                <div key={i} className="flex items-center justify-between text-sm">
                  <span className="text-gray-700 capitalize">{s.stage_type?.replace('_', ' ')}</span>
                  <span className="text-gray-500">
                    {s.audit_date_start
                      ? new Date(s.audit_date_start).toLocaleDateString('en-GB', {day:'numeric',month:'short',year:'numeric'})
                      : 'TBD'}
                    {s.audit_date_end && s.audit_date_end !== s.audit_date_start
                      ? ` – ${new Date(s.audit_date_end).toLocaleDateString('en-GB', {day:'numeric',month:'short'})}`
                      : ''}
                  </span>
                </div>
              ))}
            </div>
          </div>

          <a
            href={`/audit-sets/${id}/download`}
            target="_blank"
            className="block w-full text-center bg-[#1A4731] text-white py-3 rounded-xl font-medium hover:bg-[#143828] transition-colors"
          >
            Download Audit Package
          </a>
        </div>
      )}

      {/* Messages tab */}
      {tab === 'messages' && (
        <div className="bg-white rounded-xl border" style={{ height: 500 }}>
          <MessageThread
            fetchUrl={`/auditor/my-assignments/${id}/messages`}
            postUrl={`/auditor/my-assignments/${id}/messages`}
          />
        </div>
      )}

      {/* Upload tab */}
      {tab === 'upload' && (
        <div className="bg-white rounded-xl border p-6 space-y-4">
          <p className="text-sm text-gray-600">
            Upload your completed audit documents here. The CB team will be notified.
          </p>
          <div>
            <label className="block text-sm font-medium text-gray-700 mb-1">Document Label</label>
            <input
              className="w-full border rounded-lg px-3 py-2 text-sm"
              placeholder="e.g. Stage 2 Audit Report, FR.222 filled"
              value={uploadLabel}
              onChange={e => setUploadLabel(e.target.value)}
            />
          </div>
          <div>
            <label className="block text-sm font-medium text-gray-700 mb-1">File</label>
            <input
              type="file"
              onChange={e => setUploadFile(e.target.files?.[0] || null)}
              className="text-sm"
            />
          </div>
          <button
            onClick={handleUpload}
            disabled={!uploadFile || !uploadLabel.trim() || uploading}
            className="bg-[#1A4731] text-white px-6 py-2.5 rounded-lg text-sm disabled:opacity-40"
          >
            {uploading ? 'Uploading...' : 'Upload Document'}
          </button>
          {uploadMsg && <p className="text-sm text-gray-600">{uploadMsg}</p>}
        </div>
      )}
    </div>
  )
}
```

Register in `backend/main.py`:
```python
from audit_set.auditor_router import router as auditor_router
app.include_router(auditor_router)
```

### Verify

1. An auditor-role user who logs in can navigate to `/auditor/dashboard`
2. They see only audit sets they are assigned to (by auditor_id matching)
3. Audit detail shows client contact info, scope, NAC, stages, audit dates
4. Messages tab shows the same thread as CB/client see
5. Upload tab lets them upload files; files appear in CB portal as documents
6. Existing `(app)` portal behavior for all other roles is completely unchanged

### Commit and push

Commit: `feat(portal): auditor portal — assignments, messaging, document upload`
Push to main.

## Files to create/edit
- `backend/audit_set/auditor_router.py` — new
- `backend/main.py` — register auditor_router
- `frontend/src/app/(auditor)/layout.tsx` — new
- `frontend/src/app/(auditor)/auditor/dashboard/page.tsx` — new
- `frontend/src/app/(auditor)/auditor/audit/[id]/page.tsx` — new
