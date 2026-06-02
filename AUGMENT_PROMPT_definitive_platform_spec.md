# Certiva — Definitive Platform Specification & Audit

Read this entire document before touching any code. Then audit every file listed against this spec. Fix everything that does not match. Report what was correct, what was wrong, and what you changed.

---

## WHO USES THIS SYSTEM

IFC Global staff create audit sets on the dashboard. The company being certified does not interact with the system. There is no applicant-facing form. Everything is entered by the IFC Global coordinator.

---

## THE COMPLETE FLOW

```
Coordinator creates audit set on dashboard
    → system immediately derives scope codes
    → system immediately calculates man-days
    → system immediately creates stage records

Coordinator opens the client page
    → sees scope codes already there
    → sees man-days already calculated
    → sees stage cards ready

For each stage:
    Coordinator selects how many auditors
    Coordinator selects who (filtered dropdown)
    System validates team covers all required codes
    Coordinator picks start date(s) — range is locked by formula
    System warns if any team member is unavailable on picked dates
    
Coordinator confirms → audit package created
    → auditor availability logged
    → documents generated
    → status advances
```

There is no "Quick Calculate" widget. There is no "Derive required scope" button. There is no manual trigger of any kind. Everything in step 1 happens the moment the audit set is saved.

---

## PART 1 — AUDIT SET CREATION (backend/audit_set/service.py)

### What `create_audit_set()` must do, in this order:

**Step A — Derive integration level from boolean fields**

```python
il = audit_set.integration_level or {}
yes_count = sum(1 for v in il.values() if v is True)
if yes_count <= 1:
    audit_set.scope_integration_level = "Low"
elif yes_count <= 3:
    audit_set.scope_integration_level = "Medium"
else:
    audit_set.scope_integration_level = "High"
```

This runs before the calculation so the engine receives the correct integration level.

**Step B — Run man-day calculation**

Call `_run_calculation(audit_set)`. This already exists. Verify it receives `scope_integration_level`. If result is not None, save:
```python
audit_set.man_day_result = result
audit_set.effective_employees = int(round(result.get("eps", 0)))
```

**Step C — Derive required scope (CURRENTLY MISSING — ADD THIS)**

Immediately after Step B:
```python
audit_set.required_scope = derive_required_scope(
    standards=audit_set.standards or [],
    scope_tr=audit_set.scope_tr,
    scope_en=audit_set.scope_en,
    ea_code=audit_set.ea_code,
)
```

**Step D — Create stage records**

Call `_create_auto_stages(db, audit_set, result)`. Verify:
- `audit_type == "initial"` → Stage 1 (`stage_type="stage_1"`, `stage_order=1`, `audit_days=result["final_ph1"]`) + Stage 2 (`stage_type="stage_2"`, `stage_order=2`, `audit_days=result["final_ph2"]`)
- `audit_type == "surveillance_1"` or `"surveillance_2"` → single stage (`stage_type="surveillance"`, `stage_order=1`, `audit_days=result["final_surv1"]`)
- `audit_type == "recertification"` → single stage (`stage_type="stage_2"`, `stage_order=1`, `audit_days=result["final_recert"]` or `result["final_ph2"]`)

---

## PART 2 — MAN-DAY CALCULATION (backend/calculator/engine.py)

**Do not rewrite the engine. Audit it against these rules and fix only what is wrong.**

### ISO 9001 / ISO 14001 / ISO 45001 (IAF MD 5:2023)
- EPS = total employees (full_time + part_time + subcontractors + seasonal + unskilled), with shift workers counted once per shift
- Repetitive/low-complexity employees (unskilled, assembly line) are reduced: EPS = office_employees + (repetitive_employees × reduction_factor)
- Table lookup: separate tables for QMS (ISO 9001), EMS (ISO 14001), OHSMS (ISO 45001)
- Risk/significance modifier applied after table lookup
- Maximum table reduction: 30%

### ISO 22000 / FSSC 22000 (ISO 22003-1:2022 Annex B)
- EPS = personnel involved in food safety activities (not total headcount)
- Audit time varies by food chain category — CI and CII are more intensive than CIV
- FSSC 22000 adds a mandatory separate reporting/preparation time: minimum 1.0 auditor-day — this is NOT on-site time, it must appear as a separate line in the result

### ISO 13485 (IAF MD 9:2023 Annex B)
- EPS = total employees at site
- Time varies by number of Technical Areas (TAs) in scope
- A1.7-only (component suppliers) has lighter time requirements

### ISO 50001 (ISO 50003:2021 Tables A.3–A.4)
- K-factor: `C = (FEC × 0.25) + (FET × 0.25) + (FSEU × 0.50)`
- FEC thresholds: ≤20 TJ=1.0, 20–200=1.2, 200–2000=1.4, >2000=1.6
- FET thresholds: 1–2 types=1.0, 3=1.2, ≥4=1.4
- FSEU thresholds: 1–3=1.0, 4–6=1.2, 7–10=1.3, 11–15=1.4, ≥16=1.6
- Complexity: C<1.15=Low, 1.15≤C≤1.35=Medium, C>1.35=High
- Audit time from Table A.3 (initial) and A.4 (surveillance/recertification)

### ISO 27001 (ISO/IEC 27006-1:2024 Table C.1)
- Effective personnel includes freelancers and persons under organisational control (2024 revision)
- Complexity factors: criticality of information, technology diversity, outsourcing, multi-site

### ISO 37001 / ISO 37301
- No fixed IAF table — derive from personnel count using ISO 17021-1 principles
- Label output as "Estimated — no fixed IAF table"

### IAF MD 11:2023 — Integration reduction
Only applies when 2 or more standards are audited together.
- Low: 5% reduction (separate systems, co-located only)
- Medium: 10% reduction (shared processes, combined manual)
- High: 20% reduction (fully integrated single management system — this is the ABSOLUTE CEILING)
- After reduction, total combined time must be ≥ 50% of the sum of individual times — if floor triggers, set `md11_floor_applied: true` in the result
- Integration level is derived from the boolean fields in `audit_set.integration_level` (count of True values → Low/Medium/High as defined in Part 1 Step A)

### Phase splits
- Initial Stage 1: ≈ 1/3 of total initial time → `final_ph1`
- Initial Stage 2: ≈ 2/3 of total initial time → `final_ph2`
- Surveillance: each visit ≥ 1/3 of initial total → `final_surv1`
- Recertification: ≈ 2/3 of initial total → `final_recert`
- 20% reporting deduction applied to get final on-site time (IFC Global internal rule)

---

## PART 3 — SCOPE DERIVATION (backend/audit_set/service.py — `derive_required_scope()`)

The function must infer scope codes from the scope text. It currently returns empty for ISO 9001/14001/45001/27001 when no `ea_code` is stored. Fix this.

### Add these keyword maps (after `_ENERGY_MED_KW`):

```python
_SCOPE_TO_EA_KW: dict[str, tuple[str, ...]] = {
    "EA 1":  ("agriculture", "farming", "horticulture", "fishery", "aquaculture", "forestry", "livestock"),
    "EA 3":  ("food", "beverage", "tobacco", "bakery", "confectionery", "dairy", "meat processing",
              "cake", "tortilla", "snack", "sandwich", "pastry", "bread", "milling", "brewing",
              "gluten", "biscuit", "cookie", "cracker", "noodle"),
    "EA 4":  ("textile", "clothing", "apparel", "garment", "leather", "footwear"),
    "EA 5":  ("wood", "furniture", "paper", "pulp", "printing", "packaging material"),
    "EA 6":  ("chemical", "petrochemical", "pharmaceutical", "cosmetic", "paint", "coating"),
    "EA 7":  ("metal", "steel", "aluminium", "foundry", "forging", "casting", "metallurgy"),
    "EA 8":  ("machinery", "equipment manufacturing", "pump", "compressor", "valve"),
    "EA 9":  ("electrical", "electronics", "semiconductor", "circuit board", "pcb"),
    "EA 10": ("shipbuilding", "marine", "aerospace", "aircraft", "defence"),
    "EA 11": ("automotive", "vehicle", "car", "truck", "spare part"),
    "EA 13": ("rubber", "plastic", "polymer"),
    "EA 14": ("glass", "ceramic", "stone", "mineral", "tile"),
    "EA 15": ("concrete", "cement", "construction material"),
    "EA 16": ("construction", "building", "civil engineering", "contractor"),
    "EA 17": ("wholesale", "retail", "trade", "distribution"),
    "EA 18": ("hotel", "restaurant", "catering", "hospitality", "tourism"),
    "EA 19": ("transport", "logistics", "freight", "courier", "shipping", "warehousing"),
    "EA 20": ("mining", "quarrying", "oil", "gas", "refinery", "petroleum"),
    "EA 21": ("water treatment", "waste management", "recycling", "environmental services"),
    "EA 22": ("electricity generation", "power plant", "gas supply", "energy utility"),
    "EA 23": ("education", "training", "school", "university", "academy"),
    "EA 24": ("healthcare", "hospital", "clinic", "medical services", "diagnostic"),
    "EA 26": ("financial", "banking", "insurance", "investment"),
    "EA 27": ("information technology", "it services", "data centre", "cloud"),
    "EA 28": ("telecom", "telecommunication", "internet service"),
    "EA 29": ("engineering services", "technical consulting", "inspection", "testing laboratory"),
    "EA 33": ("software development", "software house", "it consulting", "saas"),
    "EA 34": ("management consulting", "business services", "legal services"),
    "EA 35": ("public administration", "government services", "municipality"),
}

_RISK_HIGH_KW: tuple[str, ...] = (
    "food", "pharmaceutical", "medical", "aerospace", "nuclear", "defence",
    "chemical", "petrochemical", "construction", "mining", "oil", "gas",
    "cake", "tortilla", "snack", "sandwich", "dairy", "meat", "bakery", "implant",
)
_RISK_LOW_KW: tuple[str, ...] = (
    "software development", "it consulting", "consultancy", "training",
    "education", "media", "publishing", "financial", "insurance",
)
```

Add to `_FOOD_CHAIN_KW["CIV"]` tuple: `"cake"`, `"tortilla"`, `"bread"`, `"bakery"`, `"pastry"`, `"gluten"`, `"wrap"`, `"noodle"`.

### Replace the broken elif block for ISO 9001/14001/45001/27001:

```python
        elif any(n in norm for n in ("9001", "14001", "45001", "27001")):
            if ea_code:
                codes = [ea_code]
            else:
                codes = [ea for ea, kws in _SCOPE_TO_EA_KW.items()
                         if any(kw in haystack for kw in kws)]
            if any(kw in haystack for kw in _RISK_HIGH_KW):
                risk = "High"
            elif any(kw in haystack for kw in _RISK_LOW_KW):
                risk = "Low"
            else:
                risk = "Medium"
            result[iso] = {"type": "ea", "codes": codes, "risk": risk}
```

---

## PART 4 — CLIENT DETAIL PAGE (frontend/src/app/(app)/clients/[id]/page.tsx)

### What must be visible on page load with zero clicks:

**Required scope section:** shows the derived codes per standard.
- ISO 9001/14001/45001/27001: grey/green EA code chips + coloured risk badge
- ISO 22000/FSSC: amber food category chips — NO EA codes
- ISO 13485: purple TA chips — NO EA codes
- ISO 37001/37301: blue sector badge — NO EA codes
- ISO 50001: coloured complexity badge + EA codes if present

If `required_scope` is null on a legacy record, show a single "Derive scope" button as fallback. For all records created after this fix it will never be null.

**Man-day section:** open by default. Shows per-standard breakdown, integration reduction, 50% floor if applied, FSSC surcharge if applicable, final Stage 1 and Stage 2 days.

**Remove the QuickCalcWidget entirely.** There is no scenario where the coordinator should manually enter personnel numbers. Personnel is entered when the audit set is created. If `man_day_result` is null on an existing record, fix it by adding a backend migration or re-running `_run_calculation()` on save — do not expose a calculator UI to the coordinator.

**Auto-recalculate on load if result is missing:**

```typescript
useEffect(() => {
  if (!data || data.man_day_result || autoCalcFired.current) return
  const p = data.personnel
  const total = (p?.full_time || 0) + (p?.part_time || 0) + (p?.subcontractors || 0)
              + (p?.seasonal || 0) + (p?.unskilled || 0)
  if (total <= 0) return
  autoCalcFired.current = true
  api.post(`/audit-sets/${id}/quick-calculate`, {
    personnel: {
      full_time: p?.full_time || 0, part_time: p?.part_time || 0,
      subcontractors: p?.subcontractors || 0, seasonal: p?.seasonal || 0,
      unskilled: p?.unskilled || 0,
    },
    scope_integration_level: data.scope_integration_level ?? 'Medium',
  }).then(() => queryClient.invalidateQueries({ queryKey: ['client', id] })).catch(() => {})
}, [data?.id, data?.man_day_result])
```

---

## PART 5 — STAGE PLANNING CARDS

### The rule that governs everything

```
required_calendar_days = ceil(stage.audit_days / total_auditors)
```

- `stage.audit_days` = the IAF-calculated value stored on the stage record
- `total_auditors` = lead auditor (1) + additional auditors count
- Technical experts do NOT count toward man-days (they observe, not audit)

### Stage card interaction — exact sequence

1. **Coordinator selects auditors first** (lead + additional). The dropdown is filtered — see Part 6.

2. **System computes required calendar days** from the formula above. This is displayed prominently:
   > "IAF MD 5: {stage.audit_days} audit-days ÷ {auditor_count} auditor(s) = {calendar_days} calendar day(s)"

3. **Coordinator picks start date.** The end date is auto-set: `end = suggestEndDate(start, calendar_days)`. The coordinator cannot freely pick an end date — it is always computed from start + `calendar_days`. They may pick any start date they want.

4. **Exception — non-consecutive days:** If the coordinator explicitly changes the end date, the system validates that the working days between start and end equals `calendar_days`. If not, show an error: "This date range covers {actual_working_days} working day(s) but {calendar_days} are required for {auditor_count} auditor(s) on {stage.audit_days} audit-day(s). Adjust the range."

5. **Availability check:** When dates are picked, query `/api/auditors/available` with those dates. If any assigned team member is unavailable on those dates (already booked on another audit), show a warning per person:
   > "⚠ {auditor_name} is already assigned to audit #{plan_number} on {conflicting_dates}. You can still proceed, but coordinate with the team."
   
   This is a WARNING only — it does not block saving.

6. **Coverage validation:** The team (lead + additional auditors only, not technical experts) must collectively cover all required scope codes across all standards. Display a live coverage panel below the auditor selectors showing green/red per code. Stage 2 save is hard-blocked if any code is red. Stage 1 save warns but does not block.

7. **Stage ordering:** Stage 1 end date must be strictly before Stage 2 start date. Enforce this on save.

### Reactive date update when auditors change

```typescript
useEffect(() => {
  if (!edit.audit_date_start || !stage.audit_days) return
  if (auditorCount === 0) return
  const calDays = Math.ceil(stage.audit_days / auditorCount)
  patch({ audit_date_end: suggestEndDate(edit.audit_date_start, calDays) })
}, [auditorCount])
```

Where `auditorCount = (edit.lead_auditor_name ? 1 : 0) + edit.auditors.length`.

---

## PART 6 — AUDITOR DROPDOWN FILTERING (backend/api/routes/auditors.py + frontend)

### Backend: `/api/auditors/available`

Accepts:
- `date_start`, `date_end` — to check availability
- `required_scope` — JSON string of the audit set's `required_scope` dict

Returns per auditor:
```json
{
  "id": "...",
  "name": "...",
  "is_available": true,
  "covered_scope": {
    "ISO 9001": ["EA 3"],
    "ISO 22000": ["CIV", "CIII"]
  }
}
```

**Coverage logic per standard type:**
- EA standards (9001/14001/45001/27001/50001): auditor's `ea_codes` for that standard must intersect required codes
- Food (22000/FSSC): auditor's `scope_category` must intersect required food categories
- Medical (13485): auditor's `scope_category` must intersect required TAs
- Sector (37001/37301): auditor's `scope_category` must match required sector
- Complexity (50001): auditor's `scope_category` complexity level must match or exceed required

**Inclusion rule:** Include an auditor if their `covered_scope` is non-empty for at least one standard. Exclude auditors with zero coverage across all standards.

**Availability:** Auditors with date conflicts are included but marked `is_available: false`. They appear in the dropdown greyed out with "(unavailable — booked on #{plan_number})".

### Frontend dropdown label

Each option shows:
```
{name} — {covered codes for THIS audit}
```

Examples:
- `Seung Kyu HAN — EA 3 · ISO 9001 | CIV CIII · ISO 22000`
- `Jane Smith — EA 3 · ISO 9001` (partial coverage)
- `Tom Lee — EA 3 · ISO 9001 (unavailable 19–21 May)` (greyed out)

---

## PART 7 — PACKAGE CREATION (audit package / download)

When the coordinator confirms the audit plan (all stages have a lead auditor and dates saved):

1. **Block auditor availability.** For each stage, for each assigned auditor (lead + additional), record the date range as occupied. This is what makes them show as "unavailable" in future audits during those dates.

2. **Advance status.** `audit_set.status → "active"` or `"scheduled"`.

3. **Generate documents.**
   - `accreditation_body == "UAF"` → English-language templates
   - `accreditation_body == "TÜRKAK"` → Turkish-language templates
   - If both → two separate document sets

Verify the "Download audit package" button triggers all three steps. Verify it does not 500 on a complete audit set.

---

## PART 8 — THINGS TO REMOVE

- **QuickCalcWidget component:** Remove it entirely from `clients/[id]/page.tsx`. Remove its render call. Remove the "Quick Calculate man-days" link. Personnel is entered at audit set creation time — the coordinator never re-enters it.
- **"Derive required scope" button:** Remove it from the plan overview header. Scope derivation is automatic on creation. Keep the backend endpoint as a fallback (for legacy records only), but do not surface it in the UI.

---

## AUDIT CHECKLIST

Go through each part above and for every item report:
- ✅ Already correct — what was verified
- ❌ Wrong — what the issue was, what file and function was changed, what the fix does
- ⚠️ Partially correct — what works and what still needs attention

Fix all ❌ items inline. Do not defer.

---

## VERIFICATION TEST

Create a new audit set with:
- Standards: QMS + FSMS
- Scope (EN): "Production of cakes, tortillas, gluten-free snacks, and sandwiches"
- Personnel: 45 full-time
- Audit type: Initial certification
- Integration level: 2 shared-process booleans = true (→ Medium → 10% reduction)
- Accreditation body: UAF

**Expected on client page load — no clicks:**
- Required scope: ISO 9001 → EA 3, risk High | ISO 22000 → CIV, CIII
- Man-day section open: shows per-standard breakdown, 10% integration reduction, final Stage 1 days, final Stage 2 days
- Two stage cards: Stage 1 (audit_days = final_ph1) and Stage 2 (audit_days = final_ph2)
- No QuickCalcWidget visible. No "Derive required scope" button visible.

**Stage planning test:**
- Stage 2 requires 4 audit-days (example)
- Coordinator selects lead auditor (1 person) → banner shows "4 audit-days ÷ 1 auditor = 4 calendar days"
- Coordinator adds second auditor → banner updates to "4 audit-days ÷ 2 auditors = 2 calendar days" → end date shifts automatically
- Coordinator picks May 19 as start → end date auto-sets to May 20 (2 working days)
- Auditor dropdown shows only auditors covering EA 3 (ISO 9001) or CIV/CIII (ISO 22000), labeled with which codes they cover
- Coverage panel shows green for all covered codes, red for any gap
- Save blocked if red codes remain for Stage 2

---

## FILES TO AUDIT AND POTENTIALLY CHANGE

| File | What to check |
|---|---|
| `backend/audit_set/service.py` | `create_audit_set()` calls derive_required_scope + integration level derivation; `derive_required_scope()` EA code inference from text; `_FOOD_CHAIN_KW` CIV keywords; `_create_auto_stages()` correct stage types per audit_type |
| `backend/calculator/engine.py` | Per-standard EPS formulas; IAF MD 11 rates (5/10/20%, 50% floor); phase splits; FSSC surcharge |
| `backend/api/routes/auditors.py` | `/available` returns `covered_scope` per auditor; filters zero-coverage auditors; includes unavailable auditors with booking info |
| `frontend/src/app/(app)/clients/[id]/page.tsx` | Auto-calc on load from `data.personnel`; QuickCalcWidget removed; "Derive required scope" button removed; stage card: auditor-count drives calendar days, reactive end-date update, availability warning, coverage panel, Stage 2 hard block |
| `backend/audit_set/db_models.py` | `required_scope` column exists (JSON); `scope_integration_level` column exists (String) |
