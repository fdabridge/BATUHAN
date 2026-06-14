# Portal 56 — Org Employee Roster: Wire Into All Client-Side Signing

## Context: What the Smoke Test Revealed

During smoke testing, when the client signed the **Quotation and Agreement**, the signing
used the client platform user's own name and signature (the account holder). But the
intended behavior is:

- The organization registers **employees** (real people with names, titles, and a
  signature image with transparent background)
- When any document requires an "Organization Representative" signature, the client user
  selects **which registered employee** is signing
- That employee's **name and signature image** appear in the document — not the
  account holder's name

This is not a new feature. It was built in Portal 49a. Here is what is already working:

### What's already built and working

**Backend:**
- `ClientOrgEmployee` model in `db_models.py` — table `client_org_employees` with
  columns: `id`, `client_user_id`, `full_name`, `role_title`, `signature_data` (base64
  PNG stored in-row), `signature_source`, `is_active`, `created_at`, `updated_at`
- `employee_router.py` — full CRUD: `GET/POST /org/employees`, 
  `PATCH/DELETE /org/employees/{id}`, `POST /org/employees/{id}/signature`,
  `GET /org/employees/{id}/signature`
- Router mounted in `main.py`
- `packager.py` calls `_resolve_org_attendees()` which queries `ClientOrgEmployee` for
  the client linked to the audit set and injects into FR.225 template context as
  `org_attendees`
- FR.225 templates use `{%tr for emp in org_attendees %}` docxtpl loop — each org
  employee gets a signature row with a dynamic sig_key
  `[SIG:ORG_OPENING_ORG_EMP_{uuid}]`
- `viewer_router.py` `_assert_can_sign` handles `ORG_OPENING_ORG_EMP_*` and
  `ORG_CLOSING_ORG_EMP_*` keys — looks up the employee from the sig_key UUID,
  checks client owns them, uses the employee's `signature_data` for stamping

**Frontend:**
- `/client/employees` page — full employee management UI (create, edit, delete, upload
  signature)
- Linked in client sidebar nav

### What's broken — the gaps to fix

**Gap 1** — `_get_field_status` for `ORG_OPENING_ORG_EMP_*` keys always returns
`"pending"` regardless of whether the employee has signed. These keys don't match
`SIG_TO_ROLE` so the function falls through to `_result("pending")` without checking
the `AuditDocumentSignature` record. Fix this so signed employee slots show `"signed"`.

**Gap 2** — `org_rep` slots (quotation, agreement, audit_plan, nc_form) still use the
**client user's own signature** instead of the employee roster. This is the main issue
from the smoke test: Batuhan expected the client to pick an employee when signing the
Quotation. Instead, the client's own UserSignature was used.

**Gap 3** — There is no UI in the viewer for the client to **pick which employee** is
signing an `org_rep` document. The `SignatureConfirmDialog` needs an employee picker
step when the document is client-side (`org_rep` slot).

---

## Fix 1 — `_get_field_status` for ORG_EMP sig keys

**File:** `backend/audit_set/viewer_router.py`

In `_get_field_status`, before the final fallthrough to `_result("pending")`, add
handling for dynamic ORG_EMP keys. These keys start with `ORG_OPENING_ORG_EMP_` or
`ORG_CLOSING_ORG_EMP_`.

```python
# Near the top of _get_field_status, after the SIG_TO_ROLE lookup:
ORG_EMP_PREFIXES = ("ORG_OPENING_ORG_EMP_", "ORG_CLOSING_ORG_EMP_")
if any(sig_key.startswith(p) for p in ORG_EMP_PREFIXES):
    # Check if this slot is signed in AuditDocumentSignature
    if vsp and vsp.signed_at:
        return _result("signed", vsp.signature_image)
    # Is the current user the client for this audit set?
    if current_user.role == "client" and current_user.audit_set_id == doc.audit_set_id:
        return _result("current_user")
    return _result("pending")
```

Note: `vsp` is the `AuditDocumentSignature` record queried at the top of
`_get_field_status`. Verify it is queried for ALL sig_keys including dynamic ones,
not just those in `SIG_TO_ROLE`.

---

## Fix 2 — `org_rep` slot uses employee roster instead of user's own signature

### Backend change — `viewer_router.py` `_assert_can_sign` and `sign_confirm`

The current `org_rep` eligibility check (line ~310):
```python
if role_label == "org_rep":
    return role == "client" and current_user.audit_set_id == doc.audit_set_id
```

This stays correct — the client user is still the one who clicks "sign." But the
**signing action** needs to accept an `employee_id` and use that employee's stored
`signature_data` instead of the user's own `UserSignature`.

In the `sign_confirm` endpoint (`POST /viewer/sign`), update the request body to accept
an optional `employee_id`:

```python
class SignConfirmRequest(BaseModel):
    sig_key:     str
    signed_date: Optional[str] = None
    employee_id: Optional[str] = None  # ADD THIS — required when sig_key = "org_rep"
```

In `sign_confirm`, after the eligibility check, when `sig_key == "org_rep"`:

```python
if sig_key == "org_rep":
    if not body.employee_id:
        raise HTTPException(400, "employee_id required for org_rep signing")
    
    employee = db.query(ClientOrgEmployee).filter_by(
        id=body.employee_id,
        client_user_id=current_user.id,
        is_active=True,
    ).first()
    if not employee:
        raise HTTPException(404, "Employee not found or not yours")
    if not employee.signature_data:
        raise HTTPException(400, "This employee has no signature on file")
    
    # Use employee's name and signature instead of user's own
    signer_name      = employee.full_name
    signature_image  = employee.signature_data  # base64 PNG data URL
else:
    # Existing flow: use current_user's UserSignature
    user_sig = db.query(UserSignature).filter_by(user_id=current_user.id).first()
    signer_name     = current_user.full_name
    signature_image = user_sig.image_data if user_sig else None
```

Make sure `ClientOrgEmployee` is imported in `viewer_router.py`.

### Frontend change — `SignatureConfirmDialog.tsx`

When `sigKey === 'org_rep'`, add an employee picker step before the confirm button.

The dialog should:
1. On open, fetch `GET /org/employees` to get the client's registered employees
2. Show a dropdown: "Select who is signing" populated with `[{ id, full_name, role_title, has_signature }]`
3. If no employees are registered, show a message: "No employees on file. Add employees at Settings → Employees before signing."
4. Show the selected employee's signature preview (if they have one)
5. The "Confirm signature" button is disabled until an employee is selected AND they have a signature

When the confirm button is clicked, include `employee_id` in the POST body:
```typescript
await api.post('/viewer/sign', {
  sig_key:     sigKey,
  signed_date: signedDate,
  doc_id:      docId,
  document_type: documentType,
  employee_id: selectedEmployeeId,   // ADD for org_rep
})
```

Keep the existing flow unchanged for all non-`org_rep` sigKeys (internal CB users,
lead auditor, etc.).

### Employee fetch in `SignatureConfirmDialog`

```typescript
const [employees, setEmployees] = useState<{id:string, full_name:string, role_title:string, has_signature:boolean}[]>([])
const [selectedEmpId, setSelectedEmpId] = useState<string>('')

useEffect(() => {
  if (isOpen && sigKey === 'org_rep') {
    api.get('/org/employees').then(r => setEmployees(r.data)).catch(() => {})
  }
}, [isOpen, sigKey])
```

---

## Fix 3 — Ensure `client_org_employees` table exists on Railway

The table is defined in `db_models.py` and created via `Base.metadata.create_all`.
However, if Railway's Postgres already had the schema before this model was added,
`create_all` is idempotent and may not have created the table.

Add a `_safe_add_table` guard in `create_tables()` similar to `_safe_add_column`:

```python
def _safe_create_table(table_name: str, create_sql: str) -> None:
    """Create table if it doesn't already exist."""
    try:
        engine.execute(f"SELECT 1 FROM {table_name} LIMIT 1")
    except Exception:
        try:
            engine.execute(create_sql)
            logger.info("[DB] Created missing table: %s", table_name)
        except Exception as e:
            logger.warning("[DB] Could not create table %s: %s", table_name, e)
```

Or more simply — just add `_safe_add_column` calls for each column of
`client_org_employees` in `create_tables()`, which will trigger the "table doesn't
exist" error and fall through to `create_all`. Actually the simplest fix: ensure
`Base.metadata.create_all(bind=engine, checkfirst=True)` is called — the
`checkfirst=True` flag makes it skip tables that already exist but CREATE any that don't.
Verify `create_tables()` in `db_models.py` calls `create_all` with `checkfirst=True`.
If not, add it.

---

## What to NOT change

- The `ORG_OPENING_ORG_EMP_*` signing flow for FR.225 — already correct. Employee
  UUID is in the sig_key, `_assert_can_sign` already uses the employee's `signature_data`
- The `/org/employees` CRUD endpoints — already correct
- The `/client/employees` frontend page — already correct
- The `packager.py` `_resolve_org_attendees()` — already correct

---

## Verification after deploy

1. Log in as Client. Go to `/client/employees`. Add 2 employees (e.g. Ahmad Habib,
   Managing Director) and upload a transparent-background PNG signature for each.
2. Go to a pending Quotation → "Open to Sign". Click the Org Rep signature field.
3. Expect: an employee picker appears. Select Ahmad Habib.
4. Expect: Ahmad Habib's name appears in the confirmation dialog + his signature preview.
5. Confirm. Expect: the document now shows Ahmad Habib's name and signature at the
   Org Rep position (not the client account holder's name).
6. Same test for Agreement, FR.223 (after auditor uploads it), FR.230.
7. For FR.225: after Lead Auditor uploads, open viewer as Client. The org employee rows
   should each have a signature slot. Click one. Expect: immediate sign with that
   employee's stored signature (no picker needed — employee is embedded in the sig_key).
   After signing, the slot should show "✓ Signed" (Fix 1).

---

## Files to change

| File | Change |
|------|--------|
| `backend/audit_set/viewer_router.py` | `_get_field_status`: handle ORG_EMP sig keys; `sign_confirm`: accept `employee_id`, use employee's signature for org_rep |
| `backend/audit_set/viewer_router.py` | Import `ClientOrgEmployee` |
| `frontend/src/components/SignatureConfirmDialog.tsx` | Employee picker step for `sigKey === 'org_rep'`; pass `employee_id` in POST body |
| `backend/audit_set/db_models.py` | Ensure `create_all(checkfirst=True)` so `client_org_employees` table is created on Railway |

---

## Commit message

```
Portal 56: wire org employee roster into org_rep signing

ClientOrgEmployee model and /org/employees endpoints were built in Portal 49a
but never connected to the signing flow for quotation/agreement/audit_plan/nc_form.
The client account holder's own signature was being used instead of a registered
employee's.

- viewer_router sign_confirm: accept employee_id; when sig_key=org_rep, use the
  selected employee's full_name + signature_data instead of user's UserSignature
- viewer_router _get_field_status: handle ORG_OPENING/CLOSING_ORG_EMP_* keys —
  return "signed" when AuditDocumentSignature.signed_at is set (was always "pending")
- SignatureConfirmDialog: employee picker step when sigKey=org_rep; fetches
  /org/employees, shows dropdown + preview, requires selection before confirm
- db_models create_all: checkfirst=True to ensure client_org_employees table
  is created on Railway if it was added after initial deploy
```
