# Template Audit Report — UAF Blank Set Copy
## Comprehensive placeholder check vs DB model + UI

---

## 🔴 CATEGORY A — Template Bugs: Wrong Checkbox Syntax (Fix in Word NOW)

These placeholders have **both branches returning the same value** so the checkbox never changes regardless of condition. Must be fixed before moving to TÜRKAK.

### FR.218 — Table 21 (EnMS complexity level)
| Wrong | Correct |
|---|---|
| `{{ "" if man_day_result.enms_complexity == "High" else "" }}` | `{{ "☑" if man_day_result.enms_complexity == "High" else "☐" }}` |
| `{{ "" if man_day_result.enms_complexity == "Medium" else "" }}` | `{{ "☑" if man_day_result.enms_complexity == "Medium" else "☐" }}` |
| `{{ "" if man_day_result.enms_complexity == "Low" else "" }}` | `{{ "☑" if man_day_result.enms_complexity == "Low" else "☐" }}` |

### FR.220 — Standard checkboxes + audit type checkboxes
| Wrong | Correct |
|---|---|
| `{{ "" if "QMS" in standards else "" }}` | `{{ "☑" if "QMS" in standards else "☐" }}` |
| `{{ "" if "EMS" in standards else "" }}` | `{{ "☑" if "EMS" in standards else "☐" }}` |
| `{{ "" if "OHSMS" in standards else "" }}` | `{{ "☑" if "OHSMS" in standards else "☐" }}` |
| `{{ "" if "FSMS" in standards else "" }}` | `{{ "☑" if "FSMS" in standards else "☐" }}` |
| `{{ "" if "ISMS" in standards else "" }}` | `{{ "☑" if "ISMS" in standards else "☐" }}` |
| `{{ "" if "MDQMS" in standards else "" }}` | `{{ "☑" if "MDQMS" in standards else "☐" }}` |
| `{{ "" if "ABMS" in standards else "" }}` | `{{ "☑" if "ABMS" in standards else "☐" }}` |
| `{{ "" if "ENMS" in standards else "" }}` | `{{ "☑" if "ENMS" in standards else "☐" }}` |
| `{{ "" if is_initial or is_surveillance else "" }}` | `{{ "☑" if is_initial or is_surveillance else "☐" }}` |
| `{{ "" if is_recertification else "" }}` | `{{ "☑" if is_recertification else "☐" }}` |

### FR.221 — Standard checkboxes
Same corrections as FR.220 for all `{{ "" if "XXX" in standards else "" }}` patterns.

### FR.229, FR.231, FR.231-1, FR.232, FR.232-1 — Audit type checkboxes
| Wrong | Correct |
|---|---|
| `{{ " " if is_initial else " " }}` | `{{ "☑" if is_initial else "☐" }}` |
| `{{ " " if is_surveillance else " " }}` | `{{ "☑" if is_surveillance else "☐" }}` |
| `{{ "" if is_recertification else "" }}` | `{{ "☑" if is_recertification else "☐" }}` |
| `{{ "" if is_special else "" }}` | `{{ "☑" if is_special else "☐" }}` |

---

## 🔴 CATEGORY B — Template Bugs: Missing Site Conditionals (Fix in Word NOW)

These site address cells will **crash at render time** if the company has fewer than 3 sites — they access index 1 and 2 without a `{%tr if %}` guard.

Affected files: **FR.229, FR.232, FR.232-1**

| Wrong | Correct |
|---|---|
| Row with `{{ sites[1].address }}` (no guard) | First cell: `{%tr if sites\|length > 1 %}{{ sites[1].address }}` · Last cell: `{%tr endif %}` |
| Row with `{{ sites[2].address }}` (no guard) | First cell: `{%tr if sites\|length > 2 %}{{ sites[2].address }}` · Last cell: `{%tr endif %}` |

---

## 🟡 CATEGORY C — Naming Mismatches: Template vs DB (Fix in filler aliases OR in Word)

The sites JSON in the DB (`AuditSet.sites`) has these exact field names: `address`, `process_description`, `employee_count`, `energy_tj`, `energy_types`, `seu_count`. Templates use different names in some places.

| Template uses | DB field name | Fix |
|---|---|---|
| `sites[n].employees` (FR.222) | `employee_count` | Change template to `{{ sites[0].employee_count }}` |
| `sites[n].process` (FR.223, FR.224) | `process_description` | Change template to `{{ sites[0].process_description }}` |
| `sites[n].scope` (FR.222) | Does not exist per site | Replace with `{{ scope_en }}` (audit-level scope applies to all sites) |
| `subcontractors` (FR.229, FR.231, FR.231-1, FR.232, FR.232-1) | `personnel.subcontractors` | Filler flattens: `subcontractors = personnel["subcontractors"]` |
| `shift_count` (FR.222, FR.223) | `personnel.shift_count` | Filler flattens: `shift_count = personnel["shift_count"]` |
| `initial_fee` (FR.220, FR.221) | `certification_fee` | Filler alias: `initial_fee = audit_set.certification_fee` |

---

## 🟡 CATEGORY D — Missing Computed Fields (Filler must build these — data exists in DB)

These variables don't exist directly in the DB but can be computed from what is stored. All are filler responsibility.

| Variable | How to compute |
|---|---|
| `today` | `date.today()` formatted DD/MM/YYYY |
| `standards_str` | `", ".join(standards)` with full names e.g. "ISO 9001:2015, ISO 14001:2015" |
| `audit_type_display` | Human label: "Initial Certification" / "Surveillance" / "Recertification" |
| `is_initial` | `audit_type == "initial"` |
| `is_surveillance` | `audit_type.startswith("surveillance")` |
| `is_recertification` | `audit_type == "recertification"` |
| `audit_dates` | `f"{stage.audit_date_start.strftime('%d/%m/%Y')} – {stage.audit_date_end.strftime('%d/%m/%Y')}"` |
| `audit_date_end` | `stage.audit_date_end` formatted DD/MM/YYYY |
| `report_date` | `stage.audit_date_end + 1 calendar day` formatted DD/MM/YYYY |
| `plan_date` | `stage.audit_date_start − 5 working days` formatted DD/MM/YYYY |
| `notification_date` | `stage.audit_date_start − 2 months` formatted DD/MM/YYYY |
| `opening_meeting_date` | Stage 1 `audit_date_start` (initial/recert) or Surv `audit_date_start` |
| `closing_meeting_date` | Stage 2 `audit_date_end` (initial/recert) or Surv `audit_date_end` |
| `stage1_dates` | Stage 1's formatted date range |
| `stage2_dates` | Stage 2's formatted date range (empty if not scheduled) |
| `stage2_start_date` | Stage 2's `audit_date_start` formatted DD/MM/YYYY |
| `surv1_estimated_date` | Stage 2 `audit_date_end` + 1 year − 1 day |
| `surv2_estimated_date` | Surv1 estimated + 1 year − 1 day |
| `recert_estimated_date` | Surv2 estimated + 1 year − 1 day |
| `total_employees` | `personnel["full_time"] + personnel["part_time"] + personnel.get("unskilled", 0)` |
| `integration_pct` | Count of True values in integration_level / 8 × 100 |
| `site_addresses` (FR.221) | Newline-joined list of all `sites[n].address` |
| `stage_1_days` (FR.221) | Stage 1's `audit_days` |
| `stage_2_days` (FR.221) | Stage 2's `audit_days` |
| `surv_days` (FR.221) | `man_day_result.final_surv1` |
| `risk_category` (FR.222) | Already stored in `audit_set.risk_category` — just pass it |
| `complexity_category` (FR.222) | Extract from `man_day_result.standard_results` for EMS/OHSMS |
| `man_day_result_qms/ems/ohsms/fsms/isms/mdqms/abms/enms` | Extract from `man_day_result["standard_results"]` list by matching standard name |
| `lead_auditor_codes` | Build `covered_codes_display` for the lead auditor from auditor DB |
| `auditors[n].covered_codes_display` | Build from auditor's scope data in auditor DB |
| `technical_experts[n].covered_codes_display` | Same |

---

## 🔴 CATEGORY E — Missing DB Fields + UI Inputs (New fields needed in model AND Certiva UI)

These variables reference data that is **not currently collected anywhere in the application**.

### E1. `audit_language` — ALREADY IN PENDING_CHANGES
- What: Language the audit is conducted in (e.g. "Turkish", "Russian", "Bengali")
- Where needed: FR.222, FR.223
- UI task: Add "Audit Language" text input to audit set creation form, pre-filled from country lookup
- DB task: `ALTER TABLE audit_sets ADD COLUMN audit_language VARCHAR`

### E2. `is_special` audit type — NOT IN SYSTEM AT ALL
- What: A "Special Audit" triggered by complaints, significant company changes, or regulatory investigation
- Where needed: FR.229, FR.232, FR.232-1 (checkbox row)
- UI task: Add "Special Audit" as a valid `audit_type` option
- DB task: `audit_type` column already VARCHAR — just allow "special" as a value
- Filler task: Add `is_special = audit_type == "special"` computed variable

### E3. `sites[n].audit_days` — NOT STORED PER SITE
- What: Audit duration for a specific site (FR.222 shows per-site audit duration)
- Where needed: FR.222 site table's Audit Duration column
- Options:
  - A) Add `audit_days` to each site JSON object in the UI (complex)
  - B) Leave the Audit Duration column blank and fill manually (simpler)
- **Recommendation:** Leave blank (MANUAL) for now. Remove `{{ sites[0].audit_days }}` from FR.222 and replace with empty cell.

### E4. `personnel.office_employees` and `personnel.repetitive_employees` — EXTRACTED BY CALCULATOR BUT NOT STORED BACK
- What: The calculator's `ExtractedFormData` has `office_employees` and `repetitive_employees` but these are NOT written back to `AuditSet.personnel` JSON
- Where needed: FR.218
- DB task: Store `office_employees` and `repetitive_employees` back into `personnel` JSON when calculator runs, or add as separate columns
- UI task: None (calculated automatically)

---

## 🟠 CATEGORY F — Missing Calculator Outputs (CalculationResult model needs extending)

These variables are used in FR.218 for the detailed EnMS and ISMS breakdown, but the `CalculationResult` model does not currently expose them.

| Variable | What it is | Fix |
|---|---|---|
| `enms_range_ec` | IAF range bracket for annual energy consumption | Add to CalculationResult or compute in filler from raw values |
| `enms_range_et` | IAF range bracket for number of energy types | Same |
| `enms_range_seu` | IAF range bracket for SEU count | Same |
| `enms_fec` | Complexity factor for energy consumption (FEC) | Add to CalculationResult |
| `enms_fet` | Complexity factor for energy types (FET) | Add to CalculationResult |
| `enms_fseu` | Complexity factor for SEUs (FSEU) | Add to CalculationResult |
| `man_day_result_fsms.haccp_addition` | Additional man-days for HACCP studies (TH) | Add to StandardAuditResult or CalculationResult |
| `man_day_result_isms.isms_business_score` | ISMS business complexity score | Add to CalculationResult |
| `man_day_result_isms.isms_it_score` | ISMS IT complexity score | Add to CalculationResult |

---

## ✅ CATEGORY G — Variables That Are Fine (confirmed in DB or trivially computable)

`company_name`, `company_address`, `phone`, `email`, `website`, `representative`, `scope_en`, `non_applicable_clauses`, `ea_code`, `ea_category`, `ea_technical_area`, `effective_employees`, `plan_number`, `certification_fee`, `surveillance_fee`, `scope_integration_level`, `lead_auditor_name`, `audit_days`, `standards` (list), `integration_level` (JSON with all 8 keys), `man_day_result` (CalculationResult JSON), `auditors` (JSON list with name/standard fields), `technical_experts`, `observers`, `personnel` (JSON with all shift/count fields)

---

## Summary: What to Do Right Now

### Fix in Word immediately (before TÜRKAK):
1. **FR.218:** Fix 3 EnMS checkbox lines (Category A)
2. **FR.220:** Fix 10 checkbox lines — all standard + audit type checkboxes (Category A)
3. **FR.221:** Fix 7 standard checkbox lines (Category A)
4. **FR.229, FR.231, FR.231-1, FR.232, FR.232-1:** Fix audit type checkbox lines (Category A)
5. **FR.229, FR.232, FR.232-1:** Add `{%tr if %}` guards to site rows 2 and 3 (Category B)
6. **FR.222:** Change `sites[0].employees` → `sites[0].employee_count`, remove `sites[n].scope` or replace with `scope_en`, remove `sites[n].audit_days` (leave cell empty) (Category C)
7. **FR.223, FR.224:** Change `sites[0].process` → `sites[0].process_description` (Category C)

### Add to PENDING_CHANGES (backend/frontend tasks):
1. `audit_language` field + UI input (already there)
2. `is_special` audit type — add to allowed audit_type values + UI dropdown
3. Store `office_employees` + `repetitive_employees` back to personnel JSON after calculator runs
4. Extend `CalculationResult` model with EnMS factors (enms_fec/fet/fseu, ranges) and ISMS scores and FSMS haccp_addition
5. Filler computed variables list (Category D) — all must be implemented in `filler.py`
