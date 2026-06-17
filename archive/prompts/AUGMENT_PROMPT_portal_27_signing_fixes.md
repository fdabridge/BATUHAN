# Prompt 27 — Signing Flow Fixes + Stage Gating

## Context

Test run on the live Railway deployment revealed five problems:

1. **`SignatureConfirmDialog` always shows "no signature"** — even when the user has a saved signature. Root cause: the component checks `r.data?.has_signature` but the backend `GET /me/signature` never returns that field.

2. **"Set up my signature" link goes to the wrong URL for the client portal** — it hard-codes `/settings/signature` (CB route). Client users who click it land on the CB portal, get redirected away, and never return to the viewer.

3. **`PendingSignaturesWidget` inline "Sign" button bypasses the viewer** — CB planners can sign quotations/agreements directly from the dashboard without opening the document. This means the visual drawn signature is never placed. Quotation and agreement signing MUST go through the viewer.

4. **Stage-gating gaps on the CB audit set page** — at `in_planning` stage, the page shows Certification Committee, Meeting Attendees (FR.225), and FR.222 Audit Programme even though these sections are only relevant after the agreement is signed and the audit is scheduled.

5. **FR.218 internal approvals "Sign" button does not show the user's drawn signature** — it skips straight to OTP. Add a visual signature preview step before OTP is sent.

---

## Fix 1 — `backend/auth/user_signature_router.py`

In the `GET /me/signature` handler, add `has_signature: True` to the return dict so the frontend check works cleanly:

```python
# BEFORE:
return {
    "image_data": sig.image_data,
    "source":     sig.source,
    "created_at": sig.created_at.isoformat(),
    "updated_at": sig.updated_at.isoformat(),
}

# AFTER:
return {
    "has_signature": True,
    "image_data":    sig.image_data,
    "source":        sig.source,
    "created_at":    sig.created_at.isoformat(),
    "updated_at":    sig.updated_at.isoformat(),
}
```

---

## Fix 2 — `frontend/src/components/SignatureConfirmDialog.tsx`

### 2a — Fix the `has_signature` check (line ~58)

```typescript
// BEFORE:
if (r.data?.has_signature && r.data?.image_data) {

// AFTER:
if (r.data?.image_data) {
```

### 2b — Fix the "Set up my signature" link to be portal-aware

Add a helper function before the component:

```typescript
function getSignatureSettingsUrl(): string {
  if (typeof window === 'undefined') return '/settings/signature'
  const p = window.location.pathname
  if (p.startsWith('/client/'))  return '/client/signature'
  if (p.startsWith('/auditor/')) return '/auditor/signature'
  return '/settings/signature'
}
```

Change the hard-coded link in the `no_signature` stage:

```tsx
// BEFORE:
<a href="/settings/signature" target="_blank" rel="noreferrer" ...>

// AFTER:
<a href={getSignatureSettingsUrl()} target="_blank" rel="noreferrer" ...>
```

---

## Fix 3 — `frontend/src/components/ui/PendingSignaturesWidget.tsx`

### 3a — Add `document_id` to the interface

```typescript
interface PendingSig {
  id:             string
  audit_set_id:   string
  plan_number:    number | null
  company_name:   string
  document_label: string
  document_type:  string
  document_id:    string   // ← ADD — comes from _sig_to_dict's "document_id" field
}
```

### 3b — Replace "Sign" button with "Open to Sign" for quotation/agreement

For documents that have viewer support (`document_type === 'quotation'` or `'agreement'`), replace the inline "Sign" button with a link to the viewer. Keep the inline OTP "Sign" button only for FR218 and FR222.

```tsx
{signingId !== sig.id && (
  sig.document_type === 'quotation' || sig.document_type === 'agreement' ? (
    <a
      href={`/viewer/shared_doc/${sig.document_id}`}
      className="rounded-lg bg-[#1A4731] px-3 py-1.5 text-xs font-medium text-white hover:bg-[#143828]"
    >
      Open to Sign
    </a>
  ) : (
    <button
      type="button"
      onClick={() => requestOtp(sig)}
      disabled={busy}
      className="rounded-lg bg-[#1A4731] px-3 py-1.5 text-xs font-medium text-white disabled:opacity-40"
    >
      Sign
    </button>
  )
)}
```

Also: remove the inline OTP input/verify block for rows where `sig.document_type` is `'quotation'` or `'agreement'` — those are never shown since the button is replaced. The simplest implementation is to only render the OTP block when `sig.document_type !== 'quotation' && sig.document_type !== 'agreement'`.

---

## Fix 4 — Stage gating: `CommitteeSection` and `MeetingAttendeesSection`

### `frontend/src/components/ui/CommitteeSection.tsx`

```typescript
// BEFORE (line ~65):
const showSection = workflowStatus && workflowStatus !== 'pending_review'

// AFTER:
const COMMITTEE_STAGES = ['agreement_signed', 'audit_scheduled', 'audit_in_progress', 'under_review', 'certified']
const showSection = workflowStatus != null && COMMITTEE_STAGES.includes(workflowStatus)
```

### `frontend/src/components/ui/MeetingAttendeesSection.tsx`

Same change:

```typescript
// BEFORE (line ~72):
const showSection = workflowStatus && workflowStatus !== 'pending_review'

// AFTER:
const MEETING_STAGES = ['agreement_signed', 'audit_scheduled', 'audit_in_progress', 'under_review', 'certified']
const showSection = workflowStatus != null && MEETING_STAGES.includes(workflowStatus)
```

---

## Fix 5 — `frontend/src/components/ui/InternalApprovalsSection.tsx`

### 5a — Show FR.222 only at `audit_scheduled` or later

FR.222 (Audit Programme) is only relevant once an audit is scheduled. Add a gate inside the component:

```typescript
const FR222_STAGES = ['audit_scheduled', 'audit_in_progress', 'under_review', 'certified']
const showFR222 = workflowStatus != null && FR222_STAGES.includes(workflowStatus)
```

Wrap the entire FR.222 card JSX with `{showFR222 && ( ... )}`.

### 5b — Show visual signature preview before OTP for FR.218 / FR.222 signing

Add state variables to the component:

```typescript
const [sigPreviewImage, setSigPreviewImage] = useState<string | null>(null)
const [sigPreviewSlot,  setSigPreviewSlot]  = useState<SigSlot | null>(null)
const [sigPreviewBusy,  setSigPreviewBusy]  = useState(false)
```

Replace the existing `requestOtp` call in `SignerRow`'s "Sign" button with a new `handleSignClick` wrapper. Add this function to the component body (before the return):

```typescript
async function handleSignClick(slot: SigSlot) {
  setSigPreviewBusy(true)
  setSigPreviewSlot(null)
  setSigPreviewImage(null)
  try {
    const r = await api.get('/me/signature')
    if (r.data?.image_data) {
      setSigPreviewImage(r.data.image_data)
      setSigPreviewSlot(slot)
    } else {
      window.open('/settings/signature', '_blank')
    }
  } catch {
    // silently fall through — user will see no preview
    setSigPreviewSlot(slot)
  } finally {
    setSigPreviewBusy(false)
  }
}

function handleConfirmSign() {
  const slot = sigPreviewSlot
  setSigPreviewSlot(null)
  setSigPreviewImage(null)
  if (slot) requestOtp(slot)
}
```

Pass `handleSignClick` and `sigPreviewBusy` down to `SignerRow` via `rowProps`:

```typescript
const rowProps = {
  signingId, otpSent, otpValue, error, busy: busy || sigPreviewBusy,
  onSign:      handleSignClick,   // ← was requestOtp
  onVerify:    verifyOtp,
  onOtpChange: setOtpValue,
  onCancel:    () => { setSigningId(null); setOtpSent(false); setOtpValue('') },
  onResend:    requestOtp,
}
```

Add a signature preview modal/overlay at the bottom of the component's return JSX (before the closing `</div>`). Show it when `sigPreviewSlot !== null`:

```tsx
{sigPreviewSlot && (
  <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/50 p-4">
    <div className="w-full max-w-sm overflow-hidden rounded-xl bg-white shadow-2xl">
      <div className="flex items-center justify-between border-b px-5 py-4">
        <p className="text-sm font-semibold text-gray-900">
          Confirm signature — {ROLE_LABELS[sigPreviewSlot.signer_role_label] ?? sigPreviewSlot.signer_role_label}
        </p>
        <button
          type="button"
          onClick={() => { setSigPreviewSlot(null); setSigPreviewImage(null) }}
          className="text-gray-400 hover:text-gray-600"
        >✕</button>
      </div>
      <div className="px-5 py-4 space-y-4">
        <p className="text-sm text-gray-600">
          Your saved signature will be recorded. Click <strong>Send verification code</strong> to continue.
        </p>
        {sigPreviewImage ? (
          <div
            className="flex items-center justify-center rounded-lg p-4"
            style={{
              background: 'repeating-conic-gradient(#e5e7eb 0% 25%, #fff 0% 50%) 0 0 / 12px 12px',
              minHeight: 80,
            }}
          >
            <img src={sigPreviewImage} alt="Your signature" className="max-h-16 max-w-full object-contain" />
          </div>
        ) : (
          <p className="text-xs text-gray-400 italic">No signature image on file.</p>
        )}
        <button
          type="button"
          onClick={handleConfirmSign}
          className="w-full rounded-lg bg-[#1A4731] py-2.5 text-sm font-medium text-white hover:bg-[#1A4731]/90"
        >
          Send verification code
        </button>
        <button
          type="button"
          onClick={() => { setSigPreviewSlot(null); setSigPreviewImage(null) }}
          className="w-full text-sm text-gray-500 hover:text-gray-700"
        >
          Cancel
        </button>
      </div>
    </div>
  </div>
)}
```

---

## Verification Checklist

After implementing, confirm:

- [ ] CB planner opens a quotation in the viewer → clicks CB_PLANNER box → `SignatureConfirmDialog` shows signature preview (not "no signature") → OTP sent → signed ✅
- [ ] Client opens a document in the client portal viewer → clicks CLIENT box → `SignatureConfirmDialog` shows signature preview → OTP sent → signed ✅
- [ ] Client portal "no signature" dialog → "Set up my signature" opens `/client/signature` (not `/settings/signature`) ✅
- [ ] `PendingSignaturesWidget` shows "Open to Sign" (not "Sign") for quotation rows → clicking opens `/viewer/shared_doc/{id}` ✅
- [ ] CB audit set at `in_planning`: CommitteeSection and MeetingAttendeesSection are NOT visible ✅
- [ ] CB audit set at `agreement_signed`: CommitteeSection and MeetingAttendeesSection ARE visible ✅
- [ ] FR.222 Audit Programme section is NOT visible until `audit_scheduled` ✅
- [ ] FR.218 "Sign" button shows signature preview modal → "Send verification code" → OTP → signed ✅
