# Scope-Aware Stage Planning — Complete Multi-Standard Implementation

## What we are building

The audit stage planning page must become fully scope-aware for every standard IFC Global certifies.
Right now it shows a generic auditor dropdown with no filtering. We need it to:

1. Derive the required scope codes/categories for every standard from the client's scope text
2. Auto-calculate man-days using the correct table for each standard
3. Show only auditors who cover the required codes — labelled with what they personally cover for THIS audit
4. Validate that the assigned team collectively covers every required code for every standard before allowing save

This must work for all standards — individually and in any integrated combination.

---

## Reference: every standard and its scope system

This is the authoritative table. Never mix these up.

| Standard | Scope System | What drives auditor eligibility |
|---|---|---|
| ISO 9001 | IAF EA codes (EA 1–39) + Risk level (High/Medium/Low) | Auditor's ISO 9001 `ea_codes` must include the required EA code |
| ISO 14001 | IAF EA codes (EA 1–39) + Env. significance (High/Medium/Low/Limited) | Auditor's ISO 14001 `ea_codes` must include the required EA code |
| ISO 45001 | IAF EA codes (EA 1–39) + OHS risk (High/Medium/Low, AB-defined) | Auditor's ISO 45001 `ea_codes` must include the required EA code |
| ISO 27001 | IAF EA codes (EA 1–39) + ISMS complexity factors | Auditor's ISO 27001 `ea_codes` must include the required EA code |
| ISO 22000 | Food chain categories — NOT EA codes | Auditor's ISO 22000 `scope_category` must include the required category codes |
| FSSC 22000 | Food chain categories — same as ISO 22000 | Auditor's FSSC 22000 `scope_category` must include the required category codes |
| ISO 13485 | Medical device Technical Areas (A1.1–A1.7, A2.1–A2.4) — NOT EA codes | Auditor's ISO 13485 `scope_category` must include the required TA codes |
| ISO 50001 | IAF EA codes + Energy complexity (Low/Medium/High via K-factor) | Auditor's ISO 50001 `ea_codes` must include required EA code AND complexity must match |
| ISO 37001 | Sector (Public / Private / Third sector/NGO) — no standard code system | Auditor's ISO 37001 `scope_category` must match the client sector |
| ISO 37301 | Sector (Public / Private / Third sector/NGO) — no standard code system | Auditor's ISO 37301 `scope_category` must match the client sector |

---

## Step 1 — Derive required scope codes from the client's scope text

When a client audit set is loaded, derive what codes/categories are required for each standard.
Store the result in a new JSON column `required_scope` on `audit_sets`.

### Structure of `required_scope`

```json
{
  "ISO 9001":    {"type": "ea_codes",        "codes": ["EA 3"], "risk": "High"},
  "ISO 14001":   {"type": "ea_codes",        "codes": ["EA 3"], "env_significance": "Medium"},
  "ISO 45001":   {"type": "ea_codes",        "codes": ["EA 3"], "ohs_risk": "High"},
  "ISO 27001":   {"type": "ea_codes",        "codes": ["EA 33"]},
  "ISO 22000":   {"type": "food_categories", "codes": ["CIV", "CIII"]},
  "FSSC 22000":  {"type": "food_categories", "codes": ["CIV", "CIII"]},
  "ISO 13485":   {"type": "medical_tas",     "codes": ["A1.1", "A1.3"]},
  "ISO 50001":   {"type": "ea_codes",        "codes": ["EA 3"], "complexity": "Medium"},
  "ISO 37001":   {"type": "sector",          "codes": ["Private"]},
  "ISO 37301":   {"type": "sector",          "codes": ["Private"]}
}
```

Only include keys for the standards that are actually in this audit set's `standards` field.

### Derivation rules per standard

**ISO 9001, ISO 14001, ISO 45001, ISO 27001, ISO 50001 → EA codes:**
Use the existing `ea_code` field on `AuditSet` as the primary source (it's already stored).
If empty, infer from `scope_en` using Claude with the IAF EA code list.
Examples:
- "Production of cakes, tortillas, snacks" → EA 3 (Food products, beverages and tobacco)
- "Software development, IT services" → EA 33 (Information technology)
- "Hospital, healthcare services" → EA 38 (Health and social work)
- "Construction of buildings" → EA 28 (Construction)
- "Manufacture of automobiles" → EA 22 (Other transport equipment)
- "Financial services, banking" → EA 32 (Financial intermediation)
- "Aerospace manufacturing" → EA 21 (Aerospace)
- "Pharmaceutical manufacturing" → EA 13 (Pharmaceuticals)
- "Medical device manufacturing" → EA 13 (Pharmaceuticals) for 9001; use TA codes for 13485

For ISO 45001: also set `ohs_risk` — High for manufacturing/construction/mining/chemical/food/pharma/aerospace, Medium for most other manufacturing and trade, Low for pure office/service environments.
For ISO 14001: also set `env_significance` — High for food processing, manufacturing, chemical, construction; Limited for pure office/service organizations.
For ISO 50001: also set `complexity` — derive from scope: large industrial/multiple energy types → High; mid-size manufacturing → Medium; small facilities/office → Low.

**ISO 22000 and FSSC 22000 → Food chain categories:**
Map `scope_en` to food chain category codes (from ISO 22003-1:2022 Annex A):

| Category | Description | Trigger keywords in scope |
|---|---|---|
| BIII | Pre-harvest plant handling, cleaning/sorting/packing of whole harvested plants | grain storage, fresh produce packing, crop cooling, post-harvest plant handling |
| C0 | Animal primary conversion: slaughterhouses, abattoirs, lairage, evisceration | slaughter, abattoir, animal slaughter, primary animal processing |
| CI | Processing of perishable animal products: meat, dairy, fish, ice cream | meat processing, dairy, cheese, yogurt, fish processing, seafood, deli meats, ice cream |
| CII | Processing of perishable plant products: fresh-cut, juices | fresh-cut vegetables, fresh juice, chilled plant, minimally processed vegetables |
| CIII | Processing of perishable mixed products: sandwiches, ready meals, meal kits | sandwiches, ready meals, prepared foods, mixed perishable, meal kits |
| CIV | Processing of ambient stable products: confectionery, canned, dried, beverages | cakes, biscuits, cookies, snacks, chips, crackers, tortillas, confectionery, chocolate, candy, gum, canned, dried goods, cereals, pasta, rice, flour, edible oils, sauces, ambient beverages |
| D | Feed and pet food | animal feed, pet food, livestock feed, aquafeed |
| E | Catering: restaurants, canteens, food service | catering, restaurant, canteen, food service, hotel kitchen, take-away |
| FI | Wholesale/retail/e-commerce of food | food retail, food wholesale, supermarket, food distribution |
| FII | Food brokering/trading (no physical possession) | food broker, food trader, food import export without physical handling |
| G | Storage, distribution, transport of food | cold chain, food logistics, food warehousing, food transport, temperature-controlled |
| I | Production of food packaging and packaging materials | food packaging, food-contact packaging, packaging materials manufacturer |
| K | (Bio)chemicals, food ingredients, processing aids, bio-cultures | food additives, flavours, enzymes, food ingredients, processing aids, bio-cultures, food-grade chemicals |

Example: "Production of cakes, tortillas, gluten-free snacks, and sandwiches"
→ CIV (cakes, tortillas, snacks = ambient stable products)
→ CIII (sandwiches = perishable mixed products)

**ISO 13485 → Medical Device Technical Areas:**
Map `scope_en` to TA codes (from IAF MD 9:2023 Annex A):

| TA | Description | Trigger keywords |
|---|---|---|
| A1.1 | Non-active medical devices (general) | bandages, wound care, catheters, surgical instruments, syringes, dental devices (non-electronic), diagnostic test strips |
| A1.2 | Non-active implantable devices | hip replacement, knee replacement, dental implants, bone screws, vascular stents, hernia mesh |
| A1.3 | Active (non-implantable) devices | diagnostic imaging, X-ray, ultrasound, MRI, CT scanner, patient monitoring, infusion pumps, ventilators, surgical energy |
| A1.4 | Active implantable devices | pacemakers, implantable defibrillators, cochlear implants, neurostimulators |
| A1.5 | Sterilization | sterilization, EtO, autoclave, gamma sterilization, aseptic processing |
| A1.6 | Special technologies | software as medical device, SaMD, nanomaterials, AI medical device |
| A1.7 | Parts, components, raw materials, services | medical device components, raw materials for medical devices, calibration services for medical |
| A2.1 | IVD instruments and software | IVD analyzers, laboratory instruments, diagnostic software |
| A2.2 | IVD reagents, calibrators, controls | IVD reagents, calibrators, diagnostic controls |
| A2.3 | IVD specimen receptacles | blood collection tubes, sample containers, specimen receptacles |
| A2.4 | Companion diagnostic devices | companion diagnostics |

**ISO 37001 and ISO 37301 → Sector:**
Derive from the client's industry type:
- `Private`: commercial companies, corporations, manufacturers, banks, consulting firms, food producers — default for most commercial clients
- `Public`: government agencies, municipalities, state-owned enterprises, public hospitals, ministries
- `Third sector/NGO`: non-profit organizations, NGOs, charities, associations, foundations

**Derivation method:**
Use Claude (via existing `anthropic` client in backend) with a focused system prompt: given the scope text, the client name, and the standards list, return the `required_scope` JSON. Fall back to the keyword-matching rules above if the API call fails.

**When to run derivation:**
- When the audit set detail page loads and `required_scope` is null/empty
- When the scope text changes
- Via a "Refresh scope codes" button on the plan overview

**Display on plan overview:**
Show the derived codes on the client plan overview page, below the scope text fields. Group by standard. Use the correct visual style per type:
- EA codes: small grey chips (EA 3, EA 28...)
- Food chain categories: small amber tags (CIV, CIII...)
- Medical TAs: small purple tags (A1.1, A1.3...)
- Sector: blue badge (Private, Public...)
- Complexity: colored badge (Low=green, Medium=amber, High=red)
- Risk/env. significance: same colored badge as complexity

The user must be able to manually edit/override these before they are used for auditor filtering.

---

## Step 2 — Man-day calculation for every standard

Auto-calculate when `required_scope` and `personnel` are both known. Do not require the user to click anything.

### Calculation rules

**ISO 9001, ISO 14001, ISO 45001 — IAF MD 5:2023:**
Look up total audit time from the relevant MD 5 table using total personnel count (`audit_set.personnel.total` or sum of all personnel fields).
- Maximum reduction from table value: 30% (applied for simple/low-risk organizations)
- Risk/significance modifiers: High risk → table value or above; Low → can reduce up to 30%
- Stage split: Stage 1 ≈ 1/3 of total; Stage 2 ≈ 2/3 of total
- Surveillance ≥ 1/3 of initial total per visit

**ISO 22000 — ISO 22003-1:2022 Annex B:**
Use the food chain category and personnel count to look up audit time.
Stage split same as above.

**FSSC 22000 — ISO 22003-1:2022 Annex B + FSSC Scheme v6:**
Same as ISO 22000 plus:
- Mandatory SEPARATE reporting/preparation time: minimum 1.0 auditor-day (8 hours) — this is NOT on-site time, it is additional
- Interpreter required: add minimum 0.5 auditor-days
- Off-site storage facility: add minimum 0.25 auditor-days per facility

**ISO 13485 — IAF MD 9:2023:**
Look up audit time from IAF MD 9 Annex B table using personnel count and number of TAs in scope.
Stage split: Stage 1 ≈ 1/3; Stage 2 ≈ 2/3.

**ISO 50001 — ISO 50003:2021 Tables A.3–A.4:**
Look up audit time using personnel count and complexity level (Low/Medium/High).
Stage split: Stage 1 ≈ 1/3; Stage 2 ≈ 2/3.

**ISO 27001 — ISO/IEC 27006-1:2024 Table C.1:**
Look up audit time using effective personnel count (include freelancers and persons under organizational control even if not directly employed).
Complexity factors: criticality of information, technology diversity (number of IT platforms), extent of outsourcing, multi-site scope.
Stage split: Stage 1 ≈ 1/3; Stage 2 ≈ 2/3.

**ISO 37001 and ISO 37301:**
Use ISO 17021-1 principles. These standards do not have a fixed IAF MD 5 equivalent table. Use personnel count with a reasonable multiplier. Show as "estimated" with a note.

**Integrated audits — IAF MD 11:2023:**
When two or more standards are audited together:
1. Calculate each standard's time individually using its own table
2. Apply integration reduction:
   - Low integration (separate systems, co-located): 0–5% reduction
   - Medium integration (shared processes, combined manual): 5–15% reduction
   - High integration (fully integrated single management system): up to 20% reduction
3. Absolute floor: total combined time cannot be less than 50% of the sum of individual times
4. The integration level is a user-selectable field (default: Medium)

Common integrated combinations and their typical integration level:
- ISO 9001 + ISO 14001 + ISO 45001: often High (fully integrated IMS)
- ISO 9001 + ISO 22000: Medium (different system structures but shared documented info)
- ISO 9001 + ISO 13485: Medium to High
- ISO 9001 + ISO 27001: Medium (different focus areas)
- ISO 14001 + ISO 50001: Medium to High (overlapping energy/environmental aspects)
- ISO 9001 + ISO 37001: Low to Medium

**Display:**
In the "IAF MD 5 man-day calculation" section (currently collapsed), show:
- Per-standard breakdown: standard name, table used, personnel count, individual time
- Integration reduction applied (if multiple standards)
- Total combined audit time
- Stage 1 suggested duration (days) and suggested date range
- Stage 2 suggested duration (days) and suggested date range
- Note explaining the basis (which table, which standard)

Expand this section by default (not collapsed) when viewing an audit set.

---

## Step 3 — Scope-filtered and scope-labelled auditor dropdown

The auditor dropdown for each stage must show only auditors who contribute coverage for at least one required code/category in this audit.

### Filtering rules

For each auditor, look at their `standard_qualifications`. For each standard in this audit:

**ISO 9001, ISO 14001, ISO 45001, ISO 27001, ISO 50001 (EA code standards):**
The auditor's qualification for that standard must have the required EA code in its `ea_codes` array. Match by the numeric part (EA 3 matches "EA 3", "3", "ea3").

**ISO 22000, FSSC 22000 (food chain categories):**
The auditor's qualification for that standard must have `scope_category` containing at least one of the required food chain category codes (CI, CIV, CIII, etc.). The `scope_category` is stored as comma-separated string.

**ISO 13485 (medical device TAs):**
The auditor's qualification must have `scope_category` containing at least one of the required TA codes (A1.1, A1.3, etc.).

**ISO 50001 (EA codes + complexity):**
The auditor's qualification must have the required EA code AND `scope_category` complexity level must be equal to or more capable than required (High > Medium > Low).

**ISO 37001, ISO 37301 (sector):**
The auditor's `scope_category` for that standard must match the required sector.

An auditor passes the filter if they contribute coverage for at least one standard and at least one code within it.

### Dropdown label format

Replace the plain "Name — Role" label with a coverage-aware label:

```
Seung Kyu HAN — Lead Auditor
Covers: CI, CIV, CIII (ISO 22000/FSSC) · EA 3 (ISO 9001) · Private (ISO 37001)
```

Only show the codes that are relevant to THIS audit's required scope — not the auditor's full credentials. Do not show codes/standards that aren't required for this audit.

For auditors who are unavailable (date conflict), show them greyed out at the bottom with the conflict reason as before.

For auditors who are qualified for the standard but don't cover any required code (e.g., they have ISO 22000 but only for CI and the client needs CIV, CIII), exclude them from the dropdown entirely — they provide no coverage value.

### Multi-standard audits

For an ISO 9001 + ISO 22000 integrated audit, the dropdown should include any auditor who covers ISO 9001 OR ISO 22000 — because the team collectively must cover both. An auditor who only covers ISO 9001 (EA 3) and not ISO 22000 is still useful if another team member covers ISO 22000.

---

## Step 4 — Live team coverage validation

Below the lead auditor selector and the auditors multi-select for each stage, show a live coverage panel that updates as auditors are added or removed.

### Coverage panel

Build a coverage map: for each standard in this audit and each required code, track which team members cover it.

Display as a compact table or list:

```
Coverage check — ISO 9001 (EA 3):    ✓ Seung Kyu HAN
Coverage check — ISO 22000 (CIV):    ✓ Seung Kyu HAN
Coverage check — ISO 22000 (CIII):   ✓ Seung Kyu HAN
Coverage check — ISO 22000 (CI):     — not required for this client
```

Or for a case with missing coverage:
```
Coverage check — ISO 13485 (A1.3):   ✗ Not covered — add an auditor qualified for A1.3
Coverage check — ISO 13485 (A1.1):   ✓ Dr. Smith
```

### Save block

If any required code/category is not covered by any team member, block the "Save stage" button and show:
"Cannot save: the following required scope areas have no qualified auditor assigned: A1.3 (ISO 13485). Please add a team member who covers this technical area."

For Stage 1 (documentation review), coverage requirements may be lighter — the platform should still warn but allow save with a warning flag rather than a hard block. For Stage 2 (on-site audit), the coverage check is a hard block.

---

## Key implementation notes

**Database:**
Add column `required_scope JSON` to `audit_sets` table using `_safe_add_column`.
Add column `integration_level VARCHAR` (Low/Medium/High) to `audit_sets` table, default 'Medium'.

**Backend endpoint changes:**
Extend `/api/auditors/available` to accept:
- `required_standards`: comma-separated list of standard codes (e.g. "ISO 9001,ISO 22000")
- `required_categories`: JSON-encoded dict of {standard: [codes]} matching the `required_scope` structure
This replaces the current single `standard_code` + `ea_code` params, which only handle one standard and one EA code.

The response for each auditor should include `covered_scope`: what they actually cover from the required list (not their full credentials). This is what the dropdown label shows.

**Frontend — plan overview section:**
Add a "Required scope" display row between the existing scope text and the audit stages section.
Add an "Integration level" selector (Low / Medium / High) that affects the man-day calculation.
Expand the man-day calculation section by default.

**Frontend — stage cards:**
Replace the current single auditor dropdown with the filtered dropdown.
Add the live coverage panel below the auditor selectors.
The coverage panel is the most important UX element — make it clear and visible.

**Standards in this system that use "QMS/EMS/OHSMS/FSMS" labels:**
The audit set stores standards as labels like "QMS", "EMS", "OHSMS", "FSMS", "ISMS", "MDQMS", "ABMS", "ENMS". Map these to ISO codes for all the filtering logic:
- QMS → ISO 9001
- EMS → ISO 14001
- OHSMS → ISO 45001
- FSMS → ISO 22000 AND/OR FSSC 22000 (check which is in the audit)
- ISMS → ISO 27001
- MDQMS → ISO 13485
- ABMS → ISO 37001
- ENMS → ISO 50001
- CMS → ISO 37301
