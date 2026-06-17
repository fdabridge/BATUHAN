# Portal 75 — Fix Stage 1 complete gate: FR.231 lives in AuditSetAuditReport, not AuditSetSharedDocument

## Root cause

`_assert_stage1_complete_gate` in `backend/audit_set/workflow_router.py` calls:

```python
stage1_reports = _stage_docs(
    db, audit_set_id, "stage1_report", "stage_1", include_null_stage=True,
)
if not stage1_reports:
    failures.append("Stage 1 FR.231 Stage Report has not been uploaded")
```

`_stage_docs` queries `AuditSetSharedDocument`. But FR.231 audit reports are
uploaded via `report_router.py` and stored in `AuditSetAuditReport` — a
completely separate table. `AuditSetSharedDocument` never gets a
`stage1_report` row, so the gate always fails with "has not been uploaded" even
when the LA has signed and the CM has approved the report.

---

## Change — `backend/audit_set/workflow_router.py`

### Edit 1 — add `AuditSetAuditReport` to the import block (~line 23)

**BEFORE:**
```python
from audit_set.db_models import (
    AuditDocumentSignature,
    AuditSet,
    AuditSetSharedDocument,
    AuditSetStage,
    AuditSetStatusEvent,
    get_db as get_audit_db,
)
```

**AFTER:**
```python
from audit_set.db_models import (
    AuditDocumentSignature,
    AuditSet,
    AuditSetAuditReport,
    AuditSetSharedDocument,
    AuditSetStage,
    AuditSetStatusEvent,
    get_db as get_audit_db,
)
```

---

### Edit 2 — replace `_stage_docs` check in `_assert_stage1_complete_gate` (~line 172)

**BEFORE:**
```python
    stage1_reports = _stage_docs(
        db, audit_set_id, "stage1_report", "stage_1", include_null_stage=True,
    )
    if not stage1_reports:
        failures.append("Stage 1 FR.231 Stage Report has not been uploaded")
    elif any(_unsigned_required_count(db, r.id) for r in stage1_reports):
        failures.append("Stage 1 FR.231 Stage Report is not fully signed")
```

**AFTER:**
```python
    # FR.231 is stored in AuditSetAuditReport (uploaded via report_router),
    # not in AuditSetSharedDocument — check the correct table.
    stage1_audit_reports = (
        db.query(AuditSetAuditReport)
        .filter_by(audit_set_id=audit_set_id, stage_type="stage_1")
        .filter(AuditSetAuditReport.report_form.in_(["FR.231", "FR.229"]))
        .all()
    )
    if not stage1_audit_reports:
        failures.append("Stage 1 FR.231 Stage Report has not been uploaded")
    elif not any(
        r.la_signed_at is not None and r.reviewer_signed_at is not None
        for r in stage1_audit_reports
    ):
        failures.append("Stage 1 FR.231 Stage Report is not fully signed")
```

The gate passes when at least one Stage 1 audit report (FR.231 or FR.229) has
both `la_signed_at` and `reviewer_signed_at` populated — meaning both the Lead
Auditor signature and the Certification Manager approval are complete.

---

## What does NOT change

- `_stage_docs` helper — untouched (still used for FR.222, FR.223, FR.224)
- `_unsigned_required_count` helper — untouched
- `_assert_stage_entry_gate` — untouched
- All other gates — untouched
- `report_router.py` — untouched
- Frontend — no changes

---

## Files to change

| File | Change |
|------|--------|
| `backend/audit_set/workflow_router.py` | Add `AuditSetAuditReport` to import; replace `_stage_docs` FR.231 check with `AuditSetAuditReport` query |

---

## Commit message

```
Portal 75: fix stage1_complete gate — FR.231 is in AuditSetAuditReport

_assert_stage1_complete_gate was querying AuditSetSharedDocument for
document_type="stage1_report", but FR.231 audit reports are uploaded via
report_router and stored in AuditSetAuditReport. The shared-doc table never
gets a stage1_report row, so the gate always failed with "has not been
uploaded" even when both LA and CM had signed.

Fix: query AuditSetAuditReport for stage_type="stage_1" + report_form
IN ("FR.231","FR.229"). Gate passes when at least one report has both
la_signed_at and reviewer_signed_at set.
```
