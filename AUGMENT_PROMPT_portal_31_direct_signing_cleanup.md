# Prompt 31 — Direct Signing Cleanup (Audit Reports + Meeting Attendees)

## Context

Prompt 28 removed OTP from shared document signing and internal approvals. Two signing
flows were not covered and are now broken (email is permanently stubbed to return False):

1. **Audit report signing** — Lead Auditor signs the uploaded report; a Committee Reviewer
   then approves it. Both use OTP sent by email → broken.

2. **Meeting attendee signing** — Opening / closing meeting attendance is captured via a
   tokenised guest link sent by email → never arrives → attendees can never be marked as
   signed.

For the retroactive operation, both flows are required to record historical audit data.
This prompt replaces all remaining OTP / email-token signing with **direct sign** (same
pattern as Prompt 28).

**Nothing else changes.** Workflow transitions, document generation, committee setup,
and stage planning are untouched.

---

## Summary of changes

| File | What changes |
|------|-------------|
| `backend/audit_set/report_router.py` | Add 2 direct-sign endpoints; keep OTP endpoints (don't delete — just ignore) |
| `backend/audit_set/meeting_router.py` | Add 1 direct-sign endpoint |
| `frontend/src/components/ui/AuditReportSection.tsx` | Replace OTP review-approve flow with direct approve button |
| `frontend/src/components/ui/MeetingAttendeesSection.tsx` | Add direct sign buttons for opening and closing meetings |
| Auditor portal report-signing page (wherever it lives) | Replace OTP LA-sign flow with direct sign button |

---

## Change 1 — `backend/audit_set/report_router.py`

### 1a — Add Lead Auditor direct-sign endpoint

```python
@router.post("/audit-sets/{audit_set_id}/audit-reports/{rid}/sign/la/direct")
def la_sign_direct(
    audit_set_id: str,
    rid: str,
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

    report.la_signed_at = datetime.utcnow()
    report.status       = "pending_review"
    db.commit()
    db.refresh(report)
    return _report_dict(report)
```

### 1b — Add Committee Reviewer direct-approve endpoint

```python
@router.post("/audit-sets/{audit_set_id}/audit-reports/{rid}/sign/review/direct")
def review_sign_direct(
    audit_set_id: str,
    rid: str,
    db:      Session = Depends(get_db),
    current_user: PlatformUser = Depends(get_current_user),
):
    # Admin and executive can always approve.
    # Other roles must be a registered Committee Reviewer for this audit set.
    if current_user.role not in ("admin", "executive"):
        reviewer = _get_committee_reviewer(audit_set_id, current_user, db)
        if not reviewer:
            raise HTTPException(403, "You are not a registered reviewer for this audit set")

    report = db.query(AuditSetAuditReport).filter_by(
        id=rid, audit_set_id=audit_set_id
    ).first()
    if not report:
        raise HTTPException(404, "Report not found")
    if report.status == "approved":
        raise HTTPException(400, "Report already approved")
    if report.status != "pending_review":
        raise HTTPException(400, f"Report status is '{report.status}', expected 'pending_review'")

    report.reviewer_signed_at = datetime.utcnow()
    report.status             = "approved"
    db.commit()
    db.refresh(report)
    return _report_dict(report, can_review=False)
```

### 1c — Update `_report_dict` to expose `la_signed_at` and `reviewer_signed_at`

`_report_dict` already serialises both fields — no change needed.

---

## Change 2 — `backend/audit_set/meeting_router.py`

Add a direct-sign endpoint to the `protected_router` (auth required, CB staff or auditor):

```python
class DirectSignSchema(BaseModel):
    meeting_type: str  # "opening" | "closing"

@protected_router.post("/{audit_set_id}/meeting-attendees/{att_id}/sign-direct")
def sign_attendee_direct(
    audit_set_id: str,
    att_id:       str,
    body: DirectSignSchema,
    db:           Session = Depends(get_db),
    current_user: PlatformUser = Depends(get_current_user),
):
    if current_user.role not in ALLOWED_ROLES:
        raise HTTPException(403, "Not authorized")
    if body.meeting_type not in ("opening", "closing"):
        raise HTTPException(400, "meeting_type must be 'opening' or 'closing'")

    att = db.query(AuditSetMeetingAttendee).filter_by(
        id=att_id, audit_set_id=audit_set_id
    ).first()
    if not att:
        raise HTTPException(404, "Attendee not found")

    now = datetime.utcnow()
    if body.meeting_type == "opening":
        if att.opening_signed_at:
            raise HTTPException(400, "Opening meeting already marked as signed")
        att.opening_signed_at = now
    else:
        if att.closing_signed_at:
            raise HTTPException(400, "Closing meeting already marked as signed")
        att.closing_signed_at = now

    db.commit()
    db.refresh(att)
    return _att_dict(att)
```

---

## Change 3 — `frontend/src/components/ui/AuditReportSection.tsx`

### 3a — Remove all OTP state and functions

Remove:
- `otpStates`, `otpValues`, `messages`, `busy` state
- `requestReviewOtp()` function
- `verifyReviewOtp()` function

### 3b — Replace with direct-approve state

```typescript
const [approving, setApproving] = useState<Record<string, boolean>>({})
const [errors,    setErrors]    = useState<Record<string, string>>({})
```

### 3c — Add `handleApprove` function

```typescript
async function handleApprove(id: string) {
  setApproving(a => ({ ...a, [id]: true }))
  setErrors(e => ({ ...e, [id]: '' }))
  try {
    const r = await api.post<AuditReport>(
      `/audit-sets/${auditSetId}/audit-reports/${id}/sign/review/direct`
    )
    setReports(prev =>
      prev.map(rpt => (rpt.id === id ? { ...rpt, ...r.data, can_review: false } : rpt))
    )
  } catch (err: unknown) {
    const detail = (err as { response?: { data?: { detail?: string } } })?.response?.data?.detail
    setErrors(e => ({ ...e, [id]: detail || 'Approval failed' }))
  } finally {
    setApproving(a => ({ ...a, [id]: false }))
  }
}
```

### 3d — Update the report card render

Replace the OTP block (the `r.can_review` section and the `state === 'otp_sent'` and
`state === 'done'` sections) with:

```tsx
{r.can_review && r.status === 'pending_review' && (
  <div className="mt-2">
    <button
      type="button"
      onClick={() => handleApprove(r.id)}
      disabled={approving[r.id]}
      className="flex items-center gap-1.5 rounded-lg bg-[#1A4731] px-4 py-2 text-sm text-white disabled:opacity-40 hover:bg-[#143828]"
    >
      {approving[r.id] && <span className="animate-spin text-sm">⟳</span>}
      {approving[r.id] ? 'Approving…' : 'Approve Report'}
    </button>
    {errors[r.id] && (
      <p className="mt-1 text-xs text-red-500">{errors[r.id]}</p>
    )}
  </div>
)}
{r.status === 'approved' && (
  <p className="mt-1 text-sm font-medium text-green-600">Report approved ✓</p>
)}
```

---

## Change 4 — `frontend/src/components/ui/MeetingAttendeesSection.tsx`

### 4a — Add direct-sign state

```typescript
const [signing, setSigning] = useState<Record<string, boolean>>({})
const [signErr, setSignErr] = useState<Record<string, string>>({})
```

### 4b — Add `handleDirectSign` function

```typescript
async function handleDirectSign(attId: string, meetingType: 'opening' | 'closing') {
  const key = `${attId}-${meetingType}`
  setSigning(s => ({ ...s, [key]: true }))
  setSignErr(e => ({ ...e, [key]: '' }))
  try {
    const r = await api.post<Attendee>(
      `/audit-sets/${auditSetId}/meeting-attendees/${attId}/sign-direct`,
      { meeting_type: meetingType }
    )
    setAttendees(prev => prev.map(a => (a.id === attId ? r.data : a)))
  } catch (err: unknown) {
    const detail = (err as { response?: { data?: { detail?: string } } })?.response?.data?.detail
    setSignErr(e => ({ ...e, [key]: detail || 'Failed' }))
  } finally {
    setSigning(s => ({ ...s, [key]: false }))
  }
}
```

### 4c — Update the attendee row render

In the attendee list render, find where `opening_signed` and `closing_signed` badges are
shown. After each `SignBadge` that shows "Pending", add a direct-sign button:

```tsx
{/* Opening meeting */}
<SignBadge signed={att.opening_signed} label="Opening" />
{!att.opening_signed && (
  <button
    type="button"
    onClick={() => handleDirectSign(att.id, 'opening')}
    disabled={signing[`${att.id}-opening`]}
    className="rounded px-2 py-0.5 text-xs text-certiva-primary border border-certiva-primary hover:bg-certiva-primary/5 disabled:opacity-50"
  >
    {signing[`${att.id}-opening`] ? '…' : 'Mark Signed'}
  </button>
)}
{signErr[`${att.id}-opening`] && (
  <span className="text-xs text-red-500">{signErr[`${att.id}-opening`]}</span>
)}

{/* Closing meeting */}
<SignBadge signed={att.closing_signed} label="Closing" />
{!att.closing_signed && (
  <button
    type="button"
    onClick={() => handleDirectSign(att.id, 'closing')}
    disabled={signing[`${att.id}-closing`]}
    className="rounded px-2 py-0.5 text-xs text-certiva-primary border border-certiva-primary hover:bg-certiva-primary/5 disabled:opacity-50"
  >
    {signing[`${att.id}-closing`] ? '…' : 'Mark Signed'}
  </button>
)}
{signErr[`${att.id}-closing`] && (
  <span className="text-xs text-red-500">{signErr[`${att.id}-closing`]}</span>
)}
```

Also: keep the existing "Resend invite" button (it silently fails since email is off but
doesn't break anything) OR remove it — your call. If removing, be careful not to leave
dead state variables.

---

## Change 5 — Auditor portal: report LA signing

Find the page / component in the auditor portal that lets the lead auditor sign their
own report. It currently calls `POST /audit-reports/{rid}/sign/la/request-otp`. Search for
`sign/la/request-otp` across `frontend/src/app/(auditor)/` to locate the component.

Replace its OTP signing flow with a direct sign call to
`POST /audit-sets/{id}/audit-reports/{rid}/sign/la/direct`:

- Remove OTP input field and "Send code" / "Verify" buttons
- Add a single "Sign Report" button that calls the direct endpoint
- On success, mark the report as `pending_review` in the local state

The same pattern as the `handleApprove` in Change 3 — just a different endpoint and
status transition (`pending_la` → `pending_review`).

If you cannot locate the auditor portal sign component, search for `request-otp` in
`frontend/src/app/(auditor)/` and follow the import chain.

---

## Verification Checklist

- [ ] CB admin (or committee reviewer) sees "Approve Report" button on a `pending_review`
  report — clicks → status changes to "approved" with reviewer_signed_at ✅
- [ ] Lead auditor on the auditor portal sees "Sign Report" button — clicks → status
  changes from `pending_la` to `pending_review` ✅
- [ ] CB planner adds a meeting attendee → "Mark Signed" buttons appear next to Opening
  and Closing badges → clicking marks the correct field with a timestamp ✅
- [ ] Marking opening signed hides the Opening "Mark Signed" button (idempotent) ✅
- [ ] Marking closing when opening is not yet signed works independently ✅
- [ ] Trying to approve a report that is already approved → 400 error (backend) ✅
- [ ] No OTP emails are required for any of the above flows ✅
