# Prompt 28 — Auth Overhaul: Username Login + No OTP + No Email

## Context

The system currently requires email OTP verification for every document signing event.
We are removing OTP entirely and disabling all email sending for the following reasons:
- A retroactive bulk operation is being performed: ~100 clients are being onboarded with
  backdated dates. Email delivery is not available for these clients.
- Client and CB accounts will use username + password credentials. Email is stored as a
  data field only — no emails are ever sent by the system.

The only existing account is the admin (`info@ifcglobal.us`). Its login must continue
working exactly as before. All new accounts (clients, CB staff, auditors) will have a
`username` field and log in with that username instead of email.

**Critical constraint: do not break any existing signing table logic, workflow transitions,
or document status state machines. Only the OTP layer and email sending are removed.**

---

## Overview of changes

1. `backend/email_service.py` — stub all `send_*` functions to no-ops
2. `backend/auth/db_models.py` — add nullable `username` column to `platform_users`
3. `backend/auth/service.py` — update `authenticate()` to try username first, then email; add `get_user_by_username()`; accept `username` in `create_user()`
4. `backend/auth/schemas.py` — add `username` to `UserCreateSchema`, `UserResponse`, `UserUpdateSchema`
5. `backend/api/routes/admin_users.py` — pass `username` through to `create_user()`
6. `backend/audit_set/viewer_router.py` — replace OTP-based signing with direct `POST /viewer/sign/confirm`
7. `backend/audit_set/signatures_router.py` — replace OTP-based FR218/FR222 signing with `POST /{id}/signatures/{sig_id}/sign-direct`
8. `frontend/src/app/(auth)/login/page.tsx` — change Email field to Username
9. `frontend/src/components/SignatureConfirmDialog.tsx` — remove OTP step; single click signs
10. `frontend/src/components/ui/InternalApprovalsSection.tsx` — remove OTP step from modal
11. `frontend/src/app/(client)/client/documents/page.tsx` — remove inline OTP signing machinery

---

## Change 1 — `backend/email_service.py`

Stub every public `send_*` function to return `False` immediately. Keep function signatures
and imports intact so no other file needs to change its imports.

```python
# REPLACE the body of every send_* function with:
#   return False
# Keep the function signature, docstring (if any), and return type.

# Example — do this for ALL functions:
def send_otp_code(to: str, full_name: str, otp: str, document_label: str) -> bool:
    return False

def send_document_released(to: str, full_name: str, document_label: str) -> bool:
    return False

def send_client_status_update(to: str, full_name: str, new_status: str, notes: str = "") -> bool:
    return False

def send_client_welcome(to: str, full_name: str, temp_password: str) -> bool:
    return False

def send_impartiality_declaration_request(*args, **kwargs) -> bool:
    return False

def send_new_message_notification(*args, **kwargs) -> bool:
    return False

def send_meeting_signing_link(*args, **kwargs) -> bool:
    return False

def send_meeting_otp(*args, **kwargs) -> bool:
    return False
```

Apply this to every function in the file. Do not delete the functions — only replace their
bodies with `return False`.

---

## Change 2 — `backend/auth/db_models.py`

Add a nullable `username` column to `PlatformUser` and register a safe migration.

```python
# In PlatformUser class, add after the `email` column:
username = Column(String, nullable=True, index=True)

# In create_tables(), add:
_safe_add_column_auth("platform_users", "username VARCHAR")
```

`username` is nullable because the existing admin account has no username and logs in by
email. New accounts will have a username set on creation.

---

## Change 3 — `backend/auth/service.py`

### 3a — Add `get_user_by_username()`

```python
def get_user_by_username(db: Session, username: str) -> PlatformUser | None:
    return db.query(PlatformUser).filter(PlatformUser.username == username).first()
```

### 3b — Update `authenticate()` to accept username OR email

```python
# BEFORE:
def authenticate(db: Session, email: str, password: str) -> PlatformUser | None:
    user = get_user_by_email(db, email)

# AFTER:
def authenticate(db: Session, identifier: str, password: str) -> PlatformUser | None:
    """Accept username or email as identifier."""
    user = get_user_by_username(db, identifier) or get_user_by_email(db, identifier)
```

Keep the rest of the function identical.

### 3c — Update `create_user()` to accept optional `username`

```python
# BEFORE:
def create_user(
    db: Session,
    email: str,
    password: str,
    full_name: str,
    role: str,
    auditor_id: str | None = None,
) -> PlatformUser:
    user = PlatformUser(
        email=email,
        password_hash=hash_password(password),
        full_name=full_name,
        role=role,
        auditor_id=auditor_id,
    )

# AFTER:
def create_user(
    db: Session,
    email: str,
    password: str,
    full_name: str,
    role: str,
    auditor_id: str | None = None,
    username: str | None = None,
) -> PlatformUser:
    user = PlatformUser(
        email=email,
        password_hash=hash_password(password),
        full_name=full_name,
        role=role,
        auditor_id=auditor_id,
        username=username,
    )
```

Also add `"username"` to the `_UPDATABLE` set in `update_user()`:

```python
_UPDATABLE = {"full_name", "role", "is_active", "auditor_id", "username"}
```

---

## Change 4 — `backend/auth/schemas.py`

```python
# UserCreateSchema — add username field:
class UserCreateSchema(BaseModel):
    email: str
    password: str
    full_name: str
    role: str
    auditor_id: str | None = None
    username: str | None = None      # ← ADD

# UserUpdateSchema — add username field:
class UserUpdateSchema(BaseModel):
    full_name: str | None = None
    role: str | None = None
    is_active: bool | None = None
    auditor_id: str | None = None
    username: str | None = None      # ← ADD

# UserResponse — add username field:
class UserResponse(BaseModel):
    id: str
    email: str
    username: str | None             # ← ADD
    full_name: str
    role: str
    is_active: bool
    auditor_id: str | None
    last_login: datetime | None
    created_at: datetime

    class Config:
        from_attributes = True
```

Do NOT change `LoginRequest`. It keeps `email: str` as the JSON field name — the
value passed can be a username or email; the `authenticate()` function handles both.

---

## Change 5 — `backend/api/routes/admin_users.py`

In `admin_create_user`, pass `username` through to `create_user`:

```python
# BEFORE:
user = create_user(db, body.email, body.password, body.full_name, body.role, body.auditor_id)

# AFTER:
user = create_user(db, body.email, body.password, body.full_name, body.role, body.auditor_id, body.username)
```

---

## Change 6 — `backend/audit_set/viewer_router.py`

### 6a — Remove OTP infrastructure

Remove the following from the file:
- `OTP_EXPIRY = 10` constant
- `_hash_otp()` function
- `SignOtpRequest` Pydantic class
- `SignVerifyRequest` Pydantic class
- `POST /viewer/sign/request-otp` endpoint (`sign_request_otp` function)
- `POST /viewer/sign/verify` endpoint (`sign_verify` function)

Also remove from the import line:
```python
# REMOVE from the email_service import:
from email_service import send_document_released, send_otp_code, send_client_status_update
```
(email_service functions are now no-ops; the import can stay or be removed — if keeping
it, it won't matter. But since we're also cleaning up _commit_existing_signing_record
below, remove the import entirely.)

### 6b — Clean up `_commit_existing_signing_record`

In `_commit_existing_signing_record`, remove all `send_*` calls. These are the blocks
wrapped in `try: send_document_released(...) except: pass` and
`try: send_otp_code(...) except: pass` and `try: send_client_status_update(...) except: pass`.

Remove every such block entirely. The surrounding logic (workflow transitions,
`doc.status = "released"`, `audit_set.workflow_status = ...`, `db.commit()`) must be
kept exactly as-is — only the email sending blocks are removed.

### 6c — Add `POST /viewer/sign/confirm`

Add this new Pydantic class and endpoint to replace the OTP flow:

```python
class SignConfirmRequest(BaseModel):
    document_type: str
    doc_id:        str
    sig_key:       str


@router.post("/sign/confirm")
def sign_confirm(
    body:         SignConfirmRequest,
    request:      Request,
    db:           Session      = Depends(get_db),
    auth_db:      Session      = Depends(get_auth_db),
    current_user: PlatformUser = Depends(get_current_user),
):
    """
    Direct sign endpoint — no OTP required.
    Validates authorization, records VisualSignaturePlacement with the user's
    saved signature image, then mirrors the event into workflow/legal tables
    via _commit_existing_signing_record.
    """
    _assert_can_sign(body.document_type, body.doc_id, body.sig_key, current_user, db)

    user_sig = auth_db.query(UserSignature).filter_by(user_id=current_user.id).first()
    if not user_sig:
        raise HTTPException(
            400,
            "No signature on file. Go to Settings → My Signature to set one up, then try again.",
        )

    # Reuse or create the pending VisualSignaturePlacement row.
    vsp = (
        db.query(VisualSignaturePlacement)
        .filter_by(
            document_type=body.document_type,
            doc_id=body.doc_id,
            sig_key=body.sig_key,
            user_id=current_user.id,
        )
        .filter(VisualSignaturePlacement.signed_at.is_(None))
        .first()
    )
    if not vsp:
        vsp = VisualSignaturePlacement(
            document_type=body.document_type,
            doc_id=body.doc_id,
            sig_key=body.sig_key,
            user_id=current_user.id,
        )
        db.add(vsp)

    ip = request.client.host if request.client else None
    vsp.signature_image = user_sig.image_data
    vsp.otp_hash        = None
    vsp.otp_expires     = None
    vsp.signed_at       = datetime.utcnow()
    vsp.signed_ip       = ip
    db.commit()

    _commit_existing_signing_record(
        body.document_type, body.doc_id, body.sig_key, current_user, ip, db, auth_db,
    )

    return {
        "signed":    True,
        "sig_key":   body.sig_key,
        "signed_at": vsp.signed_at.isoformat(),
    }
```

---

## Change 7 — `backend/audit_set/signatures_router.py`

### 7a — Remove OTP endpoints

Remove:
- `POST /{audit_set_id}/signatures/{sig_id}/request-otp` (`request_cb_signature_otp`)
- `POST /{audit_set_id}/signatures/{sig_id}/verify` (`verify_cb_signature`)
- `OTP_EXPIRY` constant
- `_hash_otp()` function
- `from email_service import send_document_released, send_otp_code` import line

### 7b — Add `sign-direct` endpoint

```python
@router.post("/{audit_set_id}/signatures/{sig_id}/sign-direct")
def sign_direct(
    audit_set_id: str,
    sig_id:       str,
    request:      Request,
    db:           Session      = Depends(get_db),
    auth_db:      Session      = Depends(get_auth_db),
    current_user: PlatformUser = Depends(get_current_user),
):
    """Direct sign for FR218/FR222 internal slots — no OTP required."""
    if current_user.role not in CB_ROLES:
        raise HTTPException(403, "Not authorized")

    sig = db.query(AuditDocumentSignature).filter_by(
        id=sig_id, audit_set_id=audit_set_id
    ).first()
    if not sig:
        raise HTTPException(404, "Signature slot not found")

    # Self-assign if the slot is unassigned and the caller is eligible.
    if sig.signer_user_id is None:
        eligible = (
            sig.signer_role_label == "cb_cert_manager"
            and current_user.role in ("admin", "executive")
        )
        if not eligible:
            raise HTTPException(403, "You are not eligible to sign this slot")
        sig.signer_user_id = current_user.id
        sig.signer_name    = current_user.full_name
        sig.signer_email   = current_user.email
    elif sig.signer_user_id != current_user.id:
        raise HTTPException(403, "This signature slot is not assigned to you")

    if sig.signed_at:
        raise HTTPException(400, "Already signed")

    sig.signed_at      = datetime.utcnow()
    sig.signed_ip      = request.client.host if request.client else None
    sig.otp_hash       = None
    sig.otp_expires_at = None

    # Flush before count so the updated signed_at is visible.
    db.flush()

    # If this slot has a linked shared document, check whether all required
    # signatures are now collected and release the document if so.
    if sig.document_id:
        doc = db.query(AuditSetSharedDocument).filter_by(id=sig.document_id).first()
        if doc and doc.status == "pending_cb_signature":
            remaining = (
                db.query(AuditDocumentSignature)
                .filter_by(document_id=sig.document_id, required=True)
                .filter(AuditDocumentSignature.signed_at.is_(None))
                .count()
            )
            if remaining == 0:
                doc.status = "released"
                audit_set = db.query(AuditSet).filter_by(id=audit_set_id).first()
                if audit_set and doc.document_type == "quotation":
                    if audit_set.workflow_status == "in_planning":
                        audit_set.workflow_status = "quotation_sent"
                        db.add(AuditSetStatusEvent(
                            audit_set_id=audit_set_id,
                            from_status="in_planning",
                            to_status="quotation_sent",
                            triggered_by=current_user.id,
                            notes="Quotation signed by CB planner and released (direct sign)",
                        ))

    db.commit()
    return {"signed": True, "signed_at": sig.signed_at.isoformat()}
```

Add to the imports at the top of `signatures_router.py`:
```python
from fastapi import APIRouter, Depends, HTTPException, Request
# (Request is already imported; add it if missing)
```

Also add these to the existing `audit_set.db_models` import block if not already present:
```python
AuditSet, AuditSetStatusEvent
```

---

## Change 8 — `frontend/src/app/(auth)/login/page.tsx`

Three cosmetic changes only — the API call body stays `{ email, password }`:

```tsx
// 1. State variable name stays `email`, but label changes:
<label htmlFor="email" ...>
  Username          {/* was: Email */}
</label>

// 2. Input type and placeholder:
<Input
  id="email"
  type="text"                          {/* was: type="email" */}
  placeholder="username or email"      {/* was: "you@example.com" */}
  value={email}
  onChange={(e) => setEmail(e.target.value)}
  autoComplete="username"              {/* was: "email" */}
/>

// 3. Error message:
// was: "Invalid email or password."
// now: "Invalid username or password."
```

Do not change the API call body — it still sends `{ email: ..., password }`. The backend
`authenticate()` now tries username first so this works for both email and username values.

---

## Change 9 — `frontend/src/components/SignatureConfirmDialog.tsx`

Remove the OTP step entirely. The dialog becomes: loading → preview → signing → success.

### 9a — Simplify Stage type

```typescript
// BEFORE:
type Stage = 'loading' | 'no_signature' | 'preview' | 'otp_sent' | 'verifying' | 'success'

// AFTER:
type Stage = 'loading' | 'no_signature' | 'preview' | 'signing' | 'success'
```

### 9b — Remove OTP state

Remove these state variables:
```typescript
const [otp, setOtp] = useState('')
const otpRef = useRef<HTMLInputElement>(null)
```

Remove the `useEffect` that focused the OTP input:
```typescript
// REMOVE this entire useEffect:
useEffect(() => {
  if (stage === 'otp_sent') {
    const t = setTimeout(() => otpRef.current?.focus(), 80)
    return () => clearTimeout(t)
  }
}, [stage])
```

### 9c — Replace `handleRequestOtp` with `handleConfirm`

Remove `handleRequestOtp()` and `handleVerify()` entirely.

Add this single function:
```typescript
async function handleConfirm() {
  setStage('signing')
  setErrorMsg('')
  setStatusMsg('')
  try {
    await api.post('/viewer/sign/confirm', {
      document_type: documentType,
      doc_id:        docId,
      sig_key:       sigKey,
    })
    setStage('success')
    setTimeout(() => onSigned(sigKey), 1400)
  } catch (e: unknown) {
    const err = e as { response?: { data?: { detail?: string } } }
    setErrorMsg(err.response?.data?.detail ?? 'Failed to sign. Please try again.')
    setStage('preview')
  }
}
```

### 9d — Simplify the JSX body

Remove the `otp_sent` and `verifying` stage blocks entirely.

In the `preview` stage block:
- Remove the `{statusMsg && ...}` line (no longer needed)
- Change the button:
```tsx
// BEFORE:
<button type="button" onClick={handleRequestOtp} ...>
  Send verification code
</button>

// AFTER:
<button type="button" onClick={handleConfirm} ...>
  Sign Document
</button>
```

Replace the `verifying` stage block with the `signing` stage block:
```tsx
{stage === 'signing' && (
  <div className="flex items-center justify-center gap-2 py-10 text-sm text-gray-500">
    <Loader2 size={18} className="animate-spin text-[#1A4731]" />
    Signing…
  </div>
)}
```

The `success` stage block stays identical.

Also remove the `statusMsg` state variable if it is no longer used after the above changes.

---

## Change 10 — `frontend/src/components/ui/InternalApprovalsSection.tsx`

### 10a — Remove OTP state and functions

Remove these state variables:
```typescript
const [signingId, setSigningId] = useState<string | null>(null)
const [otpSent, setOtpSent]     = useState(false)
const [otpValue, setOtpValue]   = useState('')
const [error, setError]         = useState('')
```

Remove functions: `requestOtp()`, `verifyOtp()`

### 10b — Replace `handleConfirmSign` with direct sign

Replace:
```typescript
function handleConfirmSign() {
  const slot = sigPreviewSlot
  setSigPreviewSlot(null)
  setSigPreviewImage(null)
  if (slot) requestOtp(slot)
}
```

With:
```typescript
async function handleConfirmSign() {
  const slot = sigPreviewSlot
  setSigPreviewSlot(null)
  setSigPreviewImage(null)
  if (!slot) return
  setBusy(true)
  try {
    await api.post(`/audit-sets/${auditSetId}/signatures/${slot.id}/sign-direct`)
    await load()
  } catch (e: unknown) {
    const detail = (e as { response?: { data?: { detail?: string } } })?.response?.data?.detail
    alert(detail || 'Failed to sign. Please try again.')
  } finally {
    setBusy(false)
  }
}
```

### 10c — Simplify `rowProps`

```typescript
// BEFORE:
const rowProps = {
  signingId, otpSent, otpValue, error, busy: busy || sigPreviewBusy,
  onSign:      handleSignClick,
  onVerify:    verifyOtp,
  onOtpChange: setOtpValue,
  onCancel:    () => { setSigningId(null); setOtpSent(false); setOtpValue('') },
  onResend:    requestOtp,
}

// AFTER:
const rowProps = {
  busy: busy || sigPreviewBusy,
  onSign: handleSignClick,
}
```

### 10d — Simplify `SignerRow`

The `SignerRow` component no longer needs OTP props. Simplify its interface and body:

```typescript
function SignerRow({
  slot, busy, onSign,
}: {
  slot:   SigSlot
  busy:   boolean
  onSign: (s: SigSlot) => void
}) {
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
          ) : (slot.is_mine || slot.can_claim) ? (
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
    </div>
  )
}
```

### 10e — Update the modal button

In the `sigPreviewSlot` modal, the "Send verification code" button becomes "Sign":

```tsx
// BEFORE:
<button type="button" onClick={handleConfirmSign} ...>
  Send verification code
</button>

// AFTER:
<button type="button" onClick={handleConfirmSign} disabled={busy} ...>
  {busy ? 'Signing…' : 'Sign'}
</button>
```

---

## Change 11 — `frontend/src/app/(client)/client/documents/page.tsx`

Remove the entire inline OTP signing machinery. Documents are signed via the viewer only.

### 11a — Remove state

Remove:
```typescript
const [signingDoc, setSigningDoc] = useState<string | null>(null)
const [otpSent, setOtpSent]       = useState(false)
const [otpValue, setOtpValue]     = useState('')
const [signError, setSignError]   = useState('')
const [signLoading, setSignLoading] = useState(false)
```

### 11b — Remove functions

Remove `requestOtp()` and `submitOtp()` entirely.

### 11c — Simplify the document card JSX

Replace the action buttons block:

```tsx
// BEFORE (the mt-4 flex div with Sign Document button + OTP panel):
<div className="mt-4 flex items-center gap-2">
  <a href={`/client/viewer/shared_doc/${doc.id}`} ...>Open</a>
  <button onClick={() => downloadDoc(doc.id, doc.label)} ...>Download</button>
  {doc.status !== 'signed' && (
    <button onClick={() => requestOtp(doc.id)} ...>Sign Document</button>
  )}
  {doc.status === 'signed' && doc.signed_at && (
    <span ...>Signed on {fmtDate(doc.signed_at)}</span>
  )}
</div>
{signingDoc === doc.id && ( ... OTP panel ... )}

// AFTER:
<div className="mt-4 flex items-center gap-2">
  <a href={`/client/viewer/shared_doc/${doc.id}`}
    className="inline-flex items-center gap-1.5 rounded-lg border border-[#1A4731] px-3 py-1.5
      text-sm font-medium text-[#1A4731] hover:bg-[#1A4731]/5 transition-colors"
  >
    {doc.status !== 'signed' ? 'Open to Sign' : 'Open'}
  </a>
  <button
    type="button"
    onClick={() => downloadDoc(doc.id, doc.label)}
    className="rounded-lg border border-[#1A4731] px-3 py-1.5 text-sm text-[#1A4731] transition-colors hover:bg-green-50"
  >
    Download
  </button>
  {doc.status === 'signed' && doc.signed_at && (
    <span className="text-xs text-gray-400">
      Signed on {fmtDate(doc.signed_at)}
    </span>
  )}
</div>
```

Remove the entire `{signingDoc === doc.id && (...)}` OTP panel block.

---

## Verification Checklist

After implementing, confirm:

- [ ] Admin logs in at `/login` with `info@ifcglobal.us` + existing password — works ✅
- [ ] A new user with `username="john.smith"` logs in at `/login` entering `john.smith` — works ✅
- [ ] CB planner opens quotation in viewer → clicks CB_PLANNER signature box → `SignatureConfirmDialog` shows signature preview → clicks "Sign Document" → signs immediately, no OTP input shown ✅
- [ ] Client opens agreement in viewer → clicks CLIENT box → same single-click flow ✅
- [ ] FR218 "Sign" button → preview modal opens → "Sign" button → signs immediately ✅
- [ ] No email is ever sent anywhere — check Railway logs for any SMTP errors ✅
- [ ] `GET /admin/users/` returns `username` field in response ✅
- [ ] `POST /admin/users/` accepts `username` in request body ✅
- [ ] Client documents page shows "Open to Sign" for unsigned documents, no "Sign Document" button ✅
- [ ] Signing a quotation still triggers `workflow_status → quotation_sent` and `doc.status → released` ✅
- [ ] Signing an agreement still triggers `workflow_status → agreement_signed` ✅
