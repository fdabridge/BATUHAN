# AUGMENT PROMPT — Portal 40: Fix Auditor Filtering in Stage Planner

## Problem

In the audit stage planner, the lead auditor and auditor dropdowns show **all auditors** regardless of which standard the audit set is for. The label reads "0 of 0 auditors qualified & available for ISO 9001 on selected dates" — the system is not finding any qualified auditors.

**Root cause:** The auditor qualification lookup is reading from the top-level `ea_codes` field on the `Auditor` model. After the bulk JSON import, all auditors have `ea_codes = null` at the top level. Qualifications are now stored per-standard in the `AuditorStandardQualification` table (joined via `auditor_standard_qualifications`).

---

## Fix Required

### Backend — Auditor availability/qualification query

Find the endpoint (likely in `backend/api/routes/auditors.py` or `backend/api/routes/audit_sets.py`) that returns available auditors for a stage. It probably does something like:

```python
# WRONG — reads top-level ea_codes
auditors = db.query(Auditor).filter(Auditor.ea_codes.contains(ea_code))
```

Replace the qualification check with a join to `AuditorStandardQualification`:

```python
from auditors.models import AuditorStandardQualification

# Get auditors qualified for the given standard
qualified = (
    db.query(Auditor)
    .join(
        AuditorStandardQualification,
        AuditorStandardQualification.auditor_id == Auditor.id
    )
    .filter(
        AuditorStandardQualification.standard_code == standard_code,
        AuditorStandardQualification.is_qualified == True,
    )
)
```

If the stage also filters by EA codes (for QMS/EMS/OHSMS audits), add:

```python
# Only apply EA code filter if the standard uses EA codes
# (ISO 9001, ISO 14001, ISO 45001 → ea_codes list)
# (ISO 22000/FSSC → scope_category string)
# (ISO 50001, ISO 27001, ISO 13485, ISO 37001 → no code filter)

if ea_code_required:
    qualified = qualified.filter(
        AuditorStandardQualification.ea_codes.contains(ea_code)
    )
```

The filter should use `AuditorStandardQualification.ea_codes` (the per-standard field), never `Auditor.ea_codes`.

---

### The "0 of N" qualified count label

The label "0 of 0 auditors qualified & available for ISO 9001 on selected dates" should show:
- **Numerator**: auditors in the dropdown who are available on the selected dates (no conflicting audit assignments)
- **Denominator**: total auditors qualified for that standard

Fix the count query to use the same `AuditorStandardQualification` join described above.

---

### Dropdown filtering — what auditors should appear

The dropdown for **Lead Auditor** should only show auditors where:
1. `AuditorStandardQualification.standard_code == <audit standard>` AND `is_qualified == True`
2. `technical_depth == "Lead Auditor"` (i.e., role is lead_auditor)

The dropdown for **Auditors** (team members) should show auditors with the same standard qualification, regardless of `technical_depth`.

The dropdown for **Technical Experts** should show auditors where `role == "technical_expert"` and they have a qualification for the standard (or a related standard).

---

### Availability check (date-based)

If availability filtering exists (checking whether an auditor is already assigned to another audit on the selected dates), make sure it runs **after** the qualification filter, not instead of it. The dates filter should narrow down the already-qualified list, not replace it.

---

## What NOT to change

- Do not modify `AuditorStandardQualification` model or schema
- Do not modify the bulk import endpoint
- Do not touch the auditor list page or profile page
- Do not modify `auditors_import.json`

---

---

### EA Code Coverage Panel (new UI feature)

After the team is selected for a stage, show a **coverage summary** directly in the stage planner UI — below the auditor dropdowns, above the Save button.

**Logic:**

1. Get the audit set's EA codes (e.g. `["EA 3", "EA 5", "EA 28"]` from `audit_set.ea_codes`)
2. For each assigned auditor (lead + team), look up their `AuditorStandardQualification` for the relevant standard and read their `ea_codes` list
3. Compute: which required EA codes are covered by at least one team member, and which are not

**UI display (inline, compact):**

Show a small coverage block like:

```
EA Code Coverage — ISO 9001
✓ EA 3   Aslan Aslan
✓ EA 5   Hakan Kurt
✓ EA 28  Aslan Aslan
✗ EA 30  — not covered
```

- Green checkmark (✓) for covered codes, with the auditor name next to it
- Red ✗ for uncovered codes
- If all codes are covered: show a green "Full coverage" badge
- If any code is missing: show a yellow "Incomplete coverage" warning badge

This panel should update **reactively** as auditors are added or removed from the stage (no page reload required — recalculate on dropdown change).

For **FSMS standards** (ISO 22000 / FSSC 22000) the audit set uses `scope_category` (food chain categories like CI, CII, E) instead of EA codes. Apply the same logic using the auditor's `AuditorStandardQualification.scope_category` field. Show the same covered/uncovered pattern.

For **ISO 50001, ISO 27001, ISO 13485, ISO 37001** — no EA codes or scope categories apply. Do not show the coverage panel for these standards.

---

## Verification

After deploying, open any audit set for ISO 9001. The stage planner should:
1. Show a non-zero count like "80 of 80 auditors qualified for ISO 9001"
2. The lead auditor dropdown should only show lead auditors qualified for ISO 9001
3. An auditor qualified only for ISO 22000 should NOT appear in the ISO 9001 dropdown
4. After selecting a lead auditor and one team auditor, the EA code coverage panel appears showing which EA codes are covered by which auditor, and highlighting any gaps
