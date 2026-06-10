# AUGMENT PROMPT — Portal 13: Internal Document Approvals (FR.218 + FR.222)

## Context
Certiva — FastAPI backend + Next.js 14 App Router frontend.
**DO NOT BREAK THE EXISTING PORTAL. All changes are additive.**

Role system: admin, planner, officer, executive, auditor, client.
`AuditDocumentSignature` table was added in Prompt 12 — this prompt extends it.

---

## What this builds

Two internal CB documents require multi-party signatures that are never exposed to the client:

**FR.218 — Application Review Form**
- Triggered automatically when a planner approves an application (pending_review → in_planning)
- Signers in order:
  1. `cb_planner` — the planner who approved the application (auto-assigned)
  2. `cb_reviewer` — only when standards include FSMS (ISO 22000) or ISMS (ISO 27001); unassigned until Prompt 14 committee appointment
  3. `cb_cert_manager` — any admin/executive user (self-assigns on sign)

**FR.222 — Audit Programme**
- Triggered manually by a planner from the client detail page
- Signers:
  1. `cb_planner` — the planner who triggers it (auto-assigned)
  2. `cb_cert_manager` — any admin/executive user (self-assigns on sign)

Both use the existing `AuditDocumentSignature` table with `document_id = None`
(internal documents are not uploaded files).

---

## Backend

### 1. `backend/audit_set/workflow_router.py` — auto-create FR.218 slots on approval

In `update_workflow_status`, after `db.commit()` and before the client email block, add:

```python
# When application is approved → auto-create FR.218 signature slots
if from_status == "pending_review" and to_status == "in_planning":
    from audit_set.db_models import AuditDocumentSignature
    # Slot 1: Planning Officer (the approving planner)
    db.add(AuditDocumentSignature(
        audit_set_id=audit_set_id,
        document_id=None,
        document_type="FR218",
        signer_role_label="cb_planner",
        signer_user_id=current_user.id,
        signer_name=current_user.full_name,
        signer_email=current_user.email,
        required=True,
        order_index=0,
    ))
    # Slot 2: Reviewer — only for FSMS / ISMS (unassigned until committee appointment)
    fsms_isms = {"FSMS", "ISMS", "ISO 22000", "ISO 27001", "FSSC 22000"}
    standards = set(audit_set.standards or [])
    if standards & fsms_isms:
        db.add(AuditDocumentSignature(
            audit_set_id=audit_set_id,
            document_id=None,
            document_type="FR218",
            signer_role_label="cb_reviewer",
            signer_user_id=None,          # assigned in Prompt 14 via committee appointment
            signer_name=None,
            signer_email=None,
            required=True,
            order_index=1,
        ))
    # Slot 3: Certification Manager (unassigned — any admin/executive self-assigns on sign)
    db.add(AuditDocumentSignature(
        audit_set_id=audit_set_id,
        document_id=None,
        document_type="FR218",
        signer_role_label="cb_cert_manager",
        signer_user_id=None,
        signer_name=None,
        signer_email=None,
        required=True,
        order_index=2,
    ))
    db.commit()
```

Add `AuditDocumentSignature` to the import at the top of `workflow_router.py`:
```python
from audit_set.db_models import AuditSet, AuditSetStatusEvent, AuditDocumentSignature, get_db as get_audit_db
```

---

### 2. `backend/audit_set/signatures_router.py` — three additions

#### A. Update `get_my_pending_signatures` to include unassigned eligible slots

Replace the existing query block with:

```python
# Slots explicitly assigned to me
assigned = (
    db.query(AuditDocumentSignature)
    .filter_by(signer_user_id=current_user.id)
    .filter(AuditDocumentSignature.signed_at.is_(None))
    .all()
)

# Unassigned slots this user is eligible to claim
eligible_labels = []
if current_user.role in ("admin", "executive"):
    eligible_labels.append("cb_cert_manager")
# cb_reviewer eligibility (EA-code check added in Prompt 14)
if current_user.role in ("admin", "executive", "auditor"):
    eligible_labels.append("cb_reviewer")

unassigned = []
if eligible_labels:
    unassigned = (
        db.query(AuditDocumentSignature)
        .filter(AuditDocumentSignature.signer_user_id.is_(None))
        .filter(AuditDocumentSignature.signer_role_label.in_(eligible_labels))
        .filter(AuditDocumentSignature.signed_at.is_(None))
        .all()
    )

sigs = assigned + unassigned
```

Keep the rest of the function (enrichment loop) the same.

#### B. Update `request_cb_signature_otp` to self-assign unassigned slots

After the "not found" check and before the "already signed" check, add:

```python
# Self-assign if the slot is unassigned and the caller is eligible
if sig.signer_user_id is None:
    eligible = False
    if sig.signer_role_label == "cb_cert_manager" and current_user.role in ("admin", "executive"):
        eligible = True
    if sig.signer_role_label == "cb_reviewer" and current_user.role in ("admin", "executive", "auditor"):
        eligible = True
    if not eligible:
        raise HTTPException(403, "You are not eligible to sign this slot")
    sig.signer_user_id = current_user.id
    sig.signer_name    = current_user.full_name
    sig.signer_email   = current_user.email
    db.commit()
elif sig.signer_user_id != current_user.id:
    raise HTTPException(403, "This signature is not assigned to you")
```

Remove the existing `if sig.signer_user_id != current_user.id: raise 403` check from the original
function (it is replaced by the block above).

#### C. New endpoint: `GET /audit-sets/{id}/internal-signatures`

Add this endpoint to `signatures_router.py`:

```python
@router.get("/{audit_set_id}/internal-signatures")
def get_internal_signatures(
    audit_set_id: str,
    db: Session = Depends(get_db),
    current_user: PlatformUser = Depends(get_current_user),
):
    """
    Returns all internal document signature slots (FR218, FR222) for this audit set.
    CB only. Powers the InternalApprovalsSection on the client detail page.
    """
    if current_user.role not in CB_ROLES:
        raise HTTPException(403, "Not authorized")

    sigs = (
        db.query(AuditDocumentSignature)
        .filter_by(audit_set_id=audit_set_id)
        .filter(AuditDocumentSignature.document_type.in_(["FR218", "FR222"]))
        .order_by(AuditDocumentSignature.document_type, AuditDocumentSignature.order_index)
        .all()
    )

    # Determine which unassigned slots the caller is eligible to sign
    eligible_labels = set()
    if current_user.role in ("admin", "executive"):
        eligible_labels.add("cb_cert_manager")
    if current_user.role in ("admin", "executive", "auditor"):
        eligible_labels.add("cb_reviewer")

    results = []
    for s in sigs:
        results.append({
            "id":               s.id,
            "document_type":    s.document_type,
            "signer_role_label": s.signer_role_label,
            "signer_name":      s.signer_name,
            "signer_user_id":   s.signer_user_id,
            "is_signed":        s.signed_at is not None,
            "signed_at":        s.signed_at.isoformat() if s.signed_at else None,
            "is_mine":          s.signer_user_id == current_user.id,
            "can_claim":        s.signer_user_id is None and s.signer_role_label in eligible_labels and s.signed_at is None,
            "pending_appointment": s.signer_role_label == "cb_reviewer" and s.signer_user_id is None,
            "required":         s.required,
            "order_index":      s.order_index,
        })
    return results
```

#### D. New endpoint: `POST /audit-sets/{id}/signatures/create-fr222`

Add this endpoint to `signatures_router.py`:

```python
@router.post("/{audit_set_id}/signatures/create-fr222")
def create_fr222_signatures(
    audit_set_id: str,
    db: Session = Depends(get_db),
    current_user: PlatformUser = Depends(get_current_user),
):
    """
    Planner triggers creation of FR.222 Audit Programme signature slots.
    Idempotent — if slots already exist, returns them without creating duplicates.
    """
    if current_user.role not in {"admin", "planner"}:
        raise HTTPException(403, "Only planners can create the audit programme signature")

    existing = (
        db.query(AuditDocumentSignature)
        .filter_by(audit_set_id=audit_set_id, document_type="FR222")
        .first()
    )
    if existing:
        # Already created — return current state via get_internal_signatures logic
        return {"created": False, "message": "FR.222 signature slots already exist"}

    # Slot 1: Planning Officer
    db.add(AuditDocumentSignature(
        audit_set_id=audit_set_id,
        document_id=None,
        document_type="FR222",
        signer_role_label="cb_planner",
        signer_user_id=current_user.id,
        signer_name=current_user.full_name,
        signer_email=current_user.email,
        required=True,
        order_index=0,
    ))
    # Slot 2: Certification Manager (unassigned)
    db.add(AuditDocumentSignature(
        audit_set_id=audit_set_id,
        document_id=None,
        document_type="FR222",
        signer_role_label="cb_cert_manager",
        signer_user_id=None,
        signer_name=None,
        signer_email=None,
        required=True,
        order_index=1,
    ))
    db.commit()
    return {"created": True}
```

Also update `verify_cb_signature` in `signatures_router.py` — the existing `sig.signer_user_id != current_user.id` check needs the same self-assignment logic. Add the same block from section B above to `verify_cb_signature` as well (before the "Already signed" check):

```python
# Self-assign if unassigned
if sig.signer_user_id is None:
    eligible = False
    if sig.signer_role_label == "cb_cert_manager" and current_user.role in ("admin", "executive"):
        eligible = True
    if sig.signer_role_label == "cb_reviewer" and current_user.role in ("admin", "executive", "auditor"):
        eligible = True
    if not eligible:
        raise HTTPException(403, "You are not eligible to sign this slot")
    sig.signer_user_id = current_user.id
    sig.signer_name    = current_user.full_name
    sig.signer_email   = current_user.email
elif sig.signer_user_id != current_user.id:
    raise HTTPException(403, "This signature is not assigned to you")
```

Remove the original `if sig.signer_user_id != current_user.id: raise 403` guard from `verify_cb_signature`.

**Note:** For internal document signatures (FR218, FR222), `sig.document_id` is `None`, so the
"release document to client" block in `verify_cb_signature` will be skipped (it's already inside
`if sig.document_id:` check). No changes needed to that block.

---

## Frontend

### 1. New file `frontend/src/components/ui/InternalApprovalsSection.tsx`

```tsx
'use client'

import { useEffect, useState } from 'react'
import api from '@/lib/api'

interface SigSlot {
  id: string
  document_type: 'FR218' | 'FR222'
  signer_role_label: string
  signer_name: string | null
  is_signed: boolean
  signed_at: string | null
  is_mine: boolean
  can_claim: boolean
  pending_appointment: boolean
  required: boolean
  order_index: number
}

const ROLE_LABELS: Record<string, string> = {
  cb_planner:      'Planning Officer',
  cb_cert_manager: 'Certification Manager',
  cb_reviewer:     'Independent Reviewer',
}

const DOC_LABELS: Record<string, string> = {
  FR218: 'FR.218 — Application Review',
  FR222: 'FR.222 — Audit Programme',
}

function fmtDate(iso: string | null) {
  if (!iso) return ''
  return new Date(iso).toLocaleDateString('en-GB', { day: 'numeric', month: 'short', year: 'numeric' })
}

export function InternalApprovalsSection({
  auditSetId,
  workflowStatus,
}: {
  auditSetId: string
  workflowStatus: string | null
}) {
  const [slots, setSlots]         = useState<SigSlot[]>([])
  const [loading, setLoading]     = useState(true)
  const [signingId, setSigningId] = useState<string | null>(null)
  const [otpSent, setOtpSent]     = useState(false)
  const [otpValue, setOtpValue]   = useState('')
  const [error, setError]         = useState('')
  const [busy, setBusy]           = useState(false)

  async function load() {
    try {
      const r = await api.get<SigSlot[]>(`/audit-sets/${auditSetId}/internal-signatures`)
      setSlots(r.data)
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => { load() }, [auditSetId])

  // Only show this section after application has been approved
  const showSection = workflowStatus && workflowStatus !== 'pending_review'
  if (!showSection) return null

  async function createFR222() {
    setBusy(true)
    try {
      await api.post(`/audit-sets/${auditSetId}/signatures/create-fr222`)
      await load()
    } catch (e: unknown) {
      const detail = (e as { response?: { data?: { detail?: string } } })?.response?.data?.detail
      alert(detail || 'Failed to create FR.222 signatures')
    } finally {
      setBusy(false)
    }
  }

  async function requestOtp(slot: SigSlot) {
    setSigningId(slot.id)
    setOtpSent(false)
    setError('')
    setBusy(true)
    try {
      await api.post(`/audit-sets/${auditSetId}/signatures/${slot.id}/request-otp`)
      setOtpSent(true)
    } catch (e: unknown) {
      const detail = (e as { response?: { data?: { detail?: string } } })?.response?.data?.detail
      setError(detail || 'Failed to send code')
    } finally {
      setBusy(false)
    }
  }

  async function verifyOtp(slot: SigSlot) {
    setBusy(true)
    setError('')
    try {
      await api.post(`/audit-sets/${auditSetId}/signatures/${slot.id}/verify?otp=${otpValue}`)
      setSigningId(null)
      setOtpValue('')
      setOtpSent(false)
      await load()
    } catch (e: unknown) {
      const detail = (e as { response?: { data?: { detail?: string } } })?.response?.data?.detail
      setError(detail || 'Invalid code')
    } finally {
      setBusy(false)
    }
  }

  // Group slots by document type
  const grouped = slots.reduce<Record<string, SigSlot[]>>((acc, s) => {
    acc[s.document_type] = acc[s.document_type] || []
    acc[s.document_type].push(s)
    return acc
  }, {})

  const hasFR218 = (grouped['FR218'] || []).length > 0
  const hasFR222 = (grouped['FR222'] || []).length > 0

  return (
    <div className="mt-8">
      <h2 className="mb-3 text-sm font-semibold uppercase tracking-wide text-gray-700">
        Internal Approvals
      </h2>

      <div className="space-y-4">
        {/* FR.218 — always shown after approval */}
        <div className="rounded-xl border bg-white p-4">
          <div className="mb-3 flex items-center justify-between">
            <p className="text-sm font-medium text-gray-800">{DOC_LABELS['FR218']}</p>
            {hasFR218 && (grouped['FR218'] || []).every(s => s.is_signed) && (
              <span className="rounded-full bg-green-100 px-2 py-0.5 text-xs font-semibold text-green-700">
                Fully Signed ✓
              </span>
            )}
          </div>

          {loading ? (
            <p className="text-xs text-gray-400">Loading…</p>
          ) : !hasFR218 ? (
            <p className="text-xs text-gray-400">Signature slots pending creation…</p>
          ) : (
            <div className="space-y-2">
              {(grouped['FR218'] || []).map(slot => (
                <SignerRow
                  key={slot.id}
                  slot={slot}
                  signingId={signingId}
                  otpSent={otpSent}
                  otpValue={otpValue}
                  error={error}
                  busy={busy}
                  onSign={requestOtp}
                  onVerify={verifyOtp}
                  onOtpChange={setOtpValue}
                  onCancel={() => { setSigningId(null); setOtpSent(false); setOtpValue('') }}
                  onResend={requestOtp}
                />
              ))}
            </div>
          )}
        </div>

        {/* FR.222 — shown always, with create button if not yet initiated */}
        <div className="rounded-xl border bg-white p-4">
          <div className="mb-3 flex items-center justify-between">
            <p className="text-sm font-medium text-gray-800">{DOC_LABELS['FR222']}</p>
            {hasFR222 && (grouped['FR222'] || []).every(s => s.is_signed) && (
              <span className="rounded-full bg-green-100 px-2 py-0.5 text-xs font-semibold text-green-700">
                Fully Signed ✓
              </span>
            )}
          </div>

          {loading ? (
            <p className="text-xs text-gray-400">Loading…</p>
          ) : !hasFR222 ? (
            <div className="flex items-center gap-3">
              <p className="text-xs text-gray-400">Not yet initiated.</p>
              <button
                type="button"
                onClick={createFR222}
                disabled={busy}
                className="rounded-lg border border-[#1A4731] px-3 py-1.5 text-xs font-medium text-[#1A4731] hover:bg-green-50 disabled:opacity-40"
              >
                Initiate Audit Programme Signing
              </button>
            </div>
          ) : (
            <div className="space-y-2">
              {(grouped['FR222'] || []).map(slot => (
                <SignerRow
                  key={slot.id}
                  slot={slot}
                  signingId={signingId}
                  otpSent={otpSent}
                  otpValue={otpValue}
                  error={error}
                  busy={busy}
                  onSign={requestOtp}
                  onVerify={verifyOtp}
                  onOtpChange={setOtpValue}
                  onCancel={() => { setSigningId(null); setOtpSent(false); setOtpValue('') }}
                  onResend={requestOtp}
                />
              ))}
            </div>
          )}
        </div>
      </div>
    </div>
  )
}

// ── Signer row sub-component ─────────────────────────────────────────────────

function SignerRow({
  slot, signingId, otpSent, otpValue, error, busy,
  onSign, onVerify, onOtpChange, onCancel, onResend,
}: {
  slot: SigSlot
  signingId: string | null
  otpSent: boolean
  otpValue: string
  error: string
  busy: boolean
  onSign: (s: SigSlot) => void
  onVerify: (s: SigSlot) => void
  onOtpChange: (v: string) => void
  onCancel: () => void
  onResend: (s: SigSlot) => void
}) {
  const isActive = signingId === slot.id

  return (
    <div className="rounded-lg border border-gray-100 bg-gray-50 p-3">
      <div className="flex items-center justify-between">
        <div>
          <p className="text-xs font-medium text-gray-700">
            {ROLE_LABELS[slot.signer_role_label] ?? slot.signer_role_label}
          </p>
          <p className="mt-0.5 text-xs text-gray-400">
            {slot.is_signed
              ? `✓ Signed by ${slot.signer_name} on ${fmtDate(slot.signed_at)}`
              : slot.pending_appointment
              ? 'Pending committee appointment'
              : slot.signer_name
              ? `Assigned: ${slot.signer_name}`
              : 'Unassigned — eligible users can sign'}
          </p>
        </div>
        <div className="flex items-center gap-2">
          {slot.is_signed ? (
            <span className="rounded-full bg-green-100 px-2 py-0.5 text-xs font-semibold text-green-700">✓</span>
          ) : slot.pending_appointment ? (
            <span className="rounded-full bg-gray-200 px-2 py-0.5 text-xs text-gray-500">Pending</span>
          ) : (slot.is_mine || slot.can_claim) && !isActive ? (
            <button
              type="button"
              onClick={() => onSign(slot)}
              disabled={busy}
              className="rounded bg-[#1A4731] px-2.5 py-1 text-xs text-white disabled:opacity-40"
            >
              Sign
            </button>
          ) : !slot.is_mine && !slot.can_claim && !slot.is_signed ? (
            <span className="rounded-full bg-amber-100 px-2 py-0.5 text-xs text-amber-700">Awaiting</span>
          ) : null}
        </div>
      </div>

      {/* Inline OTP form */}
      {isActive && (
        <div className="mt-2 rounded border bg-white p-2">
          {!otpSent ? (
            <p className="text-xs text-gray-500">{busy ? 'Sending code…' : 'Sending 6-digit code to your email…'}</p>
          ) : (
            <div className="flex items-center gap-2">
              <input
                className="w-28 rounded border px-2 py-1 text-center font-mono text-sm tracking-widest focus:outline-none focus:ring-2 focus:ring-[#1A4731]/30"
                placeholder="000000"
                maxLength={6}
                value={otpValue}
                onChange={e => onOtpChange(e.target.value.replace(/\D/g, ''))}
              />
              <button
                type="button"
                onClick={() => onVerify(slot)}
                disabled={otpValue.length !== 6 || busy}
                className="rounded bg-[#1A4731] px-2.5 py-1 text-xs text-white disabled:opacity-40"
              >
                {busy ? '…' : 'Confirm'}
              </button>
              <button type="button" onClick={onCancel} className="text-xs text-gray-400">Cancel</button>
              <button type="button" onClick={() => onResend(slot)} className="text-xs text-gray-400 underline">Resend</button>
            </div>
          )}
          {error && <p className="mt-1 text-xs text-red-500">{error}</p>}
        </div>
      )}
    </div>
  )
}
```

### 2. Wire `InternalApprovalsSection` into `frontend/src/app/(app)/clients/[id]/page.tsx`

Add import:
```tsx
import { InternalApprovalsSection } from '@/components/ui/InternalApprovalsSection'
```

In the page return, add it after `<SharedDocumentsSection>`:
```tsx
<InternalApprovalsSection
  auditSetId={id}
  workflowStatus={data.workflow_status ?? null}
/>
```

The section renders nothing when `workflow_status` is `pending_review` or `null`, so it won't show on internal plans created outside the portal.

---

## Verification

1. `python3 -m py_compile backend/audit_set/workflow_router.py backend/audit_set/signatures_router.py`
2. `cd frontend && npx tsc --noEmit`
3. Manual test — FR.218 flow:
   a. Open a plan in `pending_review` → approve it (WorkflowStatusBar "Mark as In Planning")
   b. Refresh `/clients/{id}` → "Internal Approvals" section appears
   c. FR.218 shows three rows: Planning Officer (assigned, can sign), Certification Manager (unassigned, "eligible users can sign")
   d. If standards include FSMS/ISMS: third row shows "Pending committee appointment"
   e. Log in as planner → Sign Planning Officer slot via OTP → row shows ✓
   f. Log in as admin/executive → Sign Certification Manager slot → self-assigns + signs via OTP
4. Manual test — FR.222 flow:
   a. On any plan in `in_planning` or beyond → click "Initiate Audit Programme Signing"
   b. Two rows appear: Planning Officer + Certification Manager
   c. Sign both via OTP as appropriate users
5. Confirm `GET /audit-sets/my-pending-signatures` now includes unassigned cert_manager slots for admin/executive users
6. Commit and push to main

## Constraint
DO NOT modify any other endpoint, component, or page beyond what is listed.

New file: `frontend/src/components/ui/InternalApprovalsSection.tsx`

Modified files:
- `backend/audit_set/workflow_router.py` — auto-create FR.218 slots on approval
- `backend/audit_set/signatures_router.py` — unassigned slot support + FR.222 endpoint + internal-signatures endpoint
- `frontend/src/app/(app)/clients/[id]/page.tsx` — wire InternalApprovalsSection
