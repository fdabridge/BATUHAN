# AUGMENT PROMPT — Portal 41: Signing Date Fix + Auditor Coverage Logic Fix

---

## Problem 1 — Signing Date Records Server Date Instead of User-Selected Date

When a document is signed (Quotation, FR.218, FR.224, any "Sign" button), the displayed
"Signed [date]" always shows today's server date — even though the signing flow lets the
user select a specific signing date.

### Fix

Find the endpoint that records a signature. It currently ignores the user-provided date:

```python
# WRONG — uses server clock
signature.signed_at = datetime.utcnow()
```

Fix to use the user-provided date:

```python
class SignDocumentRequest(BaseModel):
    signed_date: Optional[date] = None
    # ... other existing fields

signature.signed_at = payload.signed_date or date.today()
```

If the request schema already has a `signed_date` field but it is not wired through to
the model, wire it through.

Also check the frontend signing modal — confirm the selected date is included in the POST
body. If it is not being sent, add it.

Apply to ALL signing paths: document release, FR.218 (Planning Officer + Certification
Manager slots), FR.224 impartiality declarations, and any other Sign button.

---

## Problem 2 — Auditor Dropdown and Coverage Panel Logic Is Broken

### Background — the correct multi-standard logic (do not deviate from this)

An audit set can cover 1–7+ management system standards simultaneously (integrated audit).
Example: ISO 9001 (EA 3, EA 5) + ISO 14001 (EA 3) + ISO 22000 (CI, CII).

Coverage requirements per standard type:
- **ISO 9001, ISO 14001, ISO 45001, ISO 50001, ISO 27001**: IAF EA codes (EA 1–39)
- **ISO 22000, FSSC 22000**: food chain categories (CI, CII, CIII, CIV, BIII, C0, D, E, FI, FII, G, I, K) — NOT EA codes
- **ISO 13485**: IAF MD 9 Technical Areas (A1.1–A1.7, A2.1–A2.4) — NOT EA codes
- **ISO 37001, ISO 37301**: no standard code system — no coverage check needed

Per IAF MD 11:2023: **the team collectively must cover all required codes/categories.
Individual auditors do NOT need to cover all codes — each auditor only needs to cover at
least one required code/category across any standard in the audit set.**

This means:
- Auditor A covers ISO 9001 EA 3 → valid team member
- Auditor B covers ISO 9001 EA 5 → valid team member  
- Auditor C covers ISO 22000 CI only → valid team member
- Together they cover everything

### Current broken behavior

`GET /auditors/available` is filtering the dropdown to only show auditors who match the
audit set's EA codes at the top level, OR (after Prompt 40) only auditors matching a
specific single EA code. This means:
- Only EA 3 auditors show up even if the audit needs EA 5 coverage
- FSMS auditors don't appear in integrated audits that include ISO 22000
- It is impossible to build a team that collectively covers all codes

### Fix — Backend: `GET /auditors/available` (or equivalent endpoint)

The dropdown query must return any auditor who covers AT LEAST ONE required code or
category across ANY standard in the audit set.

Step-by-step logic:

1. Get all standards in the audit set (e.g. `["ISO 9001", "ISO 14001", "ISO 22000"]`)

2. For each standard, get its required scope codes from the audit set:
   - ISO 9001/14001/45001/50001/27001 → `audit_set.ea_codes` (e.g. `["EA 3", "EA 5"]`)
   - ISO 22000/FSSC → `audit_set.scope_category` (e.g. `"CI, CII, E"`)
   - ISO 13485 → technical areas from the audit set (wherever these are stored)
   - ISO 37001/37301 → no code filter, include any auditor qualified for this standard

3. Build the union set of required (standard, code) pairs:
   ```
   required_coverage = [
     ("ISO 9001", "EA 3"), ("ISO 9001", "EA 5"),
     ("ISO 14001", "EA 3"),
     ("ISO 22000", "CI"), ("ISO 22000", "CII"),
   ]
   ```

4. Return any auditor who has an `AuditorStandardQualification` row where:
   - `standard_code` matches one of the standards in the audit set AND
   - `is_qualified == True` AND
   - their `ea_codes` (for EA-based standards) or `scope_category` (for FSMS) contains
     at least one of the required codes for that standard

   In SQL terms: the auditor must match at least one `(standard_code, code)` pair from
   `required_coverage`.

5. Apply `technical_depth` filter:
   - Lead Auditor dropdown: only `technical_depth == "Lead Auditor"`
   - Auditors dropdown: any `technical_depth`
   - Technical Experts dropdown: `role == "technical_expert"`

6. Apply date availability filter last (after the qualification filter).

Do NOT filter by a single ea_code param. The ea_code param can remain for backward
compatibility but the dropdown must not use it.

### Fix — Frontend: Dropdown labels

Each auditor in the dropdown should show what they cover for THIS audit's standards. Read
their `AuditorStandardQualification` rows for the standards in this audit set and show all
relevant codes/categories:

```
Hasan Eryılmaz — lead_auditor — ISO 9001: EA 3, EA 5 | ISO 22000: CI, CII
Erol Öziyi — lead_auditor — ISO 9001: EA 3
Fatma Şen — lead_auditor — ISO 22000: CI, E
```

### Fix — Coverage Panel

The coverage panel already exists. Fix its logic to:

1. Build the full required coverage matrix for this audit set (same logic as step 3 above):
   - Group by standard: ISO 9001 needs EA 3, EA 5; ISO 22000 needs CI, CII; etc.

2. For each selected auditor (lead + team members + technical experts), read their
   `AuditorStandardQualification` rows for each standard and collect their codes/categories.

3. For each (standard, code/category) pair, mark as:
   - ✓ covered — at least one team member covers it (show the auditor's name)
   - ✗ uncovered — no team member covers it

4. Display grouped by standard:
   ```
   ISO 9001
     ✓ EA 3   Hasan Eryılmaz
     ✗ EA 5   — not covered

   ISO 22000
     ✓ CI     Fatma Şen
     ✗ CII    — not covered
   ```

5. Summary badge:
   - All covered → green "Full coverage"
   - Any missing → yellow "Coverage incomplete" (warning, save still allowed)

6. Update reactively on every dropdown change — no page reload.

7. Standards with no code system (ISO 37001, ISO 37301): show the standard name with a
   ✓ if any qualified auditor is on the team, ✗ if not.

### Save blocking behavior — keep as-is

Do not change Stage 1 (warning, save allowed) vs Stage 2 (block if uncovered) behavior.
This is intentional — Stage 1 documentation review can proceed with a partial team; Stage 2
on-site audit requires full coverage.

---

## What NOT to change

- Do not modify `AuditorStandardQualification`, `Auditor` models, or any schemas
- Do not modify the bulk import endpoint
- Do not touch the auditor list page or profile page

---

## Verification

1. **Signing date**: Sign a document with date set to 15 May 2026 → displays "Signed 15 May 2026"

2. **Integrated audit dropdown**: Create or open an audit set with ISO 9001 (EA 3, EA 5)
   + ISO 22000 (CI). The lead auditor dropdown must include:
   - Auditors qualified for ISO 9001 with EA 3 (they cover EA 3)
   - Auditors qualified for ISO 9001 with EA 5 (they cover EA 5)
   - Auditors qualified for ISO 22000 with CI (they cover CI)
   All three groups appear in the same dropdown.

3. **Coverage panel**: Select one auditor with ISO 9001 EA 3 → panel shows ✓ EA 3, ✗ EA 5,
   ✗ CI. Add an auditor with ISO 9001 EA 5 → EA 5 turns ✓. Add an ISO 22000 CI auditor →
   CI turns ✓. Full coverage badge appears.

4. **FSMS-only audit**: Audit set with ISO 22000 (CI, CII). Dropdown shows auditors with
   food chain categories, not EA codes.
