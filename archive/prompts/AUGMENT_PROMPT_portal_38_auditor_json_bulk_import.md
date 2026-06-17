# AUGMENT PROMPT — Portal 38: Auditor JSON Bulk Import Endpoint

## Background

The existing `POST /admin/users/bulk-import` (CSV) endpoint creates auditor
profiles with a flat EA code list that gets copied identically to every standard
qualification. This is wrong: each standard has its own specific EA codes (e.g.
an auditor may have EA 2, 15, 17 for QMS but all 39 for OHSMS, and food chain
categories CI/CII/CIV for FSMS — completely different per standard).

We have a correctly structured file `auditors_import.json` (138 auditors, already
in the repo root) that contains per-standard EA codes in the exact format the
`AuditorCreateSchema` + `StandardQualificationItem` already support.

This prompt does three things:
1. Adds a new `POST /auditors/bulk-import-json` endpoint that imports correctly
2. Adds a `DELETE /auditors/purge-all` endpoint so the wrong existing imports can
   be wiped before re-importing
3. Updates the frontend Admin → Users page to expose a "JSON Import" button

---

## Part A — Backend: new endpoint `POST /auditors/bulk-import-json`

### File: `backend/api/routes/auditors.py`

Add the following two imports near the top (after existing imports):

```python
import secrets
import string
```

Add the following two schemas inside the file (before the router routes):

```python
class BulkAuditorEntry(BaseModel):
    """One auditor entry in the JSON bulk import payload."""
    # All AuditorCreateSchema fields
    name: str
    role: Optional[str] = None
    field_of_expertise: Optional[str] = None
    ea_codes: Optional[list[str]] = None
    accreditation_bodies: Optional[list[str]] = None
    standard_qualifications: list = []   # list[StandardQualificationItem]

    # Account creation fields (optional — auto-generated if omitted)
    username: Optional[str] = None      # defaults to first.last
    password: Optional[str] = None      # defaults to random 10 chars


class BulkAuditorImportPayload(BaseModel):
    auditors: list[BulkAuditorEntry]
    replace_all: bool = False   # if True, purge all existing auditors first
```

Add the following helper inside the file:

```python
def _make_username(name: str) -> str:
    """'Ahmet Yakup Boran' -> 'ahmet.boran'"""
    import unicodedata, re
    replacements = {'ş':'s','ğ':'g','ı':'i','ö':'o','ü':'u','ç':'c',
                    'Ş':'S','Ğ':'G','İ':'I','Ö':'O','Ü':'U','Ç':'C'}
    n = name.strip()
    for k, v in replacements.items():
        n = n.replace(k, v)
    n = unicodedata.normalize('NFKD', n).encode('ascii', 'ignore').decode()
    parts = [p.lower() for p in n.split() if p.strip()]
    if len(parts) == 0: return 'user'
    if len(parts) == 1: return parts[0]
    return f"{parts[0]}.{parts[-1]}"


def _gen_password(length: int = 10) -> str:
    alphabet = string.ascii_letters + string.digits
    return ''.join(secrets.choice(alphabet) for _ in range(length))
```

Add the following route (after the existing `@router.post("/")` route):

```python
@router.post("/bulk-import-json")
def bulk_import_json(
    payload: BulkAuditorImportPayload,
    db: Session = Depends(get_db),
    auth_db: Session = Depends(get_auth_db),
    _: PlatformUser = Depends(require_admin),
):
    """
    Import auditors from structured JSON.
    Each entry creates an Auditor profile (with per-standard EA codes) AND
    a PlatformUser account linked to it.
    
    Set replace_all=true to purge all existing auditor records and their
    linked platform user accounts before importing (clean slate).
    
    Returns the full credentials list so usernames/passwords can be saved.
    """
    from auditors.service import create_auditor
    from auditors.schemas import AuditorCreateSchema, StandardQualificationItem
    from auditors.models import Auditor as AuditorModel
    from auth.db_models import PlatformUser as PU
    from auth.service import create_user
    import passlib.context as _pc

    # ── Optional purge ──────────────────────────────────────────────────────
    if payload.replace_all:
        # Delete all linked PlatformUser accounts (role=auditor) first
        existing_auditors = db.query(AuditorModel).all()
        auditor_ids = {a.id for a in existing_auditors}
        auth_db.query(PU).filter(
            PU.auditor_id.in_(auditor_ids)
        ).delete(synchronize_session=False)
        auth_db.commit()
        # Delete all Auditor records (cascades to qualifications etc.)
        db.query(AuditorModel).delete(synchronize_session=False)
        db.commit()
        logger.info("[BulkImport] Purged all existing auditors")

    # ── Track used usernames for deduplication ──────────────────────────────
    existing_usernames: set[str] = {
        u.username for u in auth_db.query(PU).all() if u.username
    }

    created: list[dict] = []
    skipped: list[dict] = []
    errors:  list[dict] = []

    for i, entry in enumerate(payload.auditors):
        # Build username (deduplicate)
        base_uname = entry.username or _make_username(entry.name)
        uname = base_uname
        suffix = 2
        while uname in existing_usernames:
            uname = f"{base_uname}{suffix}"
            suffix += 1
        existing_usernames.add(uname)

        pw = entry.password or _gen_password()

        # Convert raw standard_qualifications dicts to StandardQualificationItem
        sq_items = []
        for sq in entry.standard_qualifications:
            if isinstance(sq, dict):
                sq_items.append(StandardQualificationItem(**sq))
            else:
                sq_items.append(sq)

        # Build AuditorCreateSchema
        create_schema = AuditorCreateSchema(
            name=entry.name,
            role=entry.role,
            field_of_expertise=entry.field_of_expertise,
            ea_codes=entry.ea_codes,
            accreditation_bodies=entry.accreditation_bodies,
            standard_qualifications=sq_items,
        )

        try:
            # Create auditor profile
            auditor = create_auditor(db, create_schema)

            # Create platform user account
            email = f"{uname}@certiva.internal"
            user = create_user(
                db=auth_db,
                email=email,
                password=pw,
                full_name=entry.name,
                role="auditor",
                auditor_id=auditor.id,
                username=uname,
            )

            created.append({
                "index":      i,
                "name":       entry.name,
                "username":   uname,
                "password":   pw,
                "email":      email,
                "auditor_id": auditor.id,
                "user_id":    user.id,
            })
            logger.info("[BulkImport] Created auditor %s (username=%s)", entry.name, uname)

        except Exception as exc:
            logger.exception("[BulkImport] Failed for %s: %s", entry.name, exc)
            errors.append({"index": i, "name": entry.name, "reason": str(exc)})

    return {
        "summary": {
            "total":   len(payload.auditors),
            "created": len(created),
            "skipped": len(skipped),
            "errors":  len(errors),
        },
        "credentials": created,   # full list — save this immediately
        "errors": errors,
    }


@router.delete("/purge-all")
def purge_all_auditors(
    db: Session = Depends(get_db),
    auth_db: Session = Depends(get_auth_db),
    _: PlatformUser = Depends(require_admin),
):
    """
    Delete ALL auditor records and their linked portal accounts.
    Admin-only. Use before a clean re-import.
    """
    from auditors.models import Auditor as AuditorModel
    from auth.db_models import PlatformUser as PU

    existing = db.query(AuditorModel).all()
    auditor_ids = {a.id for a in existing}
    deleted_users = auth_db.query(PU).filter(
        PU.auditor_id.in_(auditor_ids)
    ).delete(synchronize_session=False)
    auth_db.commit()
    deleted_auditors = db.query(AuditorModel).delete(synchronize_session=False)
    db.commit()
    return {
        "deleted_auditors": deleted_auditors,
        "deleted_users": deleted_users,
    }
```

### Required imports to add to `backend/api/routes/auditors.py`

The route uses `get_auth_db` (the auth database session). Add this import:

```python
from auth.db_models import get_db as get_auth_db
from auth.service import create_user
```

These may already exist in the file — check before adding.

---

## Part B — Frontend: JSON Import button on Admin → Auditors page

### File: `frontend/src/app/(app)/auditors/page.tsx`

This change adds a "JSON Import" button next to the existing "+ New auditor" button.
When clicked it opens a file picker (accepts `.json`), reads the file, and POSTs to
`/auditors/bulk-import-json` with `replace_all: true`. It then shows a result modal
with the credentials (name / username / password) which can be copied as CSV.

Find the page header section (the `<div>` with the "New auditor" button) and add
this component BEFORE the existing button:

```tsx
{/* JSON Bulk Import */}
<JsonImportButton />
```

Add the following component to the file (above the main page component):

```tsx
function JsonImportButton() {
  const [loading, setLoading]   = useState(false)
  const [result,  setResult]    = useState<null | { summary: Record<string,number>; credentials: Record<string,string>[]; errors: Record<string,unknown>[] }>(null)
  const [err,     setErr]       = useState<string | null>(null)
  const fileRef = useRef<HTMLInputElement>(null)
  const queryClient = useQueryClient()

  async function handleFile(e: React.ChangeEvent<HTMLInputElement>) {
    const file = e.target.files?.[0]
    if (!file) return
    setLoading(true); setErr(null); setResult(null)
    try {
      const text = await file.text()
      const auditors = JSON.parse(text)
      const res = await api.post('/auditors/bulk-import-json', {
        auditors,
        replace_all: true,
      })
      setResult(res.data)
      queryClient.invalidateQueries({ queryKey: ['auditors'] })
    } catch (e: unknown) {
      const detail = (e as { response?: { data?: { detail?: string } } })?.response?.data?.detail
      setErr(detail ?? 'Import failed.')
    } finally {
      setLoading(false)
      if (fileRef.current) fileRef.current.value = ''
    }
  }

  function downloadCredentials() {
    if (!result) return
    const header = 'full_name,username,password\n'
    const rows = result.credentials.map(c => `"${c.name}","${c.username}","${c.password}"`)
    const blob = new Blob([header + rows.join('\n')], { type: 'text/csv' })
    const url = URL.createObjectURL(blob)
    const a = document.createElement('a'); a.href = url; a.download = 'auditor_credentials.csv'; a.click()
    URL.revokeObjectURL(url)
  }

  return (
    <>
      <input ref={fileRef} type="file" accept=".json" className="hidden" onChange={handleFile} />
      <button
        type="button"
        onClick={() => fileRef.current?.click()}
        disabled={loading}
        className="flex items-center gap-1 rounded-lg border border-certiva-primary px-3 py-2
          text-sm font-medium text-certiva-primary hover:bg-certiva-primary/5 disabled:opacity-50"
      >
        {loading ? <Loader2 size={14} className="animate-spin" /> : null}
        {loading ? 'Importing…' : 'Import JSON'}
      </button>

      {/* Result modal */}
      {(result || err) && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 p-4">
          <div className="w-full max-w-lg rounded-xl bg-white shadow-xl p-6">
            {err && (
              <div className="text-sm text-red-700 mb-4">{err}</div>
            )}
            {result && (
              <>
                <h2 className="text-base font-semibold text-gray-800 mb-3">Import complete</h2>
                <div className="grid grid-cols-3 gap-3 text-center text-xs mb-4">
                  <div className="rounded-lg bg-green-50 p-3">
                    <p className="text-2xl font-bold text-green-700">{result.summary.created}</p>
                    <p className="text-green-600">Created</p>
                  </div>
                  <div className="rounded-lg bg-gray-50 p-3">
                    <p className="text-2xl font-bold text-gray-600">{result.summary.skipped ?? 0}</p>
                    <p className="text-gray-500">Skipped</p>
                  </div>
                  <div className={`rounded-lg p-3 ${result.errors.length > 0 ? 'bg-red-50' : 'bg-gray-50'}`}>
                    <p className={`text-2xl font-bold ${result.errors.length > 0 ? 'text-red-600' : 'text-gray-600'}`}>{result.errors.length}</p>
                    <p className={result.errors.length > 0 ? 'text-red-500' : 'text-gray-500'}>Errors</p>
                  </div>
                </div>
                {result.errors.length > 0 && (
                  <div className="mb-3 max-h-24 overflow-y-auto rounded border border-red-100 bg-red-50 p-2 text-xs text-red-600">
                    {result.errors.map((e, i) => (
                      <p key={i}>{String(e.name)}: {String(e.reason)}</p>
                    ))}
                  </div>
                )}
                <p className="text-xs text-amber-700 bg-amber-50 border border-amber-200 rounded-lg px-3 py-2 mb-4">
                  Download the credentials CSV now — passwords cannot be recovered later.
                </p>
                <button
                  onClick={downloadCredentials}
                  className="mb-2 w-full rounded-lg bg-certiva-primary px-4 py-2 text-sm font-medium text-white hover:opacity-90"
                >
                  Download credentials CSV
                </button>
              </>
            )}
            <button
              onClick={() => { setResult(null); setErr(null) }}
              className="w-full rounded-lg border border-gray-200 px-4 py-2 text-sm text-gray-600 hover:bg-gray-50"
            >
              Close
            </button>
          </div>
        </div>
      )}
    </>
  )
}
```

Add `useRef` to the React import at the top if not already present:
```tsx
import { useState, useRef } from 'react'
```

---

## Part C — What NOT to change

- Do not modify `create_auditor()` in `auditors/service.py` — it already handles
  `StandardQualificationItem` with per-standard `ea_codes` correctly
- Do not modify `AuditorCreateSchema` or `StandardQualificationItem`
- Do not modify the existing CSV bulk import endpoint — keep it as-is
- Do not modify any calculator logic, audit set logic, or any other router

---

## How it will be used (after this prompt is pushed)

1. Go to **Admin → Auditors**
2. Click **Import JSON**
3. Select `auditors_import.json` from the BATUHAN folder
4. The endpoint runs `replace_all=true` — clears the bad CSV imports, reimports
   all 138 auditors with per-standard EA codes
5. A modal shows "138 created, 0 errors" with a **Download credentials CSV** button
6. Download the CSV — it has every auditor's username + password — save it immediately
