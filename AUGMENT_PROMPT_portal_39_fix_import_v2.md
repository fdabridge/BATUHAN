# AUGMENT PROMPT — Portal 38 Fix v2: Complete Cascade Delete for Bulk JSON Import

## Problem

`POST /auditors/bulk-import-json` still returns 500 when `replace_all: true`.

The previous fix (fc89124) only deleted `AuditorStandardQualification` before deleting auditors. There are **6 more child tables** with FK references to the `auditors` table that must also be deleted first, or the bulk DELETE throws an FK constraint violation.

---

## Changes Required

### File: `backend/api/routes/auditors.py`

Find the `replace_all` block inside the `bulk_import_json` endpoint. Replace it with the following — delete ALL child tables in the correct order before deleting auditors.

The existing auditor IDs must be collected first, then all child records for those IDs must be deleted, then the auditors themselves.

```python
if payload.replace_all:
    # Collect all existing auditor IDs
    existing_auditors = db.query(AuditorModel).all()
    auditor_ids = [a.id for a in existing_auditors]

    if auditor_ids:
        # 1. Delete linked PlatformUser accounts in auth DB
        auth_db.query(PU).filter(
            PU.auditor_id.in_(auditor_ids)
        ).delete(synchronize_session=False)
        auth_db.commit()

        # 2. Delete all child tables in dependency order (FK → auditors.id)
        from auditors.models import (
            AuditorStandardQualification,
            AuditorEducation,
            AuditorLanguage,
            AuditorWorkExperience,
            AuditorTrainingRecord,
            AuditorAuditLog,
            AuditorWitnessRecord,
        )

        db.query(AuditorStandardQualification).filter(
            AuditorStandardQualification.auditor_id.in_(auditor_ids)
        ).delete(synchronize_session=False)

        db.query(AuditorEducation).filter(
            AuditorEducation.auditor_id.in_(auditor_ids)
        ).delete(synchronize_session=False)

        db.query(AuditorLanguage).filter(
            AuditorLanguage.auditor_id.in_(auditor_ids)
        ).delete(synchronize_session=False)

        db.query(AuditorWorkExperience).filter(
            AuditorWorkExperience.auditor_id.in_(auditor_ids)
        ).delete(synchronize_session=False)

        db.query(AuditorTrainingRecord).filter(
            AuditorTrainingRecord.auditor_id.in_(auditor_ids)
        ).delete(synchronize_session=False)

        db.query(AuditorAuditLog).filter(
            AuditorAuditLog.auditor_id.in_(auditor_ids)
        ).delete(synchronize_session=False)

        db.query(AuditorWitnessRecord).filter(
            AuditorWitnessRecord.auditor_id.in_(auditor_ids)
        ).delete(synchronize_session=False)

        db.commit()

    # 3. Now safe to delete all auditors
    db.query(AuditorModel).delete(synchronize_session=False)
    db.commit()
    logger.info("[BulkImport] Purged all existing auditors and all child records")
```

> **Important:** The model class names above (`AuditorEducation`, `AuditorLanguage`, etc.) are what I expect based on convention. Check the actual class names in `backend/auditors/models.py` and use whatever names are actually defined there. If any of these models don't exist yet (table exists but no ORM model), use a raw SQL DELETE instead:
> ```python
> db.execute(text("DELETE FROM auditor_education WHERE auditor_id = ANY(:ids)"), {"ids": auditor_ids})
> ```

---

Apply the **exact same child-table deletion logic** to the `DELETE /auditors/purge-all` endpoint as well.

---

## What NOT to change

- Do not touch `AuditorCreateSchema`, `StandardQualificationItem`, or `create_auditor()`
- Do not modify any other endpoint or router
- Do not modify the frontend

---

## How to verify

After deploying, call `POST /auditors/bulk-import-json` with a small test payload (3–5 auditors, `replace_all: true`). It should return 200 with a `results` array. If it still errors, paste the Railway web service logs (not the Celery worker logs) here so we can see the actual traceback.

---

## Separate issue (do NOT fix in this prompt)

The Celery worker service is crash-looping with:
```
ModuleNotFoundError: No module named 'storage.file_store'
```
This is a separate problem in `jobs/state.py`. Do not touch this — it does not affect the auditor import endpoint.
