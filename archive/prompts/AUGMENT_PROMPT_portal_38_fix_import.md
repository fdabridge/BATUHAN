# AUGMENT PROMPT — Portal 38 Fix: Bulk JSON Import Failing

## Problem

`POST /auditors/bulk-import-json` (added in Portal 38) returns a 500 error when called.
The frontend shows "Import failed." because the error has no `detail` field (500, not 422).

## Most Likely Root Causes

### 1. `create_user()` in `auth/service.py` doesn't accept `auditor_id`

The endpoint calls:
```python
user = create_user(
    db=auth_db,
    email=email,
    password=pw,
    full_name=entry.name,
    role="auditor",
    auditor_id=auditor.id,
    username=uname,
)
```

If `create_user()` signature does NOT have `auditor_id` as a parameter, this throws `TypeError` → 500.

**Fix:** Add `auditor_id: Optional[int] = None` to `create_user()` and pass it through to the `PlatformUser(...)` constructor.

### 2. `replace_all` delete may fail due to cascade

The purge code:
```python
auth_db.query(PU).filter(PU.auditor_id.in_(auditor_ids)).delete(synchronize_session=False)
auth_db.commit()
db.query(AuditorModel).delete(synchronize_session=False)
db.commit()
```

If `AuditorStandardQualification` or other related tables have a foreign key to `Auditor` without `CASCADE DELETE`, the `AuditorModel` bulk delete will fail with an integrity error.

**Fix:** Before deleting Auditors, also delete their qualifications:
```python
from auditors.models import AuditorStandardQualification
db.query(AuditorStandardQualification).filter(
    AuditorStandardQualification.auditor_id.in_(auditor_ids)
).delete(synchronize_session=False)
db.commit()
db.query(AuditorModel).delete(synchronize_session=False)
db.commit()
```

---

## Changes Required

### File: `backend/auth/service.py` — `create_user()` function

Add `auditor_id: Optional[int] = None` to the function signature, and include it in the `PlatformUser(...)` constructor call. Example:

```python
# BEFORE (approximate — check actual code)
def create_user(db, email, password, full_name, role, username=None):
    user = PlatformUser(
        email=email,
        username=username,
        password_hash=...,
        full_name=full_name,
        role=role,
    )

# AFTER
def create_user(db, email, password, full_name, role, username=None, auditor_id=None, audit_set_id=None):
    user = PlatformUser(
        email=email,
        username=username,
        password_hash=...,
        full_name=full_name,
        role=role,
        auditor_id=auditor_id,
        audit_set_id=audit_set_id,
    )
```

> Check the actual current signature and add only what's missing. Don't remove existing params.

### File: `backend/api/routes/auditors.py` — `bulk_import_json` endpoint

Add the qualification cascade delete BEFORE deleting auditors in the `replace_all` block:

```python
if payload.replace_all:
    from auditors.models import AuditorStandardQualification
    existing_auditors = db.query(AuditorModel).all()
    auditor_ids = [a.id for a in existing_auditors]

    # Delete linked PlatformUser accounts
    if auditor_ids:
        auth_db.query(PU).filter(
            PU.auditor_id.in_(auditor_ids)
        ).delete(synchronize_session=False)
        auth_db.commit()

        # Delete standard qualifications first (FK constraint)
        db.query(AuditorStandardQualification).filter(
            AuditorStandardQualification.auditor_id.in_(auditor_ids)
        ).delete(synchronize_session=False)
        db.commit()

    # Now delete the auditors themselves
    db.query(AuditorModel).delete(synchronize_session=False)
    db.commit()
    logger.info("[BulkImport] Purged all existing auditors and qualifications")
```

Also apply the same cascade fix to the `DELETE /auditors/purge-all` endpoint.

---

## What NOT to change

- Do not modify `AuditorCreateSchema` or `StandardQualificationItem`
- Do not modify `create_auditor()` in `auditors/service.py`
- Do not touch any other endpoint or router
