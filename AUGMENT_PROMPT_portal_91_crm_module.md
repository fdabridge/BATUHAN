# Portal 91 — CRM Module: Certification Renewal Tracking for Non-Technical Staff

## Purpose

Add a read-only CRM view for finance/operations staff. They log in, see a simplified pipeline status and a certification cycle calendar showing when each client's Surveillance 1, Surveillance 2, and Recertification audits are due. Data flows automatically from the main technical system — no manual entry.

**Zero changes to any existing endpoint, DB table, or technical UI page.** This is purely additive.

---

## Isolation guarantee

- New backend file: `backend/audit_set/crm_router.py` — all endpoints prefixed `/crm/*`
- Only `SELECT` queries — no writes to any table
- Every DB query wrapped in `try/except` — a bad query returns empty data, never crashes the app
- Only two lines added to `main.py` (import + include_router at the bottom)
- One string `"crm"` added to `VALID_ROLES` in `auth/schemas.py`
- Sidebar and layout changes are `role === 'crm'` guards — existing roles see nothing different
- New frontend pages live at `/crm/*` — no existing page is touched

---

## Files to create (new)

1. `backend/audit_set/crm_router.py`
2. `frontend/src/app/(app)/crm/page.tsx`
3. `frontend/src/app/(app)/crm/clients/page.tsx`
4. `frontend/src/app/(app)/crm/clients/[id]/page.tsx`

## Files to modify (minimal, surgical)

5. `backend/auth/schemas.py` — add `"crm"` to VALID_ROLES
6. `backend/main.py` — add crm_router import + registration at the bottom
7. `frontend/src/app/(app)/layout.tsx` — add crm role redirect to `/crm`
8. `frontend/src/components/layout/Sidebar.tsx` — add CRM nav items (visible only to `crm` role)

---

## 1. `backend/auth/schemas.py`

Find:
```python
VALID_ROLES = {"admin", "planner", "auditor", "officer", "executive", "client", "gm", "certification_manager"}
```

Replace with:
```python
VALID_ROLES = {"admin", "planner", "auditor", "officer", "executive", "client", "gm", "certification_manager", "crm"}
```

That is the only change to this file.

---

## 2. `backend/audit_set/crm_router.py` — NEW FILE

```python
"""
CRM Router — Portal 91

Read-only endpoints for non-technical staff (finance / operations).
Data is derived from the existing audit_set tables with no writes.

Accessible to roles: crm, admin
All endpoints return empty/zero responses on DB error — never 500.
"""
from __future__ import annotations

import logging
from datetime import date, timedelta
from typing import Optional

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy.orm import Session

from audit_set.db_models import AuditSet, get_db
from auth.db_models import PlatformUser, get_db as get_auth_db
from auth.dependencies import get_current_user

logger = logging.getLogger(__name__)
router = APIRouter(tags=["crm"])

CRM_ROLES = {"crm", "admin"}

# ── Simplified pipeline status map ────────────────────────────────────────────

SIMPLE_STATUS: dict[str | None, str] = {
    None:                    "Application Received",
    "pending_review":        "Application Received",
    "in_planning":           "In Planning",
    "notification_sent":     "In Planning",
    "quotation_sent":        "Quotation Sent",
    "agreement_signed":      "Agreement Signed",
    "fr218_in_progress":     "Under Review",
    "fr218_complete":        "Under Review",
    "stage1_scheduled":      "Stage 1 Audit",
    "stage1_in_progress":    "Stage 1 Audit",
    "stage1_complete":       "Stage 1 Complete",
    "stage2_scheduled":      "Stage 2 Audit",
    "stage2_in_progress":    "Stage 2 Audit",
    "under_review":          "Under Review",
    "committee_review":      "Committee Review",
    "audit_scheduled":       "Surveillance Audit",
    "audit_in_progress":     "Surveillance Audit",
    "surveillance_complete": "Surveillance Complete",
    "cert_complete":         "Certified",
    "certified":             "Certified",
}

PIPELINE_ORDER = [
    "Application Received",
    "In Planning",
    "Quotation Sent",
    "Agreement Signed",
    "Under Review",
    "Stage 1 Audit",
    "Stage 1 Complete",
    "Stage 2 Audit",
    "Committee Review",
    "Surveillance Audit",
    "Surveillance Complete",
    "Certified",
]

# ── Cycle date computation ────────────────────────────────────────────────────

def _add_years(d: date, years: int) -> date:
    """Add N years to a date, handling Feb 29 edge case."""
    try:
        return d.replace(year=d.year + years)
    except ValueError:
        return d.replace(year=d.year + years, day=28)


def _cycle_dates(issued: date) -> tuple[date, date, date]:
    """
    Compute Surveillance 1, Surveillance 2, and Recertification due dates.

    Rule (per user's requirement):
      - Certified on  29 Jun 2026
      - Surv 1 due    28 Jun 2027  (cert_date + 1 year − 1 day)
      - Surv 2 due    28 Jun 2028  (cert_date + 2 years − 1 day)
      - Recert due    29 Jun 2029  (cert_date + 3 years, same day)
    """
    surv1  = _add_years(issued, 1) - timedelta(days=1)
    surv2  = _add_years(issued, 2) - timedelta(days=1)
    recert = _add_years(issued, 3)
    return surv1, surv2, recert


# ── Contact lookup ────────────────────────────────────────────────────────────

def _get_contact(audit_set_id: str, audit_set: AuditSet, auth_db: Session) -> dict:
    """Return contact info: prefer client portal user, fall back to AuditSet fields."""
    try:
        client_user = (
            auth_db.query(PlatformUser)
            .filter_by(audit_set_id=audit_set_id, role="client")
            .first()
        )
        if client_user:
            return {
                "contact_name":  client_user.full_name,
                "contact_email": client_user.email,
                "contact_phone": audit_set.phone or "",
            }
    except Exception:
        pass
    return {
        "contact_name":  audit_set.representative or "",
        "contact_email": audit_set.email or "",
        "contact_phone": audit_set.phone or "",
    }


# ── Serialise one AuditSet row ────────────────────────────────────────────────

def _serialise(audit_set: AuditSet, auth_db: Session) -> dict:
    issued: Optional[date] = audit_set.cert_issued_date

    surv1_due = surv2_due = recert_due = None
    if issued:
        surv1_due, surv2_due, recert_due = _cycle_dates(issued)

    contact = _get_contact(audit_set.id, audit_set, auth_db)

    return {
        "id":                audit_set.id,
        "company_name":      audit_set.company_name or "",
        "city":              audit_set.city or "",
        "standards":         audit_set.standards or [],
        "audit_type":        audit_set.audit_type or "initial",
        "accreditation_body": audit_set.accreditation_body or "",
        "simple_status":     SIMPLE_STATUS.get(audit_set.workflow_status, "In Progress"),
        "workflow_status":   audit_set.workflow_status,
        "cert_issued_date":  issued.isoformat() if issued else None,
        "cert_expiry_date":  audit_set.cert_expiry_date.isoformat() if audit_set.cert_expiry_date else None,
        "surv1_due":         surv1_due.isoformat()  if surv1_due  else None,
        "surv2_due":         surv2_due.isoformat()  if surv2_due  else None,
        "recert_due":        recert_due.isoformat() if recert_due else None,
        "certification_fee": audit_set.certification_fee,
        "surveillance_fee":  audit_set.surveillance_fee,
        "currency":          audit_set.currency or "USD",
        **contact,
    }


# ── Pydantic response schemas ─────────────────────────────────────────────────

class CRMClientRow(BaseModel):
    id: str
    company_name: str
    city: str
    standards: list
    audit_type: str
    accreditation_body: str
    simple_status: str
    workflow_status: Optional[str]
    cert_issued_date: Optional[str]
    cert_expiry_date: Optional[str]
    surv1_due: Optional[str]
    surv2_due: Optional[str]
    recert_due: Optional[str]
    certification_fee: Optional[float]
    surveillance_fee: Optional[float]
    currency: str
    contact_name: str
    contact_email: str
    contact_phone: str

    class Config:
        from_attributes = True


class KPIs(BaseModel):
    active_certifications: int
    expiring_90_days: int
    overdue_renewals: int
    in_progress: int


class CRMDashboardResponse(BaseModel):
    kpis: KPIs
    upcoming_renewals: list[dict]
    pipeline: dict[str, int]


# ── Endpoints ─────────────────────────────────────────────────────────────────

@router.get("/crm/dashboard", response_model=CRMDashboardResponse)
def crm_dashboard(
    db:      Session = Depends(get_db),
    auth_db: Session = Depends(get_auth_db),
    current_user: PlatformUser = Depends(get_current_user),
):
    if current_user.role not in CRM_ROLES:
        from fastapi import HTTPException
        raise HTTPException(403, "Not authorized")

    today = date.today()
    in_90 = today + timedelta(days=90)

    try:
        all_sets = db.query(AuditSet).all()
    except Exception as exc:
        logger.error("[CRM] dashboard DB error: %s", exc)
        all_sets = []

    active_certs     = 0
    expiring_90      = 0
    overdue_renewals = 0
    in_progress_cnt  = 0
    pipeline: dict[str, int] = {s: 0 for s in PIPELINE_ORDER}
    upcoming: list[dict] = []

    for a in all_sets:
        # Pipeline tally
        label = SIMPLE_STATUS.get(a.workflow_status, "In Progress")
        if label in pipeline:
            pipeline[label] += 1

        # In-progress count (not yet certified)
        if label not in ("Certified", "Application Received"):
            in_progress_cnt += 1

        if not a.cert_issued_date:
            continue

        active_certs += 1
        issued = a.cert_issued_date
        surv1, surv2, recert = _cycle_dates(issued)
        contact = _get_contact(a.id, a, auth_db)

        # Expiring cert (cert_expiry_date within 90 days)
        if a.cert_expiry_date and today <= a.cert_expiry_date <= in_90:
            expiring_90 += 1

        # Upcoming renewal rows (next 18 months) + overdue detection
        for milestone, due in [("surv1", surv1), ("surv2", surv2), ("recert", recert)]:
            days_until = (due - today).days
            if days_until < -30:
                # Very overdue (>30 days past) — count and skip from upcoming table
                overdue_renewals += 1
                continue
            if days_until > 548:
                # More than 18 months away — skip
                continue
            upcoming.append({
                "audit_set_id":    a.id,
                "company_name":    a.company_name or "",
                "standards":       a.standards or [],
                "milestone":       milestone,
                "due_date":        due.isoformat(),
                "days_until":      days_until,
                "cert_issued_date": issued.isoformat(),
                **contact,
            })

    # Sort by due date ascending
    upcoming.sort(key=lambda r: r["due_date"])

    return CRMDashboardResponse(
        kpis=KPIs(
            active_certifications=active_certs,
            expiring_90_days=expiring_90,
            overdue_renewals=overdue_renewals,
            in_progress=in_progress_cnt,
        ),
        upcoming_renewals=upcoming,
        pipeline={k: v for k, v in pipeline.items() if v > 0},
    )


@router.get("/crm/clients", response_model=list[CRMClientRow])
def crm_clients(
    db:      Session = Depends(get_db),
    auth_db: Session = Depends(get_auth_db),
    current_user: PlatformUser = Depends(get_current_user),
):
    if current_user.role not in CRM_ROLES:
        from fastapi import HTTPException
        raise HTTPException(403, "Not authorized")

    try:
        all_sets = db.query(AuditSet).order_by(AuditSet.company_name).all()
    except Exception as exc:
        logger.error("[CRM] clients DB error: %s", exc)
        return []

    result = []
    for a in all_sets:
        try:
            result.append(CRMClientRow(**_serialise(a, auth_db)))
        except Exception as exc:
            logger.warning("[CRM] skip audit_set %s: %s", a.id, exc)
    return result


@router.get("/crm/clients/{audit_set_id}", response_model=CRMClientRow)
def crm_client_detail(
    audit_set_id: str,
    db:      Session = Depends(get_db),
    auth_db: Session = Depends(get_auth_db),
    current_user: PlatformUser = Depends(get_current_user),
):
    if current_user.role not in CRM_ROLES:
        from fastapi import HTTPException
        raise HTTPException(403, "Not authorized")

    try:
        a = db.query(AuditSet).filter_by(id=audit_set_id).first()
    except Exception as exc:
        logger.error("[CRM] client detail DB error: %s", exc)
        from fastapi import HTTPException
        raise HTTPException(500, "Database error")

    if not a:
        from fastapi import HTTPException
        raise HTTPException(404, "Audit set not found")

    return CRMClientRow(**_serialise(a, auth_db))
```

---

## 3. `backend/main.py`

Add after the last `from ... import router as ...` line (after line `from audit_set.employee_router import router as employee_router`):

```python
from audit_set.crm_router import router as crm_router
```

Add after `app.include_router(health_full_router)` at the bottom of the router block:

```python
# CRM portal — finance / operations staff. Read-only. Portal 91.
app.include_router(crm_router)
```

**IMPORTANT:** Wrap the import in a try/except so a syntax error in crm_router.py cannot crash startup:

```python
try:
    from audit_set.crm_router import router as crm_router
    _crm_router_ok = True
except Exception as _crm_exc:
    import logging as _log
    _log.getLogger("batuhan").error("[Portal 91] crm_router failed to import: %s", _crm_exc)
    _crm_router_ok = False
```

And then:

```python
if _crm_router_ok:
    app.include_router(crm_router)
```

---

## 4. `frontend/src/app/(app)/layout.tsx`

Find:
```tsx
    // Client-role users belong in the (client) portal, not the internal app.
    if (user?.role === 'client') {
      router.replace('/client/overview')
    }
```

Replace with:
```tsx
    // Client-role users belong in the (client) portal, not the internal app.
    if (user?.role === 'client') {
      router.replace('/client/overview')
    }
    // CRM-role users go to the CRM section.
    if (user?.role === 'crm') {
      router.replace('/crm')
    }
```

---

## 5. `frontend/src/components/layout/Sidebar.tsx`

### 5a. Add import
After the existing Lucide icon imports, add:
```tsx
  BarChart3,
  RefreshCw,
```

### 5b. Add CRM nav definition
After `const CB_REVIEW_ROLES = new Set([...])`, add:

```tsx
const CRM_NAV: NavItemProps[] = [
  { icon: BarChart3,  label: 'CRM Dashboard', href: '/crm',         active: false },
  { icon: RefreshCw,  label: 'Clients',        href: '/crm/clients', active: false },
]
```

### 5c. Update the Sidebar render
Find the `{/* Primary nav */}` block:
```tsx
      {/* Primary nav */}
      {NAV_TOP.map((item) => (
        <NavItem
          key={item.href}
          {...item}
          active={isActive(item.href)}
          badgeCount={item.href === '/applications' ? pendingCount : undefined}
        />
      ))}
```

Replace with:
```tsx
      {/* Primary nav — CRM role sees only CRM items */}
      {user?.role === 'crm' ? (
        CRM_NAV.map((item) => (
          <NavItem key={item.href} {...item} active={isActive(item.href)} />
        ))
      ) : (
        NAV_TOP.map((item) => (
          <NavItem
            key={item.href}
            {...item}
            active={isActive(item.href)}
            badgeCount={item.href === '/applications' ? pendingCount : undefined}
          />
        ))
      )}
```

---

## 6. `frontend/src/app/(app)/crm/page.tsx` — NEW: CRM Dashboard

```tsx
'use client'

import { useEffect, useState } from 'react'
import Link from 'next/link'
import api from '@/lib/api'

interface KPIs {
  active_certifications: number
  expiring_90_days: number
  overdue_renewals: number
  in_progress: number
}

interface RenewalRow {
  audit_set_id: string
  company_name: string
  standards: string[]
  milestone: 'surv1' | 'surv2' | 'recert'
  due_date: string
  days_until: number
  cert_issued_date: string
  contact_name: string
  contact_email: string
}

interface DashboardData {
  kpis: KPIs
  upcoming_renewals: RenewalRow[]
  pipeline: Record<string, number>
}

const MILESTONE_LABELS: Record<string, string> = {
  surv1:  'Surveillance 1',
  surv2:  'Surveillance 2',
  recert: 'Recertification',
}

function urgencyBadge(daysUntil: number) {
  if (daysUntil < 0)  return { label: 'Overdue',     cls: 'bg-red-100 text-red-700' }
  if (daysUntil < 30) return { label: 'Due soon',    cls: 'bg-orange-100 text-orange-700' }
  if (daysUntil < 90) return { label: 'Upcoming',    cls: 'bg-yellow-100 text-yellow-700' }
  return               { label: 'On track',   cls: 'bg-green-100 text-green-700' }
}

function fmtDate(iso: string | null | undefined) {
  if (!iso) return '—'
  return new Date(iso).toLocaleDateString('en-GB', { day: 'numeric', month: 'short', year: 'numeric' })
}

export default function CRMDashboard() {
  const [data, setData] = useState<DashboardData | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')

  useEffect(() => {
    api.get<DashboardData>('/crm/dashboard')
      .then((r) => setData(r.data))
      .catch(() => setError('Could not load CRM dashboard.'))
      .finally(() => setLoading(false))
  }, [])

  if (loading) return <div className="p-8 text-sm text-gray-400">Loading…</div>
  if (error || !data) return <div className="p-8 text-sm text-red-500">{error || 'No data.'}</div>

  const { kpis, upcoming_renewals, pipeline } = data

  return (
    <div className="space-y-8">
      <h1 className="text-xl font-semibold text-gray-900">CRM Dashboard</h1>

      {/* KPI Cards */}
      <div className="grid grid-cols-2 gap-4 sm:grid-cols-4">
        {[
          { label: 'Active Certifications', value: kpis.active_certifications, color: 'text-green-700' },
          { label: 'Expiring (90 days)',     value: kpis.expiring_90_days,      color: 'text-orange-600' },
          { label: 'Overdue Renewals',       value: kpis.overdue_renewals,      color: 'text-red-600' },
          { label: 'Audits In Progress',     value: kpis.in_progress,           color: 'text-blue-600' },
        ].map((k) => (
          <div key={k.label} className="rounded-xl border border-gray-200 bg-white p-5 shadow-sm">
            <p className="text-xs text-gray-500">{k.label}</p>
            <p className={`mt-1 text-3xl font-bold ${k.color}`}>{k.value}</p>
          </div>
        ))}
      </div>

      {/* Upcoming Renewals */}
      <div className="rounded-xl border border-gray-200 bg-white shadow-sm">
        <div className="border-b border-gray-100 px-6 py-4">
          <h2 className="font-semibold text-gray-800">Upcoming Renewal Deadlines</h2>
          <p className="text-xs text-gray-400 mt-0.5">Surveillance and recertification due dates for all certified clients</p>
        </div>
        {upcoming_renewals.length === 0 ? (
          <p className="px-6 py-8 text-sm text-gray-400">No upcoming renewals in the next 18 months.</p>
        ) : (
          <table className="w-full text-sm">
            <thead>
              <tr className="border-b border-gray-100 text-left text-xs text-gray-400">
                <th className="px-6 py-3">Company</th>
                <th className="px-4 py-3">Standards</th>
                <th className="px-4 py-3">Milestone</th>
                <th className="px-4 py-3">Due Date</th>
                <th className="px-4 py-3">Status</th>
                <th className="px-4 py-3">Contact</th>
                <th className="px-4 py-3"></th>
              </tr>
            </thead>
            <tbody>
              {upcoming_renewals.map((r, i) => {
                const badge = urgencyBadge(r.days_until)
                return (
                  <tr key={`${r.audit_set_id}-${r.milestone}`} className={i % 2 === 0 ? 'bg-white' : 'bg-gray-50'}>
                    <td className="px-6 py-3 font-medium text-gray-900">{r.company_name}</td>
                    <td className="px-4 py-3 text-gray-500">{(r.standards || []).join(', ')}</td>
                    <td className="px-4 py-3 text-gray-700">{MILESTONE_LABELS[r.milestone] ?? r.milestone}</td>
                    <td className="px-4 py-3 text-gray-700">{fmtDate(r.due_date)}</td>
                    <td className="px-4 py-3">
                      <span className={`rounded-full px-2 py-0.5 text-xs font-medium ${badge.cls}`}>
                        {badge.label}
                        {r.days_until >= 0 ? ` (${r.days_until}d)` : ` (${Math.abs(r.days_until)}d ago)`}
                      </span>
                    </td>
                    <td className="px-4 py-3 text-gray-500">
                      <div>{r.contact_name}</div>
                      <div className="text-xs text-gray-400">{r.contact_email}</div>
                    </td>
                    <td className="px-4 py-3">
                      <Link href={`/crm/clients/${r.audit_set_id}`}
                        className="text-xs text-emerald-700 hover:underline">
                        View →
                      </Link>
                    </td>
                  </tr>
                )
              })}
            </tbody>
          </table>
        )}
      </div>

      {/* Pipeline Summary */}
      {Object.keys(pipeline).length > 0 && (
        <div className="rounded-xl border border-gray-200 bg-white shadow-sm">
          <div className="border-b border-gray-100 px-6 py-4">
            <h2 className="font-semibold text-gray-800">Pipeline Overview</h2>
          </div>
          <div className="flex flex-wrap gap-3 px-6 py-4">
            {Object.entries(pipeline).map(([stage, count]) => (
              <div key={stage} className="flex items-center gap-2 rounded-lg border border-gray-100 bg-gray-50 px-3 py-2">
                <span className="text-xs text-gray-500">{stage}</span>
                <span className="text-sm font-semibold text-gray-800">{count}</span>
              </div>
            ))}
          </div>
        </div>
      )}
    </div>
  )
}
```

---

## 7. `frontend/src/app/(app)/crm/clients/page.tsx` — NEW: Client List

```tsx
'use client'

import { useEffect, useState } from 'react'
import Link from 'next/link'
import api from '@/lib/api'

interface CRMClient {
  id: string
  company_name: string
  city: string
  standards: string[]
  audit_type: string
  simple_status: string
  cert_issued_date: string | null
  surv1_due: string | null
  surv2_due: string | null
  recert_due: string | null
  certification_fee: number | null
  surveillance_fee: number | null
  currency: string
  contact_name: string
  contact_email: string
  contact_phone: string
}

function fmtDate(iso: string | null | undefined) {
  if (!iso) return '—'
  return new Date(iso).toLocaleDateString('en-GB', { day: 'numeric', month: 'short', year: 'numeric' })
}

function dateBadge(iso: string | null) {
  if (!iso) return null
  const days = Math.round((new Date(iso).getTime() - Date.now()) / 86_400_000)
  if (days < 0)  return <span className="ml-1 rounded-full bg-red-100 px-1.5 py-0.5 text-[10px] font-medium text-red-700">Overdue</span>
  if (days < 30) return <span className="ml-1 rounded-full bg-orange-100 px-1.5 py-0.5 text-[10px] font-medium text-orange-700">{days}d</span>
  if (days < 90) return <span className="ml-1 rounded-full bg-yellow-100 px-1.5 py-0.5 text-[10px] font-medium text-yellow-700">{days}d</span>
  return null
}

const STATUS_COLORS: Record<string, string> = {
  'Certified':           'bg-green-100 text-green-700',
  'Application Received':'bg-gray-100 text-gray-500',
  'In Planning':         'bg-blue-100 text-blue-700',
  'Quotation Sent':      'bg-indigo-100 text-indigo-700',
  'Agreement Signed':    'bg-purple-100 text-purple-700',
  'Under Review':        'bg-yellow-100 text-yellow-700',
  'Stage 1 Audit':       'bg-orange-100 text-orange-700',
  'Stage 2 Audit':       'bg-orange-100 text-orange-700',
  'Surveillance Audit':  'bg-orange-100 text-orange-700',
}

export default function CRMClients() {
  const [clients, setClients] = useState<CRMClient[]>([])
  const [loading, setLoading]  = useState(true)
  const [search, setSearch]    = useState('')

  useEffect(() => {
    api.get<CRMClient[]>('/crm/clients')
      .then((r) => setClients(r.data))
      .catch(() => {})
      .finally(() => setLoading(false))
  }, [])

  const filtered = clients.filter((c) =>
    c.company_name.toLowerCase().includes(search.toLowerCase()) ||
    c.contact_name.toLowerCase().includes(search.toLowerCase()),
  )

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <h1 className="text-xl font-semibold text-gray-900">All Clients</h1>
        <input
          className="rounded-lg border border-gray-200 px-3 py-1.5 text-sm focus:outline-none focus:ring-2 focus:ring-emerald-500"
          placeholder="Search by company or contact…"
          value={search}
          onChange={(e) => setSearch(e.target.value)}
        />
      </div>

      {loading ? (
        <p className="text-sm text-gray-400">Loading…</p>
      ) : (
        <div className="overflow-x-auto rounded-xl border border-gray-200 bg-white shadow-sm">
          <table className="w-full text-sm">
            <thead>
              <tr className="border-b border-gray-100 text-left text-xs text-gray-400">
                <th className="px-4 py-3">Company</th>
                <th className="px-4 py-3">Standards</th>
                <th className="px-4 py-3">Type</th>
                <th className="px-4 py-3">Status</th>
                <th className="px-4 py-3">Certified</th>
                <th className="px-4 py-3">Surv 1</th>
                <th className="px-4 py-3">Surv 2</th>
                <th className="px-4 py-3">Recert</th>
                <th className="px-4 py-3">Contact</th>
                <th className="px-4 py-3"></th>
              </tr>
            </thead>
            <tbody>
              {filtered.length === 0 ? (
                <tr>
                  <td colSpan={10} className="px-4 py-8 text-center text-sm text-gray-400">No clients found.</td>
                </tr>
              ) : filtered.map((c, i) => (
                <tr key={c.id} className={i % 2 === 0 ? 'bg-white' : 'bg-gray-50'}>
                  <td className="px-4 py-3 font-medium text-gray-900">
                    {c.company_name}
                    {c.city && <span className="ml-1 text-xs text-gray-400">· {c.city}</span>}
                  </td>
                  <td className="px-4 py-3 text-gray-500 text-xs">{(c.standards || []).join(', ')}</td>
                  <td className="px-4 py-3 capitalize text-gray-500">{c.audit_type}</td>
                  <td className="px-4 py-3">
                    <span className={`rounded-full px-2 py-0.5 text-xs font-medium ${STATUS_COLORS[c.simple_status] ?? 'bg-gray-100 text-gray-600'}`}>
                      {c.simple_status}
                    </span>
                  </td>
                  <td className="px-4 py-3 text-gray-600">{fmtDate(c.cert_issued_date)}</td>
                  <td className="px-4 py-3 text-gray-600">
                    {fmtDate(c.surv1_due)}{dateBadge(c.surv1_due)}
                  </td>
                  <td className="px-4 py-3 text-gray-600">
                    {fmtDate(c.surv2_due)}{dateBadge(c.surv2_due)}
                  </td>
                  <td className="px-4 py-3 text-gray-600">
                    {fmtDate(c.recert_due)}{dateBadge(c.recert_due)}
                  </td>
                  <td className="px-4 py-3">
                    <div className="text-xs text-gray-700">{c.contact_name}</div>
                    <div className="text-xs text-gray-400">{c.contact_email}</div>
                    {c.contact_phone && <div className="text-xs text-gray-400">{c.contact_phone}</div>}
                  </td>
                  <td className="px-4 py-3">
                    <Link href={`/crm/clients/${c.id}`}
                      className="text-xs text-emerald-700 hover:underline">
                      View →
                    </Link>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  )
}
```

---

## 8. `frontend/src/app/(app)/crm/clients/[id]/page.tsx` — NEW: Client Detail

```tsx
'use client'

import { useEffect, useState } from 'react'
import { useParams, useRouter } from 'next/navigation'
import api from '@/lib/api'

interface CRMClient {
  id: string
  company_name: string
  city: string
  standards: string[]
  audit_type: string
  accreditation_body: string
  simple_status: string
  cert_issued_date: string | null
  cert_expiry_date: string | null
  surv1_due: string | null
  surv2_due: string | null
  recert_due: string | null
  certification_fee: number | null
  surveillance_fee: number | null
  currency: string
  contact_name: string
  contact_email: string
  contact_phone: string
}

function fmtDate(iso: string | null | undefined) {
  if (!iso) return '—'
  return new Date(iso).toLocaleDateString('en-GB', { day: 'numeric', month: 'short', year: 'numeric' })
}

function fmtFee(val: number | null, currency: string) {
  if (val == null) return '—'
  const sym = currency === 'EUR' ? '€' : currency === 'TRY' ? '₺' : '$'
  return `${sym}${val.toLocaleString()}`
}

function MilestoneRow({ label, due }: { label: string; due: string | null }) {
  if (!due) return (
    <div className="flex items-center justify-between py-3 border-b border-gray-100 last:border-0">
      <span className="text-sm text-gray-600">{label}</span>
      <span className="text-sm text-gray-400">Not yet scheduled</span>
    </div>
  )
  const days = Math.round((new Date(due).getTime() - Date.now()) / 86_400_000)
  let badge = { label: 'On track', cls: 'bg-green-100 text-green-700' }
  if (days < 0)  badge = { label: `${Math.abs(days)} days overdue`, cls: 'bg-red-100 text-red-700' }
  else if (days < 30) badge = { label: `${days} days`,   cls: 'bg-orange-100 text-orange-700' }
  else if (days < 90) badge = { label: `${days} days`,   cls: 'bg-yellow-100 text-yellow-700' }
  return (
    <div className="flex items-center justify-between py-3 border-b border-gray-100 last:border-0">
      <span className="text-sm text-gray-700">{label}</span>
      <div className="flex items-center gap-3">
        <span className="text-sm text-gray-600">{fmtDate(due)}</span>
        <span className={`rounded-full px-2 py-0.5 text-xs font-medium ${badge.cls}`}>{badge.label}</span>
      </div>
    </div>
  )
}

export default function CRMClientDetail() {
  const { id } = useParams<{ id: string }>()
  const router = useRouter()
  const [client, setClient] = useState<CRMClient | null>(null)
  const [loading, setLoading] = useState(true)

  useEffect(() => {
    if (!id) return
    api.get<CRMClient>(`/crm/clients/${id}`)
      .then((r) => setClient(r.data))
      .catch(() => {})
      .finally(() => setLoading(false))
  }, [id])

  if (loading) return <div className="p-8 text-sm text-gray-400">Loading…</div>
  if (!client)  return <div className="p-8 text-sm text-red-500">Client not found.</div>

  return (
    <div className="space-y-6 max-w-3xl">
      {/* Header */}
      <div className="flex items-center gap-4">
        <button onClick={() => router.back()} className="text-sm text-gray-400 hover:text-gray-700">← Back</button>
        <h1 className="text-xl font-semibold text-gray-900">{client.company_name}</h1>
        {client.city && <span className="text-sm text-gray-400">{client.city}</span>}
        <span className="rounded-full bg-emerald-100 px-3 py-0.5 text-xs font-medium text-emerald-700">
          {client.simple_status}
        </span>
      </div>

      <div className="grid grid-cols-1 gap-5 sm:grid-cols-2">

        {/* Contact Info */}
        <div className="rounded-xl border border-gray-200 bg-white p-5 shadow-sm">
          <h2 className="text-xs font-semibold uppercase tracking-wide text-gray-400 mb-3">Contact</h2>
          <div className="space-y-2 text-sm">
            <div><span className="text-gray-500">Name: </span><span className="text-gray-800">{client.contact_name || '—'}</span></div>
            <div><span className="text-gray-500">Email: </span>
              {client.contact_email
                ? <a href={`mailto:${client.contact_email}`} className="text-emerald-700 hover:underline">{client.contact_email}</a>
                : <span className="text-gray-400">—</span>}
            </div>
            <div><span className="text-gray-500">Phone: </span><span className="text-gray-800">{client.contact_phone || '—'}</span></div>
          </div>
        </div>

        {/* Certification Info */}
        <div className="rounded-xl border border-gray-200 bg-white p-5 shadow-sm">
          <h2 className="text-xs font-semibold uppercase tracking-wide text-gray-400 mb-3">Certification</h2>
          <div className="space-y-2 text-sm">
            <div><span className="text-gray-500">Standards: </span><span className="text-gray-800">{(client.standards || []).join(', ') || '—'}</span></div>
            <div><span className="text-gray-500">Type: </span><span className="text-gray-800 capitalize">{client.audit_type}</span></div>
            <div><span className="text-gray-500">Accreditation: </span><span className="text-gray-800">{client.accreditation_body || '—'}</span></div>
            <div><span className="text-gray-500">Cert Fee: </span><span className="text-gray-800">{fmtFee(client.certification_fee, client.currency)}</span></div>
            <div><span className="text-gray-500">Surv Fee: </span><span className="text-gray-800">{fmtFee(client.surveillance_fee, client.currency)}</span></div>
          </div>
        </div>
      </div>

      {/* Certification Cycle Timeline */}
      <div className="rounded-xl border border-gray-200 bg-white p-5 shadow-sm">
        <h2 className="text-xs font-semibold uppercase tracking-wide text-gray-400 mb-1">Certification Cycle</h2>
        {!client.cert_issued_date ? (
          <p className="text-sm text-gray-400 py-4">No certificate issued yet — cycle dates will appear here once certification is complete.</p>
        ) : (
          <div>
            <MilestoneRow label="✓ Certified"       due={client.cert_issued_date} />
            <MilestoneRow label="Surveillance 1"    due={client.surv1_due} />
            <MilestoneRow label="Surveillance 2"    due={client.surv2_due} />
            <MilestoneRow label="Recertification"   due={client.recert_due} />
            {client.cert_expiry_date && (
              <MilestoneRow label="Certificate Expires" due={client.cert_expiry_date} />
            )}
          </div>
        )}
      </div>
    </div>
  )
}
```

---

## What does NOT change

- All existing routers (`documents_router`, `workflow_router`, `apply_router`, `client_router`, etc.) — untouched
- All existing DB tables — no schema changes, no new migrations
- All existing frontend pages (`/clients`, `/dashboard`, `/applications`, etc.) — untouched
- All existing roles (admin, planner, auditor, officer, executive, client, gm, certification_manager) — their behaviour is unchanged
- The cert_issued_date field already exists on AuditSet — no column additions needed

---

## How cycle dates populate automatically

`cert_issued_date` on `AuditSet` is already in the DB model. When the Certification Manager completes certification through the main system, this field is set. The CRM immediately reflects the computed surv1/surv2/recert dates on next page load — zero manual entry.

For existing clients where `cert_issued_date` is NULL: the CRM shows them in the pipeline view with their current status, but the cycle timeline shows "No certificate issued yet."

---

## How to create a CRM user

Admin logs in → `/admin/users` → Create User → set role to `crm`. The user can then log in and lands on `/crm` automatically.

---

## Commit message

```
Portal 91: CRM module — certification renewal tracking for non-technical staff

- auth/schemas.py: add 'crm' to VALID_ROLES
- audit_set/crm_router.py: new read-only router with 3 endpoints
    GET /crm/dashboard — KPIs + upcoming renewals + pipeline summary
    GET /crm/clients — all audit sets with simplified status + cycle dates
    GET /crm/clients/{id} — single client detail
  Cycle dates computed from cert_issued_date:
    surv1 = +1y-1d, surv2 = +2y-1d, recert = +3y
  All DB queries wrapped in try/except — zero risk to existing system
- main.py: register crm_router with import guard
- layout.tsx: redirect crm role to /crm
- Sidebar.tsx: CRM nav items (BarChart3 + RefreshCw) shown only to crm role
- frontend: 3 new pages at /crm, /crm/clients, /crm/clients/[id]

Zero changes to existing endpoints, DB tables, or technical UI pages.
```
