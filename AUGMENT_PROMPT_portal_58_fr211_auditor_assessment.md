# Portal 58 — FR.211 Auditor Assessment: Client Upload + Sign Per Stage

## Context

During smoke testing, Issue 6 identified: after each audit stage is completed, the
client organization should upload the **FR.211 Lead Auditor/Auditor Assessment Form**
and sign it. This is not done online — the client downloads the blank FR.211 from the
audit package (it is already generated with pre-filled fields), scores the auditor on
paper or digitally, then uploads the completed form back to the portal and signs it.

**This is a per-stage document.** After Stage 1 audit → client uploads+signs Stage 1
FR.211. After Stage 2 audit → client uploads+signs Stage 2 FR.211.

**The templates are already fixed** (9 files across all standard folders):
- `[SIG:CLIENT]` renamed to `[SIG:ORG_REP]` in all FR.211 DOCX files
- Template variables already present: `{{ assessed_person_name }}`, `{{ audit_dates }}`,
  `{{ company_name }}`, `{{ standards_str }}`

---

## What needs to be built

### 1. New document type: `auditor_assessment`

**File:** `backend/audit_set/documents_router.py`

Add to `DOC_SIG_SLOTS`:
```python
"auditor_assessment": ["org_rep"],
```

Add to `CLIENT_VISIBLE_TYPES` (client can see and sign their own upload):
```python
CLIENT_VISIBLE_TYPES = {..., "auditor_assessment"}
```

Add to the document upload allow-list for client role. The client should be able to
upload `auditor_assessment` documents from their portal. Check `upload_shared_document`
or `upload_audit_document` — add `"auditor_assessment"` to whatever type allow-list
gates client uploads.

---

### 2. FR.211 included in packager output (blank, pre-filled)

**File:** `backend/audit_set/packager.py`

FR.211 is already in the blank set folders per stage. Add it to the packager so it
appears in the downloaded audit package with basic fields pre-filled:

```python
FR211_CONTEXT = {
    "company_name":         ctx["company_name"],
    "standards_str":        ctx["standards_str"],
    "audit_dates":          ctx["stage_1_date_range"],   # or stage_2_date_range
    "assessed_person_name": ctx["lead_auditor_name"],
}
```

Map `FR211_MAP` in `field_maps.py`:
```python
FR211_MAP = {
    "company_name":         "company_name",
    "standards_str":        "standards_str",
    "audit_dates":          "audit_dates",
    "assessed_person_name": "assessed_person_name",
}
```

The `assessed_person_name` is the lead auditor for that stage — read from
`AuditSetStage.lead_auditor_name` for the relevant stage.

Generate one FR.211 per stage (Stage 1 and Stage 2 as separate documents in the
audit package).

---

### 3. Client upload UI — FR.211 per stage

**File:** `frontend/src/app/(client)/client/audit/[id]/page.tsx`
(or wherever the client's document section renders for a specific audit set)

Add an "Auditor Assessment" section that shows:

```
Stage 1 Auditor Assessment (FR.211)
[Upload completed form]  [Open to Sign] ← shows after upload

Stage 2 Auditor Assessment (FR.211)
[Upload completed form]  [Open to Sign] ← shows after upload
```

The upload posts to:
```
POST /audit-sets/{id}/documents/upload
  ?label=FR.211 Auditor Assessment — Stage 1
  &document_type=auditor_assessment
  &stage_type=stage_1
  &upload_date=YYYY-MM-DD
```

Once uploaded, the client clicks "Open to Sign" → viewer opens → `[SIG:ORG_REP]` slot
shows with the employee picker (Portal 56 flow).

---

### 4. When to show the upload section

Show the FR.211 Stage 1 upload section when `audit_set.status` is `stage1_complete`
or later (Stage 1 audit is done, client can now assess).

Show the FR.211 Stage 2 upload section when `audit_set.status` is `stage2_complete`
or later.

If FR.211 is already uploaded and signed for a stage, show "✓ Submitted" instead.

---

### 5. CB/CM can see FR.211 in shared documents

FR.211 should appear in the CB's shared documents view (planner and CM) once the client
uploads it. Include `"auditor_assessment"` in `CB_VISIBLE_TYPES` so it appears in the
planner's documents list for that audit set.

The CM reviews FR.211 as part of their Stage 1/2 review before advancing the gate.

---

### 6. Do NOT gate-block on FR.211

Do not add FR.211 as a hard gate requirement for `stage1_complete → stage2_in_progress`
at this stage. The CM should be able to see it and be expected to review it, but the
gate should not block if it's missing. This can be added as a hard gate later.

---

## Files to change

| File | Change |
|------|--------|
| `backend/audit_set/documents_router.py` | Add `"auditor_assessment"` to `DOC_SIG_SLOTS`, `CLIENT_VISIBLE_TYPES`, `CB_VISIBLE_TYPES`, client upload allow-list |
| `backend/audit_set/field_maps.py` | Add `FR211_MAP` |
| `backend/audit_set/packager.py` | Generate FR.211 per stage with pre-filled fields; inject `assessed_person_name = lead_auditor_name` |
| `frontend/src/app/(client)/client/audit/[id]/page.tsx` | Add FR.211 upload sections per stage (Stage 1 visible at stage1_complete+, Stage 2 at stage2_complete+) |

---

## Commit message

```
Portal 58: FR.211 auditor assessment — client upload + sign per stage

After each audit stage, the client uploads the completed FR.211 Lead Auditor
Assessment Form and signs it with the org rep employee picker.

- DOC_SIG_SLOTS: add auditor_assessment → [org_rep]
- CLIENT/CB_VISIBLE_TYPES: include auditor_assessment
- packager: generate FR.211 per stage with company_name, standards_str,
  audit_dates, assessed_person_name (lead auditor name) pre-filled
- field_maps: FR211_MAP
- Client portal: FR.211 upload section per stage, visible after stage complete

Templates already fixed in this commit: [SIG:CLIENT] → [SIG:ORG_REP]
in all 9 FR.211 files across 3 standard folders × 3 audit types.
```
