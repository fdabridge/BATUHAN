# Comprehensive Platform Audit & Fix — Certiva for IFC Global

## Purpose

Conduct a thorough audit of the entire Certiva platform against the authoritative source documents listed below. For every item found to be wrong, incomplete, or inconsistent — fix it. For every item confirmed correct — document it as verified. This is not a visual review; it requires reading the actual source files and verifying logic against the IAF/ISO/IFC documents.

## Authoritative source documents (in the repository)

- `REFERENCE_ISO_IAF_Standards_Knowledge.md` — per-standard scope systems, audit time rules, food chain categories, TAs, K-factor, AB rules
- IAF MD 5:2023 — audit time for ISO 9001, ISO 14001, ISO 45001
- IAF MD 9:2023 Issue 5 — audit time and TA rules for ISO 13485
- IAF MD 11:2023 — integrated audit time reduction (max 20%, floor 50%)
- ISO 22003-1:2022 — food chain categories and audit time for ISO 22000 / FSSC 22000
- ISO 50003:2021 Tables A.3–A.4 — K-factor and audit time for ISO 50001
- ISO/IEC 27006-1:2024 Table C.1 — audit time for ISO 27001
- ISO 17021-1 — certification body requirements (stage ordering, impartiality, decision rules)
- UAF accreditation requirements (English documents)
- TÜRKAK accreditation requirements (Turkish documents)

---

## SECTION 1 — Calculation engine audit

File to review: `backend/calculator/engine.py`, `backend/calculator/tables.py`, `backend/calculator/models.py`

### 1.1 — Per-standard EPS and table lookup

Verify that each standard uses the correct effective person count (EPS) formula and looks up the correct table:

**ISO 9001, ISO 14001, ISO 45001 (IAF MD 5:2023):**
- EPS = total employees at HQ + shift workers (counted once per shift)
- Table lookup: separate tables for QMS, EMS, OHSMS
- Risk/significance modifier applied after table lookup
- Maximum table reduction: 30%

**ISO 22000 / FSSC 22000 (ISO 22003-1:2022 Annex B):**
- EPS = total personnel involved in food safety activities (NOT total company headcount)
- Time varies by food chain category — CI and CII are more audit-intensive than CIV
- FSSC 22000 adds mandatory separate reporting/preparation time: minimum 1.0 auditor-day (this is NOT on-site time — it is additional and must appear as a separate line item)
- Verify this FSSC surcharge is present in the calculation and clearly labelled

**ISO 13485 (IAF MD 9:2023 Annex B):**
- EPS based on total employees at site
- Separate table for number of Technical Areas (TAs) in scope
- A1.7-only (suppliers/components) has lighter time requirements

**ISO 50001 (ISO 50003:2021 Tables A.3–A.4):**
- K-factor formula: C = (FEC × 0.25) + (FET × 0.25) + (FSEU × 0.50)
- FEC thresholds: ≤20 TJ=1.0, 20–200=1.2, 200–2000=1.4, >2000=1.6
- FET thresholds: 1–2 types=1.0, 3=1.2, ≥4=1.4
- FSEU thresholds: 1–3=1.0, 4–6=1.2, 7–10=1.3, 11–15=1.4, ≥16=1.6
- Complexity: C<1.15=Low, 1.15≤C≤1.35=Medium, C>1.35=High
- Audit time from Table A.3 (initial) and A.4 (surveillance/recertification) using EPS + complexity level

**ISO 27001 (ISO/IEC 27006-1:2024 Table C.1):**
- Effective personnel count: MUST include freelancers and persons under organizational control even if not directly employed (2024 change from 27006-1:2024)
- Complexity factors applied: criticality of information, technology diversity (number of IT platforms), extent of outsourcing, multi-site scope
- Maximum reduction: 30%

**ISO 37001 / ISO 37301:**
- No fixed IAF MD 5 table — use ISO 17021-1 principles
- Derive from personnel count using a reasonable proportional estimate
- Label as "Estimated — no fixed IAF table" in the output

### 1.2 — Integration reduction (IAF MD 11:2023)

Only applies when 2 or more standards are audited together.

Verify the rates in `_MD11_RATES`:
- Low: 5% (separate systems, co-located only)
- Medium: 10% (shared processes, combined manual)
- High: 20% (fully integrated single management system — this is the ABSOLUTE CEILING per IAF MD 11)

Verify the 50% floor:
- After applying integration reduction, total combined time must be ≥ 50% of the sum of each standard's individual table time
- If floor is triggered, document it in the result with `md11_floor_applied: true`

Verify the engine does NOT apply integration reduction when only 1 standard is selected.

### 1.3 — Phase split and audit type outputs

The engine must produce correct time outputs for all four audit scenarios:

**Initial certification (2 stages):**
- Stage 1 (documentation review): ~1/3 of total initial audit time
- Stage 2 (on-site audit): ~2/3 of total initial audit time
- Stage 1 must complete before Stage 2 begins (ISO 17021-1 requirement)

**Surveillance (each visit, years 1 and 2 of 3-year cycle):**
- Single stage (on-site only — no Stage 1 for surveillance)
- Each surveillance visit ≥ 1/3 of the initial total audit time
- Cumulative time across both surveillance visits in the 3-year cycle must approximately equal the initial total
- First surveillance must be within 12 months of the certification decision date

**Recertification (end of 3-year cycle):**
- Treated similarly to Stage 2 alone (~2/3 of initial total)
- May include a Stage 1 element if significant changes have occurred
- Single stage unless CB decides Stage 1 is needed

**Transfer certification:**
- Similar to recertification — review of existing system, on-site audit
- No Stage 1 required unless CB policy requires it

Verify these outputs exist in `CalculationResult`: `final_ph1`, `final_ph2`, `final_surv1`, `final_recert`.

### 1.4 — Reporting deduction

Verify the 20% reporting/preparation time deduction is applied correctly and labelled. This is IFC Global's internal deduction for off-site preparation time, NOT the same as the FSSC 22000 mandatory reporting day.

---

## SECTION 2 — Audit type logic in audit set management

Files: `backend/audit_set/service.py`, `backend/audit_set/db_models.py`

### 2.1 — Stage structure per audit type

When an audit set is created with a given `audit_type`, the correct stage structure must be auto-generated:

| Audit Type | Stages to create |
|---|---|
| Initial certification | Stage 1 (stage_type="stage_1", stage_order=1) + Stage 2 (stage_type="stage_2", stage_order=2) |
| Surveillance 1 | Single stage (stage_type="surveillance", stage_order=1) |
| Surveillance 2 | Single stage (stage_type="surveillance", stage_order=2) |
| Recertification | Single stage (stage_type="stage_2", stage_order=1) — or two stages if Stage 1 review is included |
| Transfer | Single stage (stage_type="stage_2", stage_order=1) |

Verify: if `audit_type` is "surveillance", the UI must NOT show a Stage 1 card. Only one stage card (the surveillance visit) should appear.

Verify: if `audit_type` is "initial", two stage cards must appear — Stage 1 and Stage 2.

### 2.2 — Stage ordering constraint

Stage 1 end date must be before Stage 2 start date. If a user tries to set Stage 2 dates that overlap or precede Stage 1, the save must be blocked with a clear error message. This was previously implemented — verify it is still in place and working.

### 2.3 — Surveillance time assignment

When audit_type is "surveillance", the man-day time assigned to that stage should come from `final_surv1` in the calculation result, NOT from `final_ph1` or `final_ph2`. Verify the service correctly maps surveillance stages to the surveillance time output.

### 2.4 — Audit type label in the UI

The plan overview must show "Initial certification", "Surveillance 1", "Surveillance 2", "Recertification" — not raw strings like "initial" or "surveillance". Verify the frontend maps these correctly.

---

## SECTION 3 — Scope derivation and required codes

Files: `backend/audit_set/service.py` (derive-scope endpoint), frontend client detail page

### 3.1 — Derivation correctness per standard

Verify the `derive_required_scope()` function correctly maps client scope text to:
- EA codes (correct numbered codes from the official IAF list, EA 1–39)
- Food chain categories (BIII, C0, CI, CII, CIII, CIV, D, E, FI, FII, G, I, K)
- Medical device TAs (A1.1–A1.7, A2.1–A2.4)
- Energy complexity (Low/Medium/High from K-factor context)
- Sector (Public/Private/Third sector/NGO)

Test with: "Production of cakes, tortillas, gluten-free snacks, and sandwiches"
Expected result:
- ISO 9001 → EA 3, risk: High (food manufacturing is high-risk for QMS)
- ISO 22000 / FSSC 22000 → CIV (cakes, tortillas, snacks), CIII (sandwiches)

Test with: "Manufacture of orthopaedic implants and spinal fixation devices"
Expected result:
- ISO 9001 → EA 13 or EA 17, risk: High
- ISO 13485 → A1.2 (non-active implantable devices)

Test with: "Software development and IT consulting"
Expected result:
- ISO 9001 → EA 33, risk: Low
- ISO 27001 → EA 33

### 3.2 — Scope display on plan overview

After derivation, the required scope codes must be visible on the client detail page with correct visual styling:
- EA codes: grey/green chips
- Food chain categories: amber tags
- Medical TAs: purple tags
- Sector: blue badge
- Energy complexity / risk level: colored badge (green=Low, amber=Medium, red=High)

Verify the "Derive required scope" button works and updates the display immediately without a full page reload.

---

## SECTION 4 — Auditor qualification and matching

Files: `backend/auditors/extractor.py`, `backend/api/routes/auditors.py`, frontend auditors pages

### 4.1 — FR.201 extraction

Verify `extract_auditor_from_document()`:
- `max_tokens` is 8192 (not 2048 — the old value that caused truncation)
- The backfill function `_backfill_scope_categories()` receives the raw document text as a fallback haystack
- Per-standard `ea_codes` are extracted for ISO 9001, 14001, 45001, 27001, 50001
- `scope_category` is populated for ISO 22000/FSSC (food categories), ISO 13485 (TAs), ISO 37001/37301 (sector), ISO 50001 (complexity)
- Accreditation body names are validated — CB names (like "Certification Partner Global FZ LLC") are stripped, only genuine AB names (UAF, TÜRKAK, DAkkS, UKAS, ANAB etc.) are kept
- If extraction results in `accreditation_body: null`, the qualification is flagged with `_needs_review: true`

### 4.2 — Auditor profile display

On the auditor detail page, each qualification card must show:
- ISO 9001 / 14001 / 45001 / 27001 / 50001: EA code chips + risk/complexity badge from `scope_category`
- ISO 22000 / FSSC 22000: amber food chain category tags (CI, CIV, etc.) from `scope_category` — NO EA codes
- ISO 13485: purple TA tags (A1.1, A1.3, etc.) from `scope_category` — NO EA codes
- ISO 37001 / ISO 37301: blue sector badge (Private/Public/NGO) from `scope_category` — NO EA codes

Verify: food/medical/sector standards do NOT show an EA codes section. Verify: EA code standards do NOT show food category tags.

### 4.3 — Add/Edit auditor form — scope inputs

In the Add Auditor modal and the Edit Qualifications form on the auditor detail page:

- ISO 22000 / FSSC 22000: clickable amber buttons (BIII, C0, CI, CII, CIII, CIV, D, E, FI, FII, G, I, K) — multi-select — NO EA codes text input
- ISO 13485: clickable purple buttons (A1.1 through A2.4) — multi-select — NO EA codes text input
- ISO 37001 / ISO 37301: dropdown (Public / Private / Third sector/NGO) — NO EA codes text input
- ISO 50001: EA codes text input + energy complexity dropdown (Low / Medium / High)
- ISO 9001 / 14001 / 45001: EA codes text input + risk/significance dropdown (High / Medium / Low; ISO 14001 also has "Limited")
- ISO 27001: EA codes text input only

Verify: the same `ScopeInput` component (or equivalent) is used in BOTH the Add modal and the Edit form on the detail page — they must behave identically.

### 4.4 — Auditor availability and scope matching

The `/api/auditors/available` endpoint must:
- Accept `required_categories` param (JSON-encoded `required_scope` dict)
- For each auditor, compute `covered_scope`: which required codes/categories they personally cover
- Return `covered_scope` per auditor so the frontend can label the dropdown
- Exclude auditors who cover ZERO codes for ALL required standards (when `required_scope` is known)
- Unavailable auditors (date conflict) appear greyed out — they are NOT excluded, just deprioritized

### 4.5 — Stage planning auditor dropdown

Verify:
- Dropdown labels show auditor name + the specific codes they cover for THIS audit
- Auditors with zero coverage are excluded (not just greyed out) when `required_scope` is known
- For multi-standard audits, an auditor appears if they cover at least one standard's codes

### 4.6 — Team coverage validation

Verify:
- A live coverage panel below the auditor selectors shows per-code coverage status
- Stage 2 save is hard-blocked if any required code is uncovered by the team
- Stage 1 save shows an amber warning but is not hard-blocked
- The coverage check uses the TEAM collectively (lead auditor + all additional auditors + technical experts)

---

## SECTION 5 — Document generation (UAF and TÜRKAK)

Files: `backend/audit_set/` (document assembly logic), blank set templates

### 5.1 — Language routing

UAF accreditation: all generated documents must be in English. Verify that when `accreditation_body` is "UAF", the document templates used are the English-language UAF templates.

TÜRKAK accreditation: all generated documents must be in Turkish. Verify that when `accreditation_body` is "TÜRKAK" or "TURKAK", the document templates used are the Turkish-language TÜRKAK templates.

If an audit set covers both UAF and TÜRKAK (IFC Global is accredited by both), generate separate document sets: one English (UAF) and one Turkish (TÜRKAK).

### 5.2 — Document population

Verify that generated documents are populated with:
- Client name, address, certification scope (in the correct language)
- Standards being certified
- Audit dates (Stage 1, Stage 2 / surveillance)
- Lead auditor name and role
- Accreditation body name and reference number
- IFC Global name, logo, accreditation details

Do NOT verify specific document content or field accuracy in this audit (this will be tested separately). Only verify that the language routing logic is correctly implemented and that the documents are generated without errors.

### 5.3 — Download audit package

Verify the "Download audit package" button on the client detail page triggers document generation and returns a downloadable file (ZIP or PDF). Verify it does not throw a 500 error for a client with a complete audit set (standards, scope, stages, lead auditor assigned).

---

## SECTION 6 — Frontend consistency audit

### 6.1 — Standards label mapping

The system stores standards as labels: QMS, EMS, OHSMS, FSMS, ISMS, MDQMS, ABMS, ENMS, CMS.
These must be correctly mapped to ISO codes throughout the frontend:
- QMS → ISO 9001
- EMS → ISO 14001
- OHSMS → ISO 45001
- FSMS → ISO 22000 and/or FSSC 22000
- ISMS → ISO 27001
- MDQMS → ISO 13485
- ABMS → ISO 37001
- ENMS → ISO 50001
- CMS → ISO 37301

Verify: wherever a standard code is displayed to users (qualification cards, stage planning, dropdown labels), the ISO code is used — not the raw QMS/EMS label, except where the label is appropriate (e.g. the plan overview pills showing "QMS" "FSMS" are acceptable as a compact summary).

### 6.2 — Man-day section display

Verify the man-day calculation section on the client detail page shows:
- Whether it is open by default (it should be)
- Per-standard breakdown with the standard name, table reference, and individual time
- Integration reduction with the level label (Low 5% / Medium 10% / High 20%)
- Whether the 50% floor was applied (show this if `md11_floor_applied` is true)
- FSSC 22000 reporting surcharge as a separate line item
- Final Stage 1 and Stage 2 recommended durations
- Suggested start and end dates for each stage

### 6.3 — Audit type stage card structure

Verify:
- Initial certification: two stage cards (Stage 1 — Documentation review, Stage 2 — On-site audit)
- Surveillance: one stage card (Surveillance visit — no Stage 1)
- Recertification: one stage card
- Stage cards clearly show which stage they are in the header

---

## Deliverable

For each section above, report:
1. ✅ Confirmed correct — what was verified and how
2. ❌ Found wrong — what the issue is and what was fixed (with file name and change summary)
3. ⚠️ Partially correct — what works and what still needs attention

Fix all ❌ items in-place. Do not defer fixes to a follow-up task.
