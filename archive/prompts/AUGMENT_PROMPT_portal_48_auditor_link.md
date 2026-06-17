# AUGMENT PROMPT — Portal 48: Link Auditor Record in Admin → Users

## Problem

The auditor portal (`/auditor/dashboard`) shows "0 audits assigned" for auditor
users even when they are scheduled as Lead Auditor on a stage.

Root cause: `_get_auditor_assignments` in `auditor_router.py` immediately returns
an empty list when `PlatformUser.auditor_id` is `None`:

```python
def _get_auditor_assignments(current_user: PlatformUser, db: Session):
    if not current_user.auditor_id:
        return []          # ← every auditor user created via UI hits this
```

`PlatformUser.auditor_id` is a soft FK to `auditors.auditors.id`.
`AuditSetStage.lead_auditor_id` stores the same auditors record ID.
Unless `platform_users.auditor_id` equals `audit_set_stages.lead_auditor_id`,
the assignment is invisible to the auditor portal.

The Admin → Users edit modal never included a UI field for `auditor_id`.
The backend and TypeScript types already support it — only the UI is missing.

---

## What to Change

### File: `frontend/src/app/(app)/admin/users/page.tsx`

Make two targeted changes to this file only. Do NOT touch any backend file.

---

### Change 1 — `EditUserModal`: add Auditor Record field

**Current `EditUserModal` state init (inside the `useEffect`):**
```typescript
setForm({ full_name: user.full_name, role: user.role, is_active: user.is_active })
```

**Replace with:**
```typescript
setForm({
  full_name:   user.full_name,
  role:        user.role,
  is_active:   user.is_active,
  auditor_id:  user.auditor_id ?? null,
})
```

---

**Add a `useQuery` for the auditors list inside `EditUserModal`, right after the
existing `useMutation` for `m`:**

```typescript
const { data: auditorList } = useQuery<AuditorSummary[]>({
  queryKey: ['auditors-list'],
  queryFn:  () => api.get<AuditorSummary[]>('/auditors/?active_only=false').then((r) => r.data),
  enabled:  !!user,   // only fetch when modal is open
})
```

Import `AuditorSummary` at the top of the file from `@/types`.

---

**Inside the form JSX, add the Auditor Record field AFTER the Role `<select>` and
BEFORE the Active `<Switch>` — but only render it when `form.role === 'auditor'`:**

```tsx
{form.role === 'auditor' && (
  <div>
    <label className={lblCls}>
      Auditor record <span className="font-normal text-gray-400">(links this login to an auditor profile)</span>
    </label>
    <select
      value={form.auditor_id ?? ''}
      onChange={(e) => setForm((f) => ({ ...f, auditor_id: e.target.value || null }))}
      className={inputCls}
    >
      <option value="">— not linked —</option>
      {(auditorList ?? []).map((a) => (
        <option key={a.id} value={a.id}>
          {a.name}
        </option>
      ))}
    </select>
    {form.auditor_id && (
      <p className="mt-1 text-xs text-gray-400">ID: {form.auditor_id}</p>
    )}
  </div>
)}
```

---

**In `handleSubmit`, include `auditor_id` in the mutation payload:**

Current:
```typescript
m.mutate({ ...form, full_name: form.full_name?.trim() })
```

The spread already covers it — no change needed here as long as `form.auditor_id`
is part of `form` state (which Change 1 ensures). Verify the mutation payload type
`AdminUserUpdatePayload` already has `auditor_id?: string | null` — it does.

---

### Change 2 — `CreateUserModal`: add Auditor Record field (same pattern)

Apply the same pattern to `CreateUserModal` for consistency — when `form.role === 'auditor'`,
show the auditor record dropdown.

**Add `useQuery` for auditors list inside `CreateUserModal`:**
```typescript
const { data: auditorList } = useQuery<AuditorSummary[]>({
  queryKey: ['auditors-list'],
  queryFn:  () => api.get<AuditorSummary[]>('/auditors/?active_only=false').then((r) => r.data),
  enabled:  open && form.role === 'auditor',
})
```

**Add the field JSX after the Role `<select>`:**
```tsx
{form.role === 'auditor' && (
  <div>
    <label className={lblCls}>Auditor record <span className="font-normal text-gray-400">(optional — links to auditor profile)</span></label>
    <select
      value={form.auditor_id ?? ''}
      onChange={(e) => setForm((f) => ({ ...f, auditor_id: e.target.value || null }))}
      className={inputCls}
    >
      <option value="">— not linked —</option>
      {(auditorList ?? []).map((a) => (
        <option key={a.id} value={a.id}>
          {a.name}
        </option>
      ))}
    </select>
  </div>
)}
```

`AdminUserCreatePayload` already has `auditor_id?: string | null` — no type changes needed.

---

## What NOT to Change

- Do NOT touch any backend file.
- Do NOT touch `auditor_router.py`, `auth/service.py`, or any other route.
- Do NOT touch `admin_router.py`.
- Do NOT add any new API endpoints.
- Do NOT touch `types/index.ts` — `AuditorSummary`, `AdminUser`, `AdminUserUpdatePayload`,
  and `AdminUserCreatePayload` all already have the right fields.

---

## Verification

1. Go to Admin → Users.
2. Click edit (pencil) on an auditor-role user.
3. A new "Auditor record" dropdown appears listing all auditors from the database.
4. Select the correct auditor (e.g. "Adil Murat Sayar") and click Save.
5. The auditor logs into their portal — `GET /auditor/my-assignments` now returns
   their assigned audit sets instead of an empty array.
6. Confirm with: check the user row — `auditor_id` column in `platform_users`
   should be set to the selected auditor's `id`.

---

## SQL Quick-Fix (run in Railway Postgres BEFORE deploying, to unblock the current test)

If you need to fix this immediately without waiting for a deploy:

```sql
-- Step 1: find the auditor record ID for Adil Murat Sayar
SELECT id, name FROM auditors WHERE name ILIKE '%adil%';

-- Step 2: find the platform user ID for his login
SELECT id, full_name, auditor_id FROM platform_users WHERE role = 'auditor';

-- Step 3: link them (replace the UUIDs with actual values from steps 1 & 2)
UPDATE platform_users
SET auditor_id = '<auditor_record_id_from_step1>'
WHERE id = '<platform_user_id_from_step2>';

-- Also check the stage to confirm lead_auditor_id matches
SELECT lead_auditor_id, lead_auditor_name
FROM audit_set_stages
WHERE audit_set_id = (
  SELECT id FROM audit_sets ORDER BY created_at DESC LIMIT 1
);
-- The lead_auditor_id here must equal the auditor_id you just set above.
```
