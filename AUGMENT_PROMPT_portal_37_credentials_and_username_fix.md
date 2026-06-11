# AUGMENT PROMPT — Portal 37: Credentials on Screen + Username Fix

## Context

Two small but user-facing bugs to fix. Both stem from the same root cause: when
a client account is created via the portal application endpoint (`POST /apply`),
the `username` field on `PlatformUser` is never set, and the temporary password
is never returned in the API response.

---

## Bug 1 — Credentials must be shown on screen after applying

**Symptom:** After submitting the application form (`/apply`), the success screen
says "Login credentials have been sent to your email address." The email delivery
is unreliable and considered secondary. The user needs to see their username and
temporary password right on the success screen immediately after submitting.

**Root cause:** `backend/audit_set/apply_router.py` currently returns:

```python
return {
    "success": True,
    "message": "Application submitted successfully. Check your email for login credentials.",
    "plan_number": plan_number,
}
```

The `temp_password` variable exists in that function but is never included in the
response. The frontend (`frontend/src/app/apply/page.tsx`) does not capture any
credentials from the response — it just does `setSuccess(true)` and the success
screen hard-codes "Login credentials have been sent to your email address."

---

## Bug 2 — Username shows "—" in admin users panel

**Symptom:** In Admin → Users (`/admin/users`), the Username column shows "—"
for every client account created via the portal.

**Root cause:** `apply_router.py` creates `PlatformUser` without setting the
`username` field:

```python
user = PlatformUser(
    email=payload.representative_email,
    password_hash=pwd_ctx.hash(temp_password),
    full_name=payload.representative_name,
    role="client",
    is_active=True,
    audit_set_id=audit_set.id,
    # ← username is never set here
)
```

`PlatformUser.username` is nullable (`Column(String, nullable=True)`), so it
stores `None`. The admin table renders `u.username ?? '—'` which becomes "—".

For client portal users, the email address IS the login identifier. The
`username` should be set to the same value as `email` at account-creation time.

---

## Changes Required

### 1. `backend/audit_set/apply_router.py`

**Two changes in the same function `submit_application()`:**

**Change A — set `username` on PlatformUser:**

```python
# BEFORE
user = PlatformUser(
    email=payload.representative_email,
    password_hash=pwd_ctx.hash(temp_password),
    full_name=payload.representative_name,
    role="client",
    is_active=True,
    audit_set_id=audit_set.id,
)

# AFTER
user = PlatformUser(
    email=payload.representative_email,
    username=payload.representative_email,   # ← ADD THIS LINE
    password_hash=pwd_ctx.hash(temp_password),
    full_name=payload.representative_name,
    role="client",
    is_active=True,
    audit_set_id=audit_set.id,
)
```

**Change B — include credentials in the return dict:**

```python
# BEFORE
return {
    "success": True,
    "message": "Application submitted successfully. Check your email for login credentials.",
    "plan_number": plan_number,
}

# AFTER
return {
    "success":      True,
    "message":      "Application submitted successfully.",
    "plan_number":  plan_number,
    "username":     payload.representative_email,
    "temp_password": temp_password,
}
```

> Do NOT remove the `send_client_welcome(...)` call. Email delivery stays as a
> backup. Just also return the credentials in the response.

---

### 2. `frontend/src/app/apply/page.tsx`

**Three changes:**

**Change A — Add a `credentials` state alongside `success`:**

Find the existing state declarations near the top of `ApplyPage`:

```tsx
const [success, setSuccess] = useState(false)
const [error, setError]     = useState('')
```

Replace with:

```tsx
const [success, setSuccess]         = useState(false)
const [credentials, setCredentials] = useState<{ username: string; password: string } | null>(null)
const [error, setError]             = useState('')
```

**Change B — Capture credentials from the API response:**

Find the `handleSubmit` function. Currently it reads:

```tsx
await axios.post(`${apiBase}/apply`, { ... })
setSuccess(true)
```

Replace those two lines with:

```tsx
const res = await axios.post(`${apiBase}/apply`, { ... })
setCredentials({
  username: res.data.username   || payload.representative_email,
  password: res.data.temp_password || '',
})
setSuccess(true)
```

Note: the object passed to `axios.post` is the same large payload already there.
Only the two lines AFTER it change — replace `await axios.post(...)` (currently
discarding the return value) with `const res = await axios.post(...)`, and then
set credentials from `res.data`.

**Change C — Redesign the success screen to display credentials prominently:**

Find the `if (success)` block (starts around line 207). Replace the entire block
with the following:

```tsx
if (success) {
  return (
    <div className="min-h-screen bg-gray-50 flex items-center justify-center p-6">
      <div className="bg-white rounded-xl shadow-sm border p-10 max-w-lg w-full">
        {/* Header */}
        <div className="flex flex-col items-center text-center mb-8">
          <div className="w-14 h-14 bg-green-100 rounded-full flex items-center justify-center mb-4">
            <svg className="w-7 h-7 text-green-700" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M5 13l4 4L19 7" />
            </svg>
          </div>
          <h2 className="text-xl font-bold text-gray-900 mb-1">Application Submitted</h2>
          <p className="text-sm text-gray-500">
            Thank you. Your application is under review.
          </p>
        </div>

        {/* Credentials box */}
        {credentials && (
          <div className="mb-8 rounded-xl border-2 border-amber-200 bg-amber-50 p-5">
            <div className="flex items-center gap-2 mb-3">
              <svg className="w-4 h-4 text-amber-600 shrink-0" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2}
                  d="M12 9v2m0 4h.01M10.29 3.86L1.82 18a2 2 0 001.71 3h16.94a2 2 0 001.71-3L13.71 3.86a2 2 0 00-3.42 0z" />
              </svg>
              <p className="text-sm font-semibold text-amber-800">
                Save your login credentials — you won&rsquo;t see them again
              </p>
            </div>

            <div className="space-y-3">
              {/* Username row */}
              <div className="flex items-center justify-between gap-3 rounded-lg bg-white border border-amber-200 px-3 py-2.5">
                <div className="min-w-0">
                  <p className="text-[11px] font-medium text-gray-400 uppercase tracking-wide mb-0.5">Username</p>
                  <p className="text-sm font-mono text-gray-800 truncate">{credentials.username}</p>
                </div>
                <button
                  type="button"
                  onClick={() => navigator.clipboard.writeText(credentials.username)}
                  className="shrink-0 text-xs text-amber-700 hover:text-amber-900 font-medium border border-amber-300 rounded px-2 py-1"
                >
                  Copy
                </button>
              </div>

              {/* Password row */}
              <div className="flex items-center justify-between gap-3 rounded-lg bg-white border border-amber-200 px-3 py-2.5">
                <div className="min-w-0">
                  <p className="text-[11px] font-medium text-gray-400 uppercase tracking-wide mb-0.5">Temporary Password</p>
                  <p className="text-sm font-mono text-gray-800 tracking-widest">{credentials.password}</p>
                </div>
                <button
                  type="button"
                  onClick={() => navigator.clipboard.writeText(credentials.password)}
                  className="shrink-0 text-xs text-amber-700 hover:text-amber-900 font-medium border border-amber-300 rounded px-2 py-1"
                >
                  Copy
                </button>
              </div>
            </div>

            <p className="mt-3 text-xs text-amber-700">
              These credentials have also been sent to your email address as a backup.
            </p>
          </div>
        )}

        <a
          href="/login"
          className="block w-full text-center bg-[#1A4731] text-white px-6 py-2.5 rounded-lg text-sm font-medium hover:opacity-90"
        >
          Go to Portal Login
        </a>
      </div>
    </div>
  )
}
```

> The credentials state is typed as `{ username: string; password: string } | null`.
> If for any reason the API didn't return them (defensive), the amber credentials
> box simply doesn't render (`{credentials && (...)}`) and the page still works.

---

## Files Changed Summary

| File | Change |
|------|--------|
| `backend/audit_set/apply_router.py` | Add `username=payload.representative_email` to `PlatformUser(...)` constructor; add `username` and `temp_password` fields to the return dict |
| `frontend/src/app/apply/page.tsx` | Add `credentials` state; capture `res.data.username` + `res.data.temp_password` on submit; replace success screen with prominent credentials display |

---

## What NOT to change

- Do not modify `apply_router.py`'s `send_client_welcome(...)` call — email stays as backup
- Do not modify the admin users page — it already renders `u.username ?? '—'` correctly, it just needs the backend to supply a value
- Do not touch any other router, service, schema, or DB migration — `username` column already exists in `platform_users` (`_safe_add_column_auth` already handles it)
- Do not modify `clients/[id]/page.tsx` — the detail page doesn't show a username field
