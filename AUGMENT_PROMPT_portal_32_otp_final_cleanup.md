# Prompt 32 — OTP Final Cleanup (NC Forms, Declarations, Assessments)

## Context

After Prompts 28 and 31, these OTP-based signing flows remain. All are broken because
email is permanently disabled. This prompt eliminates the last four.

| OTP flow | Who signs | Portal | Backend route |
|----------|-----------|--------|---------------|
| NC form — LA signs | Lead Auditor | Auditor | `POST /audit-sets/{id}/nc-forms/{nid}/sign/la/request-otp` |
| NC form — Client signs | Client | Client | `POST /client/my-audit-set/nc-forms/{nid}/sign/request-otp` |
| Declaration — Auditor signs | Auditor | Auditor | `POST /audit-sets/{id}/declarations/{did}/sign/request-otp` |
| Assessment — Client signs | Client | Client | `POST /client/my-audit-set/assessments/{aid}/sign/request-otp` |

All four get direct-sign equivalents — no OTP, no email, no code entry.

---

## Summary of changes

| File | What changes |
|------|-------------|
| `backend/audit_set/nc_router.py` | Add 2 direct-sign endpoints (LA + client) |
| `backend/audit_set/declaration_router.py` | Add 1 direct-sign endpoint |
| `backend/audit_set/assessment_router.py` | Add 1 direct-sign endpoint |
| `frontend/src/app/(auditor)/auditor/audit/[id]/page.tsx` | Replace OTP in `AuditorNCFormsView` and `AuditorDeclarationsView` |
| `frontend/src/components/ui/NCFormClientSection.tsx` | Replace OTP |
| `frontend/src/app/(client)/client/assessments/page.tsx` | Replace OTP in `AssessmentCard` / `CardShell` |

---

## Change 1 — `backend/audit_set/nc_router.py`

### 1a — Lead Auditor direct-sign

```python
@router.post("/audit-sets/{audit_set_id}/nc-forms/{nid}/sign/la/direct")
def la_sign_direct(
    audit_set_id: str,
    nid: str,
    db:      Session = Depends(get_db),
    current_user: PlatformUser = Depends(get_current_user),
):
    # Reuse the existing auth helper that verifies the user is the stage lead auditor
    nc = db.query(AuditSetNCForm).filter_by(id=nid, audit_set_id=audit_set_id).first()
    if not nc:
        raise HTTPException(404, "NC form not found")
    _check_la_auth(nc, current_user, db)     # raises 403 if not authorized
    if nc.la_signed_at:
        raise HTTPException(400, "Already signed by Lead Auditor")

    nc.la_signed_at = datetime.utcnow()
    nc.status       = "pending_client"
    db.commit()
    db.refresh(nc)
    return _nc_dict(nc)
```

### 1b — Client direct-sign

```python
@router.post("/client/my-audit-set/nc-forms/{nid}/sign/direct")
def client_sign_direct(
    nid: str,
    db:      Session = Depends(get_db),
    current_user: PlatformUser = Depends(get_current_user),
):
    # Reuse existing client auth logic — current_user must be the audit set's client
    audit_set = _get_client_audit_set(current_user, db)     # raises 404/403 if not found
    nc = db.query(AuditSetNCForm).filter_by(
        id=nid, audit_set_id=audit_set.id
    ).first()
    if not nc:
        raise HTTPException(404, "NC form not found")
    if nc.status not in ("pending_client",):
        raise HTTPException(400, f"NC form status is '{nc.status}', expected 'pending_client'")
    if nc.client_signed_at:
        raise HTTPException(400, "Already signed by client")

    nc.client_signed_at = datetime.utcnow()
    nc.status           = "complete"
    db.commit()
    db.refresh(nc)
    return _nc_dict(nc)
```

> **Note:** If `_check_la_auth` or `_get_client_audit_set` don't exist by those exact
> names, use whatever the existing OTP endpoints use to perform the same authorization
> check — just adapt the naming. Read the existing `la_request_otp` and
> `client_nc_request_otp` functions to find the exact pattern.

---

## Change 2 — `backend/audit_set/declaration_router.py`

```python
@router.post("/audit-sets/{audit_set_id}/declarations/{did}/sign/direct")
def sign_declaration_direct(
    audit_set_id: str,
    did: str,
    db:      Session = Depends(get_db),
    current_user: PlatformUser = Depends(get_current_user),
):
    decl = db.query(AuditSetDeclaration).filter_by(
        id=did, audit_set_id=audit_set_id
    ).first()
    if not decl:
        raise HTTPException(404, "Declaration not found")
    if decl.is_signed:
        raise HTTPException(400, "Declaration already signed")

    # Authorization: the declaration's auditor_ref_id must match current_user.auditor_id
    # Admin is always allowed (same bypass as other endpoints).
    if current_user.role != "admin":
        if not current_user.auditor_id or decl.auditor_ref_id != current_user.auditor_id:
            raise HTTPException(403, "You may only sign your own declaration")

    decl.is_signed = True
    decl.signed_at = datetime.utcnow()
    db.commit()
    db.refresh(decl)
    return _decl_dict(decl)
```

> Adapt field names / helper functions to match what already exists in
> `declaration_router.py`. Read the `request_otp` endpoint to see the exact ORM
> model name and dict helper.

---

## Change 3 — `backend/audit_set/assessment_router.py`

```python
@router.post("/client/my-audit-set/assessments/{aid}/sign/direct")
def sign_assessment_direct(
    aid: str,
    db:  Session = Depends(get_db),
    current_user: PlatformUser = Depends(get_current_user),
):
    audit_set = _get_client_audit_set(current_user, db)
    assessment = db.query(AuditSetAssessment).filter_by(
        id=aid, audit_set_id=audit_set.id
    ).first()
    if not assessment:
        raise HTTPException(404, "Assessment not found")
    if assessment.is_signed:
        raise HTTPException(400, "Assessment already signed")
    if not assessment.rating:
        raise HTTPException(400, "Rating must be set before signing — save a draft first")

    assessment.is_signed = True
    assessment.signed_at = datetime.utcnow()
    db.commit()
    db.refresh(assessment)
    return _assessment_dict(assessment)
```

> Adapt helper names to match existing code. Check `request_otp` to find
> `_get_client_audit_set`, the ORM model name, and the dict helper.

---

## Change 4 — Auditor portal: NC form signing
### File: `frontend/src/app/(auditor)/auditor/audit/[id]/page.tsx`
#### In `AuditorNCFormsView`

**Remove:**
- `otpState`, `otpValues`, `messages`, `busy` state
- `requestOtp()`, `verifyOtp()` functions

**Add:**
```typescript
const [signing,   setSigning]   = useState<Record<string, boolean>>({})
const [signErrs,  setSignErrs]  = useState<Record<string, string>>({})
```

**Add `handleSign` function:**
```typescript
async function handleSign(id: string) {
  setSigning(s => ({ ...s, [id]: true }))
  setSignErrs(e => ({ ...e, [id]: '' }))
  try {
    const r = await api.post(`/audit-sets/${auditSetId}/nc-forms/${id}/sign/la/direct`)
    const updated = r.data as typeof forms[number]
    setForms(prev => prev.map(f => f.id === id ? { ...f, ...updated } : f))
  } catch (err: unknown) {
    const detail = (err as { response?: { data?: { detail?: string } } })?.response?.data?.detail
    setSignErrs(e => ({ ...e, [id]: detail || 'Signing failed' }))
  } finally {
    setSigning(s => ({ ...s, [id]: false }))
  }
}
```

**Replace the OTP block in the pending-form card:**

Remove the `state === 'idle'` / `state === 'otp_sent'` / `state === 'done'` sections.
Replace with:

```tsx
<button
  type="button"
  onClick={() => handleSign(f.id)}
  disabled={signing[f.id]}
  className="rounded-lg bg-[#1A4731] px-4 py-2 text-sm text-white disabled:opacity-40 hover:bg-[#143828]"
>
  {signing[f.id] ? 'Signing…' : 'Sign NC Form'}
</button>
{signErrs[f.id] && (
  <p className="mt-1 text-xs text-red-500">{signErrs[f.id]}</p>
)}
```

---

## Change 5 — Auditor portal: declaration signing
### File: `frontend/src/app/(auditor)/auditor/audit/[id]/page.tsx`
#### In `AuditorDeclarationsView`

**Remove:**
- `otpState`, `otpValues`, `messages`, `busy` state
- `requestOtp()`, `verifyOtp()` functions

**Add:**
```typescript
const [signing,  setSigning]  = useState<Record<string, boolean>>({})
const [signErrs, setSignErrs] = useState<Record<string, string>>({})
```

**Add `handleSign` function:**
```typescript
async function handleSign(id: string) {
  setSigning(s => ({ ...s, [id]: true }))
  setSignErrs(e => ({ ...e, [id]: '' }))
  try {
    await api.post(`/audit-sets/${auditSetId}/declarations/${id}/sign/direct`)
    setDeclarations(prev => prev.map(d =>
      d.id === id ? { ...d, is_signed: true, signed_at: new Date().toISOString() } : d
    ))
  } catch (err: unknown) {
    const detail = (err as { response?: { data?: { detail?: string } } })?.response?.data?.detail
    setSignErrs(e => ({ ...e, [id]: detail || 'Signing failed' }))
  } finally {
    setSigning(s => ({ ...s, [id]: false }))
  }
}
```

**Replace the OTP block in each pending declaration card:**

Keep the "I confirm" checkbox and `confirmed` state — that's good UX.

Replace `state === 'idle'` button (`requestOtp`) with:

```tsx
<button
  type="button"
  onClick={() => handleSign(d.id)}
  disabled={!confirmed[d.id] || signing[d.id]}
  className="rounded-lg bg-[#1A4731] px-5 py-2.5 text-sm font-medium text-white disabled:opacity-40 hover:bg-[#143828]"
>
  {signing[d.id] ? 'Signing…' : 'Sign Declaration'}
</button>
{signErrs[d.id] && (
  <p className="mt-1 text-xs text-red-500">{signErrs[d.id]}</p>
)}
```

Remove the `state === 'otp_sent'` block (OTP input + verify + resend buttons) entirely.
Remove the `state === 'done'` block and replace with the `is_signed` guard that already
exists (declarations move to `otherDeclarations` list after signing).

---

## Change 6 — Client portal: NC form signing
### File: `frontend/src/components/ui/NCFormClientSection.tsx`

**Remove:**
- `otpState`, `otpValues`, `messages`, `busy` state
- `requestOtp()`, `verifyOtp()` functions

**Add:**
```typescript
const [signing,  setSigning]  = useState<Record<string, boolean>>({})
const [signErrs, setSignErrs] = useState<Record<string, string>>({})
```

**Add `handleSign` function:**
```typescript
async function handleSign(id: string) {
  setSigning(s => ({ ...s, [id]: true }))
  setSignErrs(e => ({ ...e, [id]: '' }))
  try {
    await api.post(`/client/my-audit-set/nc-forms/${id}/sign/direct`)
    setForms(prev => prev.map(f => f.id === id
      ? { ...f, status: 'complete', client_signed_at: new Date().toISOString() }
      : f
    ))
  } catch (err: unknown) {
    const detail = (err as { response?: { data?: { detail?: string } } })?.response?.data?.detail
    setSignErrs(e => ({ ...e, [id]: detail || 'Signing failed' }))
  } finally {
    setSigning(s => ({ ...s, [id]: false }))
  }
}
```

**Update `NCFormRow`:**

Remove the `state`, `otpValue`, `onRequestOtp`, `onVerifyOtp`, `onOtpChange` props
from the interface and the component.

Replace the `state === 'idle'` / `state === 'otp_sent'` / `state === 'done'` blocks with:

```tsx
<button
  type="button"
  onClick={() => handleSign(f.id)}
  disabled={signing[f.id]}
  className="rounded-lg bg-[#1A4731] px-4 py-2 text-sm text-white disabled:opacity-40 hover:bg-[#143828]"
>
  {signing[f.id] ? 'Signing…' : 'Sign NC Form'}
</button>
{signErrs[f.id] && (
  <p className="mt-1 text-xs text-red-500">{signErrs[f.id]}</p>
)}
```

Update the `NCFormRow` call site to pass the simpler props:

```tsx
{forms.map(f => (
  <NCFormRow
    key={f.id}
    f={f}
    signing={!!signing[f.id]}
    signErr={signErrs[f.id] || ''}
    onDownload={() => download(f.id, f.file_name)}
    onSign={() => handleSign(f.id)}
  />
))}
```

---

## Change 7 — Client portal: assessment signing
### File: `frontend/src/app/(client)/client/assessments/page.tsx`

The `AssessmentCard` component currently has `step: 'form' | 'otp' | 'done'`.
Remove the `'otp'` step entirely.

**Remove:**
- `otp` state
- `requestOtp()` function — the `saveDraft` + `request-otp` two-step
- `verifyOtp()` function

**Keep:**
- `rating`, `comments`, `saveDraft` state and functions — the rating form stays
- `busy` state (rename to `signing` for clarity or keep as `busy`)

**Add `handleSign` function (replaces `requestOtp` + `verifyOtp`):**
```typescript
async function handleSign() {
  if (!rating) { setError('Please select a rating before signing'); return }
  setBusy(true)
  setError('')
  try {
    // Save draft first to ensure rating is persisted, then sign
    await api.patch(`/client/my-audit-set/assessments/${assessment.id}/draft`, {
      rating,
      comments: comments || null,
    })
    await api.post(`/client/my-audit-set/assessments/${assessment.id}/sign/direct`)
    onSigned()
  } catch (err: unknown) {
    const detail = (err as { response?: { data?: { detail?: string } } })?.response?.data?.detail
    setError(detail || 'Failed to submit')
  } finally {
    setBusy(false)
  }
}
```

**Update `CardShell` props and render:**

Remove `otp`, `setOtp`, `setStep`, `requestOtp`, `verifyOtp` from the `CardShellProps`
interface and the function signature.

In the `step === 'form'` render, find the "Submit & Sign" (or "Review & Sign") button
that currently calls `requestOtp`. Change its `onClick` to call `handleSign` directly.

Remove the entire `step === 'otp'` render block (OTP input + Confirm + Resend).

The `step` state can be simplified to `'form' | 'done'` or removed entirely since there
is no intermediate step.

---

## Verification Checklist

- [ ] Auditor portal → NC forms tab → "Sign NC Form" → single click → form moves to
  "Awaiting client" ✅
- [ ] Client portal → NC forms (documents page) → "Sign NC Form" → single click →
  form marked complete with client_signed_at ✅
- [ ] Auditor portal → declarations tab → tick checkbox → "Sign Declaration" →
  single click → declaration marked signed ✅
- [ ] Client portal → assessments page → pick rating → "Submit" → single click →
  assessment signed ✅
- [ ] Admin can also sign declarations (admin bypass) ✅
- [ ] Signing an already-signed item → 400 error shown inline ✅
- [ ] No OTP code, no email, no resend button anywhere in any of the above flows ✅
