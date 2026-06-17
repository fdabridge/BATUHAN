# Prompt 29 — Bulk User Import (CB Staff + Auditors)

## Context

All user accounts are created by the admin — there is no self-signup.
Two types of accounts are being created:

- **CB staff** (roles: `planner`, `officer`, `executive`, `admin`) — internal staff.
  Only need: full name, username, password, role, email (stored but never used).

- **Auditors** (role: `auditor`) — external auditors used since last year.
  Need all of the above plus: standard qualifications with EA codes,
  accreditation bodies, and technical depth per standard.
  Each auditor account must be linked to an `Auditor` profile record (the
  competency/qualification record used when assigning auditors to audit sets).

**Critical architecture note:** `platform_users` lives in the auth database.
`auditors` (and `auditor_standard_qualifications`) live in a **separate** auditors
database. Both are accessed via their own SQLAlchemy sessions. When creating an
auditor account, the `Auditor` record must be created in the auditors DB first,
then `PlatformUser` is created in the auth DB with `auditor_id` pointing to it.

---

## CSV format

A single CSV file handles both CB staff and auditors. Auditor-specific columns
are ignored for non-auditor rows.

```
full_name,username,email,password,role,standards,ea_codes,accreditation_bodies,technical_depth
John Smith,john.smith,john@ifcglobal.us,TempPass123,planner,,,, 
Jane Doe,jane.doe,jane@example.com,TempPass456,auditor,ISO 9001|ISO 14001,EA 3|EA 7,UAF|TURKAK,Lead Auditor
Ali Yilmaz,ali.yilmaz,ali@example.com,TempPass789,auditor,ISO 45001,EA 28,TURKAK,Team Auditor
```

- `standards`: pipe-separated standard codes e.g. `ISO 9001|ISO 14001|ISO 45001`
- `ea_codes`: pipe-separated EA codes applied to ALL standards for this auditor e.g. `EA 3|EA 7`
- `accreditation_bodies`: pipe-separated e.g. `UAF|TURKAK`
- `technical_depth`: single value applied to all standards: `Lead Auditor` | `Team Auditor` | `Technical Expert`
- For non-auditor rows, leave `standards`, `ea_codes`, `accreditation_bodies`, `technical_depth` blank.

---

## Change 1 — Backend: `backend/api/routes/admin_users.py`

### 1a — Add imports

```python
import csv
import io
from fastapi import File, UploadFile
from auditors.models import Auditor, AuditorStandardQualification, get_db as get_auditors_db
```

### 1b — Add bulk import endpoint

```python
@router.post("/users/bulk-import")
async def admin_bulk_import(
    file:          UploadFile = File(...),
    db:            Session    = Depends(get_db),
    auditors_db:   Session    = Depends(get_auditors_db),
    _admin:        PlatformUser = Depends(require_admin),
):
    """
    CSV bulk import for CB staff and auditor accounts.
    Idempotent: rows whose username already exists in platform_users are skipped.
    Returns a summary of what was created, skipped, and any row-level errors.
    """
    contents = await file.read()
    try:
        text = contents.decode("utf-8-sig")   # utf-8-sig strips BOM if present
    except UnicodeDecodeError:
        text = contents.decode("latin-1")

    reader = csv.DictReader(io.StringIO(text))

    created = []
    skipped = []
    errors  = []

    for i, row in enumerate(reader, start=2):   # row 1 = header
        full_name  = (row.get("full_name")  or "").strip()
        username   = (row.get("username")   or "").strip()
        email      = (row.get("email")      or "").strip()
        password   = (row.get("password")   or "").strip()
        role       = (row.get("role")       or "").strip().lower()
        standards_raw     = (row.get("standards")          or "").strip()
        ea_codes_raw      = (row.get("ea_codes")           or "").strip()
        accred_raw        = (row.get("accreditation_bodies") or "").strip()
        tech_depth        = (row.get("technical_depth")    or "").strip()

        # ── Validate required fields ──────────────────────────────────────────
        if not full_name or not username or not password or not role:
            errors.append({"row": i, "username": username or "?",
                           "reason": "Missing required field (full_name / username / password / role)"})
            continue

        from auth.schemas import VALID_ROLES
        if role not in VALID_ROLES:
            errors.append({"row": i, "username": username,
                           "reason": f"Invalid role '{role}'. Must be one of {sorted(VALID_ROLES)}"})
            continue

        # ── Check for duplicate username ──────────────────────────────────────
        from auth.service import get_user_by_username, get_user_by_email
        if get_user_by_username(db, username):
            skipped.append({"row": i, "username": username, "reason": "Username already exists"})
            continue

        # ── Auditor path: create Auditor profile first ────────────────────────
        auditor_id = None
        if role == "auditor":
            standards = [s.strip() for s in standards_raw.split("|") if s.strip()]
            ea_codes  = [c.strip() for c in ea_codes_raw.split("|")  if c.strip()]
            accred    = [a.strip() for a in accred_raw.split("|")     if a.strip()]

            auditor = Auditor(
                name=full_name,
                email=email or None,
                role=tech_depth or "Lead Auditor",
                ea_codes=ea_codes if ea_codes else None,
                accreditation_bodies=accred if accred else None,
                is_active=True,
            )
            auditors_db.add(auditor)
            auditors_db.flush()   # get auditor.id before committing

            for std in standards:
                auditors_db.add(AuditorStandardQualification(
                    auditor_id=auditor.id,
                    standard_code=std,
                    accreditation_body=accred[0] if accred else None,
                    ea_codes=ea_codes if ea_codes else None,
                    technical_depth=tech_depth or "Lead Auditor",
                    is_qualified=True,
                ))
            auditors_db.commit()
            auditor_id = auditor.id

        # ── Create platform_users account ─────────────────────────────────────
        from auth.service import create_user
        try:
            user = create_user(
                db=db,
                email=email or f"{username}@certiva.internal",
                password=password,
                full_name=full_name,
                role=role,
                auditor_id=auditor_id,
                username=username,
            )
            created.append({
                "row":         i,
                "username":    username,
                "full_name":   full_name,
                "role":        role,
                "user_id":     user.id,
                "auditor_id":  auditor_id,
            })
        except Exception as exc:
            # Roll back auditor record if user creation failed
            if auditor_id:
                try:
                    a = auditors_db.query(Auditor).filter_by(id=auditor_id).first()
                    if a:
                        auditors_db.delete(a)
                        auditors_db.commit()
                except Exception:
                    pass
            errors.append({"row": i, "username": username, "reason": str(exc)})

    return {
        "summary": {
            "total_rows": len(created) + len(skipped) + len(errors),
            "created":    len(created),
            "skipped":    len(skipped),
            "errors":     len(errors),
        },
        "created": created,
        "skipped": skipped,
        "errors":  errors,
    }
```

---

## Change 2 — Frontend: `frontend/src/app/(app)/admin/users/page.tsx`

### 2a — Add `username` to the types used on this page

The `AdminUser` type (in `/types` or wherever it is defined) needs a `username` field:
```typescript
username: string | null
```

The `AdminUserCreatePayload` type needs:
```typescript
username?: string
```

Find the types file (likely `frontend/src/types/index.ts` or similar) and add these
fields. If the types are inlined, add them there.

### 2b — Update `CreateUserModal` to include `username` field

Add `username: ''` to the initial form state, and add the input field between
Full name and Email:

```tsx
// After the Full name field, before the Email field:
<div>
  <label className={lblCls}>Username * <span className="font-normal text-gray-400">(used to log in)</span></label>
  <input
    type="text"
    value={form.username ?? ''}
    onChange={(e) => setForm((f) => ({ ...f, username: e.target.value.trim() }))}
    className={inputCls}
    placeholder="e.g. john.smith"
  />
</div>
```

Update validation to require `username`:
```typescript
if (!form.full_name.trim() || !form.email.trim() || !form.password || !form.username?.trim()) {
  setErr('All fields are required.')
  return
}
```

Pass `username` in the mutation payload:
```typescript
m.mutate({ ...form, full_name: form.full_name.trim(), email: form.email.trim(), username: form.username?.trim() })
```

### 2c — Add `username` column to the users table

In the `<thead>` row, add a "Username" column after "User":
```tsx
<th className="px-4 py-3">Username</th>
```

In each user row, add the cell after the avatar+name cell:
```tsx
<td className="px-4 py-3 font-mono text-xs text-gray-500">{u.username ?? '—'}</td>
```

Update `colSpan` values in the loading/error/empty rows from `6` to `7`.

### 2d — Add `BulkImportModal` component

Add this new component above the `AdminUsersPage` function:

```tsx
function BulkImportModal({
  open, onClose, onSuccess,
}: { open: boolean; onClose: () => void; onSuccess: () => void }) {
  const [file,    setFile]    = useState<File | null>(null)
  const [result,  setResult]  = useState<BulkImportResult | null>(null)
  const [loading, setLoading] = useState(false)
  const [error,   setError]   = useState<string | null>(null)
  const fileRef = useRef<HTMLInputElement>(null)

  useEffect(() => {
    if (open) { setFile(null); setResult(null); setError(null) }
  }, [open])

  async function handleImport() {
    if (!file) { setError('Please select a CSV file.'); return }
    setLoading(true)
    setError(null)
    setResult(null)
    try {
      const fd = new FormData()
      fd.append('file', file)
      const r = await api.post<BulkImportResult>('/admin/users/bulk-import', fd, {
        headers: { 'Content-Type': 'multipart/form-data' },
      })
      setResult(r.data)
      if (r.data.summary.created > 0) onSuccess()
    } catch (e) {
      setError(extractDetail(e, 'Import failed.'))
    } finally {
      setLoading(false)
    }
  }

  return (
    <Modal open={open} title="Bulk import users" onClose={onClose}>
      <div className="space-y-4">
        {/* Format guide */}
        <div className="rounded-lg bg-gray-50 p-3 text-xs text-gray-600">
          <p className="mb-1 font-medium text-gray-700">Expected CSV columns:</p>
          <code className="block leading-5 text-gray-500">
            full_name, username, email, password, role,<br />
            standards, ea_codes, accreditation_bodies, technical_depth
          </code>
          <p className="mt-2 text-gray-400">
            Pipe-separate multiple values: <code>ISO 9001|ISO 14001</code><br />
            Leave auditor columns blank for non-auditor rows.<br />
            Rows with existing usernames are skipped (safe to re-run).
          </p>
        </div>

        {/* File input */}
        <div>
          <label className={lblCls}>CSV file *</label>
          <input
            ref={fileRef}
            type="file"
            accept=".csv,text/csv"
            onChange={(e) => setFile(e.target.files?.[0] ?? null)}
            className="w-full rounded-lg border border-gray-200 px-3 py-2 text-sm
              text-gray-700 file:mr-2 file:rounded file:border-0 file:bg-gray-100
              file:px-2 file:py-0.5 file:text-xs focus:outline-none"
          />
        </div>

        {error && (
          <div className="rounded border border-red-200 bg-red-50 px-3 py-2 text-xs text-red-700">
            {error}
          </div>
        )}

        {/* Result summary */}
        {result && (
          <div className="space-y-2">
            <div className="grid grid-cols-3 gap-2 text-center text-xs">
              <div className="rounded-lg bg-green-50 p-2">
                <p className="text-lg font-semibold text-green-700">{result.summary.created}</p>
                <p className="text-green-600">Created</p>
              </div>
              <div className="rounded-lg bg-gray-50 p-2">
                <p className="text-lg font-semibold text-gray-600">{result.summary.skipped}</p>
                <p className="text-gray-500">Skipped</p>
              </div>
              <div className={`rounded-lg p-2 ${result.summary.errors > 0 ? 'bg-red-50' : 'bg-gray-50'}`}>
                <p className={`text-lg font-semibold ${result.summary.errors > 0 ? 'text-red-600' : 'text-gray-600'}`}>
                  {result.summary.errors}
                </p>
                <p className={result.summary.errors > 0 ? 'text-red-500' : 'text-gray-500'}>Errors</p>
              </div>
            </div>

            {result.errors.length > 0 && (
              <div className="max-h-32 overflow-y-auto rounded border border-red-100 bg-red-50 p-2">
                {result.errors.map((e, i) => (
                  <p key={i} className="text-xs text-red-600">
                    Row {e.row} ({e.username}): {e.reason}
                  </p>
                ))}
              </div>
            )}
          </div>
        )}

        <button
          type="button"
          onClick={handleImport}
          disabled={!file || loading}
          className="flex w-full items-center justify-center gap-2 rounded-lg bg-certiva-primary
            px-4 py-2 text-sm font-medium text-white hover:opacity-90 disabled:opacity-60"
        >
          {loading && <Loader2 size={14} className="animate-spin" />}
          {loading ? 'Importing…' : 'Import'}
        </button>
      </div>
    </Modal>
  )
}
```

Add this type above the component (or in the types file):
```typescript
interface BulkImportResult {
  summary: { total_rows: number; created: number; skipped: number; errors: number }
  created: { row: number; username: string; full_name: string; role: string; user_id: string; auditor_id: string | null }[]
  skipped: { row: number; username: string; reason: string }[]
  errors:  { row: number; username: string; reason: string }[]
}
```

### 2e — Wire up BulkImportModal in `AdminUsersPage`

Add state variable:
```typescript
const [bulkOpen, setBulkOpen] = useState(false)
```

Add "Bulk import" button next to "Add user" in the header:
```tsx
<div className="flex items-center gap-2">
  <button
    type="button" onClick={() => setBulkOpen(true)}
    className="flex items-center gap-1 rounded-lg border border-certiva-primary px-3 py-2
      text-sm font-medium text-certiva-primary hover:bg-certiva-primary/5"
  >
    <Upload size={14} /> Bulk import
  </button>
  <button
    type="button" onClick={() => setCreateOpen(true)}
    className="flex items-center gap-1 rounded-lg bg-certiva-primary px-3 py-2 text-sm font-medium text-white hover:opacity-90"
  >
    <Plus size={14} /> Add user
  </button>
</div>
```

Add `Upload` to the lucide-react import at the top of the file.

Add the modal to the modals block at the bottom:
```tsx
<BulkImportModal
  open={bulkOpen}
  onClose={() => setBulkOpen(false)}
  onSuccess={invalidate}
/>
```

---

## Verification Checklist

- [ ] Upload a CSV with 2 CB staff rows and 2 auditor rows → summary shows 4 created ✅
- [ ] Re-upload the same CSV → summary shows 4 skipped, 0 created (idempotent) ✅
- [ ] Auditor user logs in with their username + password → lands on auditor dashboard ✅
- [ ] Auditor's profile appears in the auditor roster (`/admin/auditors` or similar) with correct standards and EA codes ✅
- [ ] CB planner logs in with username → lands on planner dashboard ✅
- [ ] Row with missing required field → appears in errors list with a clear reason ✅
- [ ] Row with invalid role → appears in errors list ✅
- [ ] "Add user" modal now includes a Username field and requires it ✅
- [ ] Users table shows a Username column ✅
- [ ] Admin account (`info@ifcglobal.us`) still works, shows `username: null` in the table ✅
