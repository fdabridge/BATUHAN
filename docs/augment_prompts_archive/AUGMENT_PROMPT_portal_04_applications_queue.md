# Portal Build — Prompt 4 of 8: CB Applications Queue + Workflow Status

## ⚠️ CRITICAL: DO NOT BREAK THE EXISTING PORTAL
- Do NOT modify existing `/clients` pages or audit set detail pages
- Do NOT change existing `status` field behavior
- Only ADD new sidebar item, new `/applications` page, and new workflow_status API endpoints
- Existing audit sets with `workflow_status = null` must continue to appear normally

---

## Context

When a client submits an application (Prompt 3), the CB coordinator needs to see it in a queue,
review it, complete the missing info (fees, EA codes, auditor), and then approve it.
This prompt builds that queue and the workflow status transition API.

---

## Task

### Backend: Workflow status API

#### New file: `backend/audit_set/workflow_router.py`

```python
"""
BATUHAN — Audit Set workflow status transitions.
Manages the client portal certification lifecycle.
"""
from __future__ import annotations
from datetime import datetime
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from audit_set.db_models import AuditSet, AuditSetStatusEvent, get_db
from auth.db_models import PlatformUser, get_db as get_auth_db
from auth.router import get_current_user
from email_service import send_client_status_update

router = APIRouter(prefix="/audit-sets", tags=["workflow"])

VALID_TRANSITIONS = {
    # (from_status_or_None, to_status): allowed_roles
    (None,               "pending_review"):    {"system"},
    ("pending_review",   "in_planning"):       {"admin", "planner"},
    ("in_planning",      "quotation_sent"):    {"admin", "planner"},
    ("quotation_sent",   "agreement_signed"):  {"admin", "planner", "client"},
    ("agreement_signed", "audit_scheduled"):   {"admin", "planner"},
    ("audit_scheduled",  "audit_in_progress"): {"admin", "planner", "auditor"},
    ("audit_in_progress","under_review"):      {"admin", "planner", "auditor"},
    ("under_review",     "certified"):         {"admin", "executive"},
}

class WorkflowUpdateSchema(BaseModel):
    workflow_status: str
    notes: Optional[str] = None


@router.patch("/{audit_set_id}/workflow-status")
def update_workflow_status(
    audit_set_id: str,
    payload: WorkflowUpdateSchema,
    db: Session = Depends(get_db),
    auth_db: Session = Depends(get_auth_db),
    current_user: PlatformUser = Depends(get_current_user),
):
    audit_set = db.query(AuditSet).filter_by(id=audit_set_id).first()
    if not audit_set:
        raise HTTPException(404, "Audit set not found")

    from_status = audit_set.workflow_status
    to_status = payload.workflow_status

    # Validate transition
    allowed_roles = VALID_TRANSITIONS.get((from_status, to_status))
    if allowed_roles is None:
        raise HTTPException(400, f"Invalid transition: {from_status} → {to_status}")
    if current_user.role not in allowed_roles:
        raise HTTPException(403, f"Role '{current_user.role}' cannot make this transition")

    # Apply
    audit_set.workflow_status = to_status
    event = AuditSetStatusEvent(
        audit_set_id=audit_set_id,
        from_status=from_status,
        to_status=to_status,
        triggered_by=current_user.id,
        notes=payload.notes,
    )
    db.add(event)
    db.commit()

    # Notify client if they have an account linked to this audit set
    client_user = auth_db.query(PlatformUser).filter_by(
        audit_set_id=audit_set_id, role="client"
    ).first()
    if client_user:
        send_client_status_update(
            to=client_user.email,
            full_name=client_user.full_name,
            new_status=to_status,
            notes=payload.notes or "",
        )

    return {"workflow_status": to_status, "updated": True}


@router.get("/{audit_set_id}/status-history")
def get_status_history(
    audit_set_id: str,
    db: Session = Depends(get_db),
    current_user: PlatformUser = Depends(get_current_user),
):
    events = (
        db.query(AuditSetStatusEvent)
        .filter_by(audit_set_id=audit_set_id)
        .order_by(AuditSetStatusEvent.triggered_at)
        .all()
    )
    return [
        {
            "from_status": e.from_status,
            "to_status": e.to_status,
            "triggered_by": e.triggered_by,
            "triggered_at": e.triggered_at.isoformat(),
            "notes": e.notes,
        }
        for e in events
    ]


@router.get("/pending-applications")
def list_pending_applications(
    db: Session = Depends(get_db),
    current_user: PlatformUser = Depends(get_current_user),
):
    """CB-only: list audit sets submitted via portal that are pending review."""
    if current_user.role not in {"admin", "planner", "officer", "executive"}:
        raise HTTPException(403, "Not authorized")

    results = (
        db.query(AuditSet)
        .filter(AuditSet.submitted_via_portal == True)  # noqa: E712
        .filter(AuditSet.workflow_status == "pending_review")
        .order_by(AuditSet.created_at.desc())
        .all()
    )
    return [
        {
            "id": a.id,
            "plan_number": a.plan_number,
            "company_name": a.company_name,
            "company_address": a.company_address,
            "email": a.email,
            "phone": a.phone,
            "standards": a.standards,
            "audit_type": a.audit_type,
            "scope_en": a.scope_en,
            "workflow_status": a.workflow_status,
            "created_at": a.created_at.isoformat() if a.created_at else None,
        }
        for a in results
    ]
```

Register `workflow_router` in `backend/main.py`:
```python
from audit_set.workflow_router import router as workflow_router
app.include_router(workflow_router, dependencies=[Depends(get_current_user)])
# Note: /pending-applications and /workflow-status require auth (get_current_user)
```

### Frontend: Applications page

#### New file: `frontend/src/app/(app)/applications/page.tsx`

```tsx
'use client'
import { useEffect, useState } from 'react'
import { useRouter } from 'next/navigation'
import api from '@/lib/api'

const STATUS_LABELS: Record<string, string> = {
  pending_review:    'Pending Review',
  in_planning:       'In Planning',
  quotation_sent:    'Quotation Sent',
  agreement_signed:  'Agreement Signed',
  audit_scheduled:   'Audit Scheduled',
  audit_in_progress: 'In Progress',
  under_review:      'Under Review',
  certified:         'Certified',
}

export default function ApplicationsPage() {
  const router = useRouter()
  const [apps, setApps] = useState<any[]>([])
  const [loading, setLoading] = useState(true)

  useEffect(() => {
    api.get('/audit-sets/pending-applications')
      .then(r => setApps(r.data))
      .finally(() => setLoading(false))
  }, [])

  if (loading) return <div className="p-8 text-gray-500">Loading applications...</div>

  return (
    <div className="p-6 max-w-5xl mx-auto">
      <div className="flex items-center justify-between mb-6">
        <div>
          <h1 className="text-xl font-bold text-gray-900">Client Applications</h1>
          <p className="text-sm text-gray-500 mt-0.5">Applications submitted via the client portal awaiting review</p>
        </div>
        <span className="bg-amber-100 text-amber-800 text-xs font-semibold px-3 py-1 rounded-full">
          {apps.length} pending
        </span>
      </div>

      {apps.length === 0 ? (
        <div className="text-center py-16 text-gray-400">
          <p className="text-sm">No pending applications</p>
        </div>
      ) : (
        <div className="space-y-3">
          {apps.map(app => (
            <div key={app.id} className="bg-white border rounded-xl p-5 flex items-center justify-between hover:shadow-sm transition-shadow">
              <div className="flex-1 min-w-0">
                <div className="flex items-center gap-3">
                  <h3 className="font-semibold text-gray-900 truncate">{app.company_name}</h3>
                  <span className="text-xs bg-amber-50 text-amber-700 border border-amber-200 px-2 py-0.5 rounded-full shrink-0">
                    {STATUS_LABELS[app.workflow_status] || app.workflow_status}
                  </span>
                </div>
                <p className="text-sm text-gray-500 mt-1 truncate">{app.company_address}</p>
                <div className="flex items-center gap-4 mt-2 text-xs text-gray-400">
                  <span>{(app.standards || []).join(', ')}</span>
                  <span>·</span>
                  <span>{app.audit_type?.replace('_', ' ')}</span>
                  <span>·</span>
                  <span>{app.email}</span>
                  <span>·</span>
                  <span>Submitted {new Date(app.created_at).toLocaleDateString()}</span>
                </div>
                {app.scope_en && (
                  <p className="text-xs text-gray-400 mt-1 truncate italic">"{app.scope_en}"</p>
                )}
              </div>
              <button
                onClick={() => router.push(`/clients/${app.id}`)}
                className="ml-4 bg-[#1A4731] text-white text-sm px-4 py-2 rounded-lg hover:bg-[#143828] transition-colors shrink-0"
              >
                Open & Review
              </button>
            </div>
          ))}
        </div>
      )}
    </div>
  )
}
```

#### Add "Applications" to the sidebar

In `frontend/src/components/layout/Sidebar.tsx`, find the nav items array and add:
```tsx
{ href: '/applications', label: 'Applications', icon: InboxIcon }
// Use an appropriate icon from lucide-react, e.g. Inbox or ClipboardList
// Add a badge showing the pending count — fetch /audit-sets/pending-applications on sidebar mount
```

**Important**: Add this after checking the existing sidebar structure. Do NOT change existing nav items.
The badge should show the count from the API. Use a simple `useEffect` poll or React Query.

#### Add "Approve Application" button on the audit set detail page

In `frontend/src/app/(app)/clients/[id]/page.tsx`, find the existing page and add a conditional section:

```tsx
// Add near the top of the detail page, only visible when workflow_status === 'pending_review':
{auditSet.workflow_status === 'pending_review' && (
  <div className="bg-amber-50 border border-amber-200 rounded-xl p-4 mb-6 flex items-center justify-between">
    <div>
      <p className="text-sm font-semibold text-amber-800">Client Portal Application</p>
      <p className="text-xs text-amber-700 mt-0.5">Complete the form below (fees, auditor, etc.) then approve to move to planning.</p>
    </div>
    <button
      onClick={approveApplication}
      className="bg-[#1A4731] text-white text-sm px-4 py-2 rounded-lg hover:bg-[#143828]"
    >
      Approve Application
    </button>
  </div>
)}
```

The `approveApplication` function calls:
```ts
await api.patch(`/audit-sets/${id}/workflow-status`, {
  workflow_status: 'in_planning',
  notes: 'Application reviewed and approved by CB coordinator'
})
```

### Verify

1. `/audit-sets/pending-applications` returns applications submitted via portal
2. `/applications` page shows them with correct data
3. Approving moves workflow_status to `in_planning` and sends email to client
4. Existing `/clients` page and all audit set functionality unchanged

### Commit and push

Commit: `feat(portal): CB applications queue + workflow status transitions`
Push to main.

## Files to create/edit
- `backend/audit_set/workflow_router.py` — new
- `backend/main.py` — register workflow_router
- `frontend/src/app/(app)/applications/page.tsx` — new
- `frontend/src/components/layout/Sidebar.tsx` — add Applications nav item (additive only)
- `frontend/src/app/(app)/clients/[id]/page.tsx` — add approve banner (additive only)
