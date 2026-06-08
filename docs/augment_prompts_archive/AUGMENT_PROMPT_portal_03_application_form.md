# Portal Build — Prompt 3 of 8: Public Client Application Form

## ⚠️ CRITICAL: DO NOT BREAK THE EXISTING PORTAL
- Do NOT modify any existing API route, frontend page, or component under `(app)/`
- Do NOT change existing audit set creation logic
- Add NEW routes/pages only. The existing `/clients/new` internal form is untouched.

---

## Context

A prospective client visits a public URL, fills a simple form, and submits their certification
application. On submit:
1. An `AuditSet` is created with `workflow_status = "pending_review"` and `submitted_via_portal = true`
2. A `PlatformUser` (role = "client") is created with an auto-generated password
3. A welcome email is sent with their login credentials
4. They see a "Thank you" confirmation page

The CB staff sees the application in their "Applications" queue (built in Prompt 4).

CB fills everything the client doesn't know: fees, EA codes, auditor assignment, etc.

---

## Task

### Backend

#### New file: `backend/audit_set/apply_router.py`

This is a completely NEW router with NO auth required on the submission endpoint.

```python
"""
BATUHAN — Public client application form router.
POST /apply — no authentication required.
"""
from __future__ import annotations
import secrets
import string
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, EmailStr
from sqlalchemy.orm import Session
from passlib.context import CryptContext

from audit_set.db_models import AuditSet, AuditSetStatusEvent, get_db as get_audit_db
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
        raise HTTPException(409, "An account with this email already exists. Please log in.")

    # Compute next plan_number
    from sqlalchemy import func
    max_plan = audit_db.query(func.max(AuditSet.plan_number)).scalar() or 1599
    plan_number = max_plan + 1

    # Build sites list from has_additional_sites
    sites = []
    if payload.has_additional_sites and payload.additional_site_count > 0:
        for i in range(payload.additional_site_count):
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
```

#### Register the router in `backend/main.py`

Find where other routers are included and add:
```python
from audit_set.apply_router import router as apply_router
app.include_router(apply_router)
```

Make sure this route has NO auth dependency — the `/apply` endpoint must be publicly accessible.

Also add CORS: the `/apply` endpoint should be reachable from any origin (since clients may
access it from outside the main app domain). If CORS is already configured globally, this is
already handled. If not, add `allow_origins=["*"]` specifically for the apply router.

### Frontend

#### New page: `frontend/src/app/apply/page.tsx`

This page lives OUTSIDE the `(app)` and `(auth)` route groups — it's fully public.
No auth check, no sidebar, no navbar from the internal portal.

The page renders a clean, branded form with IFC Global styling (dark green #1A4731).

```tsx
'use client'

import { useState } from 'react'
import axios from 'axios'

const STANDARDS = [
  { code: 'QMS',   label: 'ISO 9001:2015 — Quality Management' },
  { code: 'EMS',   label: 'ISO 14001:2015 — Environmental Management' },
  { code: 'OHSMS', label: 'ISO 45001:2018 — Occupational Health & Safety' },
  { code: 'FSMS',  label: 'ISO 22000:2018 — Food Safety Management' },
  { code: 'ISMS',  label: 'ISO/IEC 27001:2022 — Information Security' },
  { code: 'ENMS',  label: 'ISO 50001:2018 — Energy Management' },
  { code: 'MDQMS', label: 'ISO 13485:2016 — Medical Devices Quality' },
  { code: 'ABMS',  label: 'ISO 37001:2016 — Anti-Bribery Management' },
]

const SCOPE_EXAMPLES = [
  'Manufacturing and sales of dried fruits and roasted nuts',
  'Design, development and production of electronic control units',
  'Provision of road freight transport and logistics services',
  'Construction and installation of mechanical systems',
]

export default function ApplyPage() {
  const [form, setForm] = useState({
    company_name: '', company_address: '', city: '', country: '',
    phone: '', website: '',
    representative_name: '', representative_email: '',
    standards: [] as string[],
    audit_type: 'initial',
    scope_description: '',
    total_employees: '',
    has_additional_sites: false,
    additional_site_count: '',
  })
  const [loading, setLoading] = useState(false)
  const [success, setSuccess] = useState(false)
  const [error, setError] = useState('')

  function toggleStandard(code: string) {
    setForm(f => ({
      ...f,
      standards: f.standards.includes(code)
        ? f.standards.filter(s => s !== code)
        : [...f.standards, code],
    }))
  }

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault()
    setError('')
    if (form.standards.length === 0) {
      setError('Please select at least one standard.')
      return
    }
    setLoading(true)
    try {
      const apiBase = process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8000'
      await axios.post(`${apiBase}/apply`, {
        ...form,
        total_employees: parseInt(form.total_employees as string) || 0,
        additional_site_count: parseInt(form.additional_site_count as string) || 0,
      })
      setSuccess(true)
    } catch (err: any) {
      setError(err?.response?.data?.detail || 'Submission failed. Please try again.')
    } finally {
      setLoading(false)
    }
  }

  if (success) {
    return (
      <div className="min-h-screen bg-gray-50 flex items-center justify-center p-6">
        <div className="bg-white rounded-xl shadow-sm border p-10 max-w-md text-center">
          <div className="w-16 h-16 bg-green-100 rounded-full flex items-center justify-center mx-auto mb-4">
            <svg className="w-8 h-8 text-green-700" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M5 13l4 4L19 7" />
            </svg>
          </div>
          <h2 className="text-xl font-bold text-gray-900 mb-2">Application Submitted</h2>
          <p className="text-gray-600 mb-6">
            Thank you. We have received your application and will review it shortly.
            Login credentials have been sent to your email address.
          </p>
          <a
            href="/login"
            className="inline-block bg-[#1A4731] text-white px-6 py-2.5 rounded-lg text-sm font-medium"
          >
            Go to Portal Login
          </a>
        </div>
      </div>
    )
  }

  return (
    <div className="min-h-screen bg-gray-50 py-10 px-4">
      <div className="max-w-2xl mx-auto">
        {/* Header */}
        <div className="text-center mb-8">
          <h1 className="text-2xl font-bold text-[#1A4731]">IFC Global LLC</h1>
          <p className="text-gray-500 mt-1">Certification Application Form</p>
        </div>

        <form onSubmit={handleSubmit} className="bg-white rounded-xl shadow-sm border p-8 space-y-6">

          {/* Company Info */}
          <section>
            <h2 className="text-sm font-semibold text-gray-700 uppercase tracking-wide mb-4">Company Information</h2>
            <div className="grid grid-cols-1 gap-4">
              <Field label="Company Name *" required>
                <input className={inputCls} value={form.company_name} onChange={e => setForm({...form, company_name: e.target.value})} required />
              </Field>
              <Field label="Company Address *" required>
                <input className={inputCls} value={form.company_address} onChange={e => setForm({...form, company_address: e.target.value})} required />
              </Field>
              <div className="grid grid-cols-2 gap-4">
                <Field label="City">
                  <input className={inputCls} value={form.city} onChange={e => setForm({...form, city: e.target.value})} />
                </Field>
                <Field label="Country">
                  <input className={inputCls} value={form.country} onChange={e => setForm({...form, country: e.target.value})} />
                </Field>
              </div>
              <div className="grid grid-cols-2 gap-4">
                <Field label="Phone">
                  <input className={inputCls} type="tel" value={form.phone} onChange={e => setForm({...form, phone: e.target.value})} />
                </Field>
                <Field label="Website">
                  <input className={inputCls} type="url" placeholder="https://" value={form.website} onChange={e => setForm({...form, website: e.target.value})} />
                </Field>
              </div>
            </div>
          </section>

          {/* Contact Person */}
          <section>
            <h2 className="text-sm font-semibold text-gray-700 uppercase tracking-wide mb-4">Contact Person</h2>
            <div className="grid grid-cols-1 gap-4">
              <Field label="Full Name *" required>
                <input className={inputCls} value={form.representative_name} onChange={e => setForm({...form, representative_name: e.target.value})} required />
              </Field>
              <Field label="Email Address *" required>
                <input className={inputCls} type="email" value={form.representative_email} onChange={e => setForm({...form, representative_email: e.target.value})} required />
                <p className="text-xs text-gray-400 mt-1">Your portal login credentials will be sent to this address.</p>
              </Field>
            </div>
          </section>

          {/* Standards */}
          <section>
            <h2 className="text-sm font-semibold text-gray-700 uppercase tracking-wide mb-4">Standards Requested *</h2>
            <div className="grid grid-cols-1 gap-2">
              {STANDARDS.map(s => (
                <label key={s.code} className="flex items-center gap-3 p-3 rounded-lg border cursor-pointer hover:bg-gray-50 transition-colors">
                  <input
                    type="checkbox"
                    checked={form.standards.includes(s.code)}
                    onChange={() => toggleStandard(s.code)}
                    className="w-4 h-4 accent-[#1A4731]"
                  />
                  <span className="text-sm text-gray-700">{s.label}</span>
                </label>
              ))}
            </div>
          </section>

          {/* Audit Type */}
          <section>
            <h2 className="text-sm font-semibold text-gray-700 uppercase tracking-wide mb-4">Audit Type *</h2>
            <div className="grid grid-cols-3 gap-3">
              {[
                {v:'initial', l:'Initial Certification'},
                {v:'surveillance', l:'Surveillance'},
                {v:'recertification', l:'Recertification'},
              ].map(opt => (
                <label key={opt.v} className={`p-3 rounded-lg border text-center cursor-pointer text-sm transition-colors ${form.audit_type === opt.v ? 'bg-[#1A4731] text-white border-[#1A4731]' : 'bg-white text-gray-700 hover:bg-gray-50'}`}>
                  <input type="radio" name="audit_type" value={opt.v} checked={form.audit_type === opt.v} onChange={e => setForm({...form, audit_type: e.target.value})} className="hidden" />
                  {opt.l}
                </label>
              ))}
            </div>
          </section>

          {/* Scope */}
          <section>
            <h2 className="text-sm font-semibold text-gray-700 uppercase tracking-wide mb-1">What Does Your Company Do? *</h2>
            <p className="text-xs text-gray-400 mb-3">Describe your main activities. Examples: {SCOPE_EXAMPLES.slice(0,2).join('; ')}</p>
            <textarea
              className={`${inputCls} h-24 resize-none`}
              placeholder={SCOPE_EXAMPLES[0]}
              value={form.scope_description}
              onChange={e => setForm({...form, scope_description: e.target.value})}
              required
            />
          </section>

          {/* Employees */}
          <section>
            <h2 className="text-sm font-semibold text-gray-700 uppercase tracking-wide mb-4">Personnel</h2>
            <div className="grid grid-cols-2 gap-4">
              <Field label="Total Number of Employees *" required>
                <input className={inputCls} type="number" min="1" value={form.total_employees} onChange={e => setForm({...form, total_employees: e.target.value})} required />
              </Field>
            </div>
            <label className="flex items-center gap-2 mt-4 cursor-pointer">
              <input type="checkbox" checked={form.has_additional_sites} onChange={e => setForm({...form, has_additional_sites: e.target.checked})} className="w-4 h-4 accent-[#1A4731]" />
              <span className="text-sm text-gray-700">We have additional sites / branches</span>
            </label>
            {form.has_additional_sites && (
              <div className="mt-3">
                <Field label="Number of Additional Sites">
                  <input className={inputCls} type="number" min="1" value={form.additional_site_count} onChange={e => setForm({...form, additional_site_count: e.target.value})} />
                </Field>
              </div>
            )}
          </section>

          {error && (
            <div className="bg-red-50 border border-red-200 text-red-700 text-sm rounded-lg p-3">
              {error}
            </div>
          )}

          <button
            type="submit"
            disabled={loading}
            className="w-full bg-[#1A4731] text-white py-3 rounded-lg font-medium hover:bg-[#143828] transition-colors disabled:opacity-60"
          >
            {loading ? 'Submitting...' : 'Submit Application'}
          </button>

          <p className="text-xs text-center text-gray-400">
            Already have an account? <a href="/login" className="text-[#1A4731] underline">Sign in here</a>
          </p>
        </form>
      </div>
    </div>
  )
}

const inputCls = "w-full border border-gray-200 rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-[#1A4731]/30 focus:border-[#1A4731]"

function Field({ label, children, required }: { label: string; children: React.ReactNode; required?: boolean }) {
  return (
    <div>
      <label className="block text-sm font-medium text-gray-700 mb-1">{label}</label>
      {children}
    </div>
  )
}
```

### Verify

1. Backend: `GET /apply` should return 405 (route exists), `POST /apply` with valid body should return `{"success": true, ...}`
2. Frontend: `/apply` page renders without auth, shows the form, submits successfully
3. Existing `/clients/new` internal page is completely untouched

### Commit and push

Commit: `feat(portal): public client application form + auto account creation`
Push to main.

## Files to create/edit
- `backend/audit_set/apply_router.py` — new file
- `backend/main.py` — register apply_router (no auth)
- `frontend/src/app/apply/page.tsx` — new public page
