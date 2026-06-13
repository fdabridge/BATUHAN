# AUGMENT PROMPT — Portal 50a: FR.224 Assignment Bugs (Two targeted fixes)

Two small but blocking bugs found during smoke testing. Both are confirmed by
reading the source. Fix exactly what is described — do not refactor surrounding code.

---

## Bug 1 — Lead auditor missing from FR.224 "Assigned auditor" dropdown

### Root cause

`frontend/src/app/(app)/clients/[id]/page.tsx` — function `buildStageEdit()`:

```typescript
function buildStageEdit(s: StageResponse): StageEdit {
  return {
    lead_auditor_id:   '',          // ← BUG: hardcoded empty string
    lead_auditor_name: s.lead_auditor_name ?? '',
    ...
  }
}
```

`lead_auditor_id` is always `''` regardless of what the API returns in `s.lead_auditor_id`.
This means:
1. Every time "Save stage" is clicked, `lead_auditor_id = ''` is written to the DB.
2. `SharedDocumentsSection.stageTeam()` calls `push(stage.lead_auditor_id, ...)` but
   `push()` bails on empty string (`!id` is true), so the lead auditor never appears
   in the FR.224 assigned-auditor dropdown.

### Fix

**File:** `frontend/src/app/(app)/clients/[id]/page.tsx`

Change `buildStageEdit()`:

```typescript
// BEFORE
function buildStageEdit(s: StageResponse): StageEdit {
  return {
    lead_auditor_id:   '',
    lead_auditor_name: s.lead_auditor_name ?? '',
    ...
  }
}

// AFTER
function buildStageEdit(s: StageResponse): StageEdit {
  return {
    lead_auditor_id:   s.lead_auditor_id   ?? '',
    lead_auditor_name: s.lead_auditor_name ?? '',
    ...
  }
}
```

That is the entire frontend change required.

### DB repair (run once after deploy)

Because stages were previously saved with `lead_auditor_id = ''`, existing audit sets
have the wrong value in the DB. After deploying the fix, the Planner must re-open
each affected stage, re-select the lead auditor from the dropdown (to repopulate the
ID), and click "Save stage" again.

Alternatively, add a one-time migration script
`backend/scripts/repair_lead_auditor_ids.py` that:
1. Queries all `AuditSetStage` rows where `lead_auditor_id` is `''` or null but
   `lead_auditor_name` is not null.
2. For each, looks up the matching `Auditor` record by `name == lead_auditor_name`.
3. Writes `stage.lead_auditor_id = auditor.id`.

```python
#!/usr/bin/env python3
"""
One-time repair: populate lead_auditor_id on AuditSetStage rows
where it is blank but lead_auditor_name is present.
Run from the backend container:
    python backend/scripts/repair_lead_auditor_ids.py
"""
from audit_set.db_models import AuditSetStage, get_db
from auditors.db_models import Auditor   # adjust import path if different

def repair():
    db = next(get_db())
    stages = db.query(AuditSetStage).filter(
        (AuditSetStage.lead_auditor_id == None) |
        (AuditSetStage.lead_auditor_id == '')
    ).all()

    fixed = 0
    for stage in stages:
        if not stage.lead_auditor_name:
            continue
        auditor = db.query(Auditor).filter_by(name=stage.lead_auditor_name).first()
        if auditor:
            stage.lead_auditor_id = auditor.id
            fixed += 1
            print(f"  Fixed stage {stage.id}: {stage.lead_auditor_name} → {auditor.id}")
        else:
            print(f"  WARN: No auditor record found for '{stage.lead_auditor_name}'")

    db.commit()
    print(f"\nDone. Fixed {fixed} stage(s).")

if __name__ == "__main__":
    repair()
```

---

## Bug 2 — Technical Experts (TEs) show 0 assignments in auditor portal

### Root cause

`backend/audit_set/auditor_router.py` — function `_stage_matches_auditor()`:

```python
def _stage_matches_auditor(stage: AuditSetStage, auditor_id: str) -> tuple[bool, bool]:
    is_lead = stage.lead_auditor_id == auditor_id
    is_team = any(
        isinstance(a, dict) and a.get("id") == auditor_id
        for a in (stage.auditors or [])   # ← BUG: technical_experts never checked
    )
    return (is_lead or is_team, is_lead)
```

`stage.technical_experts` is never included in the check.
Any TE (like Altuğ Solmaz) therefore never matches any stage, so
`_get_auditor_assignments` returns an empty list and the portal shows
"0 audits assigned".

Note: `_auditor_is_assigned()` in `documents_router.py` already correctly checks
`technical_experts` — only `auditor_router.py` has this bug.

### Fix

**File:** `backend/audit_set/auditor_router.py`

```python
# BEFORE
def _stage_matches_auditor(stage: AuditSetStage, auditor_id: str) -> tuple[bool, bool]:
    is_lead = stage.lead_auditor_id == auditor_id
    is_team = any(
        isinstance(a, dict) and a.get("id") == auditor_id
        for a in (stage.auditors or [])
    )
    return (is_lead or is_team, is_lead)

# AFTER
def _stage_matches_auditor(stage: AuditSetStage, auditor_id: str) -> tuple[bool, bool]:
    """Return (is_assigned, is_lead) for this auditor on the given stage.
    Checks lead auditor, team auditors, AND technical experts.
    """
    is_lead = bool(stage.lead_auditor_id) and stage.lead_auditor_id == auditor_id
    all_members = list(stage.auditors or []) + list(stage.technical_experts or [])
    is_team = any(
        isinstance(a, dict) and a.get("id") == auditor_id
        for a in all_members
    )
    return (is_lead or is_team, is_lead)
```

That is the entire backend change required for Bug 2.

---

## After both fixes are deployed

Verify on Railway:

1. **Bug 1:** Open an audit set → Shared Documents → "+ Release Document" →
   Type = "Audit Team Info (FR.224)" → Stage = "Stage 1" →
   "Assigned auditor" dropdown must now list Aslı Abay (Lead) AND Altuğ Solmaz (TE).

2. **Bug 2:** Log in as Altuğ Solmaz (auditor account) →
   "My Audit Assignments" must show the audit set where he is a TE.
   Opening the assignment must show the FR.224 document uploaded for him
   in an amber "Awaiting signature" card.

3. **Lead auditor portal:** Log in as Aslı Abay (auditor account) →
   After the DB repair script runs (or after re-saving the stage),
   "My Audit Assignments" must show the audit set.

---

## Files touched

| File | Change |
|---|---|
| `frontend/src/app/(app)/clients/[id]/page.tsx` | `buildStageEdit()`: `lead_auditor_id: s.lead_auditor_id ?? ''` |
| `backend/audit_set/auditor_router.py` | `_stage_matches_auditor()`: add `technical_experts` to `all_members` |
| `backend/scripts/repair_lead_auditor_ids.py` | NEW — one-time DB repair script |
