# Portal 53 — Fix: lead_auditor_id never saved in stage planning payload

## What's broken

When the CB Planner saves a stage (Stage 1 or Stage 2 team assignment), the
`lead_auditor_id` is **never sent in the PUT request body**. The backend receives
`None` for that field and writes `None` to the DB on every save — overwriting
any previously correct value.

**Downstream symptom:** When releasing FR.224, the "Assigned auditor" dropdown
in `SharedDocumentsSection` calls `stageTeam()`, which calls
`push(stage.lead_auditor_id ?? undefined, ...)`. Because `lead_auditor_id` is
`None`/empty, the lead auditor is silently dropped from the dropdown. Only
auditors and TEs stored in the `auditors[]` / `technical_experts[]` JSON arrays
appear. The lead auditor's portal also shows 0 audit assignments.

This is a continuation of the Portal 50a diagnosis. Portal 50a correctly fixed
`buildStageEdit()` to READ `lead_auditor_id` from the API response — but the
WRITE path (the PUT payload) was never updated to include it.

---

## Root cause — exact line

**File:** `frontend/src/app/(app)/clients/[id]/page.tsx`

Find the `stages` array built for `api.put('/audit-sets/${auditSetId}/planning', ...)`.
It looks like this (around line 917):

```typescript
const stages = allStages.map((s) => {
  const isThis = s.id === stage.id
  return {
    stage_type:        s.stage_type,
    stage_order:       s.stage_order,
    status:            s.status,
    lead_auditor_name: isThis ? (edit.lead_auditor_name || null) : s.lead_auditor_name,
    // ← lead_auditor_id IS MISSING FROM THIS OBJECT
    audit_date_start:  isThis ? (edit.audit_date_start  || null) : s.audit_date_start,
    audit_date_end:    isThis ? (edit.audit_date_end    || null) : s.audit_date_end,
    auditors:          isThis ? edit.auditors          : ((s.auditors as TeamMember[]) ?? []),
    technical_experts: isThis ? edit.technical_experts : ((s.technical_experts as TeamMember[]) ?? []),
    observers:         (s.observers as { name: string }[]) ?? [],
    ik_experts:        [],
    evaluators:        [],
  }
})
```

Because `lead_auditor_id` is absent, Pydantic's `StageInput` schema
(`lead_auditor_id: Optional[str] = None`) defaults it to `None`, and
`service.py:update_planning()` faithfully writes `None` to every stage row.

---

## Fix — one line added

```typescript
// BEFORE
const stages = allStages.map((s) => {
  const isThis = s.id === stage.id
  return {
    stage_type:        s.stage_type,
    stage_order:       s.stage_order,
    status:            s.status,
    lead_auditor_name: isThis ? (edit.lead_auditor_name || null) : s.lead_auditor_name,
    audit_date_start:  ...
```

```typescript
// AFTER — add lead_auditor_id immediately after lead_auditor_name
const stages = allStages.map((s) => {
  const isThis = s.id === stage.id
  return {
    stage_type:        s.stage_type,
    stage_order:       s.stage_order,
    status:            s.status,
    lead_auditor_name: isThis ? (edit.lead_auditor_name || null) : s.lead_auditor_name,
    lead_auditor_id:   isThis ? (edit.lead_auditor_id   || null) : (s.lead_auditor_id ?? null),
    audit_date_start:  isThis ? (edit.audit_date_start  || null) : s.audit_date_start,
    audit_date_end:    isThis ? (edit.audit_date_end    || null) : s.audit_date_end,
    auditors:          isThis ? edit.auditors          : ((s.auditors as TeamMember[]) ?? []),
    technical_experts: isThis ? edit.technical_experts : ((s.technical_experts as TeamMember[]) ?? []),
    observers:         (s.observers as { name: string }[]) ?? [],
    ik_experts:        [],
    evaluators:        [],
  }
})
```

### Why the non-`isThis` branch matters

All stages are submitted together in the same PUT call. When saving Stage 2,
Stage 1's entry is also included. Without the fix, Stage 1's `lead_auditor_id`
gets wiped to `None` every time Stage 2 is saved. Both branches need the field.

---

## DB repair — run after deploy

Existing audit set stages have `lead_auditor_id = NULL` from prior saves.
The repair script already exists at `backend/scripts/repair_lead_auditor_ids.py`.
**Run it now in the Railway backend console:**

```bash
python backend/scripts/repair_lead_auditor_ids.py
```

It matches `lead_auditor_name` → `Auditor.name` and backfills the ID.
Output will show `✓ FIXED` for each repaired row or `⚠ WARN` if the name
doesn't match any auditor record (means the auditor link may not be set up).

If a stage shows `⚠ WARN`, also verify the auditor's `PlatformUser.auditor_id`
is set via Admin → Users → "Link to auditor profile".

---

## What does NOT need changing

- `buildStageEdit()` in `clients/[id]/page.tsx` — already correct from Portal 50a
- `_stage_matches_auditor()` in `auditor_router.py` — already correct from Portal 50a
- `stageTeam()` in `SharedDocumentsSection.tsx` — already correct
- The backend `update_planning()` in `service.py` — already writes `lead_auditor_id` correctly, it just receives `None` because the frontend omits the field
- `_auditor_is_assigned()` in `documents_router.py` — already checks lead + auditors + TEs

Only one line of frontend code needs to change.

---

## Verification after deploy + repair

### As CB Planner

1. Open any audit set → Stage 2 panel → click "Edit team"
2. Confirm Asli Abay (or the assigned lead auditor) appears pre-selected in the lead auditor dropdown
3. Click "Save stage" — no team change needed, just a re-save
4. Go to Shared Documents → "+ Release Document" → Type: "Audit Team Info (FR.224)" → Stage: Stage 2
5. "Assigned auditor" dropdown must now show:
   - **Asli Abay** (lead auditor) ← was missing before
   - Altug Solmaz (TE)
   - Any other stage members

### As Asli Abay (lead auditor account)

1. Log in → "My Audit Assignments" must show the audit set (was: 0 assignments)
2. Open the audit → Documents tab → her FR.224 card should appear
3. Sign → done

### Regression check

- Altug's FR.224 must still appear only in Altug's portal (not Asli's)
- Asli's FR.224 must still appear only in Asli's portal (not Altug's)

---

## Files changed

| File | Change |
|------|--------|
| `frontend/src/app/(app)/clients/[id]/page.tsx` | Add `lead_auditor_id` to stage save payload (one line) |

**Do NOT touch any backend files** — the backend is correct.  
**Run the repair script** after deploy to fix existing DB rows.

---

## Commit message

```
Portal 53: fix lead_auditor_id missing from stage save payload

buildStageEdit() was fixed in Portal 50a to READ lead_auditor_id from
the API response, but the WRITE path never included it in the PUT body.
Pydantic defaulted the missing field to None and the backend faithfully
wrote None to every stage row on every save.

Fix: add lead_auditor_id to the stages.map() return object for both
the current stage (edit.lead_auditor_id) and other stages (s.lead_auditor_id).

Also run backend/scripts/repair_lead_auditor_ids.py to backfill DB rows
that were set to NULL by prior saves.
```
