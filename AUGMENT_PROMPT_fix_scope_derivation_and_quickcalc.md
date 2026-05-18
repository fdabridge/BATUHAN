# Fix: Auto-derive scope + fix EA code derivation + open QuickCalc by default

Three concrete bugs. Each has an exact file, exact location, exact fix. Do them all.

---

## BUG 1 — `create_audit_set()` never derives scope automatically

**File:** `backend/audit_set/service.py`
**Function:** `create_audit_set()` — around line 299 (after `_run_calculation` call)

**Current code:**
```python
    result = _run_calculation(audit_set)
    if result:
        audit_set.man_day_result = result
        audit_set.effective_employees = int(round(result.get("eps", 0)))
        audit_set.risk_category = (
            result["standard_results"][0].get("category", "").upper()
            if result.get("standard_results") else None
        )

    _create_auto_stages(db, audit_set, result)
    db.commit()
```

**Fix — add one line after the `if result:` block, before `_create_auto_stages`:**
```python
    result = _run_calculation(audit_set)
    if result:
        audit_set.man_day_result = result
        audit_set.effective_employees = int(round(result.get("eps", 0)))
        audit_set.risk_category = (
            result["standard_results"][0].get("category", "").upper()
            if result.get("standard_results") else None
        )

    # Always derive required scope from scope text — no manual button needed
    audit_set.required_scope = derive_required_scope(
        standards=audit_set.standards or [],
        scope_tr=audit_set.scope_tr,
        scope_en=audit_set.scope_en,
        ea_code=audit_set.ea_code,
    )

    _create_auto_stages(db, audit_set, result)
    db.commit()
```

That's it. Every new audit set will now have `required_scope` populated the moment it is created.

---

## BUG 2 — `derive_required_scope()` returns empty codes for ISO 9001/14001/45001/27001 when no EA code is stored

**File:** `backend/audit_set/service.py`
**Function:** `derive_required_scope()` — around line 127

**Current broken code:**
```python
        elif any(n in norm for n in ("9001", "14001", "45001", "27001")):
            codes = [ea_code] if ea_code else []
            result[iso] = {"type": "ea", "codes": codes}
```

When the audit set has no stored `ea_code` (which is common), this always returns `codes = []` and the frontend shows **"no codes derived"**. It never reads the scope text.

**Fix — replace the three lines above with this:**

First, add these two keyword maps near the top of the file, directly after the existing `_ENERGY_MED_KW` line:

```python
# Scope text → EA code keyword map (IAF EA 1–39)
_SCOPE_TO_EA_KW: dict[str, tuple[str, ...]] = {
    "EA 1":  ("agriculture", "farming", "horticulture", "fishery", "aquaculture", "forestry", "livestock"),
    "EA 3":  ("food", "beverage", "tobacco", "bakery", "confectionery", "dairy", "meat processing",
              "cake", "tortilla", "snack", "sandwich", "pastry", "bread", "milling", "brewing",
              "gluten", "biscuit", "cookie", "cracker", "noodle", "pasta production"),
    "EA 4":  ("textile", "clothing", "apparel", "garment", "leather", "footwear", "fabric"),
    "EA 5":  ("wood", "furniture", "paper", "pulp", "printing", "packaging material"),
    "EA 6":  ("chemical", "petrochemical", "pharmaceutical", "cosmetic", "paint", "coating", "adhesive"),
    "EA 7":  ("metal", "steel", "aluminium", "foundry", "forging", "casting", "metallurgy", "welding"),
    "EA 8":  ("machinery", "equipment manufacturing", "pump", "compressor", "valve", "industrial equipment"),
    "EA 9":  ("electrical", "electronics", "semiconductor", "circuit board", "pcb", "electronic component"),
    "EA 10": ("shipbuilding", "marine", "aerospace", "aircraft", "defence", "military equipment"),
    "EA 11": ("automotive", "vehicle", "car", "truck", "bus", "motorcycle", "spare part", "auto component"),
    "EA 13": ("rubber", "plastic", "polymer", "composite"),
    "EA 14": ("glass", "ceramic", "stone", "mineral", "tile", "brick"),
    "EA 15": ("concrete", "cement", "construction material", "aggregate"),
    "EA 16": ("construction", "building", "civil engineering", "infrastructure", "contractor", "installation"),
    "EA 17": ("wholesale", "retail", "trade", "distribution", "import", "export", "commerce"),
    "EA 18": ("hotel", "restaurant", "catering", "hospitality", "tourism", "accommodation"),
    "EA 19": ("transport", "logistics", "freight", "courier", "shipping", "warehousing", "supply chain"),
    "EA 20": ("mining", "quarrying", "extraction", "oil", "gas", "refinery", "petroleum"),
    "EA 21": ("water treatment", "waste management", "recycling", "environmental services", "sewage"),
    "EA 22": ("electricity generation", "power plant", "gas supply", "energy utility", "grid"),
    "EA 23": ("education", "training", "school", "university", "academy", "e-learning"),
    "EA 24": ("healthcare", "hospital", "clinic", "medical services", "diagnostic laboratory"),
    "EA 26": ("financial", "banking", "insurance", "investment", "fintech", "audit firm"),
    "EA 27": ("information technology", "it services", "data centre", "cloud", "managed services"),
    "EA 28": ("telecom", "telecommunication", "internet service provider", "isp"),
    "EA 29": ("engineering services", "technical consulting", "testing laboratory", "inspection"),
    "EA 33": ("software development", "software house", "it consulting", "technology consulting", "saas"),
    "EA 34": ("management consulting", "business services", "legal services", "advisory"),
    "EA 35": ("public administration", "government services", "municipality"),
    "EA 37": ("media", "publishing", "broadcasting", "advertising"),
    "EA 39": ("beauty", "cleaning services", "laundry", "personal services"),
}

# Risk level for ISO 9001 / 45001 (affects table lookup in the engine)
_RISK_HIGH_KW: tuple[str, ...] = (
    "food", "pharmaceutical", "medical", "aerospace", "nuclear", "defence",
    "chemical", "petrochemical", "construction", "mining", "oil", "gas",
    "cake", "tortilla", "snack", "sandwich", "dairy", "meat", "bakery",
    "implant", "surgical", "explosive",
)
_RISK_LOW_KW: tuple[str, ...] = (
    "software development", "it consulting", "consultancy", "training",
    "education", "media", "publishing", "financial services", "insurance",
)
```

Then replace the broken elif block:

```python
        elif any(n in norm for n in ("9001", "14001", "45001", "27001")):
            # Use stored ea_code if available, otherwise infer from scope text
            if ea_code:
                codes = [ea_code]
            else:
                codes = [
                    ea for ea, kws in _SCOPE_TO_EA_KW.items()
                    if any(kw in haystack for kw in kws)
                ]
            # Derive risk level for ISO 9001 and 45001
            if any(kw in haystack for kw in _RISK_HIGH_KW):
                risk = "High"
            elif any(kw in haystack for kw in _RISK_LOW_KW):
                risk = "Low"
            else:
                risk = "Medium"
            result[iso] = {"type": "ea", "codes": codes, "risk": risk}
```

Also fix the `_FOOD_CHAIN_KW` dict — the `"CIV"` tuple is missing common bakery and grain products.
Find the `"CIV"` entry and add these words inside its tuple: `"cake"`, `"tortilla"`, `"bread"`, `"bakery"`, `"pastry"`, `"wrap"`, `"gluten"`, `"noodle"`, `"wafer"`.

---

## BUG 3 — QuickCalcWidget is hidden as a tiny link; user must click it to enter personnel

**File:** `frontend/src/app/(app)/clients/[id]/page.tsx`
**Function:** `QuickCalcWidget`

**Current code:**
```typescript
function QuickCalcWidget({ auditSetId, onSuccess }: { auditSetId: string; onSuccess: () => void }) {
  const [open, setOpen] = useState(false)
```

When `open` is false, the component renders only as a small underlined text link: "Quick Calculate man-days". The user has to find and click it before they can enter personnel. Meanwhile the section above says "Calculation not available" with no obvious action.

**Fix:**
```typescript
  const [open, setOpen] = useState(true)
```

The widget only renders when `man_day_result` is null (see line ~1226: `{!data.man_day_result && <QuickCalcWidget ... />}`), so this only affects clients with no calculation — which is exactly when you want the form visible.

---

## Verification

After deploying these three changes:

1. Create a new audit set (or trigger "Derive required scope" on an existing one) with scope "Production of cakes, tortillas, gluten-free snacks, and sandwiches" and standards QMS + FSMS.
   - **Expected:** `required_scope` immediately shows ISO 9001 → EA 3, risk: High | ISO 22000 → CIV, CIII
   - **Expected:** No button click needed — codes appear as soon as the client page loads

2. Open a client that has no man_day_result.
   - **Expected:** Personnel input form is visible immediately (full-time, part-time, subcontractors, seasonal fields + Calculate button) — no link to click

3. Submit a new application from the application form (with scope + personnel filled).
   - **Expected:** Client detail page shows required scope codes AND man-day calculation result immediately — zero manual steps.

---

## Files changed

| File | What changes |
|---|---|
| `backend/audit_set/service.py` | (1) `create_audit_set()`: add `derive_required_scope()` call before `_create_auto_stages`. (2) Add `_SCOPE_TO_EA_KW`, `_RISK_HIGH_KW`, `_RISK_LOW_KW` dicts. (3) Replace broken elif block in `derive_required_scope()`. (4) Add cake/tortilla/bread to CIV keywords. |
| `frontend/src/app/(app)/clients/[id]/page.tsx` | `QuickCalcWidget`: `useState(false)` → `useState(true)` |
