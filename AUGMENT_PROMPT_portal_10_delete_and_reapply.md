# AUGMENT PROMPT — Portal 10: Delete Plans + Re-application Fix

## Context

Certiva — FastAPI backend + Next.js 14 App Router frontend. Same repo.
DO NOT BREAK THE EXISTING PORTAL. Every change is additive.

Two problems to fix:

1. There is no way to delete an AuditSet (plan) from the CB portal. This blocks testing because once a plan is created the email used is locked out.
2. The `/apply` form returns 409 "account already exists" even after the linked AuditSet has been deleted. Need to allow re-application when the previous audit set is gone.

---

## Fix 1 — Backend: DELETE /audit-sets/{id}

Add to `backend/audit_set/workflow_router.py` (or create a new route in the main audit_set router — your call, but prefer workflow_router.py since it already imports the needed models):

```python
@router.delete("/{audit_set_id}")
def delete_audit_set(
    audit_set_id: str,
    db: Session = Depends(get_db),
    auth_db: Session = Depends(get_auth_db),
    current_user: PlatformUser = Depends(get_current_user),
):
    """
    Hard-delete an AuditSet and its linked client PlatformUser (if any).
    Restricted to admin and planner roles.
    Cascade: audit_set_stages, audit_set_status_events, audit_set_messages,
             audit_set_shared_documents all have ON DELETE CASCADE — Postgres handles them.
    """
    if current_user.role not in {"admin", "planner"}:
        raise HTTPException(403, "Not authorized")

    audit_set = db.query(AuditSet).filter_by(id=audit_set_id).first()
    if not audit_set:
        raise HTTPException(404, "Audit set not found")

    # Delete the linked client PlatformUser in the auth DB (frees up the email)
    client_user = auth_db.query(PlatformUser).filter_by(
        audit_set_id=audit_set_id, role="client"
    ).first()
    if client_user:
        auth_db.delete(client_user)
        auth_db.commit()

    # Hard-delete the audit set (cascade handles child rows)
    db.delete(audit_set)
    db.commit()

    return {"deleted": True, "id": audit_set_id}
```

**Imports needed** (check what's already imported in the file and add only what's missing):
- `AuditSet` from `audit_set.db_models`
- `PlatformUser` from `auth.db_models`
- `get_auth_db` from `auth.db_models`

Make sure `get_auth_db` is added as a Depends parameter. Look at how `apply_router.py` imports it — use the same pattern.

---

## Fix 2 — Backend: apply_router.py re-application logic

In `backend/audit_set/apply_router.py`, replace the existing email-check block:

**Current code (around line 69–74):**
```python
# Check email not already registered
existing = auth_db.query(PlatformUser).filter_by(
    email=payload.representative_email
).first()
if existing:
    raise HTTPException(409, "An account with this email already exists. Please log in.")
```

**Replace with:**
```python
# Check email not already registered
existing = auth_db.query(PlatformUser).filter_by(
    email=payload.representative_email
).first()
if existing:
    # Allow re-application only if the linked audit set has been deleted
    # (common during testing / cancelled applications)
    if existing.audit_set_id:
        linked_set = audit_db.query(AuditSet).filter_by(id=existing.audit_set_id).first()
        if linked_set:
            raise HTTPException(
                409,
                "An account with this email already exists. "
                "Please log in to your client portal, or contact IFC Global if you need help."
            )
    # Stale user with no valid audit set — clean it up and allow re-registration
    auth_db.delete(existing)
    auth_db.commit()
```

This means: if someone's audit set was deleted by the CB (Fix 1 above), the stale PlatformUser record is automatically cleaned up on their next application attempt.

---

## Fix 3 — Frontend CB: Delete button on clients list + client detail

### A) Clients list page: `frontend/src/app/(app)/clients/page.tsx`

Add a delete icon button on each row (admin/planner only — check `useAuth().user?.role`).

- Show a trash icon (use `Trash2` from `lucide-react`) at the far right of each client row
- On click: show a `window.confirm("Delete plan #XXXX for Company Name? This cannot be undone.")` — if confirmed, call `DELETE /audit-sets/{id}`
- On success: remove the row from local state (optimistic) or re-fetch the list
- On error: show an inline error toast or alert

Only show the trash icon for users with role `admin` or `planner`.

### B) Client detail page: `frontend/src/app/(app)/clients/[id]/page.tsx`

Add a "Delete Plan" button in the header action row (next to "Download audit package" and "Generate AI report").

- Style: small button with red text and a border (`border-red-200 text-red-600 hover:bg-red-50`)
- Include `Trash2` icon from lucide-react
- On click: `window.confirm("Delete plan #XXXX? This will also remove the client's portal account. This cannot be undone.")`
- On confirm: call `DELETE /audit-sets/{id}`, then `router.push('/clients')` on success
- Only render for role `admin` or `planner`

---

## Verification checklist

1. `python3 -m py_compile backend/audit_set/workflow_router.py` (or whichever file gets the DELETE endpoint)
2. `python3 -m py_compile backend/audit_set/apply_router.py`
3. `cd frontend && npx tsc --noEmit`
4. Confirm `DELETE /audit-sets/{id}` appears in `/docs`
5. Confirm deleting an audit set via the UI removes the row from the clients list
6. Confirm that after deletion, submitting `/apply` with the same email succeeds and creates a fresh account
7. Commit and push to main

## Constraint reminder
DO NOT remove or modify any existing endpoint, component, or page beyond what is specified here.
The delete functionality is additive — new button, new endpoint, no changes to existing flows.
