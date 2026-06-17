# Portal 68 — FR.233 Generate Gate: Fix Wrong Table Check + Role Check

## Root cause

The FR.233 Word document shows zero committee rows. Investigation confirmed:

1. The `fr233_generator.py` is correct — docxtpl loop produces the right rows when given data.
2. The blank-row fallback also works — even with an empty committee, 3 placeholder rows render.
3. The stored FR.233 document in the database is a **stale cached file** generated before
   Portal 62's docxtpl rewrite (old static table-fill approach, empty committee → empty rows).
4. The user **cannot regenerate** because `POST /fr233/generate` has two bugs that block it:

### Bug 1 — Gate checks the wrong table

In `backend/audit_set/committee_router.py`, line ~534:

```python
members = db.query(AuditSetCommitteeMember).filter_by(audit_set_id=audit_set_id).count()
if members < 1:
    raise HTTPException(400, "Appoint at least one committee member before generating FR.233")
```

`AuditSetCommitteeMember` is the **old Portal 62 model** (user_id, role="reviewer"/"decision_maker").
Portal 64 moved committee appointment to the planning phase and stores the committee in
`audit_set.committee_members` (JSON column on the `audit_sets` table, populated by
`PUT /audit-sets/{id}/planning`). The old table is no longer populated.
The gate always fires → generation blocked → user sees the stale cached file.

### Bug 2 — Role check excludes `certification_manager`

Same endpoint, line ~513:

```python
if current_user.role not in {"admin", "planner", "executive"}:
    raise HTTPException(403, "Only Planner or Certification Manager may generate FR.233")
```

The error message says "Certification Manager may generate FR.233" but `"certification_manager"`
is not in the allowed set. The CM gets a 403.

---

## Fix in `backend/audit_set/committee_router.py`

In the `generate_fr233` function, make two changes:

### Fix 1 — Role check (add certification_manager)

```python
# BEFORE:
if current_user.role not in {"admin", "planner", "executive"}:
    raise HTTPException(403, "Only Planner or Certification Manager may generate FR.233")

# AFTER:
if current_user.role not in {"admin", "planner", "executive", "certification_manager"}:
    raise HTTPException(403, "Only Planner or Certification Manager may generate FR.233")
```

### Fix 2 — Gate check (use JSON column, not old table)

```python
# BEFORE:
members = db.query(AuditSetCommitteeMember).filter_by(audit_set_id=audit_set_id).count()
if members < 1:
    raise HTTPException(400, "Appoint at least one committee member before generating FR.233")

# AFTER:
committee_members = audit_set.committee_members or []
if not committee_members:
    raise HTTPException(
        400,
        "Save the certification committee in the audit planning section before generating FR.233."
    )
```

`audit_set.committee_members` is a JSON column (`Column(JSON, nullable=True)` in db_models.py)
that `PUT /audit-sets/{id}/planning` populates when the planner saves the committee picker.

---

## What NOT to change

- `fr233_generator.py` — correct as-is; `_build_committee_context` reads `audit_set.committee_members`
  and has a 3-row blank fallback. No changes needed.
- The workflow_status allowed set — `{"stage2_complete", "committee_review", "under_review",
  "stage2_in_progress"}` is fine.
- All template files — confirmed correct with `{%tr for member in committee_members %}` loop.
- The viewer, packager, or any other file — no changes needed.

---

## After deploying — manual step for existing audit set

The test audit set has a stale FR.233 in the database. After deploying this fix:

1. Go to the audit set.
2. Click "Generate FR.233" (or whatever the UI button is called).
3. The endpoint now passes both checks → calls `render_fr233_bytes` → docxtpl renders
   the committee rows from `audit_set.committee_members` → fresh document stored.
4. Open the new FR.233 → committee rows visible with member names and sig markers.

If `audit_set.committee_members` is still NULL (committee was never saved via planning UI),
the generator's 3-row blank fallback kicks in and renders placeholder rows
(`[SIG:COMMITTEE_MEMBER_BLANK_0]` etc.) so the document is at least structurally complete.

---

## Files to change

| File | Change |
|------|--------|
| `backend/audit_set/committee_router.py` | In `generate_fr233`: add `"certification_manager"` to role set; replace `AuditSetCommitteeMember` count gate with `audit_set.committee_members` JSON check |

---

## Commit message

```
Portal 68: fix FR.233 generate gate — wrong table + missing CM role

Bug 1: gate checked AuditSetCommitteeMember table (old Portal 62 model,
  no longer populated since Portal 64 moved committee to planning phase).
  New check: audit_set.committee_members JSON column, which is populated
  by PUT /audit-sets/{id}/planning when the planner saves the committee.

Bug 2: role check excluded "certification_manager" — string not in allowed
  set even though the error message said CM may generate. Added.

No changes to fr233_generator.py, templates, viewer, or packager.
```
