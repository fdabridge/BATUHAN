# Pending Backend + Frontend Changes
## To implement after all document templates are edited

These changes were identified during the document editing session and must be implemented before the docxtpl filler is built. Give this file to Augment as context when writing the filler prompt.

---

## 1. New fields on AuditSet model

### `audit_language` (String, nullable)
- Stores the language the audit is conducted in (what auditor speaks with the auditee)
- Completely independent of accreditation body
- Default: derived from `country` using a country→language lookup at creation time
- Coordinator can override freely
- Examples: Turkey → "Turkish", Russia → "Russian", Bangladesh → "Bengali", USA → "English"
- **Migration needed:** `ALTER TABLE audit_sets ADD COLUMN audit_language VARCHAR`

### `document_language` (String, default "turkish")
- Already specified in `AUGMENT_PROMPT_resolver_rewrite.md`
- TÜRKAK only: "turkish" or "english"
- UAF always generates English documents regardless of this field
- **Migration needed:** `ALTER TABLE audit_sets ADD COLUMN document_language VARCHAR DEFAULT 'turkish'`

---

## 2. Frontend — Audit Set Creation Form

### Add `audit_language` field
- Show a text input or dropdown for "Audit Language" during audit set creation
- Pre-populate with the suggested value derived from `country` (call a backend endpoint or compute client-side from a country→language map)
- Coordinator can change it before saving
- Example: if company country is Turkey, pre-fill "Turkish"; coordinator changes to "English" if the audit will be conducted in English

### Add `document_language` selector for TÜRKAK
- Already specified in `AUGMENT_PROMPT_resolver_rewrite.md`
- Show only when `accreditation_body` is TÜRKAK/TURKAK
- Default: "turkish"
- Options: "Turkish" / "English"

### Add `is_special` audit type option
- **Why:** FR.229, FR.232, FR.232-1 contain a "Special Audit" checkbox row rendered via `{{ "☑" if is_special else "☐" }}`. If "special" is never a valid audit_type, this checkbox can never be ticked.
- **Frontend:** Add "Special Audit" as a fourth option in the Audit Type dropdown (alongside Initial, Surveillance, Recertification)
- **Backend:** `audit_type` column is already VARCHAR — no migration needed, just allow "special" as a value in validation
- **Filler:** compute `is_special = audit_type == "special"`

---

## 3. Render context builder — new computed fields

These fields must be computed and passed to every docxtpl render call. They do not all exist as stored DB fields — some are derived at render time.

### Basic display fields

| Placeholder | Computed as | Used in | Why it's in the Word doc |
|---|---|---|---|
| `{{ today }}` | `date.today()` formatted DD/MM/YYYY | All documents | Every form has a "Date" field pre-filled with today's date so the coordinator doesn't type it manually |
| `{{ standards_str }}` | Full standard names joined: `"ISO 9001:2015, ISO 14001:2015"` — map from standard codes (QMS→ISO 9001:2015 etc.) | All documents | Forms list the full standard names in their header rows |
| `{{ audit_type_display }}` | Human label: `"Initial Certification"` / `"Surveillance"` / `"Recertification"` / `"Special Audit"` | FR.223, FR.224, FR.225, FR.230 | Audit type appears in form headers and cover sheets as a human-readable string, not a code |
| `{{ is_initial }}` | `audit_type == "initial"` (boolean) | FR.229, FR.231, FR.231-1, FR.232, FR.232-1 | Checkbox rows: `{{ "☑" if is_initial else "☐" }}` — one row per audit type, only the matching one gets a filled box |
| `{{ is_surveillance }}` | `audit_type.startswith("surveillance")` (boolean) | FR.229, FR.232, FR.232-1 | Same checkbox rows |
| `{{ is_recertification }}` | `audit_type == "recertification"` (boolean) | FR.229, FR.231, FR.231-1, FR.232, FR.232-1 | Same checkbox rows |
| `{{ is_special }}` | `audit_type == "special"` (boolean) | FR.229, FR.232, FR.232-1 | Same checkbox rows — "Special Audit" is a valid IAF audit type triggered by complaints or major org changes |

**Backend integration:** All six booleans and the display string are pure filler-side computations — no DB change needed. Compute them at the top of every render call from `audit_set.audit_type`.

**Frontend input:** No new UI needed — these derive from the Audit Type dropdown that already exists.

---

### Date fields

| Placeholder | Computed as | Used in | Why it's in the Word doc |
|---|---|---|---|
| `{{ plan_date }}` | `stage.audit_date_start − 5 working days` (using `businesstimedelta` or `workdays` lib) | FR.223 | The audit plan must be sent to the company 5 working days before the audit starts — this pre-fills that date cell |
| `{{ notification_date }}` | `stage.audit_date_start − 2 calendar months` | FR.234 | UAF/ISO 17021 requires the formal audit notification to be sent 2 months before — this pre-fills that date field |
| `{{ audit_dates }}` | Formatted range string: `"10–12 June 2026"` from `audit_date_start` + `audit_date_end` | All stage documents | Every form header shows the audit date range |
| `{{ opening_meeting_date }}` | Initial/recert: Stage 1 `audit_date_start`. Surveillance: Surveillance `audit_date_start`. Formatted DD/MM/YYYY | FR.225 | The opening meeting register (FR.225) must record the exact meeting date |
| `{{ closing_meeting_date }}` | Initial/recert: Stage 2 `audit_date_end`. Surveillance: Surveillance `audit_date_end`. Formatted DD/MM/YYYY | FR.225 | The closing meeting register records the closing date |
| `{{ audit_date_end }}` | `stage.audit_date_end` formatted DD/MM/YYYY | FR.230 header | The nonconformity form header shows the last audit day |
| `{{ report_date }}` | `stage.audit_date_end + 1 calendar day`, formatted DD/MM/YYYY | FR.231, FR.231-1, FR.232, FR.232-1, FR.229 | Audit reports are issued the day after the audit ends — this pre-fills the report date on the cover page |
| `{{ stage2_start_date }}` | Stage 2's `audit_date_start` formatted DD/MM/YYYY | FR.231-1 (Stage 1 copy) | FR.231-1 Table 18 has a row "Date specified for Stage 2" — it shows the scheduled start of Stage 2 while the Stage 1 report is being issued |
| `{{ surv1_estimated_date }}` | Stage 2 `audit_date_end` + 1 year − 1 day | FR.222 | The audit plan table in FR.222 has an estimated date row for the 1st surveillance — pre-filled from the certification decision date |
| `{{ surv2_estimated_date }}` | `surv1_estimated_date` + 1 year − 1 day (initial/recert) OR current surveillance `audit_date_end` + 1 year − 1 day (surv_1) | FR.222 | Same table, estimated date for 2nd surveillance |
| `{{ recert_estimated_date }}` | `surv2_estimated_date` + 1 year − 1 day | FR.222 | Same table, estimated recertification date |
| `{{ stage1_dates }}` | Stage 1's `audit_date_start`–`audit_date_end` formatted range string | FR.222 | FR.222 shows both Stage 1 and Stage 2 dates so the client can see the full initial certification schedule |
| `{{ stage2_dates }}` | Stage 2's `audit_date_start`–`audit_date_end` formatted range string. Empty string if Stage 2 not yet scheduled. | FR.222 | Same table |

**Backend integration:** All date computations happen in `filler.py` at render time. `stage.audit_date_start` and `stage.audit_date_end` already exist on `AuditSetStage`. For working-day math use Python's `businesstimedelta` library or a simple loop. For surv/recert estimated dates, look up Stage 2 from the `AuditSet.stages` relationship by `stage_type == "stage_2"`.

**Frontend input:** No new UI needed — these derive from dates already entered on the audit set and stage.

---

### Audit language

| Placeholder | Computed as | Used in | Why it's in the Word doc |
|---|---|---|---|
| `{{ audit_language }}` | `audit_set.audit_language` (stored field, defaulted from country at creation) | FR.223, FR.224 | FR.223 Audit Plan Table has an "Audit Language" row that coordinators need to know so they can assign the right auditor. FR.224 (impartiality form) also declares the audit language. |

**Backend integration:** New `audit_language` VARCHAR column on `audit_sets` table (see Section 1 above).

**Frontend input:** New "Audit Language" field on audit set creation form, pre-populated via country→language lookup (see Section 6 below).

---

### Auditor scope display strings

Each auditor/TE on the stage has `covered_scope` data in the auditor DB. Build a display string from it for each person.

| Placeholder | Format | Example | Used in |
|---|---|---|---|
| `{{ lead_auditor_codes }}` | Codes grouped by standard, joined by ` \| ` | `EA 3 (ISO 9001) \| CIV CIII (ISO 22000)` | FR.223, FR.224 |
| `{{ auditors[n].covered_codes_display }}` | Same format for each additional auditor | `EA 3 (ISO 9001)` | FR.223, FR.224 |
| `{{ technical_experts[n].covered_codes_display }}` | Same for each TE | `A1.1 A2.1 (ISO 13485)` | FR.223, FR.224 |

**Why it's in the Word doc:** FR.223 (Audit Plan) Table contains one row per team member listing their scope authorization codes. The form must show what each person is authorized to audit so the client can verify auditor competence.

**Backend integration:** Query the auditor's `covered_scope` from the Auditor model. Build `covered_codes_display` in `filler.py`. The auditor IDs are already stored in `AuditSetStage.lead_auditor_id` and `AuditSetStage.auditors` JSON.

**Frontend input:** No new UI needed — scope data comes from the existing auditor profiles.

---

### Personnel flat fields

| Placeholder | Computed as | Used in | Why it's in the Word doc |
|---|---|---|---|
| `{{ total_employees }}` | `personnel["full_time"] + personnel["part_time"] + personnel.get("unskilled", 0)` | FR.229, FR.231, FR.231-1, FR.232, FR.232-1 | The General Information table on every report includes a "Total Employees" row — pre-filling from the DB saves the auditor from typing it on-site |
| `{{ subcontractors }}` | `personnel["subcontractors"]` | FR.229, FR.231, FR.231-1, FR.232, FR.232-1 | Same table has a "Subcontractors" row |
| `{{ shift_count }}` | `personnel["shift_count"]` | FR.222, FR.223 | Man-day calculation table and audit plan both show the number of shifts |
| `{{ office_employees }}` | `personnel["office_employees"]` (see Section 4 below — must be written back after calculator runs) | FR.218 | FR.218 Table 14 (man-day calculation detail) has "Office/Management Employees" row |
| `{{ repetitive_employees }}` | `personnel["repetitive_employees"]` (see Section 4 below) | FR.218 | Same table has "Repetitive-Process Employees" row |

**Backend integration:** `total_employees`, `subcontractors`, and `shift_count` are pure filler-side extractions from the existing `personnel` JSON — no DB change needed. `office_employees` and `repetitive_employees` require the write-back described in Section 4.

**Frontend input:** No new UI needed — these come from fields already collected in the audit set form.

---

### Integration percentage

| Placeholder | Computed as | Used in | Why it's in the Word doc |
|---|---|---|---|
| `{{ integration_pct }}` | `round(sum(1 for v in integration_level.values() if v) / 8 * 100)` | FR.218 | FR.218 Table 18 has an "Integration Level (%)" cell. The 8 integration criteria are already stored as booleans in `audit_set.integration_level` JSON. |

**Backend integration:** Pure filler-side computation. `integration_level` JSON already exists on `AuditSet`.

**Frontend input:** No new UI needed — the 8 integration checkboxes are already collected.

---

### Site-level aggregated fields

| Placeholder | Computed as | Used in | Why it's in the Word doc |
|---|---|---|---|
| `{{ site_addresses }}` | `"\n".join(s["address"] for s in sites)` | FR.221 | FR.221 has a multi-line text area for all site addresses — newline-joined produces a clean list |
| `{{ enms_energy_tj }}` | `sum(s.get("energy_tj", 0) for s in sites)` | FR.218 Table 21 | The EnMS complexity table requires total annual energy consumption across all sites |
| `{{ enms_energy_types }}` | `max(s.get("energy_types", 0) for s in sites)` — or sum, per IAF guidance | FR.218 Table 21 | Number of energy types — IAF uses the site with most types |
| `{{ enms_seu_count }}` | `sum(s.get("seu_count", 0) for s in sites)` | FR.218 Table 21 | Number of Significant Energy Uses (SEUs) — summed across sites |

**Backend integration:** Pure filler-side aggregations over `audit_set.sites` JSON array — no DB change needed.

**Frontend input:** `energy_tj`, `energy_types`, and `seu_count` are already collected per-site in the Sites section of the audit set form.

---

### Audit duration fields (for FR.221)

| Placeholder | Computed as | Used in | Why it's in the Word doc |
|---|---|---|---|
| `{{ stage_1_days }}` | Stage 1's `audit_days` from `AuditSetStage` | FR.221 | FR.221 Summary table has rows for Stage 1 audit duration (person-days) |
| `{{ stage_2_days }}` | Stage 2's `audit_days` from `AuditSetStage` | FR.221 | Same table, Stage 2 row |
| `{{ surv_days }}` | `man_day_result["final_surv1"]` from `CalculationResult` | FR.221 | Same table, Surveillance row |

**Backend integration:** Look up Stage 1 and Stage 2 `AuditSetStage` records from `AuditSet.stages` relationship by `stage_type`. `man_day_result` is already stored as JSON on `AuditSet`. All pure filler-side lookups — no DB change needed.

**Frontend input:** No new UI needed — `audit_days` is already on stages, `final_surv1` comes from the calculator.

---

### Fee alias

| Placeholder | Computed as | Used in | Why it's in the Word doc |
|---|---|---|---|
| `{{ initial_fee }}` | `audit_set.certification_fee` (alias — same value, different name) | FR.220, FR.221 | FR.220 and FR.221 have a "Certification Fee" field. The template uses `initial_fee` as the placeholder name; the DB column is `certification_fee`. The filler must alias it. |

**Backend integration:** `filler.py` adds `initial_fee = audit_set.certification_fee` to the context dict. No DB change needed.

**Frontend input:** No new UI needed — certification_fee is already collected.

---

### Per-standard man-day result objects

FR.218 Table 22 shows a row per standard with the detailed calculation breakdown. The filler must extract each standard's `StandardAuditResult` from the `man_day_result["standard_results"]` list and expose them as named variables.

| Placeholder | Computed as | Used in |
|---|---|---|
| `{{ man_day_result_qms }}` | `StandardAuditResult` where `standard == "ISO 9001:2015"` (or None if not in scope) | FR.218 |
| `{{ man_day_result_ems }}` | `standard == "ISO 14001:2015"` | FR.218 |
| `{{ man_day_result_ohsms }}` | `standard == "ISO 45001:2018"` | FR.218 |
| `{{ man_day_result_fsms }}` | `standard == "ISO 22000:2018"` | FR.218 |
| `{{ man_day_result_isms }}` | `standard == "ISO/IEC 27001:2022"` | FR.218 |
| `{{ man_day_result_mdqms }}` | `standard == "ISO 13485:2016"` | FR.218 |
| `{{ man_day_result_abms }}` | `standard == "ISO 37001:2016"` | FR.218 |
| `{{ man_day_result_enms }}` | `standard == "ISO 50001:2018"` | FR.218 |

**Why it's in the Word doc:** FR.218's man-day calculation table has one row per applicable standard, each showing base days, site additions, phase 1/2 split, surveillance days etc. The template uses `{%tr if man_day_result_qms %}...{%tr endif %}` around each row so rows for standards not in scope collapse automatically.

**Backend integration:** In `filler.py`, parse `man_day_result["standard_results"]` (already stored as JSON on `AuditSet`) into a dict keyed by standard code. Set each `man_day_result_xxx` variable to the matching dict or `None`. The template `{%tr if %}` handles the None case.

**Frontend input:** No new UI needed — standards are already selected when creating the audit set, and the calculator populates `man_day_result`.

---

### Per-person standard + clause lists (FR.224 and FR.211)

These are computed per render call (one call per team member).

| Placeholder | Description |
|---|---|
| `{{ assessed_person_name }}` | Name of the person this specific copy of FR.224 or FR.211 belongs to |
| `{{ person_standards }}` | List of standard full names this person covers: `["ISO 9001:2015", "ISO 22000:2018"]` |
| `{{ person_clauses }}` | Matching list of clause strings, filtered to current stage type (see clause lookup table below) |

**Why it's in the Word doc:** FR.224 (Impartiality Declaration) has a table where each team member lists the specific standards and clauses they are responsible for. FR.211 (Client Assessment Form) similarly names the person being assessed. Both forms are generated once per team member, with only the person-specific fields changing.

**Backend integration:** `filler.py` loops over `[lead_auditor] + auditors + technical_experts` for the stage. For each person, it looks up their `covered_standards` from the auditor profile and filters clauses from the `STAGE_CLAUSES` lookup dict (hardcoded — see below).

**Frontend input:** No new UI needed — covered standards come from auditor profiles already in the system.

### Clause lookup table (hardcoded in filler.py)

```python
STAGE_CLAUSES = {
    ("ISO 9001:2015", "stage_1"):      "4.1-4.2-4.3-4.4 / 5.2-5.3 / 6.1-6.2 / 7.1-7.2-7.3-7.4-7.5 / 8.1 / 9.2 / 9.3 / 10.1",
    ("ISO 9001:2015", "stage_2"):      "4.1-4.2-4.3-4.4 / 5.1-5.2-5.3 / 6.1-6.2-6.3 / 7.1-7.2-7.3-7.4-7.5 / 8.1-8.2-8.3-8.4-8.5-8.6-8.7 / 9.1-9.2-9.3 / 10.1-10.2-10.3",
    ("ISO 9001:2015", "surveillance"): "4.1-4.2-4.3 / 5.1-5.2-5.3 / 6.1-6.2-6.3 / 7.1-7.3-7.5 / 8.2-8.4-8.5-8.6-8.7 / 9.1-9.2-9.3 / 10.1-10.2-10.3",
    # Repeat for ISO 14001:2015, ISO 45001:2018, ISO 22000:2018, ISO/IEC 27001:2022, ISO 50001:2018, ISO 13485:2016, ISO 37001:2016
    # Pull exact clause strings from FR.222's pre-printed rows (already verified correct)
}
```

---

## 4. Write office_employees and repetitive_employees back to personnel JSON

**Why:** FR.218 Table 14 (the man-day calculation detail sheet) has rows for "Office/Management Employees" and "Repetitive-Process Employees." These values are extracted from the company form during the calculator run (`ExtractedFormData.office_employees` and `ExtractedFormData.repetitive_employees`) and used to compute the final man-day count — but they are NOT currently written back to `AuditSet.personnel`. The filler needs them at render time, but they're lost after the calculator finishes.

**Backend integration:**

In `backend/calculator/service.py` (or wherever `CalculationResult` is saved back to `AuditSet`), after the calculation completes, merge these two values into the `personnel` JSON:

```python
audit_set.personnel["office_employees"] = extracted_form.office_employees
audit_set.personnel["repetitive_employees"] = extracted_form.repetitive_employees
# or update the JSON column directly via SQLAlchemy
```

No new DB column needed — the `personnel` JSON can hold arbitrary keys.

**Frontend input:** No new UI needed — the user already enters these via the calculator form. The write-back is purely a backend task.

---

## 5. Extend CalculationResult / StandardAuditResult with EnMS and ISMS detail fields

These variables are used in FR.218 for the detailed EnMS breakdown (Table 21) and ISMS complexity (Table 22), but the `CalculationResult` model does not currently expose them.

### EnMS range brackets and complexity factors (add to CalculationResult)

| Variable | What it is | Why it's in the Word doc |
|---|---|---|
| `{{ enms_range_ec }}` | IAF range bracket label for annual energy consumption (e.g., "≥ 10 TJ and < 100 TJ") | FR.218 Table 21 column "IAF Range" for energy consumption row |
| `{{ enms_range_et }}` | IAF range bracket label for number of energy types | FR.218 Table 21 "IAF Range" for energy types row |
| `{{ enms_range_seu }}` | IAF range bracket label for SEU count | FR.218 Table 21 "IAF Range" for SEUs row |
| `{{ enms_fec }}` | Complexity factor for energy consumption (FEC value, e.g., 1.0 / 1.5 / 2.0) | FR.218 Table 21 "Complexity Factor" column |
| `{{ enms_fet }}` | Complexity factor for energy types (FET value) | FR.218 Table 21 |
| `{{ enms_fseu }}` | Complexity factor for SEUs (FSEU value) | FR.218 Table 21 |

**Backend integration:** The calculator already derives `enms_complexity` (Low/Medium/High). It must also compute and store the three factor values and three range bracket strings. Add fields to `CalculationResult` Pydantic model:

```python
enms_range_ec: Optional[str] = None
enms_range_et: Optional[str] = None
enms_range_seu: Optional[str] = None
enms_fec: Optional[float] = None
enms_fet: Optional[float] = None
enms_fseu: Optional[float] = None
```

Populate them in the EnMS calculation logic (wherever `enms_k` and `enms_complexity` are currently set). The IAF ranges and factor values are fixed lookup tables from IAF MD 6.

**Frontend input:** No new UI needed — these are computed from `energy_tj`, `energy_types`, and `seu_count` already collected in the Sites form.

---

### FSMS HACCP addition (add to StandardAuditResult)

| Variable | What it is | Why it's in the Word doc |
|---|---|---|
| `{{ man_day_result_fsms.haccp_addition }}` | Additional man-days for HACCP studies (TH) | FR.218 Table 22's FSMS row has a "HACCP Addition" column. The form pre-fills how many extra days were added due to the number of HACCP studies. |

**Backend integration:** Add `haccp_addition: Optional[float] = None` to `StandardAuditResult`. Populate it in the FSMS calculation branch (where `haccp_studies` from `ExtractedFormData` is currently used to compute extra days). Store the computed addition value, not just the final total.

**Frontend input:** No new UI needed — `haccp_studies` is already collected in the calculator form. The addition value is purely computed.

---

### ISMS complexity scores (add to CalculationResult)

| Variable | What it is | Why it's in the Word doc |
|---|---|---|
| `{{ man_day_result_isms.isms_business_score }}` | ISMS business complexity score (numeric, e.g., 3 of 5) | FR.218 Table 22's ISMS row has a "Business Complexity Score" sub-column. Shows the auditor how complex the client's business environment is. |
| `{{ man_day_result_isms.isms_it_score }}` | ISMS IT complexity score (numeric) | Same table, "IT Complexity Score" sub-column. |

**Backend integration:** Add `isms_business_score: Optional[int] = None` and `isms_it_score: Optional[int] = None` to `CalculationResult`. Populate them in the ISMS calculation branch. They likely already exist as intermediate variables — just expose them in the result model and persist to the JSON.

**Frontend input:** No new UI needed — these are computed from inputs already collected by the ISMS calculator questions.

---

## 6. FR.224 — One copy per team member

FR.224 must be rendered once per person, not once per stage.

**Who gets a copy:** Lead auditor + each additional auditor + each technical expert.
**Observers do NOT get a copy** (no audit responsibility, no impartiality obligation).

The ZIP output for a stage with 1 lead + 2 auditors + 1 TE should contain:
```
Stage_1/
  FR.224_LeadAuditorName.docx
  FR.224_Auditor1Name.docx
  FR.224_Auditor2Name.docx
  FR.224_TechnicalExpert1Name.docx
  FR.223_...docx
  FR.231_...docx
  ...
```

For each copy the render context gets:
- `assessed_person_name` = this person's name
- `person_standards` = list of standards they cover
- `person_clauses` = matching clause strings for this stage type
- Everything else (company info, full team list, dates) stays the same across all copies

---

## 7. FR.211 — One copy per team member being assessed

FR.211 (Lead Auditor/Auditor Assessment Form) is filled BY the client organization ABOUT each audit team member. So:
- If stage has lead + 2 additional auditors + 1 TE → generate 4 copies of FR.211
- Each copy pre-fills `assessed_person_name` with the team member being rated
- The client fills the rating section on-site

**Who gets assessed:** Lead auditor + additional auditors + technical experts.
**Observers do NOT get a copy.**

---

## 8. Country → Language default

At audit set creation time, derive a default `audit_language` from `country`. Use the `pycountry` library or a simple lookup:

```python
COUNTRY_LANGUAGE = {
    "Turkey": "Turkish",
    "Türkiye": "Turkish",
    "Russia": "Russian",
    "Bangladesh": "Bengali",
    "United States": "English",
    "United Kingdom": "English",
    "Germany": "German",
    "France": "French",
    # Add as needed — this is a default suggestion only, coordinator overrides
}

def default_audit_language(country: str) -> str:
    return COUNTRY_LANGUAGE.get(country, "English")  # English fallback
```

---

## 9. Summary of files to change

| File | Change |
|---|---|
| `backend/audit_set/db_models.py` | Add `audit_language` and `document_language` columns; allow `"special"` as `audit_type` value |
| `backend/audit_set/schemas.py` | Add both fields to Create/Update/Response schemas |
| `backend/audit_set/service.py` | At creation: compute `audit_language` default from `country`; validate `audit_type` includes `"special"` |
| `backend/audit_set/resolver.py` | Already handled in `AUGMENT_PROMPT_resolver_rewrite.md` |
| `backend/audit_set/filler.py` *(new file)* | docxtpl render context builder + per-document render logic — implements ALL computed fields in this document |
| `backend/api/routes/audit_sets.py` | `build_audit_set_zip()` calls new filler instead of old field_maps |
| `backend/calculator/models.py` | Add `enms_range_ec/et/seu`, `enms_fec/fet/fseu`, `isms_business_score`, `isms_it_score` to `CalculationResult`; add `haccp_addition` to `StandardAuditResult` |
| `backend/calculator/service.py` | Populate new `CalculationResult` fields; write `office_employees` + `repetitive_employees` back to `AuditSet.personnel` JSON after calculation |
| `frontend/.../audit-set-form` | Add `audit_language` field (pre-filled from country); add `document_language` selector for TÜRKAK; add `"Special Audit"` option to audit type dropdown |
