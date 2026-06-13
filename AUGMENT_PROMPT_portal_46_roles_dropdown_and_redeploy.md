# AUGMENT PROMPT — Portal 46: Add Missing Roles to Admin Users Dropdown + Redeploy

## Fix — Frontend: Admin Users page roles dropdown

File: `frontend/src/app/(app)/admin/users/page.tsx`

Add `certification_manager` to the roles dropdown array (same place Portal 42 added `gm`):

```tsx
{ value: 'certification_manager', label: 'Certification Manager' }
```

Also verify these roles are all present in the dropdown. Add any that are missing:

| value | label |
|-------|-------|
| `admin` | Admin |
| `planner` | Planning Officer |
| `gm` | General Manager |
| `certification_manager` | Certification Manager |
| `auditor` | Auditor |
| `client` | Client |

Also add `certification_manager` to `VALID_ROLES` in `backend/auth/schemas.py` if it is
not already there (check first — Portal 42 may have added it).

## Trigger redeploy

Portal 45 (commit e05cc2e) is on `origin/main` but did not trigger a Railway redeploy.
Make a trivial commit (e.g. add a comment to any file) and push to `origin/main` to
force Railway to pick up Portal 45 + Portal 46 together.

## Verification

1. Admin → Users → Add User → roles dropdown shows "Certification Manager" as an option
2. Create a user with role Certification Manager — it saves successfully
3. Railway shows a new deployment triggered by this push
