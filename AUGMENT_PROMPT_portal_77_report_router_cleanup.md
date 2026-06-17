# Portal 77 — report_router.py cleanup + reviewer signing fixes

## What is wrong (found by inspection after Portal 76)

| # | Severity | Issue |
|---|----------|-------|
| 1 | Critical | `review_request_otp` + `review_verify_otp` still registered — OTP was removed system-wide |
| 2 | Critical | `la_request_otp` + `la_verify_otp` still registered — same problem |
| 3 | High | `la_sign_direct` never calls `_notify_reviewer` — reviewer never gets email when LA signs |
| 4 | High | `review_sign_direct` never sets `reviewer_user_id` / `reviewer_signed_ip` — audit trail is broken |
| 5 | High | `review_sign_direct` doesn't run the workflow-advance logic (under_review → certified + notify client) — only the dead OTP `review_verify_otp` did that |
| 6 | High | `review_sign_direct` double-fetches the report with a broken conditional auth pattern |
| 7 | Medium | Frontend auditor portal `page.tsx` reviewer panel calls OTP routes (`request-otp` / `verify`) |
| 8 | Medium | `AuditReportSection.tsx` "Assign Reviewer" button visible to `officer` / `gm` who get 403 |
| 9 | Low | Dead imports: `hashlib`, `timedelta`, `send_otp_code`, `OTP_EXPIRY`, `_hash` |

---

## File 1 — `backend/audit_set/report_router.py`

### Edit 1 — Replace module docstring + remove dead imports

**BEFORE:**
```python
"""
BATUHAN — FR.231 / FR.229 / FR.232 Audit Report Signing (Prompt 19).

Lead Auditor uploads the report file and signs it (auditor portal).
Committee Reviewer then approves via OTP (CB portal).

Routes:
  POST /audit-sets/{id}/audit-reports/upload             (auditor + admin/planner)
  GET  /audit-sets/{id}/audit-reports                    (CB + auditor)
  GET  /audit-sets/{id}/audit-reports/{rid}/download     (CB + auditor)
  POST /audit-sets/{id}/audit-reports/{rid}/sign/la/request-otp   (lead auditor)
  POST /audit-sets/{id}/audit-reports/{rid}/sign/la/verify         (lead auditor)
  POST /audit-sets/{id}/audit-reports/{rid}/sign/review/request-otp  (committee reviewer)
  POST /audit-sets/{id}/audit-reports/{rid}/sign/review/verify       (committee reviewer)
"""
from __future__ import annotations
import hashlib
import os
import secrets
from datetime import date, datetime, timedelta
from typing import Optional
```

**AFTER:**
```python
"""
BATUHAN — FR.231 / FR.229 / FR.232 Audit Report Signing.

Lead Auditor uploads and signs via direct-sign (auditor portal).
Assigned Reviewer Auditor (or CM/admin bypass) approves via direct-sign.

Routes:
  POST /audit-sets/{id}/audit-reports/upload                     (auditor + admin/planner)
  GET  /audit-sets/{id}/audit-reports                            (CB + auditor)
  GET  /audit-sets/{id}/audit-reports/reviewer-candidates        (CB)
  GET  /audit-sets/{id}/audit-reports/{rid}/download             (CB + auditor)
  PUT  /audit-sets/{id}/audit-reports/{rid}/reviewer             (planner/admin)
  POST /audit-sets/{id}/audit-reports/{rid}/sign/la/direct       (lead auditor)
  POST /audit-sets/{id}/audit-reports/{rid}/sign/review/direct   (reviewer auditor / CM)
"""
from __future__ import annotations
import os
import secrets
from datetime import date, datetime
from typing import Optional
```

---

### Edit 2 — Remove `send_otp_code` from email_service import

**BEFORE:**
```python
from email_service import (
    send_audit_report_review_request,
    send_client_status_update,
    send_otp_code,
)
```

**AFTER:**
```python
from email_service import (
    send_audit_report_review_request,
    send_client_status_update,
)
```

---

### Edit 3 — Remove `OTP_EXPIRY` constant

**BEFORE:**
```python
OTP_EXPIRY    = 10  # minutes
```

**AFTER:**
```python
# (OTP_EXPIRY removed — OTP signing was removed system-wide)
```

---

### Edit 4 — Remove `_hash` helper function

**BEFORE:**
```python
def _hash(val: str) -> str:
    return hashlib.sha256(val.encode()).hexdigest()
```

**AFTER:**
*(delete entirely — `hashlib` import also no longer needed)*

---

### Edit 5 — Remove `la_request_otp` and `la_verify_otp` (dead OTP routes)

**BEFORE:**
```python
@router.post("/audit-sets/{audit_set_id}/audit-reports/{rid}/sign/la/request-otp")
def la_request_otp(
    audit_set_id: str,
    rid: str,
    db:      Session = Depends(get_db),
    auth_db: Session = Depends(get_auth_db),
    current_user: PlatformUser = Depends(get_current_user),
):
    report = db.query(AuditSetAuditReport).filter_by(
        id=rid, audit_set_id=audit_set_id
    ).first()
    if not report:
        raise HTTPException(404, "Report not found")
    _check_la_auth(report, current_user, db)
    if report.la_signed_at:
        raise HTTPException(400, "Already signed")

    otp = f"{secrets.randbelow(900000) + 100000}"
    report.la_otp_hash    = _hash(otp)
    report.la_otp_expires = datetime.utcnow() + timedelta(minutes=OTP_EXPIRY)
    db.commit()

    try:
        send_otp_code(
            to=current_user.email,
            full_name=current_user.full_name,
            otp=otp,
            document_label=f"{report.report_form} — {report.label}",
        )
    except Exception:
        pass

    return {"message": f"Code sent to {current_user.email}. Valid for {OTP_EXPIRY} minutes."}


class SignReportBody(BaseModel):
    signed_date: Optional[date] = None


@router.post("/audit-sets/{audit_set_id}/audit-reports/{rid}/sign/la/verify")
def la_verify_otp(
    audit_set_id: str,
    rid: str,
    otp: str,
    request: Request,
    body:    SignReportBody = Body(default_factory=SignReportBody),
    db:      Session = Depends(get_db),
    auth_db: Session = Depends(get_auth_db),
    current_user: PlatformUser = Depends(get_current_user),
):
    report = db.query(AuditSetAuditReport).filter_by(
        id=rid, audit_set_id=audit_set_id
    ).first()
    if not report:
        raise HTTPException(404, "Report not found")
    _check_la_auth(report, current_user, db)
    if report.la_signed_at:
        raise HTTPException(400, "Already signed")
    if not report.la_otp_hash or not report.la_otp_expires:
        raise HTTPException(400, "No pending OTP. Request one first.")
    if datetime.utcnow() > report.la_otp_expires:
        raise HTTPException(400, "OTP expired. Please request a new one.")
    if _hash(otp.strip()) != report.la_otp_hash:
        raise HTTPException(400, "Invalid code.")

    signed_dt = (
        datetime.combine(body.signed_date, datetime.min.time())
        if body.signed_date else datetime.utcnow()
    )
    report.la_user_id      = current_user.id
    report.la_signed_at    = signed_dt
    report.la_signed_ip    = request.client.host if request.client else None
    report.la_otp_hash     = None
    report.la_otp_expires  = None
    report.status          = "pending_review"
    db.commit()

    # Portal 76 — notify the assigned reviewer auditor (or legacy committee reviewer).
    audit_set = db.query(AuditSet).filter_by(id=audit_set_id).first()
    _notify_reviewer(db, report, audit_set)

    return {
        "signed": True,
        "status": "pending_review",
        "la_signed_at": report.la_signed_at.isoformat(),
    }
```

**AFTER:**
```python
class SignReportBody(BaseModel):
    signed_date: Optional[date] = None
```

*(Both OTP routes deleted. `SignReportBody` stays — it is used by the direct-sign routes.)*

---

### Edit 6 — Fix `la_sign_direct`: add `Request`, record `la_user_id` / `la_signed_ip`, call `_notify_reviewer`

**BEFORE:**
```python
@router.post("/audit-sets/{audit_set_id}/audit-reports/{rid}/sign/la/direct")
def la_sign_direct(
    audit_set_id: str,
    rid: str,
    body: SignReportBody = Body(default_factory=SignReportBody),
    db:   Session = Depends(get_db),
    current_user: PlatformUser = Depends(get_current_user),
):
    report = db.query(AuditSetAuditReport).filter_by(
        id=rid, audit_set_id=audit_set_id
    ).first()
    if not report:
        raise HTTPException(404, "Report not found")
    _check_la_auth(report, current_user, db)
    if report.la_signed_at:
        raise HTTPException(400, "Report already signed by Lead Auditor")
    if report.status not in ("pending_la",):
        raise HTTPException(400, f"Report status is '{report.status}', expected 'pending_la'")

    report.la_signed_at = (
        datetime.combine(body.signed_date, datetime.min.time())
        if body.signed_date else datetime.utcnow()
    )
    report.status       = "pending_review"
    db.commit()
    db.refresh(report)
    return _report_dict(report)
```

**AFTER:**
```python
@router.post("/audit-sets/{audit_set_id}/audit-reports/{rid}/sign/la/direct")
def la_sign_direct(
    audit_set_id: str,
    rid:     str,
    request: Request,
    body:    SignReportBody = Body(default_factory=SignReportBody),
    db:      Session = Depends(get_db),
    current_user: PlatformUser = Depends(get_current_user),
):
    report = db.query(AuditSetAuditReport).filter_by(
        id=rid, audit_set_id=audit_set_id
    ).first()
    if not report:
        raise HTTPException(404, "Report not found")
    _check_la_auth(report, current_user, db)
    if report.la_signed_at:
        raise HTTPException(400, "Report already signed by Lead Auditor")
    if report.status not in ("pending_la",):
        raise HTTPException(400, f"Report status is '{report.status}', expected 'pending_la'")

    report.la_user_id   = current_user.id
    report.la_signed_at = (
        datetime.combine(body.signed_date, datetime.min.time())
        if body.signed_date else datetime.utcnow()
    )
    report.la_signed_ip = request.client.host if request.client else None
    report.status       = "pending_review"
    db.commit()

    # Notify assigned reviewer that the report is ready for their signature.
    audit_set = db.query(AuditSet).filter_by(id=audit_set_id).first()
    _notify_reviewer(db, report, audit_set)

    db.refresh(report)
    return _report_dict(report)
```

---

### Edit 7 — Remove `review_request_otp` and `review_verify_otp` (dead OTP routes)

**BEFORE** (remove these two route functions entirely):
```python
@router.post("/audit-sets/{audit_set_id}/audit-reports/{rid}/sign/review/request-otp")
def review_request_otp(
    ...
):
    ...

@router.post("/audit-sets/{audit_set_id}/audit-reports/{rid}/sign/review/verify")
def review_verify_otp(
    ...
):
    ...
```

**AFTER:** *(both deleted)*

---

### Edit 8 — Fix `review_sign_direct`: single fetch, full audit trail, workflow-advance

**BEFORE:**
```python
# ── Committee Reviewer: direct-approve (no OTP) ──────────────────────────────

@router.post("/audit-sets/{audit_set_id}/audit-reports/{rid}/sign/review/direct")
def review_sign_direct(
    audit_set_id: str,
    rid: str,
    body: SignReportBody = Body(default_factory=SignReportBody),
    db:   Session = Depends(get_db),
    current_user: PlatformUser = Depends(get_current_user),
):
    # Portal 76 — use unified auth: admin/CM bypass, assigned auditor, or
    # legacy committee-reviewer fallback.
    if current_user.role not in ("admin", "executive", "certification_manager"):
        report_pre = db.query(AuditSetAuditReport).filter_by(
            id=rid, audit_set_id=audit_set_id
        ).first()
        if report_pre:
            _check_reviewer_auth(report_pre, current_user, db)

    report = db.query(AuditSetAuditReport).filter_by(
        id=rid, audit_set_id=audit_set_id
    ).first()
    if not report:
        raise HTTPException(404, "Report not found")
    if report.status == "approved":
        raise HTTPException(400, "Report already approved")
    if report.status != "pending_review":
        raise HTTPException(400, f"Report status is '{report.status}', expected 'pending_review'")

    report.reviewer_signed_at = (
        datetime.combine(body.signed_date, datetime.min.time())
        if body.signed_date else datetime.utcnow()
    )
    report.status             = "approved"
    db.commit()
    db.refresh(report)
    return _report_dict(report, can_review=False)
```

**AFTER:**
```python
# ── Reviewer: direct-sign (Portal 77 — only signing path, no OTP) ────────────

@router.post("/audit-sets/{audit_set_id}/audit-reports/{rid}/sign/review/direct")
def review_sign_direct(
    audit_set_id: str,
    rid:     str,
    request: Request,
    body:    SignReportBody = Body(default_factory=SignReportBody),
    db:      Session = Depends(get_db),
    auth_db: Session = Depends(get_auth_db),
    current_user: PlatformUser = Depends(get_current_user),
):
    # Fetch once — 404 first, then auth.
    report = db.query(AuditSetAuditReport).filter_by(
        id=rid, audit_set_id=audit_set_id
    ).first()
    if not report:
        raise HTTPException(404, "Report not found")

    _check_reviewer_auth(report, current_user, db)

    if report.status == "approved":
        raise HTTPException(400, "Report already approved")
    if report.status != "pending_review":
        raise HTTPException(400, f"Report status is '{report.status}', expected 'pending_review'")

    signed_dt = (
        datetime.combine(body.signed_date, datetime.min.time())
        if body.signed_date else datetime.utcnow()
    )
    report.reviewer_user_id   = current_user.id
    report.reviewer_signed_at = signed_dt
    report.reviewer_signed_ip = request.client.host if request.client else None
    report.status             = "approved"
    db.commit()

    # ── Auto-advance workflow: under_review → certified ───────────────────────
    audit_set = db.query(AuditSet).filter_by(id=audit_set_id).first()
    if audit_set and audit_set.workflow_status == "under_review":
        audit_set.workflow_status  = "certified"
        audit_set.cert_issued_date = body.signed_date or datetime.utcnow().date()
        db.add(AuditSetStatusEvent(
            audit_set_id=audit_set_id,
            from_status="under_review",
            to_status="certified",
            triggered_by=current_user.id,
            notes=(
                f"Audit report '{report.report_form} — {report.label}' "
                "approved by assigned reviewer."
            ),
        ))
        db.commit()

        # Notify client — best-effort
        try:
            client_user = auth_db.query(PlatformUser).filter_by(
                audit_set_id=audit_set_id, role="client",
            ).first()
            if client_user:
                send_client_status_update(
                    to=client_user.email,
                    full_name=client_user.full_name,
                    new_status="certified",
                    notes=(
                        "Your audit report has been reviewed and approved "
                        "by the certification committee."
                    ),
                )
        except Exception:
            pass

    db.refresh(report)
    return _report_dict(report, can_review=False)
```

---

## File 2 — `frontend/src/app/(auditor)/auditor/audit/[id]/page.tsx`

### Edit 1 — Replace OTP state vars with direct-sign state vars

**BEFORE:**
```tsx
  // Reviewer OTP signing state (Portal 76)
  const [reviewOtpStep,    setReviewOtpStep]    = useState<Record<string, 'idle'|'sent'|'signing'>>({})
  const [reviewOtp,        setReviewOtp]        = useState<Record<string, string>>({})
  const [reviewSignDate,   setReviewSignDate]   = useState<Record<string, string>>({})
  const [reviewErr,        setReviewErr]        = useState<Record<string, string>>({})
```

**AFTER:**
```tsx
  // Reviewer direct-sign state (Portal 77)
  const [reviewSignDate, setReviewSignDate] = useState<Record<string, string>>({})
  const [reviewSigning,  setReviewSigning]  = useState<Record<string, boolean>>({})
  const [reviewErr,      setReviewErr]      = useState<Record<string, string>>({})
```

---

### Edit 2 — Replace OTP handler functions with single direct-sign handler

**BEFORE (remove both):**
```tsx
  async function handleReviewRequestOtp(id: string) {
    setReviewOtpStep(s => ({ ...s, [id]: 'signing' }))
    setReviewErr(e => ({ ...e, [id]: '' }))
    try {
      await api.post(`/audit-sets/${auditSetId}/audit-reports/${id}/sign/review/request-otp`)
      setReviewOtpStep(s => ({ ...s, [id]: 'sent' }))
    } catch (err: unknown) {
      const detail = (err as { response?: { data?: { detail?: string } } })?.response?.data?.detail
      setReviewErr(e => ({ ...e, [id]: detail || 'Failed to send OTP' }))
      setReviewOtpStep(s => ({ ...s, [id]: 'idle' }))
    }
  }

  async function handleReviewVerifyOtp(id: string) {
    setReviewOtpStep(s => ({ ...s, [id]: 'signing' }))
    setReviewErr(e => ({ ...e, [id]: '' }))
    try {
      const signed_date = reviewSignDate[id] || new Date().toISOString().slice(0, 10)
      const r = await api.post(
        `/audit-sets/${auditSetId}/audit-reports/${id}/sign/review/verify?otp=${encodeURIComponent(reviewOtp[id] || '')}`,
        { signed_date }
      )
      setReports(prev => prev.map(rpt => rpt.id === id ? { ...rpt, ...(r.data as object), can_review: false } : rpt))
      setReviewOtpStep(s => ({ ...s, [id]: 'idle' }))
    } catch (err: unknown) {
      const detail = (err as { response?: { data?: { detail?: string } } })?.response?.data?.detail
      setReviewErr(e => ({ ...e, [id]: detail || 'Verification failed' }))
      setReviewOtpStep(s => ({ ...s, [id]: 'sent' }))
    }
  }
```

**AFTER (one function):**
```tsx
  async function handleReviewSign(id: string) {
    setReviewSigning(s => ({ ...s, [id]: true }))
    setReviewErr(e => ({ ...e, [id]: '' }))
    try {
      const signed_date = reviewSignDate[id] || new Date().toISOString().slice(0, 10)
      const r = await api.post(
        `/audit-sets/${auditSetId}/audit-reports/${id}/sign/review/direct`,
        { signed_date }
      )
      setReports(prev =>
        prev.map(rpt =>
          rpt.id === id ? { ...rpt, ...(r.data as object), can_review: false } : rpt
        )
      )
    } catch (err: unknown) {
      const detail = (err as { response?: { data?: { detail?: string } } })?.response?.data?.detail
      setReviewErr(e => ({ ...e, [id]: detail || 'Signing failed' }))
    } finally {
      setReviewSigning(s => ({ ...s, [id]: false }))
    }
  }
```

---

### Edit 3 — Replace OTP reviewer panel JSX with direct-sign panel

Find the reviewer signing panel block (the one using `reviewOtpStep`, `step === 'idle'`, `step === 'sent'`, etc.) and replace it entirely.

**BEFORE:**
```tsx
                    {/* Portal 76 — Reviewer signing panel */}
                    {r.can_review && r.status === 'pending_review' && (() => {
                      const step = reviewOtpStep[r.id] || 'idle'
                      return (
                        <div className="mt-3 rounded-lg border border-blue-200 bg-blue-50 p-3">
                          <p className="mb-2 text-xs font-medium text-blue-800">
                            You are assigned as the reviewer for this report.
                          </p>
                          {step === 'idle' && (
                            <button
                              type="button"
                              onClick={() => handleReviewRequestOtp(r.id)}
                              className="rounded-lg bg-[#1A4731] px-3 py-1.5 text-xs text-white hover:bg-[#143828]"
                            >
                              Sign as Reviewer — Send OTP
                            </button>
                          )}
                          {step === 'sent' && (
                            <div className="space-y-2">
                              <p className="text-xs text-blue-700">
                                A verification code was sent to your email. Enter it below.
                              </p>
                              <div className="flex flex-wrap items-center gap-2">
                                <input
                                  type="text"
                                  placeholder="6-digit code"
                                  value={reviewOtp[r.id] || ''}
                                  onChange={e => setReviewOtp(ot => ({ ...ot, [r.id]: e.target.value }))}
                                  className="w-32 rounded-lg border px-2 py-1.5 text-sm"
                                />
                                <input
                                  type="date"
                                  value={reviewSignDate[r.id] || new Date().toISOString().slice(0, 10)}
                                  onChange={e => setReviewSignDate(d => ({ ...d, [r.id]: e.target.value }))}
                                  className="rounded-lg border px-2 py-1.5 text-sm"
                                />
                                <button
                                  type="button"
                                  onClick={() => handleReviewVerifyOtp(r.id)}
                                  disabled={!reviewOtp[r.id]}
                                  className="rounded-lg bg-[#1A4731] px-3 py-1.5 text-xs text-white disabled:opacity-40 hover:bg-[#143828]"
                                >
                                  Confirm Signature
                                </button>
                              </div>
                            </div>
                          )}
                          {step === 'signing' && (
                            <p className="text-xs text-gray-500">Processing…</p>
                          )}
                          {reviewErr[r.id] && (
                            <p className="mt-1 text-xs text-red-500">{reviewErr[r.id]}</p>
                          )}
                        </div>
                      )
                    })()}
```

**AFTER:**
```tsx
                    {/* Portal 77 — Reviewer direct-sign panel */}
                    {r.can_review && r.status === 'pending_review' && (
                      <div className="mt-3 rounded-lg border border-blue-200 bg-blue-50 p-3">
                        <p className="mb-2 text-xs font-medium text-blue-800">
                          You are assigned as the reviewer for this report.
                        </p>
                        <div className="flex flex-wrap items-center gap-2">
                          <input
                            type="date"
                            value={reviewSignDate[r.id] || new Date().toISOString().slice(0, 10)}
                            onChange={e => setReviewSignDate(d => ({ ...d, [r.id]: e.target.value }))}
                            className="rounded-lg border bg-white px-2 py-1.5 text-sm"
                          />
                          <button
                            type="button"
                            disabled={reviewSigning[r.id]}
                            onClick={() => handleReviewSign(r.id)}
                            className="flex items-center gap-1.5 rounded-lg bg-[#1A4731] px-3 py-1.5 text-xs text-white disabled:opacity-40 hover:bg-[#143828]"
                          >
                            {reviewSigning[r.id] && <span className="animate-spin">⟳</span>}
                            {reviewSigning[r.id] ? 'Signing…' : 'Sign as Reviewer'}
                          </button>
                        </div>
                        {reviewErr[r.id] && (
                          <p className="mt-1 text-xs text-red-500">{reviewErr[r.id]}</p>
                        )}
                      </div>
                    )}
```

---

## File 3 — `frontend/src/components/ui/AuditReportSection.tsx`

### Edit 1 — Guard "Assign Reviewer" button to planner/admin roles only

Find the "Assign Reviewer / Change Reviewer" button render condition.  Currently it shows for any CB user.  Add a role check.

First, `AuditReportSection` needs to know the current user's role.  Add a `userRole` prop:

**BEFORE:**
```tsx
export function AuditReportSection({
  auditSetId,
  workflowStatus,
}: {
  auditSetId: string
  workflowStatus: string | null
}) {
```

**AFTER:**
```tsx
export function AuditReportSection({
  auditSetId,
  workflowStatus,
  userRole,
}: {
  auditSetId: string
  workflowStatus: string | null
  userRole?: string
}) {
```

Then add a derived constant inside the component (after the state declarations):

```tsx
  const canAssignReviewer = ['admin', 'planner', 'certification_manager', 'executive'].includes(userRole ?? '')
```

Then wrap the "Assign Reviewer" button in the existing condition with `canAssignReviewer`:

**BEFORE:**
```tsx
                    {/* Assign Reviewer button — only before approval */}
                    {r.status !== 'approved' && (
                      <button
                        type="button"
                        onClick={() => openAssignPanel(r.id)}
                        ...
                      >
                        {r.reviewer_auditor_name ? 'Change Reviewer' : 'Assign Reviewer'}
                      </button>
                    )}
```

**AFTER:**
```tsx
                    {/* Assign Reviewer button — planner/admin only, before approval */}
                    {canAssignReviewer && r.status !== 'approved' && (
                      <button
                        type="button"
                        onClick={() => openAssignPanel(r.id)}
                        ...
                      >
                        {r.reviewer_auditor_name ? 'Change Reviewer' : 'Assign Reviewer'}
                      </button>
                    )}
```

### Edit 2 — Pass `userRole` wherever `AuditReportSection` is rendered

Find every usage of `<AuditReportSection` in the codebase and add the `userRole` prop
sourced from the logged-in user's role (already available in whichever page component
renders this — e.g. from `useUser()` / auth context / `currentUser.role`).

Example:
```tsx
<AuditReportSection
  auditSetId={auditSet.id}
  workflowStatus={auditSet.workflow_status}
  userRole={currentUser?.role}
/>
```

---

## What does NOT change

- `db_models.py` — no change
- `committee_router.py` — no change
- `viewer_router.py` — no change
- All other routes in `report_router.py` — upload, list, download, assign_reviewer, reviewer-candidates — all correct

---

## Commit message

```
Portal 77: remove OTP from report signing; fix review_sign_direct audit trail

Removes all dead OTP routes (la/request-otp, la/verify, review/request-otp,
review/verify) and dead helpers (_hash, OTP_EXPIRY, send_otp_code import,
timedelta import). OTP was removed system-wide; Portal 76 missed this.

Fixes:
- la_sign_direct: records la_user_id + la_signed_ip; calls _notify_reviewer
  so the assigned reviewer actually receives an email when LA signs
- review_sign_direct: single report fetch; records reviewer_user_id +
  reviewer_signed_ip; runs workflow-advance (under_review → certified) and
  notifies client — logic that was previously only in the dead OTP route
- Auditor portal reviewer panel: replaced 3-step OTP flow with single
  date-picker + "Sign as Reviewer" button calling sign/review/direct
- AuditReportSection: "Assign Reviewer" button now hidden for officer/gm
  roles that would receive a 403 from the backend
```
