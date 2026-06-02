# FR.218 & FR.231-1 Filling Guide

---

# FR.218 — Application Review Form

FR.218 is filled at application/planning time by the coordinator. It has 26 tables.  
Legend: **[AUTO]** = placeholder from system data · **[MANUAL]** = filled by coordinator · **[CALC]** = from `man_day_result` JSON

---

## TABLE 0 — General Info

| Row label | Action | Placeholder |
|---|---|---|
| Review Date | AUTO | `{{ today }}` |
| Organization | AUTO | `{{ company_name }}` |
| Address | AUTO | `{{ company_address }}` |
| Standards | AUTO | `{{ standards_str }}` |
| Is there an existing management system? | MANUAL | — |
| How long has it been implemented? | MANUAL | — |
| Stage 1 Audit: On-site / Office | MANUAL checkbox | — |

---

## TABLE 1 — Personnel

| Row label | Cell | Action | Placeholder |
|---|---|---|---|
| Number of office personnel | value | AUTO | `{{ personnel.office_employees }}` |
| Number performing repetitive tasks | value | AUTO | `{{ personnel.repetitive_employees }}` |
| Number of subcontracted employees | value | AUTO | `{{ personnel.subcontractors }}` |
| Number of seasonal employees | value | AUTO | `{{ personnel.seasonal }}` |
| Is same job performed in each shift? Y/N | value | AUTO | `{{ "Y" if personnel.shift_same_process else "N" }}` |
| Number per shift — 1. Shift | value | AUTO | `{{ personnel.shift_1_count }}` |
| Number per shift — 2. Shift | value | AUTO | `{{ personnel.shift_2_count }}` |
| Number per shift — 3. Shift | value | AUTO | `{{ personnel.shift_3_count }}` |
| Shift to be reviewed | value | MANUAL | — |
| Number of Sites | value | AUTO | `{{ sites\|length }}` |
| Number of Sites to be Assessed | value | AUTO | `{{ sites\|length }}` |
| Total number of employees | value | AUTO | `{{ total_employees }}` |
| Number of Effective Employee | value | AUTO | `{{ effective_employees }}` |

> `total_employees` and `office_employees` / `repetitive_employees` are computed by the filler from the personnel JSON. See PENDING_CHANGES.

---

## TABLE 2 — Site Addresses

Header row (Site Addresses / Reason for Selection / Number of Employees / Audit Duration) — do not touch.

| Row | Site Address cell | Reason cell | Employees cell | Duration cell |
|---|---|---|---|---|
| Row 1 | `{{ sites[0].address }}` | MANUAL | `{{ sites[0].employee_count }}` | MANUAL |
| Row 2 | `{%tr if sites\|length > 1 %}{{ sites[1].address }}` | MANUAL | `{{ sites[1].employee_count }}` | `MANUAL{%tr endif %}` |
| Row 3 | `{%tr if sites\|length > 2 %}{{ sites[2].address }}` | MANUAL | `{{ sites[2].employee_count }}` | `MANUAL{%tr endif %}` |

---

## TABLE 3 — Certification Scope

| Cell | Placeholder |
|---|---|
| Certification Scope (value cell) | `{{ scope_en }}` |

---

## TABLE 4 — EA/IAF Classification

| Cell | Placeholder |
|---|---|
| EA/IAF Code | `{{ ea_code }}` |
| Category/Subcategory | `{{ ea_category }}` |
| Technical Field | `{{ ea_technical_area }}` |

---

## TABLES 5–15 — Adjustment Factor Checkboxes

**All MANUAL.** Leave every checkbox cell blank.

The coordinator physically checks which +10% / -10% factors apply during review. These tables cover:
- Table 5: QMS reduction factors
- Table 6: General increase factors
- Table 7: QMS-specific increase factors
- Table 8: EMS increase factors
- Table 9: OHSMS increase factors
- Table 10: MDQMS (ISO 13485) increase factors
- Table 11: MDQMS reduction factors
- Table 12: ISMS (ISO 27001) reduction factors
- Table 13: ISMS / ENMS increase factors
- Table 14: ISO 50001 reduction factors
- Table 15: ISO 50001 increase factors

---

## TABLE 16 — Reduction/Increase Totals

These come from `man_day_result`:

| Row | Placeholder |
|---|---|
| Reduction Percentage | `{{ man_day_result.reporting_reduction }}` |
| Increase Percentage | MANUAL (sum of checked boxes above) |
| Total Reduction/Increase Percentage | MANUAL |

> Note: `reporting_reduction` is the standard 20% reporting deduction. The increase/decrease from the checkboxes (Tables 5–15) is entered manually as the coordinator tallies them.

---

## TABLE 17 — Integration Calculation (8 Y/N rows)

Each row has a description and a Y/N answer cell. Fill the answer cells:

| Row description | Answer cell |
|---|---|
| Has document management been approached with an integrated approach? | `{{ "Y" if integration_level.document_management else "N" }}` |
| Has management review been addressed with an integrated approach? | `{{ "Y" if integration_level.management_review else "N" }}` |
| Have internal audits been addressed with an integrated approach? | `{{ "Y" if integration_level.internal_audit else "N" }}` |
| Have policies and objectives been formulated with an integrated approach? | `{{ "Y" if integration_level.policy_objectives else "N" }}` |
| Has an integrated approach been applied in system processes? | `{{ "Y" if integration_level.process_approach else "N" }}` |
| Is the organization's improvement mechanism in line with an integrated approach? | `{{ "Y" if integration_level.improvement_mechanism else "N" }}` |
| Have management support and responsibilities been addressed with an integrated approach? | `{{ "Y" if integration_level.management_support else "N" }}` |
| Has a risk-based thinking approach been addressed with an integrated approach? | `{{ "Y" if integration_level.risk_based_thinking else "N" }}` |

---

## TABLE 18 — Integration Results

| Cell | Placeholder |
|---|---|
| Integrated Audit Execution Capability | `{{ scope_integration_level }}` |
| Integration Percentage (row 1) | `{{ integration_pct }}` |
| Integration Discount (row 1) | `{{ man_day_result.integration_reduction }}` |

> `integration_pct` = number of Y answers / 8 × 100, computed in filler.

---

## TABLE 19 — Risk/Complexity Categories

| Cell | Placeholder |
|---|---|
| QMS Risk Category | `{{ man_day_result_qms.category if "QMS" in standards else "" }}` |
| EMS Complexity Category | `{{ man_day_result_ems.category if "EMS" in standards else "" }}` |
| OHSMS Complexity Category | `{{ man_day_result_ohsms.category if "OHSMS" in standards else "" }}` |

> Filler pre-extracts per-standard results from `man_day_result.standard_results` into flat variables `man_day_result_qms`, `man_day_result_ems`, etc.

---

## TABLE 20 — ISMS / ISO 22000 Specifics

| Cell | Placeholder |
|---|---|
| ISMS Business Complexity Score | `{{ man_day_result_isms.isms_business_score if "ISMS" in standards else "" }}` |
| ISMS IT Complexity Score | `{{ man_day_result_isms.isms_it_score if "ISMS" in standards else "" }}` |
| ISMS Complexity Class (Business) | `{{ man_day_result_isms.category if "ISMS" in standards else "" }}` |
| ISMS Complexity Class (IT) | `{{ man_day_result_isms.category if "ISMS" in standards else "" }}` |
| ISO 22000 Td (basic field audit duration) | `{{ man_day_result_fsms.base_ph1 if "FSMS" in standards else "" }}` |
| ISO 22000 TH (additional HACCP days) | `{{ man_day_result_fsms.haccp_addition if "FSMS" in standards else "" }}` |
| In absence of management system, days added | MANUAL |
| Number of audit days by employee count | `{{ man_day_result_fsms.base_init if "FSMS" in standards else "" }}` |
| For each additional location | `{{ man_day_result_fsms.site_addition if "FSMS" in standards else "" }}` |
| Ts Value | `{{ man_day_result_fsms.eps if "FSMS" in standards else "" }}` |

---

## TABLE 21 — ISO 50001 EnMS Complexity

| Cell | Placeholder |
|---|---|
| Annual energy consumption (TJ) | `{{ enms_energy_tj if "ENMS" in standards else "" }}` |
| Number of energy types | `{{ enms_energy_types if "ENMS" in standards else "" }}` |
| Number of significant energy uses (SEUs) | `{{ enms_seu_count if "ENMS" in standards else "" }}` |
| Calculated EnMS Complexity Level C= | `{{ man_day_result.enms_k if "ENMS" in standards else "" }}` |
| Level of EnMS complexity result | `{{ man_day_result.enms_complexity if "ENMS" in standards else "" }}` |

The weighted value cells (25%/25%/50%) and the complexity threshold table rows are pre-printed — do not touch.

> `enms_energy_tj`, `enms_energy_types`, `enms_seu_count` are summed across sites by the filler (sites have `energy_tj`, `energy_types`, `seu_count` fields).

---

## TABLE 22 — Man-Day Calculation Results (per standard)

Each standard row has columns: Standards | A/D | Inc/Dec A/D | Intg. Reduction | Rounding | Stage 1 | Stage 2 | Surveillance | Rec.

Fill each standard's data row. Use `{%tr if %}` to hide rows for standards not in scope:

**ISO 9001 row** — first cell: `{%tr if "QMS" in standards %}ISO 9001:2015`

| Column | Placeholder |
|---|---|
| A/D | `{{ man_day_result_qms.base_init }}` |
| Inc/Dec A/D | MANUAL (from adjustment totals) |
| Intg. Reduction | `{{ man_day_result.integration_reduction }}` |
| Rounding | MANUAL |
| Stage 1 | `{{ man_day_result_qms.base_ph1 }}` |
| Stage 2 | `{{ man_day_result_qms.base_ph2 }}` |
| Surveillance | `{{ man_day_result_qms.base_surv }}` |
| Rec. | `{{ man_day_result_qms.base_recert }}{%tr endif %}` |

Apply same pattern for each remaining standard:

| Standard | Condition | Variable prefix |
|---|---|---|
| ISO 14001:2015 | `"EMS" in standards` | `man_day_result_ems` |
| ISO 45001:2018 | `"OHSMS" in standards` | `man_day_result_ohsms` |
| ISO 22000:2018 | `"FSMS" in standards` | `man_day_result_fsms` |
| ISO/IEC 27001:2022 | `"ISMS" in standards` | `man_day_result_isms` |
| ISO 13485:2016 | `"MDQMS" in standards` | `man_day_result_mdqms` |
| ISO 37001:2016 | `"ABMS" in standards` | `man_day_result_abms` |
| ISO 50001:2018 | `"ENMS" in standards` | `man_day_result_enms` |

**Total row** — always visible:

| Column | Placeholder |
|---|---|
| Stage 1 | `{{ man_day_result.final_ph1 }}` |
| Stage 2 | `{{ man_day_result.final_ph2 }}` |
| Surveillance | `{{ man_day_result.final_surv1 }}` |
| Rec. | `{{ man_day_result.final_recert }}` |

---

## TABLE 23 — Recommended Auditors

| Row | Placeholder |
|---|---|
| Recommended Auditor/Technical Expert for Audit | `{{ lead_auditor_name }}` |
| Recommended Auditor/Technical Expert for Decision | MANUAL |

---

## TABLE 24 — Notes

Leave blank. MANUAL.

---

## TABLE 25 — Signatures

Leave all cells blank. Signed on-site.

---
---

# FR.231-1 — MD-QMS Stage 1 Report

FR.231-1 is the Stage 1 audit report for ISO 13485 (Medical Device QMS). It has 20 tables.

---

## TABLE 0 — IFC GLOBAL LLC Contact Block

Static. Do not touch.

---

## TABLE 1 — Organization Information

The cell below the header says "(Name/Address/Contact Info)". Fill it:

```
{{ company_name }}
{{ company_address }}
Tel: {{ phone }}
Email: {{ email }}
```

Type all four lines inside the same cell, one per line.

---

## TABLE 2 — Scope

| Cell | Placeholder |
|---|---|
| Value cell (below SCOPE header) | `{{ scope_en }}` |

---

## TABLE 3 — Device Class Checkboxes

(Class Is / Class Im / Class Ir / Class IIa / Class IIb / Class III)

**MANUAL** — auditor checks the applicable device class on-site.

---

## TABLE 4 — Report Info

| Row | Cell | Placeholder |
|---|---|---|
| Report No | value | `{{ plan_number }}` |
| Report Date | value | `{{ report_date }}` |
| Standard/s | value | `{{ standards_str }}` |
| Lead Auditor | value | `{{ lead_auditor_name }}` |
| Auditor (row 4) | value | `{{ auditors[0].name if auditors\|length > 0 else "" }}` |
| Auditor (row 5) | value | `{%tr if auditors\|length > 1 %}{{ auditors[1].name }}{%tr endif %}` |
| Technical Expert | value | `{%tr if technical_experts\|length > 0 %}{{ technical_experts[0].name }}{%tr endif %}` |
| Evaluated | value | `{{ representative }}` |
| Evaluator | value | `{{ lead_auditor_name }}` |
| Observer | value | `{%tr if observers\|length > 0 %}{{ observers[0].name }}{%tr endif %}` |
| Organization Representative | value | `{{ representative }}` |

> "Evaluated" = the company's QMR/contact who was assessed. "Evaluator" = the lead auditor conducting the evaluation.

---

## TABLE 5 — Audit Dates

| Cell | Placeholder |
|---|---|
| Audit Date/s | `{{ audit_dates }}` |
| Audit/Day Number | `{{ audit_days }}` |

---

## TABLE 6 — Audit Type Checkboxes

| Cell | Placeholder |
|---|---|
| Initial Certification checkbox | `{{ "☑" if audit_type == "initial" else "☐" }}` |
| Recertification checkbox | `{{ "☑" if audit_type == "recertification" else "☐" }}` |

---

## TABLE 7 — Audit Place

(Site / Office checkboxes)

**MANUAL** — checked by auditor.

---

## TABLE 8 — Objectives / Criteria

| Row | Action |
|---|---|
| Audit Objectives | Pre-printed. Do not touch. |
| Audit Criteria | `{{ standards_str }}` |

---

## TABLE 9 — Site(S)

| Row | Site Address cell | Date(s) cell |
|---|---|---|
| Row 2 (site 1) | `{{ sites[0].address }}` | `{{ audit_dates }}` |
| Row 3 (site 2) | `{%tr if sites\|length > 1 %}{{ sites[1].address }}` | `{{ audit_dates }}{%tr endif %}` |
| Row 4 (site 3) | `{%tr if sites\|length > 2 %}{{ sites[2].address }}` | `{{ audit_dates }}{%tr endif %}` |

---

## TABLE 10 — Not-Applicable Clauses

| Column | Action |
|---|---|
| Clause No | `{{ non_applicable_clauses }}` in first data row, or MANUAL if multiple |
| Reasons | MANUAL |
| Result | MANUAL |

---

## TABLE 11 — Report Summary

**MANUAL** — written by lead auditor after audit.

---

## TABLE 12 — NC Totals

(Total Major / Total Critical / Total Minor)

**MANUAL** — filled after audit.

---

## TABLE 13 — General

| Row | Action | Placeholder |
|---|---|---|
| Employee number | AUTO | `{{ personnel.full_time }}` |
| Subcontractor employee number | AUTO | `{{ personnel.subcontractors }}` |
| Effective employee number | AUTO | `{{ effective_employees }}` |
| Conformity of documentation scope | MANUAL | — |
| State of achieving the audit objective | MANUAL | — |
| Any deviations from the plan | MANUAL | — |
| Conditions affecting audit program | MANUAL | — |
| Unresolved issues if any | MANUAL | — |
| Type of audit — Combine | AUTO | `{{ "☑" if integration_level and integration_level.combine else "☐" }}` |
| Type of audit — Joint | AUTO | `{{ "☑" if integration_level and integration_level.joint else "☐" }}` |
| Type of audit — Integrated | AUTO | `{{ "☑" if integration_level and integration_level.integrated else "☐" }}` |

---

## TABLE 14 — Subjects to be Reviewed

(Organization requirements / Statutory obligations / Externally provided processes / etc.)

**MANUAL** — Findings and Result columns filled by auditor on-site.

---

## TABLE 15 — ISO 13485 Requirements (77-row clause checklist)

**All MANUAL.** Findings and Conclusion (✓ / NC / OBS) filled by auditor on-site.

Do not add any placeholders to this table.

---

## TABLE 16 — Findings

(No / Clause No / Non-Conformity Statement)

**MANUAL** — filled by auditor on-site.

---

## TABLE 17 — Recommendation of Audit Team

(Stage 2 is appropriate / Stage 2 is not appropriate)

**MANUAL** — lead auditor checks the applicable row on-site.

---

## TABLE 18 — Stage 2 Date

| Cell | Placeholder |
|---|---|
| Date specified for stage 2 | `{{ stage2_start_date }}` |

> `stage2_start_date` = Stage 2's `audit_date_start` formatted as DD/MM/YYYY. Passed by filler since FR.231-1 is a Stage 1 document that references the planned Stage 2 date.

---

## TABLE 19 — Signatures

| Cell | Action | Placeholder |
|---|---|---|
| Lead Auditor (name area) | AUTO | `{{ lead_auditor_name }}` |
| Signature (row below) | Leave blank | — |
| Reviewed and approved by | MANUAL | — |
| Signature (row below) | Leave blank | — |

---

## Notes on PENDING_CHANGES

The following new computed fields are needed for FR.218 and FR.231-1. Add to filler:

- `total_employees` — `personnel.full_time + personnel.part_time + personnel.unskilled`
- `office_employees` — from `personnel.office_employees` (check if stored separately from calculator extraction)
- `repetitive_employees` — from `personnel.repetitive_employees`
- `integration_pct` — count of True values in `integration_level` / 8 × 100
- `man_day_result_qms/ems/ohsms/fsms/isms/mdqms/abms/enms` — filler extracts from `man_day_result.standard_results` list by matching standard name
- `enms_energy_tj/energy_types/seu_count` — summed across sites
- `stage2_start_date` — Stage 2's `audit_date_start` formatted DD/MM/YYYY, passed when rendering Stage 1 docs
