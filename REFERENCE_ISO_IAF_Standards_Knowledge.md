# ISO / IAF Standards Reference — Certiva Platform

**Last updated:** 2026-06-17  
**Source:** IAF mandatory documents, ISO standards, FSSC 22000 Scheme v6, TÜRKAK/UAF rules, TÜRKAK R40.01, technical_sectors.xlsx (IAF Sector Library)  
**Purpose:** Authoritative reference for coding decisions in Certiva. Do not deviate from this without reverifying against primary sources.

---

## 1. IAF EA Code System

EA codes are **industry sector identifiers** (not risk levels). They are used by ABs and CBs to define accreditation/certification scope. 39 official codes per TÜRKAK R40.01 / IAF MD 1:

**Format in Certiva:** stored and matched as `"EA 29"` (with prefix and space). This is the canonical format for `audit_set.ea_code`, auditor `ea_codes` list entries, and `_SCOPE_TO_EA_KW` dict keys.

| Code | Description | NACE Rev.2 |
|------|-------------|------------|
| EA 1 | Agriculture, forestry and fishing | 01, 02, 03 |
| EA 2 | Mining and quarrying | 05–09 |
| EA 3 | Food products, beverages and tobacco | 10, 11, 12 |
| EA 4 | Textiles and textile products | 13, 14 |
| EA 5 | Leather and leather products | 15 |
| EA 6 | Wood and wood products | 16 |
| EA 7 | Pulp, paper and paper products | 17 |
| EA 8 | Publishing companies | 58.1, 59.2 |
| EA 9 | Printing companies | 18 |
| EA 10 | Manufacture of coke and refined petroleum products | 19 |
| EA 11 | Nuclear fuel | 24.46 |
| EA 12 | Chemicals, chemical products and fibres | 20 |
| EA 13 | Pharmaceuticals | 21 |
| EA 14 | Rubber and plastic products | 22 |
| EA 15 | Non-metallic mineral products | 23 (excl. 23.5/23.6) |
| EA 16 | Concrete, cement, lime, plaster etc. | 23.5, 23.6 |
| EA 17 | Basic metals and fabricated metal products | 24 (excl. 24.46), 25 (excl. 25.4), 33.11 |
| EA 18 | Machinery and equipment | 25.4, 28, 30.4, 33.12, 33.2 |
| EA 19 | Electrical and optical equipment | 26, 27, 33.13, 33.14, 95.1 |
| EA 20 | Shipbuilding | 30.1, 33.15 |
| EA 21 | Aerospace | 30.3, 33.16 |
| EA 22 | Other transport equipment (automotive, rail, etc.) | 29, 30.2, 30.9, 33.17 |
| EA 23 | Manufacturing not elsewhere classified | 31, 32, 33.19 |
| EA 24 | Recycling | 38.3 |
| EA 25 | Electricity supply | 35.1 |
| EA 26 | Gas supply | 35.2 |
| EA 27 | Water supply | 35.3, 36 |
| EA 28 | Construction | 41, 42, 43 |
| EA 29 | Wholesale and retail trade; repair of motor vehicles etc. | 45, 46, 47, 95.2 |
| EA 30 | Hotels and restaurants | 55, 56 |
| EA 31 | Transport, storage and communications | 49, 50, 51, 52, 53, 61 |
| EA 32 | Financial intermediation; real estate; renting | 64, 65, 66, 68, 77 |
| EA 33 | Information technology | 58.2, 62, 63.1 |
| EA 34 | Engineering services | 71, 72, 74 (excl. 74.2/74.3) |
| EA 35 | Other services (consulting, legal, accounting, facility mgmt.) | 69, 70, 73, 74.2, 74.3, 78, 80, 81, 82 |
| EA 36 | Public administration | 84 |
| EA 37 | Education | 85 |
| EA 38 | Health and social work | 75, 86, 87, 88 |
| EA 39 | Other social services (media, sports, arts, personal services) | 37, 38.1, 38.2, 39, 59.1, 60, 63.9, 79, 90–96 |

**Common traps:**
- EA 17 = **metals/steel** — NOT wholesale/retail (that is EA 29)
- EA 29 = **wholesale/retail trade** — includes sales of medical devices, import/export, dealerships
- EA 12 = **chemicals** — NOT pharmaceuticals (that is EA 13)
- EA 22 = **automotive/other transport** — NOT shipbuilding (EA 20) or aerospace (EA 21)
- EA 28 = **construction** — NOT concrete manufacturing (EA 16)
- EA 33 = **IT services + software** — covers NACE 58.2 (software publishing), 62 (IT), 63.1 (data processing)
- EA 35 = **consulting/advisory/legal** — management consulting, audit firms, advertising agencies

---

## 2. Scope Classification System Per Standard

**CRITICAL TABLE — never mix these up:**

| Standard | Scope System | Codes/Categories | Audit Time Governed By |
|----------|-------------|-----------------|----------------------|
| ISO 9001 | IAF EA codes + Risk (High/Med/Low) | EA 1–39 | IAF MD 5:2023 Table QMS 1 |
| ISO 14001 | IAF EA codes + Env. significance | EA 1–39 | IAF MD 5:2023 Table EMS 1 |
| ISO 45001 | IAF EA codes + OHS risk (AB-defined) | EA 1–39 | IAF MD 5:2023 Table OH&SMS 1 |
| ISO 22000 | **Food chain categories — NOT EA codes** | BIII, C0, CI, CII, CIII, CIV, D, E, FI, FII, G, I, K | ISO 22003-1:2022 Annex B |
| FSSC 22000 | **Food chain categories — NOT EA codes** | Same as ISO 22000 | ISO 22003-1:2022 Annex B + FSSC v6 Part 3 |
| ISO 50001 | IAF EA codes + Complexity (Low/Med/High via K-factor) | EA 1–39 | ISO 50003:2021 Tables A.3–A.4 |
| ISO 27001 | Organization-defined ISMS scope (EA codes for CB accreditation only) | EA 1–39 (CB scope only) | ISO/IEC 27006-1:2024 Table C.1 |
| ISO 13485 | **Technical Areas — NOT EA codes** | A1.1–A1.7, A2.x (see below) | IAF MD 9:2023 Annex B |
| ISO 37001 | Organization-defined (applicable laws/sectors) | No standard code system | ISO 17021-1 principles |
| ISO 37301 | Organization-defined (compliance obligations) | No standard code system | ISO 17021-1 principles |

---

## 3. ISO 22000 / FSSC 22000 Food Chain Categories

**Source:** ISO 22003-1:2022 Annex A; FSSC 22000 Scheme v6

| Category | Description | PRP Standard |
|----------|-------------|--------------|
| BIII | Pre-process handling of plant products (cleaning, sorting, cooling, packing whole harvested plants) | ISO/TS 22002-3 |
| C0 | Animal primary conversion (lairage, slaughter, evisceration, bulk chilling/freezing) | FSSC-specific |
| CI | Processing of perishable animal products (meat, fish, dairy) | ISO/TS 22002-1 |
| CII | Processing of perishable plant products (fresh-cut, juice) | ISO/TS 22002-1 |
| CIII | Processing of perishable mixed products (sandwiches, ready meals) | ISO/TS 22002-1 |
| CIV | Processing of ambient stable products (canned, dry, confectionery) | ISO/TS 22002-1 |
| D | Production of feed and pet food | ISO/TS 22002-6 |
| E | Catering (food to consumers on-site or off-site) | ISO/TS 22002-2 |
| FI | Wholesale, retail, e-commerce of food products | BSI/PAS 221:2013 |
| FII | Food brokering, trading, intermediaries | BSI/PAS 221:2013 |
| G | Storage, distribution, transport (perishable and ambient) | ISO/TS 22002-5 |
| I | Production of food packaging and packaging materials | ISO/TS 22002-4 |
| K | Production of (bio)chemicals, bio-cultures, food ingredients, processing aids | ISO/TS 22002-1 / sector |

**Key rules:**
- Category A (primary production) was REMOVED in ISO 22003-1:2022 / FSSC v6. Do not use.
- BIII and C0 are NEW in v6 — they replace old Category A.
- An auditor authorized for CI is NOT automatically authorized for CII, CIII, CIV — separate competence required.
- EA code 3 (Food products) is used for the CB's general accreditation scope, but within FSMS audits, food chain category governs scope matching.

**FSSC 22000 Audit Time (deviates significantly from IAF MD 5):**
- Base time from ISO 22003-1:2022 Annex B (not MD 5)
- Mandatory SEPARATE reporting/preparation time: minimum **1.0 auditor day (8 hours)** — this is NOT included in on-site audit time
- Interpreter required: add minimum 0.5 auditor days
- Off-site storage facility: add minimum 0.25 auditor days per facility
- Separate head office function: add minimum 0.5 auditor days on-site

---

## 4. ISO 50001 Complexity Factor (K-factor)

**Source:** ISO 50003:2021, Annex A

**Formula:** C = (FEC × 0.25) + (FET × 0.25) + (FSEU × 0.50)

| Factor | Description | Value |
|--------|-------------|-------|
| FEC | Annual energy consumption | ≤20 TJ → 1.0; 20–200 TJ → 1.2; 200–2,000 TJ → 1.4; >2,000 TJ → 1.6 |
| FET | Number of energy types | 1–2 → 1.0; 3 → 1.2; ≥4 → 1.4 |
| FSEU | Number of Significant Energy Uses | 1–3 → 1.0; 4–6 → 1.2; 7–10 → 1.3; 11–15 → 1.4; ≥16 → 1.6 |

**Complexity levels:**
- C < 1.15 → **Low complexity**
- 1.15 ≤ C ≤ 1.35 → **Medium complexity**
- C > 1.35 → **High complexity**

Audit time from ISO 50003:2021 Tables A.3–A.4 using personnel count + complexity level.

---

## 5. ISO 13485 Technical Areas (TAs)

**Source:** IAF MD 9:2023 Issue 5, Annex A

**Table A.1 — Finished Medical Devices:**

| TA | Description |
|----|-------------|
| A1.1 | Non-active medical devices (bandages, surgical instruments, diagnostic agents external use) |
| A1.2 | Non-active implantable medical devices (orthopedic screws, dental implants, cardiovascular stents) |
| A1.3 | Active (non-implantable) medical devices (monitoring equipment, diagnostic imaging, surgical energy devices) |
| A1.4 | Active implantable medical devices (pacemakers, cochlear implants, neurostimulators) |
| A1.5 | Sterilization methods (EtO, steam, radiation, aseptic processing, dry heat, H₂O₂, LTSF) |
| A1.6 | Special technologies (human blood derivatives, nanomaterials, biologically active coatings, software as medical device) |
| A1.7 | Suppliers of parts, components, raw materials, and services (calibration, verification services) |

**Table A.2 — IVD Devices:**

| TA | Description |
|----|-------------|
| A2.1 | General IVD instruments and software |
| A2.2 | Reagents, calibrators, controls |
| A2.3 | Specimen receptacles |
| A2.4 | Companion diagnostic devices |

**Key rule:** Auditor authorization is per TA. The audit team collectively must cover all TAs in the client's scope — individual auditors do NOT need to cover all TAs. A1.7-only auditors have lighter competence requirements.

---

## 6. IAF MD 5:2023 — Audit Time Rules

**Standards covered:** ISO 9001, ISO 14001, ISO 45001.  
**Standards NOT covered by MD 5:** ISO 22000/FSSC (22003-1), ISO 27001 (27006-1), ISO 13485 (MD 9), ISO 50001 (50003).

**Stage split (initial certification):**
- Stage 1: ~1/3 of total audit time
- Stage 2: ~2/3 of total audit time

**Maximum reduction from table values:** 30% (must be documented with justification)

**Surveillance:** Each surveillance ≥ 1/3 of initial total; over 3-year cycle, cumulative time must equal initial.

**Recertification:** ~2/3 of initial total (similar to Stage 2 alone).

---

## 7. IAF MD 11:2023 — Integrated Audit Time Reduction

**Source:** IAF MD 11:2023

For audits covering 2+ standards simultaneously:

| Integration Level | Reduction |
|------------------|-----------|
| Low (separate systems, co-located) | 0–5% |
| Medium (shared processes, combined manual) | 5–15% |
| High (fully integrated single management system) | up to 20% |

**Key rules:**
- Reduction is applied on top of any MD 5 reduction already taken
- Example: 20% MD 5 reduction + 20% MD 11 reduction = 36% total (0.80 × 0.80)
- Absolute floor: total time cannot be less than 50% of the sum of individual standard table times
- Team collective coverage applies: each auditor does NOT need to cover all standards — the team must collectively cover all standards

---

## 8. IAF MD 22:2023 — ISO 45001 Specific

- No global risk level table for EA codes — each AB assigns risk level (High/Med/Low OHS risk) per EA code based on local legislation and hazard profiles
- TÜRKAK assigns risk levels based on Turkish OHS legislation (Law No. 6331 and regulations)
- Auditors must know applicable OHS legislation for the jurisdictions they audit in

---

## 9. ISO 27001 — Audit Time

**Source:** ISO/IEC 27006-1:2024

- Audit time from Table C.1 (personnel count × complexity factors)
- Complexity factors: criticality of information, technology diversity (number of IT platforms), extent of outsourcing, multi-site scope
- **2024 change:** Freelancers and persons not directly employed but under organizational control must be counted in effective personnel
- **Maximum reduction:** 30%
- IAF MD 26:2023 covers ISO 27001:2022 transition (all certifications must be to 2022 version; 2013 certs expired October 31, 2025)

**Note:** IAF MD 22 covers OHSMS (ISO 45001), NOT ISMS (ISO 27001). This is a common confusion.

---

## 10. Auditor Competence — Team vs. Individual

**From IAF MD 11 and IAF MD 9:**

> "The audit team shall have the collective competence to cover all of the management system standards included in the scope. Individual auditors are not required to be competent in all of the standards."

This means:
- For integrated audits (ISO 9001 + ISO 14001 + ISO 45001): Auditor A can cover ISO 9001 + 14001, Auditor B covers ISO 45001 — team collectively covers all
- For ISO 13485 multi-TA scopes: different auditors can cover different TAs — team collectively must cover all TAs in client scope
- The LEAD AUDITOR should ideally have competence across all standards for coordination purposes — but this is best practice, not always a hard rule

**Platform validation rule:**  
Check that the TEAM (lead + auditors + technical experts) collectively covers all required standards AND required scope codes (EA codes / food chain categories / TAs). Block save if any standard/code is uncovered.

---

## 11. Impartiality Rules (ISO 17021-1)

- Auditor must not have provided consulting to the client in the previous 2 years
- Auditor must not have audited the client's system in the previous 2 years (except surveillance continuity is allowed)
- Certification decision must be made by a different person than the auditor(s) who conducted the audit

---

## 12. TÜRKAK / UAF Notes

**TÜRKAK (Turkey — national AB):**
- Full IAF MLA member — no structural deviations from IAF mandatory documents
- Localization requirements: auditors must know Turkish OHS law (Law No. 6331) for ISO 45001; Turkish environmental law (Çevre Kanunu No. 2872) for ISO 14001
- Document format: Turkish required; bilingual acceptable
- CB accreditation number format: AB-XXXX-YS (YS = Yönetim Sistemi)
- Symbol usage: TÜRKAK R10.06 — CBs may use TÜRKAK mark but NOT directly EA/IAF/ILAC logos

**UAF (United Accreditation Foundation, USA):**
- Full IAF MLA member
- CBs must submit audit time calculation methodology for UAF review
- For FSSC 22000 accreditation: CBs must conform to ISO/IEC 17021, ISO 22003-1:2022, AND additional UAF international requirements
- If IFC Global uses FSSC 22000: must verify CB is FSSC Foundation-approved (separate from UAF accreditation)

---

## 13. Stage Planning Rules

**Mandatory stage order:** Stage 1 → Stage 2 → Surveillance/Recertification  
(From ISO 17021-1 — Stage 1 must complete before Stage 2 starts.)

**Stage 1 → Stage 2 gap:** No fixed mandatory minimum days in ISO 17021-1. Gap must be "sufficient time for the organization to resolve issues found in Stage 1." Industry practice: 2–8 weeks. IFC Global internal procedures (PR.202/PR.203) define the specific rules.

**First surveillance:** Must complete within 12 months of certification decision date (ISO 17021-1 §9.1.3.3).

**Certification decision:** Must be made by a different person than the audit team.

**3-year certification cycle:** Begins from certification decision date.

---

## 14. Witness Audit Requirements (IAF MD 17)

Witness audits are conducted by ABs (not CBs) to assess auditor competence for each scope code:
- Each EA code / food chain category / TA must be witnessed within the AB's assessment cycle
- Higher-risk scopes witnessed more frequently
- CB must track which auditor was witnessed for which standard AND which scope code (EA code / category / TA)
- Witness records are per-auditor, per-standard, per-scope-code

---

## Sources

- IAF MD 5:2023 — https://iaf.nu/iaf_system/uploads/documents/IAF_MD5_Issue_4_Version_3_14062023.pdf
- IAF MD 9:2023 Issue 5 — https://iaf.nu/iaf_system/uploads/documents/IAF_MD9_Issue_5_20112023.pdf
- IAF MD 11:2023 — https://iaf.nu/iaf_system/uploads/documents/IAF_MD_11_Issue_3_12092023.pdf
- IAF MD 16:2024 — https://iaf.nu/iaf_system/uploads/documents/IAF_MD16_Issue_2_21052024.pdf
- IAF MD 17:2023 — https://iaf.nu/iaf_system/uploads/documents/IAF_MD17_Issue_2_Version2_14062023.pdf
- IAF MD 22:2023 — https://iaf.nu/iaf_system/uploads/documents/IAF_MD22_Issue_2_Version2_14062023.pdf
- FSSC 22000 Scheme v6 — https://www.fssc.com/wp-content/uploads/2023/03/FSSC-22000-Scheme-Version-6-.pdf
- ISO 22003-1:2022 overview — https://blog.ansi.org/ansi/iso-22003-1-2022-food-safety/
- ISO 50003:2021 sample — https://cdn.standards.iteh.ai/samples/77575/f7a88bf0990343b9ab2bf36845e719fb/ISO-50003-2021.pdf
- ISO/IEC 27006-1:2024 changes — https://linfordco.com/blog/iso-iec-27006-updates-guidance/
- TÜRKAK — https://www.turkak.org.tr/en/institutional/certification-accreditation-department.html
