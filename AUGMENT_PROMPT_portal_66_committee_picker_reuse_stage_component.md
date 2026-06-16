# Portal 66 — Committee Picker: Reuse Stage Auditor Picker Component

## Context

The Certification Committee picker (Portal 64) was built as a custom dual-panel
"Available Auditors / Selected" layout with individual Add buttons. This is
inconsistent with the Stage 1 and Stage 2 auditor picker which uses a searchable
dropdown with chips and a coverage breakdown — and which is already working correctly.

The fix is simple: **replace CommitteePlanningCard entirely with the same auditor
picker component used for Stage 1/Stage 2**, passing the stage team member IDs as
an exclusion filter. Do not build a new component — reuse the existing one.

---

## What to do

Find the auditor picker component used for Stage 1 and Stage 2 team selection.
It is likely something like `AuditorPicker`, `StageAuditorSelect`, or similar —
the component that renders the searchable dropdown, shows selected members as chips
with EA code badges, and renders the coverage summary at the bottom.

Replace `CommitteePlanningCard` with this same component, configured as follows:

### Props / configuration differences from stage use

| Prop | Stage use | Committee use |
|------|-----------|---------------|
| `label` | "Lead auditor" / "Auditors" | "Certification Committee" |
| `excludeIds` | (none) | all Stage 1 + Stage 2 auditor IDs (lead + auditors + TEs) |
| `roleLabel` | "lead_auditor" / "auditor" | "chairperson" for first, "member" for rest |
| `coverageRequired` | same audit standards/EA codes | same audit standards/EA codes |
| `onSave` | saves stage team | saves `committee_members` JSON on audit_set |

### Chairperson vs Member

The first auditor added to the committee = Chairperson. All subsequent additions = Members. Show this in the chip label, same as how "lead_auditor" is shown on the Stage 2 chip:

```
[Ahmet Yıldız — chairperson — EA 3 (ISO 9001) ×]
[Fatma Demir — member — EA 5 (ISO 9001) ×]
```

The ordering is: first chip added = Chairperson. If the Chairperson chip is removed,
the next chip becomes Chairperson automatically (same as how removing the lead_auditor
promotes the first remaining auditor in stage planning).

### Exclusion filter

Pass the current Stage 1 and Stage 2 team member IDs to the picker so they are
filtered out of the dropdown options. Collect:

```ts
const stageExcludedIds = new Set([
  stage1.lead_auditor_id,
  ...(stage1.auditors || []).map(a => a.id),
  ...(stage1.technical_experts || []).map(te => te.id),
  stage2.lead_auditor_id,
  ...(stage2.auditors || []).map(a => a.id),
  ...(stage2.technical_experts || []).map(te => te.id),
].filter(Boolean))
```

Pass this set to the auditor picker so those auditors are excluded from the
searchable dropdown (same as how a lead_auditor is excluded from the "Auditors"
dropdown on the same stage).

The exclusion must be **live** — if the planner changes Stage 1 or Stage 2 team
assignments, the committee dropdown updates immediately to reflect the new exclusions.

### Coverage behaviour

Identical to stage picker:
- Show ✓ All required codes covered when the committee collectively covers all
  of the audit set's standards and EA codes
- Show per-standard breakdown (ISO 9001: EA 3 — Ahmet Y. ✓ EA 5 — Fatma D. ✓)
- Disable "Save committee" button (or show a warning) if coverage is incomplete

### Backend endpoint

The committee picker calls the same `GET /planning/committee/available-auditors`
endpoint built in Portal 64, passing `exclude_auditor_ids` as a query param.
No new endpoint needed — just ensure the component passes the exclusion IDs correctly.

### Save

On "Save committee", submit `committee_members` as part of the existing
`PUT /audit-sets/{id}/planning` payload (same as Portal 64 implemented).
No endpoint change needed.

---

## Files to change

| File | Change |
|------|--------|
| `frontend/.../CommitteePlanningCard.tsx` (or equivalent) | Delete this file entirely — replaced by the existing stage auditor picker component |
| `frontend/.../clients/[id]/page.tsx` (or planning page) | Replace `<CommitteePlanningCard>` usage with `<AuditorPicker>` (or whatever the stage picker component is called), passing `excludeIds={stageExcludedIds}` and committee-specific props |

---

## Commit message

```
Portal 66: committee picker — reuse stage auditor picker component

Replace custom dual-panel CommitteePlanningCard with the same auditor
picker component used for Stage 1/Stage 2 team selection. Passes stage
team member IDs as live exclusion filter. First selected = Chairperson,
shown in chip label. Coverage breakdown identical to stage picker.

Deletes CommitteePlanningCard.tsx — no new component needed.
```
