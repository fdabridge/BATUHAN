# Document Template Editing Guide
## Adding Jinja2 Placeholders to FR Forms

---

## How This Works — Read First

You will open each Word document and type special placeholder tags into specific cells. The system (docxtpl) then replaces every `{{ tag }}` with real data when generating a package.

**Syntax:**
- `{{ company_name }}` → gets replaced with the company's name
- `{{ "☑" if is_initial else "☐" }}` → shows a tick or empty box depending on audit type
- `{{ auditors[0].name if auditors|length > 0 else "" }}` → first auditor's name, or blank if no auditor

**Rule:** Type the placeholder EXACTLY as written. Curly braces, spaces, and capitalisation all matter.

**After editing:** Save the file. Do not rename it. The system finds it by the FR number prefix.

**Which files to edit:** Edit the UAF version first. Then open the TÜRKAK English version — navigate to the SAME cells and type the SAME placeholders. Then the TÜRKAK Turkish version. The cell positions are identical across all three sets; only the surrounding label language differs.

**UAF folder:** `uaf_blank_set/`
**TÜRKAK English folder:** `turkak_blank_set/english/`
**TÜRKAK Turkish folder:** `turkak_blank_set/turkish/`

---

## Checkbox / Tick Approach

These forms have no actual Word checkbox controls — they are just text cells you would normally circle or mark with a pen. For auto-filling, we replace the cell's text with a conditional that shows ☑ or ☐.

**How to do it:**
1. Click inside the cell that currently says e.g. `ISO 9001:2015`
2. Select ALL the text in the cell (Ctrl+A inside the cell)
3. Delete it
4. Type: `{{ "☑" if "QMS" in standards else "☐" }} ISO 9001:2015`

The result: if QMS is in this audit set, the cell shows `☑ ISO 9001:2015`. If not, it shows `☐ ISO 9001:2015`.

**Standard codes used in conditions:**
| Standard | Code in condition |
|---|---|
| ISO 9001 | `"QMS" in standards` |
| ISO 14001 | `"EMS" in standards` |
| ISO 45001 | `"OHSMS" in standards` |
| ISO 22000 | `"FSMS" in standards` |
| ISO/IEC 27001 | `"ISMS" in standards` |
| ISO 50001 | `"ENMS" in standards` |
| ISO 13485 | `"MDQMS" in standards` |
| ISO 37001 | `"ABMS" in standards` |

**Audit type conditions:**
- Initial: `is_initial`
- Surveillance: `is_surveillance`
- Recertification: `is_recertification`

---

## Documents That Need NO Edits

**FR.230 — Nonconformity Notification Form**
This is filled entirely by the auditor on-site. Skip it. Include as-is.

---
---

## FR.220 — Certification Quotation

**Which stage folders contain this:** `Aşama 1` / `Stage 1` / `Aşama 1` (initial Stage 1 only)

**Open:** All three copies across UAF, TÜRKAK English, TÜRKAK Turkish.
The form already has one company pre-filled as an example — you will be replacing those values with placeholders.

### Table 0 — Quotation Number
| Cell label | Cell to edit | Type this |
|---|---|---|
| `Quotation No` | The cell to the RIGHT (currently shows a number like "4526") | `{{ plan_number }}` |

### Table 1 — Company Info
The LEFT column has labels. Edit the RIGHT column (currently has example data):
| Label | Type this in the right cell |
|---|---|
| `Organization` | `{{ company_name }}` |
| `Address` | `{{ company_address }}` |
| `Phone` | `{{ phone }}` |
| `E-mail` | `{{ email }}` |

### Table 2 — Standards (checkboxes)
Each standard has its OWN cell. Click into each cell, select all text, delete, and retype with the checkbox prefix:

| Current cell text | Replace entire cell with |
|---|---|
| `ISO 9001:2015` | `{{ "☑" if "QMS" in standards else "☐" }} ISO 9001:2015` |
| `ISO 14001:2015` | `{{ "☑" if "EMS" in standards else "☐" }} ISO 14001:2015` |
| `ISO 45001:2018` | `{{ "☑" if "OHSMS" in standards else "☐" }} ISO 45001:2018` |
| `ISO 22000:2018` | `{{ "☑" if "FSMS" in standards else "☐" }} ISO 22000:2018` |
| `ISO/IEC 27001:2022` | `{{ "☑" if "ISMS" in standards else "☐" }} ISO/IEC 27001:2022` |
| `ISO 50001:2018` | `{{ "☑" if "ENMS" in standards else "☐" }} ISO 50001:2018` |
| `ISO 13485:2016` | `{{ "☑" if "MDQMS" in standards else "☐" }} ISO 13485:2016` |
| `ISO 37001:2016` | `{{ "☑" if "ABMS" in standards else "☐" }} ISO 37001:2016` |

Leave the `Other` cells unchanged.

### Table 3 — Audit Type (checkboxes)
| Current cell text | Replace entire cell with |
|---|---|
| `Initial Certification / Surveillance` | `{{ "☑" if is_initial or is_surveillance else "☐" }} Initial Certification / Surveillance` |
| `Recertification` | `{{ "☑" if is_recertification else "☐" }} Recertification` |
| `Scope Extension` | Leave unchanged |
| `Address Change` | Leave unchanged |

### Table 4 — Fee Table
The LEFT column has labels. Edit the RIGHT column (the fee cells — currently empty or has example data):
| Label | Type this in the right (fee) cell |
|---|---|
| `Initial Certification` | `{{ initial_fee }}` |
| `Surveillance (At the end of 1st Year)` | `{{ surveillance_fee }}` |
| `Surveillance (At the end of 2nd Year)` | `{{ surveillance_fee }}` |
| `Recertification` | Leave blank (no recert fee stored yet) |
| `Scope Extension` | Leave blank |
| `Address Change` | Leave blank |

**Leave unchanged:** Everything in Table 5 (disclaimer text), Table 6 (Note), Table 7 (signatures).

---

## FR.221 — Certification Agreement

**Which folders:** `Aşama 1` / `Stage 1` / `Aşama 1`

**Open:** All three copies.

### Table 0 — Agreement Number
This table has one row. The cell currently says `Agreement No:`. The cell NEXT TO IT (to the right, which is empty) — type: `{{ plan_number }}`

### Table 1 — IFC Info (DO NOT EDIT)
This table has IFC's own address already filled in. Leave it completely unchanged.

### Table 2 — Customer (Employer) Info
The LEFT column has labels. Edit cells in COLUMNS 1–4 (they are merged — click in the merged area to the right of each label):
| Label | Type this |
|---|---|
| `Employer` | `{{ company_name }}` |
| `Address` | `{{ company_address }}` |
| `Site Address(es)` | `{{ site_addresses }}` |
| `Telephone` | `{{ phone }}` |
| `E-Mail` | `{{ email }}` |
| `Web Address` | `{{ website }}` |

**Standards checkboxes (rows labeled `Standard(s)`):**
There are 3 rows of standard cells. Edit each standard cell the same way as FR.220:

Row 1 cells (C1–C4):
| Current | Replace with |
|---|---|
| `ISO 9001:2015` | `{{ "☑" if "QMS" in standards else "☐" }} ISO 9001:2015` |
| `ISO 14001:2015` | `{{ "☑" if "EMS" in standards else "☐" }} ISO 14001:2015` |
| `ISO 45001:2018` | `{{ "☑" if "OHSMS" in standards else "☐" }} ISO 45001:2018` |
| `ISO 22000:2018` | `{{ "☑" if "FSMS" in standards else "☐" }} ISO 22000:2018` |

Row 2 cells (C1–C4):
| Current | Replace with |
|---|---|
| `ISO/IEC 27001:2022` | `{{ "☑" if "ISMS" in standards else "☐" }} ISO/IEC 27001:2022` |
| `ISO 50001:2018` | `{{ "☑" if "ENMS" in standards else "☐" }} ISO 50001:2018` |
| `ISO 13485:2016` | `{{ "☑" if "MDQMS" in standards else "☐" }} ISO 13485:2016` |
| `ISO 37001:2016` | `{{ "☑" if "ABMS" in standards else "☐" }} ISO 37001:2016` |

Leave Row 3 (`Other`) unchanged.

### Table 3 — Service / Audit Days / Fees
This table has: Service label | Stage 1 days | Stage 2 days | Fee
| Row label | Stage 1 cell | Stage 2 cell | Fee cell |
|---|---|---|---|
| `Initial Audit` (the data row, not the header row) | `{{ stage_1_days }}` | `{{ stage_2_days }}` | `{{ initial_fee }}` |
| `Surveillance Audit Year 1` | `{{ surv_days }}` | *(leave blank — merged)* | `{{ surveillance_fee }}` |
| `Surveillance Audit Year 2` | `{{ surv_days }}` | *(leave blank)* | `{{ surveillance_fee }}` |

**Note:** The data row for "Initial Audit" is the SECOND row in Table 3 (the first is the header). Click in the empty cell in column 2 (Stage 1), column 3 (Stage 2), column 4 (Fee).

**Leave unchanged:** Table 4 (signatures — but note: the IFC signatory name `Deniz Alya Eryılmaz` is hardcoded there; leave it).

---

## FR.234 — Surveillance / Recertification Notification

**Which folders:** `Gözetim` / `Surv` / `GD`

**Open:** All three copies.

### Table 0 — Header
| Label | Cell to edit | Type this |
|---|---|---|
| `Date` | Empty cell to the right | `{{ today }}` |
| `Project Number` | Empty cell to the right | `{{ plan_number }}` |
| `Organisation` | Empty merged cell to the right | `{{ company_name }}` |
| `Address` | Empty merged cell to the right | `{{ company_address }}` |
| `Phone` | Empty cell | `{{ phone }}` |
| `E-mail` | Empty cell | `{{ email }}` |

### Table 1 — Audit Type (checkboxes)
| Current cell text | Replace with |
|---|---|
| `Surveillance` | `{{ "☑" if is_surveillance else "☐" }} Surveillance` |
| `Recertification` | `{{ "☑" if is_recertification else "☐" }} Recertification` |

### Table 2 — Standards
Single cell (the empty cell after `Standard(s)` label). Type: `{{ standards_str }}`

### Table 3 — Scope
Single empty cell after `Scope of Certification`. Type: `{{ scope_en }}`

### Table 4 — Organization fields
These are fields the CUSTOMER fills in (current employee count, contact info at time of surveillance, etc.). **Leave all of Table 4 blank.** The customer fills this section in manually when returning the form.

---

## FR.223 — Audit Plan *(Per-Stage Document)*

**Which folders:** ALL stage folders (`Aşama 1`, `Aşama 2`, `Gözetim`, `Stage 1`, `Stage 2`, `Surv`, `GD`)

**Important:** This document is rendered once per stage. The code fills it with stage-specific data (dates, auditors, audit days).

**Open:** ALL copies across all 9 folders (3 standard groups × 3 stage types in UAF + TÜRKAK). They all have the same structure — edit identically.

### Table 0 — Main Header
This is one large table at the top. The LEFT cells are labels; the RIGHT cells are empty (edit those).

| Label | Type this in the empty cell to the right |
|---|---|
| `Date` | `{{ today }}` |
| `Project Number` | `{{ plan_number }}` |
| `Organization` | `{{ company_name }}` |
| `Address` | `{{ company_address }}` |
| `Telephone` | `{{ phone }}` |
| `E-mail` | `{{ email }}` |
| `Organization Representative` | `{{ representative }}` |
| `Standard/s` | `{{ standards_str }}` |
| `EA/IAF Code` | `{{ ea_code }}` |
| `Category/Subcategory` | `{{ ea_category }}` |
| `Technical Area / Technological Area` | `{{ ea_technical_area }}` |
| `Scope` | `{{ scope_en }}` |
| `Not Applicable Clause(s)` | `{{ non_applicable_clauses }}` |
| `Audit Type` | `{{ audit_type_display }}` |
| `Audit Date/s` | `{{ audit_dates }}` |
| `Number of Effective Employees` | `{{ effective_employees }}` |
| `Audit Time` | `{{ audit_days }}` |
| `Shift Number` | `{{ shift_count }}` |

**Leave unchanged:** The `Audit Criteria` and `Audit Objectives` rows — these contain fixed standard text already printed in the template.

### Table 1 — Sites and Audit Team
This table has two sections.

**Sites section (top rows):**
The row labeled `Site/s` has empty cells for address, process/activity, and employee count. There are 3 site rows. Edit only the FIRST site row (rows 2–4 are for additional sites — leave blank; coordinator adds manually if needed):
| Column | Type this |
|---|---|
| Address column (C2) | `{{ sites[0].address if sites else "" }}` |
| Process/Activity column (C4) | `{{ sites[0].process if sites else "" }}` |
| Number of Employees column (C5) | `{{ sites[0].employee_count if sites else "" }}` |

**Audit Team section (lower rows):**
The rows have labels in C0 and empty cells in C1 (name), C2 (standard), C4 (EA code):

| Label (C0) | Name cell (C1) | Standard cell (C2) | EA Code cell (C4) |
|---|---|---|---|
| `Lead Auditor` | `{{ lead_auditor_name }}` | `{{ standards_str }}` | `{{ ea_code }}` |
| `Auditor` (first row) | `{{ auditors[0].name if auditors\|length > 0 else "" }}` | `{{ auditors[0].standard if auditors\|length > 0 else "" }}` | `{{ auditors[0].ea_code if auditors\|length > 0 else "" }}` |
| `Auditor` (second row) | `{{ auditors[1].name if auditors\|length > 1 else "" }}` | `{{ auditors[1].standard if auditors\|length > 1 else "" }}` | `{{ auditors[1].ea_code if auditors\|length > 1 else "" }}` |
| `Technical Experts` | `{{ technical_experts[0].name if technical_experts\|length > 0 else "" }}` | Leave blank | Leave blank |
| `Observer` | `{{ observers[0].name if observers\|length > 0 else "" }}` | Leave blank | Leave blank |

**Leave unchanged:** The footnote row at the bottom (`* If necessary, as many lines...`).

### Table 2 — Hour-by-Hour Schedule
**Leave completely blank.** The auditor fills this on-site.

### Table 3 — Impartiality Statement
**Leave unchanged.** The organization representative signs this manually.

---

## FR.224 — Audit Team Information Form *(Per-Stage Document)*

**Which folders:** ALL stage folders (same as FR.223)

This form is almost identical to FR.223. Edit these cells:

### Table 0 — Main Header
Identical fields to FR.223. Use the exact same placeholders:
`today`, `plan_number`, `company_name`, `company_address`, `phone`, `email`, `representative`, `standards_str`, `ea_code`, `ea_category`, `ea_technical_area`, `scope_en`, `non_applicable_clauses`, `audit_type_display`, `audit_dates`, `effective_employees`, `audit_days`

### Table 1 — Sites
First site row: same as FR.223 (`sites[0].address`, `sites[0].process`, `sites[0].employee_count`)

### Table 2 — Stage 1 on-site question
**Leave blank.** Auditor marks Yes/No.

### Table 3 — Clauses to be audited
**Leave blank.** Already has standard clause references printed in some versions; coordinator/auditor fills.

### Table 4 — Audit Team
Same team rows as FR.223 Table 1 team section. Use the same placeholders.

### Table 5 — Impartiality Statement
**Leave unchanged.**

---

## FR.225 — Opening / Closing Meeting Form *(Per-Stage)*

**Which folders:** ALL stage folders

This form is mostly filled on-site. Only 3 fields to pre-fill.

### Table 0 — Header
| Label | Type this |
|---|---|
| `Organization` | `{{ company_name }}` |
| `Standard/s` | `{{ standards_str }}` |
| `Audit Type` | `{{ audit_type_display }}` |

**Leave unchanged:** Everything else — the full agenda, attendance tables, signatures.

---

## FR.231 — Stage 1 Report *(Per-Stage)*

**Which folders:** `Aşama 1` / `Stage 1` / `Aşama 1`

**Important:** This is a report filled by the lead auditor AFTER conducting Stage 1. We pre-fill only the identification header. The entire checklist, findings, and recommendation sections are left blank.

### Table 0 — IFC Logo/Header
**Leave unchanged.**

### Table 1 — Organization Information
This is a big merged cell containing the header "ORGANIZATION INFORMATION". Below it (in the next row) is another big cell where the company info goes. Click in that big empty cell and type:
```
{{ company_name }}
{{ company_address }}
Tel: {{ phone }} | E-mail: {{ email }}
```

### Table 2 — Scope
Big merged cell below "SCOPE". Click in it and type: `{{ scope_en }}`

### Table 3 — Report Details
LEFT column has labels. RIGHT column is empty — fill these:
| Label | Type this |
|---|---|
| `Report No` | `{{ plan_number }}` |
| `Report Date` | `{{ today }}` |
| `Standard/s` | `{{ standards_str }}` |
| `Lead Auditor` | `{{ lead_auditor_name }}` |
| `Auditor` (first row) | `{{ auditors[0].name if auditors\|length > 0 else "" }}` |
| `Auditor` (second row) | `{{ auditors[1].name if auditors\|length > 1 else "" }}` |
| `Technical Expert` | `{{ technical_experts[0].name if technical_experts\|length > 0 else "" }}` |
| `Evaluated` | Leave blank (filled by lead auditor) |
| `Evaluator` | Leave blank |
| `Observer` | `{{ observers[0].name if observers\|length > 0 else "" }}` |
| `Organization Representative` | `{{ representative }}` |

### Table 4 — Audit Dates
| Label | Type this |
|---|---|
| `Audit Date/s` | `{{ audit_dates }}` |
| `Audit/Day Number` | `{{ audit_days }}` |

### Table 5 — Audit Type (checkboxes)
The row says `Audit Type` and then has cells for `Initial Certification` and `Recertification`:
| Current cell | Replace with |
|---|---|
| `Initial Certification` | `{{ "☑" if is_initial else "☐" }} Initial Certification` |
| `Recertification` | `{{ "☑" if is_recertification else "☐" }} Recertification` |

### Table 6 — Audit Place
**Leave unchanged.** Auditor ticks Site/Office on-site.

### Tables 7–10 — Objectives, Sites, Not-Applicable Clauses
| Table | What to do |
|---|---|
| Table 7 (Objectives) | Leave unchanged — text is pre-printed |
| Table 8 (Sites) | First site row: `{{ sites[0].address if sites else "" }}` in the address cell |
| Table 9 (Not-Applicable Clauses) | Leave blank — auditor fills |

### Table 11 — General (Employee counts)
| Label | Type this |
|---|---|
| `Employee number` | `{{ total_employees }}` |
| `Subcontractor employee number` | `{{ subcontractors }}` |
| `Effective employee number` | `{{ effective_employees }}` |

**Leave all other rows blank** — these require auditor judgment.

### Tables 12 onward — Checklist, Findings, Recommendation
**Leave entirely blank.** These are the audit findings sections — the auditor fills everything here.

---

## FR.231-1 — MD-QMS Stage 1 Report *(ISO 13485 only)*

**Which folders:** `13485/Aşama 1` (UAF only — TÜRKAK has no 13485 folder)

Identical editing to FR.231. Same tables, same placeholders, same sections to leave blank. The checklist in this version covers ISO 13485 clauses instead of 9001/14001/45001 — still leave it blank.

---

## FR.232 — Audit Report *(Stage 2 and Surveillance)*

**Which folders:** `Aşama 2` and `Gözetim` / `Stage 2` and `Surv` / `Aşama 2` and `GD`

Same structure and same editing as FR.231. Use the identical placeholders:

- Table 1 (Organization): `company_name`, `company_address`, `phone`, `email`
- Table 2 (Scope): `scope_en`
- Table 3 (Details): `plan_number`, `today`, `standards_str`, `lead_auditor_name`, `auditors[0].name`, `auditors[1].name`, `technical_experts[0].name`, `observers[0].name`, `representative`
- Table 4 (Dates): `audit_dates`, `audit_days`
- Table 5 (Audit Type checkbox): This one has `Initial Certification`, `Surveillance`, `Recertification` in one cell — leave it unchanged (auditor marks it)
- Table 7 (Sites): First row address
- Table 10 (Employee counts): `total_employees`, `subcontractors`, `effective_employees`

**Leave blank:** Everything from Table 12 onward (observations, findings, recommendation).

---

## FR.232-1 — MD-QMS Audit Report *(ISO 13485 Stage 2 / Surveillance)*

**Which folders:** `13485/Aşama 2` and `13485/Gözetim` (UAF only)

Identical editing to FR.232.

---

## FR.229 — ISMS/PIMS Audit Report *(ISO 27001 only)*

**Which folders:** `27001/Aşama 2` and `27001/Gözetim` / `27001/Stage 2` and `27001/Surv` / `27001/Aşama 2` and `27001/GD`

Same structure as FR.232. Identical placeholders and identical leave-blank sections. Note this form says "CLIENT ORGANIZATION" instead of "ORGANISATION INFORMATION" — same cell, same approach.

---

## FR.222 — Audit Program *(Whole Audit, not per-stage)*

**Which folders:** `Aşama 1` / `Stage 1` / `Aşama 1` (included in Stage 1 package — it covers the entire certification cycle)

This is the most complex form. It's one large master document with the entire certification schedule. Take your time.

### Table 0 — Main Header (13 columns wide)
The header rows have labels in C0-C1 and data cells to the right. Edit:

| Label | Type this in the data cell |
|---|---|
| `Provision/Update Date` | `{{ today }}` |
| `Project No` | `{{ plan_number }}` |
| `Organization` | `{{ company_name }}` |
| `Address` | `{{ company_address }}` |
| `Telephone` | `{{ phone }}` |
| `E-mail` | `{{ email }}` |
| `Organisation Representative` | `{{ representative }}` |
| `Audit Language` | `English` *(hardcode this — UAF is always English)* |
| `Number of Effective Employees` | `{{ effective_employees }}` |
| `Number of Shifts and Hours` | `{{ shift_count }}` |
| `Risk Category (ISO 9001)` | `{{ qms_risk_category }}` |
| `Complexity Category (ISO 14001/ISO 45001)` | `{{ ems_complexity }}` |
| `Standard/s` | `{{ standards_str }}` |
| `EA/NACE` (in the code row) | `{{ ea_code }}` |
| `Category/Sub Category` | `{{ ea_category }}` |
| `Technical Area / Technological Area` | `{{ ea_technical_area }}` |
| `Scope` | `{{ scope_en }}` |
| `Not Applicable Clause/s` | `{{ non_applicable_clauses }}` |

**Site address rows (rows labeled `Initial/Re certification Audit Site Address/s`):**
First data row under this label:
- Site Address column: `{{ sites[0].address if sites else "" }}`
- Scope of Activity column: `{{ sites[0].process if sites else "" }}`
- Number of Employees column: `{{ sites[0].employee_count if sites else "" }}`

**Audit evaluation date rows** (near the bottom of Table 0 — rows labeled `Stage 1 Audit Evaluation`, `Stage 2 Audit Evaluation`, `1. Surveillance Audit Evaluation`, etc.):
These rows have one big empty cell where the planned dates go.
| Row label | Type this |
|---|---|
| `Stage 1 Audit Evaluation` | `{{ stage_1_dates }}` |
| `Stage 2 Audit Evaluation` | `{{ stage_2_dates }}` |
| `1. Surveillance Audit Evaluation` | `{{ surv_1_dates }}` |
| `2. Surveillance Audit Evaluation` | Leave blank |
| `Recertification Audit Evaluation` | Leave blank |

### Tables 1 through 8 — Per-Standard Date Rows (ISO 14001, 45001, 22000, 27001 etc.)
Each of these tables has the same structure: a header row showing the standard name, a row for "Possible Audit Dates" with columns Stage 1 / Stage 2 / Surveillance 1 / Surveillance 2 / Recertification, and then the data row (the empty row directly below "Possible Audit Dates").

For EACH standard's table, edit the data row cells:
| Column label | Type this |
|---|---|
| `Stage 1` | `{{ stage_1_dates }}` |
| `Stage 2` | `{{ stage_2_dates }}` |
| `Surveillance 1` | `{{ surv_1_dates }}` |
| `Surveillance 2` | Leave blank |
| `Recertification` | Leave blank |

**These tables only appear if the standard is relevant.** The template contains sections for all 9 possible standards. Since we're using the same template for all audit sets, just fill all the date cells — for standards not selected, `stage_1_dates` etc. will be blank anyway.

**Leave unchanged:** All the "Clauses to be Audited" rows — they have standard clause references already printed.

---

## FR.218 — Application Review Form *(Most Complex)*

**Which folders:** `Aşama 1` / `Stage 1` / `Aşama 1`

This is the man-day calculation record. It's 26 tables long. Be systematic.

### Table 0 — Header
| Label | Type this |
|---|---|
| `Review Date` | `{{ today }}` |
| `Organization` | `{{ company_name }}` |
| `Address` | `{{ company_address }}` |
| `Standards` | `{{ standards_str }}` |

Leave `Is there an existing management system?` and `How long?` blank — auditor/coordinator fills.

### Table 1 — Personnel Numbers
This table has labels in C0 and data values in C1:
| Label | Type this in the data cell |
|---|---|
| `Number of office personnel (management, HR, market...` | `{{ full_time }}` |
| `Number of subcontracted employees` | `{{ subcontractors }}` |
| `Number of seasonal employees` | `{{ seasonal }}` |
| `Total number of employees` | `{{ total_employees }}` |
| `Number of Effective Employee` | `{{ effective_employees }}` |

Leave `Number of employees per shift`, `Shift to be reviewed`, `Number of Sites`, `Number of Sites to be Assessed` blank — coordinator fills from the application form.

### Table 2 — Site Addresses
**Leave blank.** Coordinator fills.

### Table 3 — Certification Scope
Single empty cell. Type: `{{ scope_en }}`

### Table 4 — EA/IAF Code
| Column label | Type this |
|---|---|
| `EA/IAF Code` | `{{ ea_code }}` |
| `Category/Subcategory` | `{{ ea_category }}` |
| `Technical Field` | `{{ ea_technical_area }}` |

### Tables 5–15 — Reduction/Increase Circumstance Checklists
**Leave completely blank.** These are coordinator judgment calls — they manually tick which circumstances apply. There are separate tables for QMS, EMS, OHSMS, MDQMS, ISMS, ENMS reductions and increases. No auto-fill.

### Table 16 — Reduction/Increase Totals
**Leave blank.** Calculated manually by coordinator from the checkboxes above.

### Table 17 — Integration Calculation (8 checkboxes)
This table lists 8 integration criteria, each worth 12.5%. Each row has an empty cell in C0.

| Row description (label in C1) | Type in the empty C0 cell |
|---|---|
| `Has document management been approached with an integrated approach?` | `{{ "☑" if integration.document_management else "☐" }}` |
| `Has management review been addressed with an integrated approach?` | `{{ "☑" if integration.management_review else "☐" }}` |
| `Have internal audits been addressed with an integrated approach?` | `{{ "☑" if integration.internal_audit else "☐" }}` |
| `Have policies and objectives been formulated with an integrated approach?` | `{{ "☑" if integration.policy_objectives else "☐" }}` |
| `Has an integrated approach been applied in system processes?` | `{{ "☑" if integration.process_approach else "☐" }}` |
| `Is the organization's improvement mechanism in line?` | `{{ "☑" if integration.improvement_mechanism else "☐" }}` |
| `Have management support and responsibilities been addressed?` | `{{ "☑" if integration.management_support else "☐" }}` |
| `Has a risk-based thinking approach been addressed?` | `{{ "☑" if integration.risk_based_thinking else "☐" }}` |

### Table 18 — Integration Totals
| Label | Type this |
|---|---|
| `Integrated Audit Execution Capability` | `{{ integration_percentage }}%` |
| `Integration Percentage` | `{{ integration_percentage }}%` |
| `Integration Discount` (C2, right side) | `{{ integration_discount }}%` |

### Tables 19–21 — Complexity/Risk Categories
| Label | Type this |
|---|---|
| `QMS Risk Category` | `{{ qms_risk_category }}` |
| `EMS Complexity Category` | `{{ ems_complexity }}` |
| `OHSMS Complexity Category` | `{{ ohsms_complexity }}` |
| `ISMS Business Complexity Score` | `{{ isms_complexity }}` |

Leave everything else in these tables blank — the numeric calculation breakdowns are complex and coordinator verifies them.

### Table 22 — Final Summary (Standards × Audit Days)
This is the key table. It has a row per standard showing: A/D (audit days), Inc/Dec adjustment, Integration reduction, Rounding, Stage 1, Stage 2, Surveillance, Recertification days.

For each standard row, the cells in columns 1–8 are currently empty. Fill:
| Standard | A/D | Stage 1 | Stage 2 | Surv | Recert |
|---|---|---|---|---|---|
| `ISO 9001:2015` | `{{ result.qms_days if "QMS" in standards else "" }}` | `{{ result.qms_ph1 if "QMS" in standards else "" }}` | `{{ result.qms_ph2 if "QMS" in standards else "" }}` | `{{ result.qms_surv if "QMS" in standards else "" }}` | `{{ result.qms_recert if "QMS" in standards else "" }}` |
| `ISO 14001:2015` | same pattern with `ems_` | … | … | … | … |
| (repeat for each standard row) | | | | | |
| `Total` row | Leave blank — coordinator sums | `{{ stage_1_days }}` | `{{ stage_2_days }}` | `{{ surv_days }}` | Leave blank |

**Note on columns:** The table has 9 columns (Standard | A/D | Inc/Dec | Intg. Reduction | Rounding | Stage 1 | Stage 2 | Surveillance | Rec.). Leave Inc/Dec, Integration Reduction, and Rounding columns blank — the coordinator fills those manually.

### Table 23 — Recommended Auditor
| Label | Type this |
|---|---|
| `Recommended Auditor/Technical Expert for Audit` | `{{ lead_auditor_name }}` |
| `Recommended Auditor/Technical Expert for Decision` | Leave blank |

### Tables 24–25 — Notes and Signatures
**Leave unchanged.**

---

## FR.211 — Lead Auditor / Auditor Assessment Form

**Which folders:** ALL stage folders (included in every package)

**Important:** This form is rendered ONCE PER AUDITOR being assessed. If a stage has a lead auditor + 2 additional auditors, the system generates 3 copies of this form — one for each. Each copy has a different name in the `{{ assessed_auditor_name }}` cell.

### Table 0 — Header (4 rows, no labels in separate cells — labels and values are in the SAME cells)
Actually, looking at the structure: C0 has the label, C1 has the empty data cell.
| Label (C0) | Type this in C1 |
|---|---|
| `Lead Auditor / Auditor` | `{{ assessed_auditor_name }}` |
| `Audit Date(s)` | `{{ audit_dates }}` |
| `Customer Organization` | `{{ company_name }}` |
| `Standard(s)` | `{{ standards_str }}` |

### Table 1 — Rating Criteria
**Leave completely blank.** The lead auditor scores each criterion on-site.

### Table 2 — Signatures
**Leave blank.**

---

## After Editing All UAF Files

Go through each TÜRKAK English file (in `turkak_blank_set/english/`). Open each FR form and navigate to the exact same cells — the tables have the same structure, just different language labels. Type the exact same placeholders. It should go much faster because you already know where everything goes.

Then repeat for TÜRKAK Turkish (`turkak_blank_set/turkish/`). Same again.

---

## Placeholder Reference — Complete List

These are all the variable names the code will provide. Use them in your placeholders.

**Audit Set level (same in every document):**
- `company_name` — company name
- `company_address` — full address
- `phone`, `email`, `website`
- `representative` — contact person name
- `plan_number` — e.g. "1652"
- `standards_str` — e.g. "ISO 9001:2015, ISO 14001:2015"
- `standards` — list used in conditions: `"QMS" in standards`
- `audit_type_display` — "Initial Certification" / "Surveillance" / "Recertification"
- `is_initial`, `is_surveillance`, `is_recertification` — True/False for conditions
- `scope_en` — certification scope text in English
- `ea_code`, `ea_category`, `ea_technical_area`
- `non_applicable_clauses`
- `effective_employees`, `total_employees`
- `full_time`, `part_time`, `subcontractors`, `seasonal`, `shift_count`
- `today` — today's date formatted as DD/MM/YYYY
- `qms_risk_category`, `ems_complexity`, `ohsms_complexity`, `isms_complexity`
- `integration` — object with `.document_management`, `.management_review`, `.internal_audit`, `.policy_objectives`, `.process_approach`, `.improvement_mechanism`, `.management_support`, `.risk_based_thinking`
- `integration_percentage`, `integration_discount`
- `stage_1_days`, `stage_2_days`, `surv_days`
- `stage_1_dates`, `stage_2_dates`, `surv_1_dates` — formatted date ranges
- `initial_fee`, `surveillance_fee`
- `site_addresses` — all site addresses as a string
- `sites` — list of site objects: `.address`, `.process`, `.employee_count`
- `result` — man-day result object for detailed per-standard values

**Stage level (per-stage documents — FR.223, FR.224, FR.225, FR.231, FR.232, FR.229, FR.211):**
- `audit_dates` — e.g. "10-12 June 2026"
- `audit_days` — float, e.g. 2.0
- `lead_auditor_name`
- `auditors` — list: `.name`, `.standard`, `.ea_code`
- `technical_experts` — list: `.name`
- `observers` — list: `.name`
- `audit_type_display` — same as above but reflects the specific stage
- `assessed_auditor_name` — FR.211 only: name of the person being assessed
