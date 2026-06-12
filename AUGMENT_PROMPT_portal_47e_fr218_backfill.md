# AUGMENT PROMPT — Portal 47e: Add fr218_in_progress Backfill to main.py

## Root Cause

`main.py` startup backfill only handles `agreement_signed → fr218_in_progress`.
It does NOT fix audit sets already stuck at `fr218_in_progress` where all FR.218
slots are signed but the status never advanced (because Portal 47d's `db.commit()`
fix only applies to NEW signings going forward).

Result: any audit set signed before Portal 47d was deployed remains stuck at
`fr218_in_progress` after restart. Admin must use manual SQL to unblock it.

---

## Fix — `backend/main.py`

Find the existing Portal 47 backfill block (which ends with something like):

```python
        if backfilled:
            logger.info("[BATUHAN] Portal 47 backfill: %d audit set(s) advanced to fr218_in_progress", backfilled)
    finally:
        adb.close()
except Exception as exc:
    logger.warning("[BATUHAN] Portal 47 backfill skipped: %s", exc)
```

Immediately AFTER the `adb.close()` / `except` block for the existing Portal 47
backfill (so as a second, independent try/except block), add:

```python
# Portal 47e — backfill: any audit set at fr218_in_progress where all required
# FR.218 slots are already signed should advance to fr218_complete.
try:
    from audit_set.db_models import (
        AuditSet, AuditDocumentSignature, AuditSetStatusEvent,
        get_db as audit_get_db,
    )
    from datetime import datetime as _dt
    adb2 = next(audit_get_db())
    try:
        stuck218 = adb2.query(AuditSet).filter_by(workflow_status="fr218_in_progress").all()
        completed = 0
        for aset in stuck218:
            total = (
                adb2.query(AuditDocumentSignature)
                .filter_by(audit_set_id=aset.id, document_type="FR218", required=True)
                .count()
            )
            unsigned = (
                adb2.query(AuditDocumentSignature)
                .filter_by(audit_set_id=aset.id, document_type="FR218", required=True)
                .filter(AuditDocumentSignature.signed_at.is_(None))
                .count()
            )
            if total > 0 and unsigned == 0:
                aset.workflow_status = "fr218_complete"
                adb2.add(AuditSetStatusEvent(
                    audit_set_id=aset.id,
                    from_status="fr218_in_progress",
                    to_status="fr218_complete",
                    triggered_by="system_backfill",
                    triggered_at=_dt.utcnow(),
                    notes="Portal 47e backfill: all FR.218 slots were signed, advancing to fr218_complete",
                ))
                completed += 1
        adb2.commit()
        if completed:
            logger.info(
                "[BATUHAN] Portal 47e backfill: %d audit set(s) advanced to fr218_complete",
                completed,
            )
    finally:
        adb2.close()
except Exception as exc:
    logger.warning("[BATUHAN] Portal 47e backfill skipped: %s", exc)
```

---

## What NOT to change

- Do not touch `pipeline_triggers.py` — Portal 47d already made `check_fr218_completion` self-committing.
- Do not touch `signatures_router.py`.
- Do not touch any frontend file.
- Do not modify the existing Portal 47 backfill block — add the new block after it.

---

## Verification

1. Deploy to Railway.
2. On startup, the new backfill block runs.
3. Any audit set at `fr218_in_progress` with all FR.218 slots signed is advanced
   to `fr218_complete`.
4. Check in Railway Postgres:
   ```sql
   SELECT id, plan_number, workflow_status
   FROM audit_sets
   WHERE workflow_status IN ('fr218_in_progress', 'fr218_complete')
   ORDER BY plan_number DESC;
   ```
5. Status bar on that audit set now shows "Schedule Stage 1" CTA.
6. No manual SQL intervention required.
