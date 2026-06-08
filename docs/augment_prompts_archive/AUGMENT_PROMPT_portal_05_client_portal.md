# Portal Build — Prompt 5 of 8: Client Portal Pages

## ⚠️ CRITICAL: DO NOT BREAK THE EXISTING PORTAL
- The `(app)` route group and all its pages are UNTOUCHED
- This prompt adds a NEW `(client)` route group at `/client/*`
- The login page already exists — only add role-based redirect after login, no other changes
- Clients who log in should be redirected to `/client/overview` instead of the internal dashboard

---

## Context

After a client submits an application and receives login credentials, they can log into the
portal. They should see a clean, simple interface — not the full internal CB portal.

The client portal shows:
- **Overview**: Status timeline, key dates (audit scheduled, expiry), who their assigned auditor is
- **Documents**: Documents released to them by CB, with sign button
- **Messages**: Thread with CB / auditor

This prompt builds the portal shell and Overview page. Documents and Messages are built in
Prompts 7 and 6 respectively.

---

## Task

### Backend: Client-specific API endpoints

#### New file: `backend/audit_set/client_router.py`

```python
"""
BATUHAN — Client portal API.
Routes for client-role users to view their own audit set.
"""
from __future__ import annotations
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from audit_set.db_models import AuditSet, AuditSetStatusEvent, get_db
from auth.db_models import PlatformUser, get_db as get_auth_db
from auth.router import get_current_user

router = APIRouter(prefix="/client", tags=["client-portal"])

def _get_client_audit_set(
    current_user: PlatformUser,
    db: Session,
) -> AuditSet:
    """Resolve the audit set belonging to the current client user."""
    if current_user.role != "client":
        raise HTTPException(403, "Client portal access only")
    if not current_user.audit_set_id:
        raise HTTPException(404, "No audit set linked to this account")
    audit_set = db.query(AuditSet).filter_by(id=current_user.audit_set_id).first()
    if not audit_set:
        raise HTTPException(404, "Audit set not found")
    return audit_set


@router.get("/my-audit-set")
def get_my_audit_set(
    db: Session = Depends(get_db),
    current_user: PlatformUser = Depends(get_current_user),
):
    """Returns the client's audit set — filtered to fields safe for client view."""
    audit_set = _get_client_audit_set(current_user, db)

    # Only expose safe fields — never expose fees, internal notes, or CB-only data
    stages_out = []
    for s in (audit_set.stages or []):
        stages_out.append({
            "stage_type":       s.stage_type,
            "stage_order":      s.stage_order,
            "audit_date_start": s.audit_date_start.isoformat() if s.audit_date_start else None,
            "audit_date_end":   s.audit_date_end.isoformat()   if s.audit_date_end   else None,
            "lead_auditor_name": s.lead_auditor_name,
            "status":           s.status,
        })

    return {
        "id":                audit_set.id,
        "plan_number":       audit_set.plan_number,
        "client_reference":  audit_set.client_reference,
        "company_name":      audit_set.company_name,
        "company_address":   audit_set.company_address,
        "standards":         audit_set.standards,
        "audit_type":        audit_set.audit_type,
        "accreditation_body": audit_set.accreditation_body,
        "scope_en":          audit_set.scope_en,
        "workflow_status":   audit_set.workflow_status,
        "cert_issued_date":  audit_set.cert_issued_date.isoformat()  if audit_set.cert_issued_date  else None,
        "cert_expiry_date":  audit_set.cert_expiry_date.isoformat()  if audit_set.cert_expiry_date  else None,
        "cert_status":       audit_set.cert_status,
        "stages":            stages_out,
        "created_at":        audit_set.created_at.isoformat() if audit_set.created_at else None,
    }


@router.get("/my-audit-set/status-history")
def get_my_status_history(
    db: Session = Depends(get_db),
    current_user: PlatformUser = Depends(get_current_user),
):
    audit_set = _get_client_audit_set(current_user, db)
    events = (
        db.query(AuditSetStatusEvent)
        .filter_by(audit_set_id=audit_set.id)
        .order_by(AuditSetStatusEvent.triggered_at)
        .all()
    )
    return [
        {
            "to_status":    e.to_status,
            "triggered_at": e.triggered_at.isoformat(),
            "notes":        e.notes,
        }
        for e in events
    ]
```

Register in `backend/main.py`:
```python
from audit_set.client_router import router as client_router
app.include_router(client_router)
```

### Frontend: Role-based redirect after login

In `frontend/src/app/(auth)/login/page.tsx` (or wherever the login success redirect happens),
find the redirect after successful login and update it to be role-aware:

```tsx
// After successful login:
const { role } = userData  // from the JWT/me response
if (role === 'client') {
  router.push('/client/overview')
} else if (role === 'auditor') {
  router.push('/auditor/dashboard')
} else {
  router.push('/dashboard')   // existing behavior — do NOT change this path
}
```

Also update `frontend/src/lib/auth.tsx` — in the initial hydration `useEffect`, when the user
is loaded from localStorage and the role is `client`, redirect to `/client/overview` if they
try to access an `(app)` page.

### Frontend: Client portal route group

#### New file: `frontend/src/app/(client)/layout.tsx`

```tsx
'use client'
import { useEffect } from 'react'
import { useRouter } from 'next/navigation'
import { useAuth } from '@/lib/auth'

export default function ClientLayout({ children }: { children: React.ReactNode }) {
  const { user, isLoading } = useAuth()
  const router = useRouter()

  useEffect(() => {
    if (!isLoading && !user) router.push('/login')
    if (!isLoading && user && user.role !== 'client') router.push('/dashboard')
  }, [user, isLoading])

  if (isLoading || !user) return null

  return (
    <div className="min-h-screen bg-gray-50 flex">
      {/* Sidebar */}
      <aside className="w-56 bg-white border-r shrink-0 flex flex-col">
        <div className="p-5 border-b">
          <p className="text-sm font-bold text-[#1A4731]">IFC Global</p>
          <p className="text-xs text-gray-400 mt-0.5 truncate">{user.full_name}</p>
        </div>
        <nav className="p-4 space-y-1 flex-1">
          {[
            { href: '/client/overview',  label: 'Overview' },
            { href: '/client/documents', label: 'Documents' },
            { href: '/client/messages',  label: 'Messages' },
          ].map(item => (
            <a
              key={item.href}
              href={item.href}
              className="block px-3 py-2 rounded-lg text-sm text-gray-700 hover:bg-gray-100 transition-colors"
            >
              {item.label}
            </a>
          ))}
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

      {/* Main */}
      <main className="flex-1 overflow-auto">{children}</main>
    </div>
  )
}
```

#### New file: `frontend/src/app/(client)/client/overview/page.tsx`

```tsx
'use client'
import { useEffect, useState } from 'react'
import api from '@/lib/api'

const WORKFLOW_STEPS = [
  { key: 'pending_review',    label: 'Application Received',  desc: 'Your application is being reviewed by our team.' },
  { key: 'in_planning',       label: 'Planning',               desc: 'We are preparing your audit plan and assigning your auditor.' },
  { key: 'quotation_sent',    label: 'Quotation',              desc: 'Your quotation is ready. Please review and sign.' },
  { key: 'agreement_signed',  label: 'Agreement Confirmed',    desc: 'Your agreement has been signed.' },
  { key: 'audit_scheduled',   label: 'Audit Scheduled',        desc: 'Your audit dates have been confirmed.' },
  { key: 'audit_in_progress', label: 'Audit In Progress',      desc: 'Your audit is currently underway.' },
  { key: 'under_review',      label: 'Under Review',           desc: 'The certification committee is reviewing your audit.' },
  { key: 'certified',         label: 'Certified ✓',            desc: 'Congratulations! Your certification has been issued.' },
]

const STANDARD_NAMES: Record<string, string> = {
  QMS: 'ISO 9001:2015', EMS: 'ISO 14001:2015', OHSMS: 'ISO 45001:2018',
  FSMS: 'ISO 22000:2018', ISMS: 'ISO/IEC 27001:2022', ENMS: 'ISO 50001:2018',
  MDQMS: 'ISO 13485:2016', ABMS: 'ISO 37001:2016',
}

export default function ClientOverviewPage() {
  const [data, setData]       = useState<any>(null)
  const [history, setHistory] = useState<any[]>([])
  const [loading, setLoading] = useState(true)

  useEffect(() => {
    Promise.all([
      api.get('/client/my-audit-set'),
      api.get('/client/my-audit-set/status-history'),
    ]).then(([r1, r2]) => {
      setData(r1.data)
      setHistory(r2.data)
    }).finally(() => setLoading(false))
  }, [])

  if (loading) return <div className="p-8 text-gray-400">Loading...</div>
  if (!data)   return <div className="p-8 text-red-500">Could not load your data.</div>

  const currentIdx = WORKFLOW_STEPS.findIndex(s => s.key === data.workflow_status)
  const currentStep = WORKFLOW_STEPS[currentIdx] || WORKFLOW_STEPS[0]

  // Auditor from stage_2 or stage_1
  const auditorName = data.stages?.find((s: any) => s.stage_type === 'stage_2')?.lead_auditor_name
                   || data.stages?.find((s: any) => s.stage_type === 'stage_1')?.lead_auditor_name

  const stage1 = data.stages?.find((s: any) => s.stage_type === 'stage_1')
  const stage2 = data.stages?.find((s: any) => s.stage_type === 'stage_2')

  return (
    <div className="p-6 max-w-3xl mx-auto space-y-6">
      {/* Header */}
      <div>
        <h1 className="text-xl font-bold text-gray-900">{data.company_name}</h1>
        <p className="text-sm text-gray-400 mt-0.5">
          {(data.standards || []).map((s: string) => STANDARD_NAMES[s] || s).join(' · ')}
        </p>
      </div>

      {/* Status Timeline */}
      <div className="bg-white rounded-xl border p-6">
        <h2 className="text-sm font-semibold text-gray-700 mb-5">Certification Progress</h2>
        <div className="space-y-0">
          {WORKFLOW_STEPS.map((step, idx) => {
            const isDone    = idx < currentIdx
            const isCurrent = idx === currentIdx
            const isFuture  = idx > currentIdx
            const histEvent = history.find(h => h.to_status === step.key)

            return (
              <div key={step.key} className="flex gap-4">
                {/* Indicator */}
                <div className="flex flex-col items-center">
                  <div className={`w-7 h-7 rounded-full flex items-center justify-center shrink-0 text-xs font-bold transition-all
                    ${isDone    ? 'bg-[#1A4731] text-white' : ''}
                    ${isCurrent ? 'bg-[#1A4731] text-white ring-4 ring-[#1A4731]/20' : ''}
                    ${isFuture  ? 'bg-gray-100 text-gray-400' : ''}
                  `}>
                    {isDone ? '✓' : idx + 1}
                  </div>
                  {idx < WORKFLOW_STEPS.length - 1 && (
                    <div className={`w-0.5 h-8 mt-1 ${isDone ? 'bg-[#1A4731]' : 'bg-gray-200'}`} />
                  )}
                </div>
                {/* Content */}
                <div className="pb-6 flex-1 min-w-0">
                  <p className={`text-sm font-semibold ${isFuture ? 'text-gray-400' : 'text-gray-800'}`}>
                    {step.label}
                  </p>
                  {isCurrent && (
                    <p className="text-xs text-gray-500 mt-0.5">{step.desc}</p>
                  )}
                  {histEvent && (
                    <p className="text-xs text-gray-400 mt-0.5">
                      {new Date(histEvent.triggered_at).toLocaleDateString('en-GB', {day:'numeric', month:'short', year:'numeric'})}
                      {histEvent.notes && ` — ${histEvent.notes}`}
                    </p>
                  )}
                </div>
              </div>
            )
          })}
        </div>
      </div>

      {/* Key Info Cards */}
      <div className="grid grid-cols-2 gap-4">
        {auditorName && (
          <div className="bg-white rounded-xl border p-4">
            <p className="text-xs text-gray-400 uppercase tracking-wide">Your Auditor</p>
            <p className="font-semibold text-gray-800 mt-1">{auditorName}</p>
          </div>
        )}
        {stage1?.audit_date_start && (
          <div className="bg-white rounded-xl border p-4">
            <p className="text-xs text-gray-400 uppercase tracking-wide">Stage 1 Audit</p>
            <p className="font-semibold text-gray-800 mt-1">
              {new Date(stage1.audit_date_start).toLocaleDateString('en-GB', {day:'numeric', month:'long', year:'numeric'})}
            </p>
          </div>
        )}
        {stage2?.audit_date_start && (
          <div className="bg-white rounded-xl border p-4">
            <p className="text-xs text-gray-400 uppercase tracking-wide">Stage 2 Audit</p>
            <p className="font-semibold text-gray-800 mt-1">
              {new Date(stage2.audit_date_start).toLocaleDateString('en-GB', {day:'numeric', month:'long', year:'numeric'})}
            </p>
          </div>
        )}
        {data.cert_expiry_date && (
          <div className="bg-white rounded-xl border p-4">
            <p className="text-xs text-gray-400 uppercase tracking-wide">Certificate Expires</p>
            <p className="font-semibold text-gray-800 mt-1">
              {new Date(data.cert_expiry_date).toLocaleDateString('en-GB', {day:'numeric', month:'long', year:'numeric'})}
            </p>
          </div>
        )}
      </div>

      {/* Scope */}
      {data.scope_en && (
        <div className="bg-white rounded-xl border p-4">
          <p className="text-xs text-gray-400 uppercase tracking-wide mb-1">Certification Scope</p>
          <p className="text-sm text-gray-700">{data.scope_en}</p>
        </div>
      )}
    </div>
  )
}
```

Create placeholder pages for Documents and Messages (built in later prompts):

`frontend/src/app/(client)/client/documents/page.tsx`:
```tsx
export default function ClientDocumentsPage() {
  return <div className="p-8 text-gray-400">Documents — coming soon</div>
}
```

`frontend/src/app/(client)/client/messages/page.tsx`:
```tsx
export default function ClientMessagesPage() {
  return <div className="p-8 text-gray-400">Messages — coming soon</div>
}
```

### Verify

1. A user with role=`client` logging in is redirected to `/client/overview`
2. `/client/overview` shows the status timeline, auditor name (if assigned), audit dates
3. Users with other roles (admin, planner, etc.) cannot access `/client/*` — they get redirected to `/dashboard`
4. Existing `(app)` portal is completely untouched

### Commit and push

Commit: `feat(portal): client portal — overview page with status timeline`
Push to main.

## Files to create/edit
- `backend/audit_set/client_router.py` — new
- `backend/main.py` — register client_router
- `frontend/src/app/(auth)/login/page.tsx` — add role-based redirect (additive)
- `frontend/src/lib/auth.tsx` — add client role guard (additive)
- `frontend/src/app/(client)/layout.tsx` — new
- `frontend/src/app/(client)/client/overview/page.tsx` — new
- `frontend/src/app/(client)/client/documents/page.tsx` — placeholder
- `frontend/src/app/(client)/client/messages/page.tsx` — placeholder
