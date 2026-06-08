# Certiva — Full Platform Flow Implementation

This document describes the complete correct behaviour of the Certiva platform from application submission to audit package creation. Every step is either already implemented and must be verified, or is missing and must be built. Fix everything that does not match this spec.

---

## THE FLOW — end to end

```
1. Application submitted (form filled: company, standards, scope, personnel)
        ↓  [AUTOMATIC — zero clicks]
2. Scope codes derived and saved   (EA codes / food categories / medical TAs / sector / complexity)
        ↓  [AUTOMATIC — zero clicks]
3. Man-day calculation run and saved   (Stage 1 days, Stage 2 days, Surv days)
        ↓  [AUTOMATIC — zero clicks]
4. Stage records created with correct audit_days
        ↓  [COORDINATOR ACTION]
5. Stage planning: coordinator picks dates, then assigns auditors
        ↓  [SYSTEM VALIDATES]
6. System checks: do the dates × auditor count cover the required man-days?
        ↓  [SYSTEM VALIDATES]
7. System checks: does the team collectively cover all required scope codes?
        ↓  [COORDINATOR ACTION]
8. Coordinator finalises → creates audit package
        ↓  [AUTOMATIC]
9. Auditor availability is blocked for those dates. Status → active.
```

---

## STEP 1 — Application form fields (inputs to the system)

The application form collects:

- Company name, address, country, city, phone, email, website, representative
- `standards` — list, e.g. `["QMS", "FSMS"]`
- `audit_type` — "initial" | "surveillance_1" | "surveillance_2" | "recertification"
- `scope_tr` — Turkish scope text (free text)
- `scope_en` — English scope text (free text)
- `accreditation_body` — "UAF" | "TÜRKAK"
- `personnel` — `{full_time, part_time, subcontractors, seasonal, unskilled}`
- `sites` — list of `{address, process_description, employee_count}`
- `integration_level` — dict of boolean fields indicating shared processes, combined manual, single system, etc.
- `ea_code` — optional, if the coordinator already knows the EA code

All of these fields are stored in `AuditSet`. The system must use them immediately on creation.

---

## STEP 2 — Automatic actions in `create_audit_set()` (backend/audit_set/service.py)

The function `create_audit_set()` must do ALL of the following, in this order, every time:

### 2A — Derive integration level from boolean fields

```python
il = audit_set.integration_level or {}
yes_count = sum(1 for v in il.values() if v is True)
if yes_count <= 1:
    scope_integration_level = "Low"
elif yes_count <= 3:
    scope_integration_level = "Medium"
else:
    scope_integration_level = "High"
audit_set.scope_integration_level = scope_integration_level
```

This must happen BEFORE the calculation so the engine uses the correct integration level.

### 2B — Run man-day calculation

Call `_run_calculation(audit_set)` — this already exists. Verify it passes `scope_integration_level` to the engine. If `man_day_result` comes back, save it:

```python
result = _run_calculation(audit_set)
if result:
    audit_set.man_day_result = result
    audit_set.effective_employees = int(round(result.get("eps", 0)))
```

The engine (`calculator/engine.py`) uses IAF MD 5 for ISO 9001/14001/45001, ISO 22003-1 for ISO 22000/FSSC, IAF MD 9 for ISO 13485, ISO 50003 for ISO 50001, ISO/IEC 27006 for ISO 27001. It applies IAF MD 11 integration reduction (Low=5%, Medium=10%, High=20%, 50% floor). **Do not change the engine — it is correct.**

### 2C — Derive required scope (THIS IS MISSING — add it now)

After the calculation, immediately call:

```python
audit_set.required_scope = derive_required_scope(
    standards=audit_set.standards or [],
    scope_tr=audit_set.scope_tr,
    scope_en=audit_set.scope_en,
    ea_code=audit_set.ea_code,
)
```

This must run on EVERY creation. No manual button. No user click.

### 2D — Create stage records

Call `_create_auto_stages(db, audit_set, result)` — already exists. Verify:

- `audit_type = "initial"` → creates Stage 1 (`stage_type="stage_1"`, `stage_order=1`, `audit_days=result["final_ph1"]`) + Stage 2 (`stage_type="stage_2"`, `stage_order=2`, `audit_days=result["final_ph2"]`)
- `audit_type = "surveillance_1"` or `"surveillance_2"` → creates ONE stage (`stage_type="surveillance"`, `stage_order=1`, `audit_days=result["final_surv1"]`)
- `audit_type = "recertification"` → creates ONE stage (`stage_type="stage_2"`, `stage_order=1`, `audit_days=result["final_recert"]` or `result["final_ph2"]`)

---

## STEP 3 — Fix `derive_required_scope()` so it actually works

**File:** `backend/audit_set/service.py`, function `derive_required_scope()`

The function must use the scope text to derive codes. Currently it returns empty for ISO 9001/14001/45001/27001 when no `ea_code` is stored. Fix it.

### Add these keyword maps to the file (after `_ENERGY_MED_KW`):

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
    "EA 11": ("automotive", "vehicle", "car", "truck", "spare part", "auto component"),
    "EA 13": ("rubber", "plastic", "polymer"),
    "EA 14": ("glass", "ceramic", "stone", "mineral", "tile"),
    "EA 15": ("concrete", "cement", "construction material"),
    "EA 16": ("construction", "building", "civil engineering", "contractor"),
    "EA 17": ("wholesale", "retail", "trade", "distribution", "import export"),
    "EA 18": ("hotel", "restaurant", "catering", "hospitality", "tourism"),
    "EA 19": ("transport", "logistics", "freight", "courier", "shipping", "warehousing"),
    "EA 20": ("mining", "quarrying", "oil", "gas", "refinery", "petroleum"),
    "EA 21": ("water treatment", "waste management", "recycling", "environmental services"),
    "EA 22": ("electricity generation", "power plant", "gas supply", "energy utility"),
    "EA 23": ("education", "training", "school", "university", "academy"),
    "EA 24": ("healthcare", "hospital", "clinic", "medical services", "diagnostic"),
    "EA 26": ("financial", "banking", "insurance", "investment"),
    "EA 27": ("information technology", "it services", "data centre", "cloud"),
    "EA 28": ("telecom", "telecommunication", "internet service provider"),
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

Also add these to the `"CIV"` tuple inside `_FOOD_CHAIN_KW`: `"cake"`, `"tortilla"`, `"bread"`, `"bakery"`, `"pastry"`, `"gluten"`, `"wrap"`, `"noodle"`, `"wafer"`.

### Replace the broken elif block for ISO 9001/14001/45001/27001:

**Replace this:**
```python
        elif any(n in norm for n in ("9001", "14001", "45001", "27001")):
            codes = [ea_code] if ea_code else []
            result[iso] = {"type": "ea", "codes": codes}
```

**With this:**
```python
        elif any(n in norm for n in ("9001", "14001", "45001", "27001")):
            if ea_code:
                codes = [ea_code]
            else:
                codes = [
                    ea for ea, kws in _SCOPE_TO_EA_KW.items()
                    if any(kw in haystack for kw in kws)
                ]
            if any(kw in haystack for kw in _RISK_HIGH_KW):
                risk = "High"
            elif any(kw in haystack for kw in _RISK_LOW_KW):
                risk = "Low"
            else:
                risk = "Medium"
            result[iso] = {"type": "ea", "codes": codes, "risk": risk}
```

---

## STEP 4 — Client detail page: what must display automatically (frontend)

**File:** `frontend/src/app/(app)/clients/[id]/page.tsx`

When the client detail page loads, the following must already be populated — NO button clicks, NO loading states for these:

### Required scope section
Shows the `required_scope` JSON from the audit set. Per standard:
- ISO 9001 / 14001 / 45001 / 27001 → grey/green chips for each EA code, coloured badge for risk (green=Low, amber=Medium, red=High)
- ISO 22000 / FSSC 22000 → amber chips for food categories (CIV, CIII, etc.) — NO EA codes shown
- ISO 13485 → purple chips for technical areas (A1.1, A1.2, etc.) — NO EA codes shown
- ISO 37001 / 37301 → blue badge for sector (Public / Private / Third sector) — NO EA codes shown
- ISO 50001 → coloured badge for complexity (Low/Medium/High) + EA codes if present

If `required_scope` is null (legacy record), show a "Derive scope" button. For all new records created after this fix, it will never be null.

### Man-day calculation section
Shows the `man_day_result` JSON. Must be **open by default** (already implemented — verify `useState(true)` in `ManDaySection`).

Shows:
- Per-standard breakdown: standard name, individual audit days
- Integration reduction applied (level + percentage)
- Whether 50% floor was triggered
- FSSC 22000 reporting surcharge if applicable (separate line)
- Final Stage 1 recommended days + Stage 2 recommended days

If `man_day_result` is null (client has no personnel entered), show the QuickCalcWidget **open by default** (not as a collapsed link). Change `useState(false)` to `useState(true)` inside `QuickCalcWidget`.

---

## STEP 5 — Stage planning cards: date picking + validation

**File:** `frontend/src/app/(app)/clients/[id]/page.tsx` — the stage card components

Each stage card shows:
- Stage header: "Stage 1 — Documentation review" / "Stage 2 — On-site audit" / "Surveillance visit"
- IAF recommended audit-days for this stage (from `stage.audit_days`)
- Start date picker + End date picker
- Lead auditor dropdown
- Additional auditors dropdown (multi-select)
- Technical experts dropdown (multi-select)
- Save stage button

### Date validation rule
When the user selects dates, compute working days between start and end (inclusive, Mon–Fri, no public holidays). Then:

```
working_days_in_range × total_assigned_auditors ≥ stage.audit_days
```

If this condition is NOT met, show a warning banner inside the stage card:
> "⚠ Your date range covers {working_days} working day(s) × {auditor_count} auditor(s) = {man_days_covered} man-day(s). IAF recommends {stage.audit_days} audit-day(s) for this stage. Consider expanding the date range or adding more auditors."

This is a WARNING — it does NOT block saving. The coordinator may have a valid reason (e.g. observer only days).

Stage 2 save IS hard-blocked if any required scope code is uncovered by the team (see Step 6). Stage 1 save only warns.

### Stage ordering constraint
Stage 1 end date must be strictly before Stage 2 start date. If the user tries to save Stage 2 with start date ≤ Stage 1 end date, block the save with:
> "Stage 2 cannot start before Stage 1 is complete."

---

## STEP 6 — Auditor dropdowns: filtering and labeling

**File:** `backend/api/routes/auditors.py` — `/available` endpoint
**File:** `frontend/src/app/(app)/clients/[id]/page.tsx` — stage card auditor dropdowns

### Backend: `/api/auditors/available` endpoint

Accepts these query params:
- `start_date`, `end_date` — filter by availability
- `required_scope` — JSON string of the audit set's `required_scope` dict

For each auditor, compute `covered_scope`: which required codes from `required_scope` this auditor personally covers based on their qualifications.

An auditor covers a code if:
- For EA codes (ISO 9001/14001/45001/27001/50001): their qualification for that standard includes the required EA code in `ea_codes`
- For food categories (ISO 22000/FSSC): their qualification's `scope_category` contains any of the required food categories
- For medical TAs (ISO 13485): their qualification's `scope_category` contains any of the required TAs
- For sector (ISO 37001/37301): their qualification's `scope_category` matches the required sector
- For complexity (ISO 50001): their qualification's `scope_category` matches the required complexity level (or higher)

Return format per auditor:
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

**Filtering rule:**
- Include an auditor if they cover at least one required code for at least one standard
- If `required_scope` is empty or not provided, include all active auditors
- Auditors with date conflicts (`is_available=false`) are shown but greyed out — they are NOT excluded

### Frontend: auditor dropdown labels

Each auditor option in the dropdown must show:
```
{auditor_name} — {covered codes for this audit}
```

Examples:
- `Seung Kyu HAN — EA 3 (ISO 9001), CIV CIII (ISO 22000)`
- `John Smith — EA 3 (ISO 9001)` — partial, only covers one standard

Auditors with zero coverage are excluded from the list entirely (when `required_scope` is known).
Auditors with date conflicts are shown in the list but visually greyed out with a note "(unavailable on selected dates)".

---

## STEP 7 — Team coverage validation panel

Below the auditor selectors in each stage card, show a live coverage panel. This panel updates as auditors are added/removed.

For each required code across all standards:
- Show the code (e.g. "EA 3", "CIV", "CIII")
- Show which auditor covers it (green if covered, red if uncovered)

Example:
```
ISO 9001   EA 3   ✅ covered by Seung Kyu HAN
ISO 22000  CIV    ✅ covered by Seung Kyu HAN
ISO 22000  CIII   ❌ not covered — assign an auditor with CIII
```

**Save rules:**
- Stage 2: HARD BLOCK if any required code is red. Show error: "Cannot save: CIII (ISO 22000) is not covered by any assigned auditor."
- Stage 1: Show amber warning but allow save.

---

## STEP 8 — Package creation: lock availability + advance status

When the user finalises all stages (all have lead auditor assigned + saved), the "Download audit package" button (or a separate "Confirm audit plan" button) must trigger:

1. **Block auditor availability**: For each stage, for each assigned auditor (lead + additional + technical experts), record that those calendar dates are occupied. This means the `/api/auditors/available` endpoint will return `is_available=false` for those auditors on those dates going forward.

2. **Advance status**: `audit_set.status` → `"active"` (or `"scheduled"` — use whichever status means "plan is locked, audit will happen").

3. **Generate documents**: Start the document generation process:
   - UAF accreditation → English templates
   - TÜRKAK accreditation → Turkish templates
   - If both → generate two separate sets

The "Download audit package" button already exists. Verify it calls the correct backend endpoint and that the endpoint does all three steps above.

---

## VERIFICATION CHECKLIST

After all changes are deployed, test this exact scenario:

**Test client:** Company name "Pasta Factory Ltd", standards: QMS + FSMS, scope (EN): "Production of cakes, tortillas, gluten-free snacks, and sandwiches", personnel: 45 full-time, audit type: Initial certification, accreditation body: UAF.

**Expected results — without any manual clicks after creation:**

1. `required_scope` is populated:
   - ISO 9001 → `{type: "ea", codes: ["EA 3"], risk: "High"}`
   - ISO 22000 → `{type: "food", codes: ["CIV", "CIII"]}`

2. `man_day_result` is populated (45 employees → look up IAF MD 5 table for QMS + ISO 22003-1 for FSMS)

3. Two stage cards exist: Stage 1 (audit_days = final_ph1) + Stage 2 (audit_days = final_ph2)

4. Client detail page shows:
   - Required scope section: ISO 9001 chips "EA 3" + red "High" badge; ISO 22000 amber chips "CIV" "CIII"
   - Man-day section open with per-standard breakdown and final totals
   - Two stage cards: "Stage 1 — Documentation review" and "Stage 2 — On-site audit"

5. Auditor dropdown (after selecting dates) shows only auditors who have EA 3 OR food categories CIV/CIII in their qualifications, each labeled with which codes they cover.

6. Coverage panel shows green for codes covered by assigned team, red for gaps. Stage 2 save blocked if any red.

---

## Files to change

| File | Changes |
|---|---|
| `backend/audit_set/service.py` | (1) `create_audit_set()`: add integration level derivation + `derive_required_scope()` call. (2) Add `_SCOPE_TO_EA_KW`, `_RISK_HIGH_KW`, `_RISK_LOW_KW` dicts. (3) Fix the elif block in `derive_required_scope()` for ISO 9001/14001/45001/27001. (4) Add cake/tortilla/bread/pastry to `_FOOD_CHAIN_KW["CIV"]`. |
| `backend/api/routes/auditors.py` | `/available` endpoint: accept `required_scope` param, compute `covered_scope` per auditor, filter out zero-coverage auditors. |
| `frontend/src/app/(app)/clients/[id]/page.tsx` | (1) `QuickCalcWidget`: `useState(false)` → `useState(true)`. (2) Stage card: add man-day validation warning when dates × auditors < required audit_days. (3) Coverage panel: update live as auditors change. (4) Stage 2 save: hard block if any required code uncovered. |

Do not change `backend/calculator/engine.py` — the calculation logic is correct.
