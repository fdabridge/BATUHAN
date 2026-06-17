# AUGMENT PROMPT — Portal 47d: FR.218 Auto-Advance Missing Commit

## Root Cause

In `backend/audit_set/signatures_router.py`, `sign_direct` calls `db.commit()`
on line 182, then calls `check_fr218_completion`. That function modifies
`audit_set.workflow_status` to `fr218_complete` and adds an `AuditSetStatusEvent`,
but never commits those changes. They are written to the SQLAlchemy session and
immediately lost when the request ends.

Result: FR.218 shows "Fully Signed ✓" in the UI, but `workflow_status` stays
at `fr218_in_progress` permanently. The "Schedule Stage 1" CTA never appears.

---

## Fix — `backend/audit_set/signatures_router.py`

Find the block at the end of `sign_direct` (after `db.commit()` on line ~182):

```python
# Portal 47 — if this was an FR.218 slot, check whether the document is
# now fully signed and auto-advance fr218_in_progress → fr218_complete.
if sig.document_type == "FR218":
    from audit_set.pipeline_triggers import check_fr218_completion
    check_fr218_completion(
        audit_set_id=audit_set_id,
        triggered_by=current_user.id,
        db=db,
    )
```

Replace with:

```python
# Portal 47 — if this was an FR.218 slot, check whether the document is
# now fully signed and auto-advance fr218_in_progress → fr218_complete.
if sig.document_type == "FR218":
    from audit_set.pipeline_triggers import check_fr218_completion
    advanced = check_fr218_completion(
        audit_set_id=audit_set_id,
        triggered_by=current_user.id,
        db=db,
    )
    if advanced:
        db.commit()  # commit the fr218_complete status change
```

---

## Also fix — `backend/audit_set/pipeline_triggers.py`

`check_fr218_completion` is also called from `main.py` (startup backfill) and
potentially other paths. Make it self-committing so callers don't have to
remember to commit manually. Add `db.commit()` inside the function before
returning True:

```python
def check_fr218_completion(
    audit_set_id: str, triggered_by: str, db: Session,
    effective_ts: Optional[datetime] = None,
) -> bool:
    audit_set = db.query(AuditSet).filter_by(id=audit_set_id).first()
    if not audit_set or audit_set.workflow_status != "fr218_in_progress":
        return False
    if not _all_fr218_signed(audit_set_id, db):
        return False

    audit_set.workflow_status = "fr218_complete"
    db.add(AuditSetStatusEvent(
        audit_set_id=audit_set_id,
        from_status="fr218_in_progress",
        to_status="fr218_complete",
        triggered_by=triggered_by,
        triggered_at=effective_ts or datetime.utcnow(),
        notes="Auto-advanced: FR.218 fully signed by all required parties",
    ))
    db.commit()   # ← ADD THIS LINE
    return True
```

Then remove the `if advanced: db.commit()` wrapper in `signatures_router.py`
and keep it as the original one-liner call (since the function now commits itself):

```python
if sig.document_type == "FR218":
    from audit_set.pipeline_triggers import check_fr218_completion
    check_fr218_completion(
        audit_set_id=audit_set_id,
        triggered_by=current_user.id,
        db=db,
    )
```

---

## What NOT to change

- Do not touch `InternalApprovalsSection.tsx`
- Do not touch `PendingSignaturesWidget.tsx`
- Do not touch any other router

---

## Verification

1. Create a fresh audit set (or use one at `fr218_in_progress`)
2. Sign the Planning Officer FR.218 slot
3. Sign the Certification Manager FR.218 slot
4. Immediately after CM signs → `workflow_status` in DB must be `fr218_complete`
5. Status bar advances to "FR.218 ✓" (step 6) and shows "Schedule Stage 1" CTA
6. No manual Postgres intervention required
