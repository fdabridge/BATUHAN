# Portal 88 — ISO 13485 surveillance "failed to release": fix unprotected email calls + add release logging

## Root cause

The `release_document` endpoint (`documents_router.py`) has no failure path specific to ISO 13485 or any surveillance type. The endpoint itself always returns 200 for valid `surveillance_notification` releases.

**The actual failure site is `workflow_router.update_workflow_status`.**

When the Planner clicks "Approve Application" (transitioning the set from `pending_review → in_planning`), the endpoint:

1. Validates and commits the status change (`db.commit()` at line 383) — **permanently written to DB**
2. Calls `fire_phase_triggers(...)` — safe, no-op for this transition
3. **Then calls `send_client_status_update(...)` with NO try/except (lines 401–406)**

```python
# workflow_router.py — current code (BROKEN)
client_user = auth_db.query(PlatformUser).filter_by(
    audit_set_id=audit_set_id, role="client",
).first()
if client_user:
    send_client_status_update(          # ← bare call, no try/except
        to=client_user.email,
        full_name=client_user.full_name,
        new_status=to_status,
        notes=payload.notes or "",
    )
```

If the Resend email service is unavailable, misconfigured, or the client email address is invalid, `send_client_status_update` raises an exception. FastAPI returns **500 Internal Server Error** to the frontend. The DB commit already happened — the workflow_status IS `in_planning` — but the frontend mutation sees a 500 and shows a failure.

**Why the user sees "Failed to release document.":**

The Planner sees the Approve button fail. In the surveillance workflow, "releasing" the FR.234 notification requires the set to first be in `in_planning`. Because the approval step failed (from the Planner's perspective), the Planner is confused about the state and may retry, or attempt to release the notification while believing the set is not yet approved. The "Failed to release document." string is the generic catch-all from `SharedDocumentsSection.tsx` line 157 — it fires whenever the release POST returns non-200 OR whenever the subsequent `load()` call (GET /documents) fails.

**Second unprotected email call — `apply_router.py`:**

The same pattern exists when a surveillance set is created via the portal application form:

```python
# apply_router.py — current code (BROKEN)
# The comment says "non-blocking" but the call is not actually wrapped in try/except
send_client_welcome(             # ← bare call, no try/except
    to=payload.representative_email,
    full_name=payload.representative_name,
    temp_password=temp_password,
    audit_set_id=audit_set.id,
)
```

If the welcome email throws, the `/apply` endpoint returns 500 even though both DB commits succeeded. The planner or client would see a failure on submission.

**Note:** `_auto_advance_workflow` in `documents_router.py` already wraps `send_client_status_update` correctly. Only `workflow_router.update_workflow_status` and `apply_router.py` have the unprotected pattern.

---

## The fix

### Fix 1 — `backend/audit_set/workflow_router.py`

Find the `send_client_status_update` call near the end of `update_workflow_status` (lines ~397–406):

Current:
```python
    client_user = auth_db.query(PlatformUser).filter_by(
        audit_set_id=audit_set_id, role="client",
    ).first()
    if client_user:
        send_client_status_update(
            to=client_user.email,
            full_name=client_user.full_name,
            new_status=to_status,
            notes=payload.notes or "",
        )

    return {"workflow_status": to_status, "updated": True}
```

Replace with:
```python
    client_user = auth_db.query(PlatformUser).filter_by(
        audit_set_id=audit_set_id, role="client",
    ).first()
    if client_user:
        try:
            send_client_status_update(
                to=client_user.email,
                full_name=client_user.full_name,
                new_status=to_status,
                notes=payload.notes or "",
            )
        except Exception:
            # Email is best-effort — a Resend outage or invalid address must not
            # roll back a committed status transition.
            pass

    return {"workflow_status": to_status, "updated": True}
```

---

### Fix 2 — `backend/audit_set/apply_router.py`

Find the `send_client_welcome` call near the end of the `/apply` POST handler (lines ~241–247):

Current:
```python
    # Send welcome email (non-blocking — failure doesn't roll back)
    send_client_welcome(
        to=payload.representative_email,
        full_name=payload.representative_name,
        temp_password=temp_password,
        audit_set_id=audit_set.id,
    )

    return {
        "success":      True,
        ...
    }
```

Replace with:
```python
    # Send welcome email — best-effort; a Resend outage must not fail the submission.
    try:
        send_client_welcome(
            to=payload.representative_email,
            full_name=payload.representative_name,
            temp_password=temp_password,
            audit_set_id=audit_set.id,
        )
    except Exception:
        pass

    return {
        "success":      True,
        ...
    }
```

---

### Fix 3 — `backend/audit_set/documents_router.py` — add error logging to `release_document`

Wrap the entire body of the `release_document` endpoint in a top-level try/except that logs unexpected 500s before re-raising. This ensures Railway logs capture the traceback if there is ever a genuine backend error on release.

Add this import if not already present:
```python
import logging
logger = logging.getLogger(__name__)
```

In the `release_document` function, after the initial role/type/auditset checks (after line 266), wrap the remainder in:
```python
    try:
        # ... existing file write + DB + workflow advance code ...
    except HTTPException:
        raise  # let FastAPI handle expected 4xx
    except Exception as exc:
        logger.exception(
            "[release_document] Unexpected error for audit_set_id=%s document_type=%s: %s",
            audit_set_id, document_type, exc,
        )
        raise
```

**Important:** This is a logging wrapper only — do NOT swallow exceptions. The `raise` re-raises the original exception so FastAPI still returns 500. The goal is to get a stack trace in Railway logs so the exact failure can be identified if it persists.

---

## What this does NOT change

- `_auto_advance_workflow` — already has try/except around the email call. No change.
- The actual `release_document` file upload and DB logic — unchanged.
- `fire_phase_triggers` for `notification_sent` — no-op, unchanged.
- The surveillance workflow flow (pending_review → in_planning → notification_sent) — logic unchanged.
- Any other email call sites — only the two bare calls listed above are fixed.

---

## How to verify the fix

1. On Railway, check the environment variable `RESEND_API_KEY` is set. If it is missing or expired, every email call throws — this explains why the approve step consistently fails.
2. After the fix, deploy and test: on a new surveillance set, click "Approve Application." Even if the email fails (e.g., invalid Resend key), the UI should now show success and the workflow should advance to `in_planning`.
3. Then release FR.234 from SharedDocumentsSection. Confirm it succeeds and the status advances to `notification_sent`.
4. Check Railway logs — if the logging wrapper in Fix 3 shows an exception after this deploy, that's the actual root cause for the release path. Address that separately.

---

## Commit message suggestion

```
Portal 88: wrap all bare email calls in try/except + add release_document logging

- workflow_router update_workflow_status: wrap send_client_status_update
  in try/except — a Resend outage was causing a 500 even though the DB
  commit already succeeded, leaving the workflow stuck from the Planner's POV
- apply_router: same fix for send_client_welcome — the comment said
  "non-blocking" but the call was not actually protected
- documents_router release_document: add logger.exception wrapper so any
  unexpected 500 on release is captured in Railway logs with a full traceback

Root cause: ISO 13485 surveillance "failed to release" — the Planner was
experiencing a 500 on the approve step (pending_review → in_planning),
which made them believe the release was failing. The DB was committed;
only the email was throwing.
```
