# Prompt 35 — Dynamic Application Form & Calculation Engine Improvements

## Context

The application forms currently collect only minimal data — a single `total_employees`
number and no standard-specific inputs. The calculator engine already knows how to
compute ISO 50001 K-factor, ISO 22000 food chain complexity, and ISO 27001 EPS via the
square-root method — but the forms never collect the inputs these methods require.

This prompt closes that gap:

1. **Standard-specific dynamic sections** — When the applicant selects ISO 50001, an
   EnMS energy profile panel appears. ISO 22000 → FSMS food chain categories + surcharge
   details. ISO 27001 → ISMS technical area + complexity. ISO 13485 → device classes.

2. **Better employee classification** — Align with IAF MD5: full-time, part-time (with
   FTE factor), subcontractors (in-scope flag), seasonal (peak), repetitive roles.

3. **`application_data` JSON column** — All standard-specific form inputs are stored here.
   `_run_calculation()` reads from it and passes the values to the engine.

4. **Engine improvements** — Add ISO 22003-1:2022 mandatory add-ons (off-site storage
   +0.25/site, separate head office +0.5). Fix part-time FTE conversion in the
   EPS calculation bridge.

**Nothing else changes.** Workflow, signing, certificates, documents, and all other
portal features are untouched.

---

## Summary of changes

| File | What changes |
|------|-------------|
| `backend/audit_set/db_models.py` | Add `application_data JSON` column, safe migration |
| `backend/audit_set/schemas.py` | New `ApplicationDataSchema`; add to Create/Update/Response |
| `backend/audit_set/service.py` | Read `application_data` in `_run_calculation()`; FTE fix; write-back on create/update |
| `backend/audit_set/apply_router.py` | Accept all new standard-specific + personnel fields |
| `backend/calculator/models.py` | Add `fsms_offsite_storage_count` + `fsms_separate_head_office` to `ExtractedFormData` |
| `backend/calculator/engine.py` | Add FSMS mandatory add-ons to `_lookup_standard()` |
| `frontend/src/app/apply/page.tsx` | Full redesign: dynamic sections per selected standard |
| `frontend/src/app/(app)/clients/new/page.tsx` | Add standard-specific panels to Step 2 |

---

## Change 1 — `backend/audit_set/db_models.py`

### 1a — New column on `AuditSet`

After the existing `application_date` column (added in Prompt 33), add:

```python
# ── Standard-specific application data ────────────────────────────────────
application_data = Column(JSON, nullable=True)   # EnMS/FSMS/ISMS inputs from application form
```

Make sure `JSON` is already imported from `sqlalchemy` (it is — used by `personnel`, `sites`, etc.).

### 1b — Safe migration in `create_tables()`

After the Prompt 33 `_safe_add_column` line, add:

```python
# Prompt 35 — standard-specific application data
_safe_add_column("audit_sets", "application_data JSON")
```

---

## Change 2 — `backend/audit_set/schemas.py`

### 2a — New `ApplicationDataSchema` class

Add this new class **before** `AuditSetCreateSchema`. Import `List` from `typing` if
not already imported (it is — or use `list[str]` directly for Python 3.9+):

```python
class ApplicationDataSchema(BaseModel):
    """Standard-specific inputs collected at application time.
    Stored as JSON in audit_sets.application_data.
    """
    # ISO 50001 — EnMS energy profile (used for K-factor → complexity level)
    enms_annual_energy_tj: Optional[float] = None       # annual energy consumption in TJ
    enms_num_energy_types: Optional[int] = None         # number of distinct energy sources
    enms_num_seus: Optional[int] = None                 # number of Significant Energy Uses

    # ISO 22000 / FSSC 22000 — FSMS
    fsms_food_chain_categories: list[str] = []          # e.g. ["CI", "CIV"] per ISO 22003-1:2022
    fsms_haccp_studies: Optional[int] = None            # number of HACCP / food safety studies
    fsms_offsite_storage_count: int = 0                 # off-site storage facilities in scope
    fsms_separate_head_office: bool = False             # head office separate from production site
    fsms_fssc22000: bool = False                        # FSSC 22000 add-on scheme requested
    fsms_seasonal_production: bool = False              # seasonal production / seasonal workforce

    # ISO 27001 — ISMS
    isms_technical_area: Optional[str] = None           # "A" | "B" | "C" | "D" per ISO 27006-1
    isms_data_role: Optional[str] = None                # "Controller" | "Processor" | "Both"
    isms_it_complexity: Optional[str] = None            # "Low" | "Medium" | "High"
    isms_business_complexity: Optional[str] = None      # "Low" | "Medium" | "High"

    # ISO 13485 — MDQMS
    mdqms_device_classes: list[str] = []                # e.g. ["Class I", "Class IIa", "Class IIb"]
    mdqms_regulatory_territories: list[str] = []        # e.g. ["EU MDR 2017/745", "FDA 21 CFR 820"]

    # Personnel — IAF MD5 FTE conversion
    part_time_fte_factor: float = 0.5                   # fraction to multiply part-time count (default 0.5)
    subcontractors_in_scope: bool = True                # whether subcontractors are counted in EPS
```

### 2b — Add to `AuditSetCreateSchema`

Inside `AuditSetCreateSchema`, add one field (keep all existing fields unchanged):

```python
application_data: Optional[ApplicationDataSchema] = None   # ← ADD
```

### 2c — Add to `AuditSetUpdatePlanningSchema`

Inside `AuditSetUpdatePlanningSchema`, add:

```python
application_data: Optional[ApplicationDataSchema] = None   # ← ADD
```

### 2d — Add to `AuditSetResponse`

Inside `AuditSetResponse`, add:

```python
application_data: Optional[dict] = None   # ← ADD (dict because JSON column returns dict, not model)
```

Place it near the other JSON-type fields (`personnel`, `sites`, `integration_level`).

---

## Change 3 — `backend/audit_set/service.py`

### 3a — Store `application_data` in `create_audit_set()`

Inside `create_audit_set()`, in the `AuditSet(...)` constructor block, add:

```python
application_data=data.application_data.model_dump() if data.application_data else None,
```

Place it after the `ea_technical_area` line, before the closing `)`.

### 3b — Update `application_data` in `update_planning()`

In `update_planning()`, after the last existing `if data.xxx is not None:` block, add:

```python
if data.application_data is not None:
    audit_set.application_data = data.application_data.model_dump()
    flag_modified(audit_set, "application_data")
```

### 3c — Rewrite the `_run_calculation()` EPS bridge

Find the `# ── Personnel ─────────────────────────────────────────────────────` section
inside `_run_calculation()`. **Replace the entire personnel block** (from the `p = audit_set.personnel or {}` line
through the `office_employees = max(0, total_employees - ...)` line) with:

```python
# ── Personnel — IAF MD5 EPS bridge ──────────────────────────────────────
p = audit_set.personnel or {}
full_time      = int(p.get("full_time", 0))
part_time      = int(p.get("part_time", 0))
subcontractors = int(p.get("subcontractors", 0))
seasonal       = int(p.get("seasonal", 0))
unskilled      = int(p.get("unskilled", 0))

# Read FTE conversion factors from application_data (defaults are IAF MD5-aligned)
app_data = audit_set.application_data or {}
pt_factor            = float(app_data.get("part_time_fte_factor", 0.5))
subcontractors_in_scope = bool(app_data.get("subcontractors_in_scope", True))

# Convert part-time to FTE equivalent; subcontractors only counted when in scope
import math as _math
pt_fte             = int(_math.ceil(part_time * pt_factor))
sub_count          = subcontractors if subcontractors_in_scope else 0
total_employees    = full_time + pt_fte + sub_count + seasonal + unskilled

repetitive_roles     = p.get("repetitive_roles", [])
repetitive_employees = sum(r.get("employee_count", 0) for r in repetitive_roles)
office_employees     = max(0, total_employees - repetitive_employees)
```

### 3d — EnMS: prefer `application_data` over sites fallback

Find the `# ── EnMS energy data (ISO 50001) — first site that supplies it ────` block
in `_run_calculation()`. **Replace it** with:

```python
# ── EnMS energy data (ISO 50001) ─────────────────────────────────────────
# Priority 1: explicit form data in application_data (most accurate)
# Priority 2: legacy sites[0].energy_tj (backward compat for existing audit sets)
annual_energy_tj = num_energy_types = num_seus = None
if app_data.get("enms_annual_energy_tj") is not None:
    annual_energy_tj = float(app_data["enms_annual_energy_tj"])
    num_energy_types = app_data.get("enms_num_energy_types")
    num_seus         = app_data.get("enms_num_seus")
else:
    for s in sites_raw:
        if s.get("energy_tj") is not None:
            annual_energy_tj  = float(s["energy_tj"])
            num_energy_types  = s.get("energy_types")
            num_seus          = s.get("seu_count")
            break
```

### 3e — FSMS: prefer explicit food chain categories from `application_data`

Find the `# ── Food chain categories — pulled from required_scope if already derived ─` block.
**Replace it** with:

```python
# ── Food chain categories (ISO 22000 / FSSC 22000) ───────────────────────
# Priority 1: explicit categories from application form (most precise)
# Priority 2: keyword-derived categories from required_scope (for legacy sets)
food_cats: list[str] = []
if app_data.get("fsms_food_chain_categories"):
    food_cats = list(app_data["fsms_food_chain_categories"])
else:
    rs = getattr(audit_set, "required_scope", None) or {}
    for iso_name, entry in rs.items():
        if not isinstance(entry, dict):
            continue
        if entry.get("type") == "food":
            food_cats.extend(entry.get("codes", []) or [])
```

### 3f — Pass FSMS surcharge fields to `ExtractedFormData`

In `_run_calculation()`, find the `form_data = ExtractedFormData(...)` constructor call.
Add two more keyword arguments inside it (after `food_chain_categories=food_cats`):

```python
fsms_offsite_storage_count=int(app_data.get("fsms_offsite_storage_count", 0)),
fsms_separate_head_office=bool(app_data.get("fsms_separate_head_office", False)),
```

---

## Change 4 — `backend/audit_set/apply_router.py`

### 4a — Extend `ClientApplicationSchema`

**Replace** the entire `ClientApplicationSchema` class with this expanded version:

```python
class ClientApplicationSchema(BaseModel):
    # ── Company info ──────────────────────────────────────────────────────
    company_name: str
    company_address: str
    city: str = ""
    country: str = ""
    phone: str = ""
    website: str = ""

    # ── Contact person ────────────────────────────────────────────────────
    representative_name: str          # becomes representative + client account full_name
    representative_email: str         # becomes client account email

    # ── Certification request ─────────────────────────────────────────────
    standards: list[str]              # subset of ALLOWED_STANDARDS
    audit_type: str                   # "initial" | "surveillance" | "recertification"

    # ── Scope ─────────────────────────────────────────────────────────────
    scope_description: str = ""

    # ── Personnel — IAF MD5 breakdown ─────────────────────────────────────
    full_time_employees: int = 0           # permanent full-time workforce
    part_time_employees: int = 0           # part-time employees (will be × 0.5 FTE)
    subcontractor_employees: int = 0       # subcontractors (in scope of certification)
    seasonal_employees: int = 0            # seasonal workforce at peak
    shift_count: int = 1                   # number of production shifts
    shift_same_process: bool = False       # same work repeated across shifts

    # Legacy field — still accepted; used if full_time_employees is 0
    total_employees: int = 0

    # ── Additional sites ──────────────────────────────────────────────────
    has_additional_sites: bool = False
    additional_site_count: int = 0

    # ── ISO 50001 — EnMS energy profile ──────────────────────────────────
    enms_annual_energy_tj: Optional[float] = None
    enms_num_energy_types: Optional[int] = None
    enms_num_seus: Optional[int] = None

    # ── ISO 22000 / FSSC 22000 — FSMS ────────────────────────────────────
    fsms_food_chain_categories: list[str] = []
    fsms_haccp_studies: Optional[int] = None
    fsms_offsite_storage_count: int = 0
    fsms_separate_head_office: bool = False
    fsms_fssc22000: bool = False
    fsms_seasonal_production: bool = False

    # ── ISO 27001 — ISMS ─────────────────────────────────────────────────
    isms_technical_area: Optional[str] = None   # "A" | "B" | "C" | "D"
    isms_data_role: Optional[str] = None        # "Controller" | "Processor" | "Both"

    # ── ISO 13485 — MDQMS ────────────────────────────────────────────────
    mdqms_device_classes: list[str] = []
```

### 4b — Update `submit_application()` to use new fields

In `submit_application()`, **replace** the `AuditSet(...)` creation block's `personnel=` line
and everything related to employee count with:

```python
# Resolve effective full-time count (new fields take priority over legacy total_employees)
ft = payload.full_time_employees or payload.total_employees
pt = payload.part_time_employees
sub = payload.subcontractor_employees
seas = payload.seasonal_employees

audit_set = AuditSet(
    plan_number=plan_number,
    company_name=payload.company_name,
    company_address=payload.company_address,
    city=payload.city,
    country=payload.country,
    phone=payload.phone,
    website=payload.website,
    representative=payload.representative_name,
    email=payload.representative_email,
    standards=payload.standards,
    audit_type=payload.audit_type,
    scope_en=payload.scope_description,
    scope_tr="",
    accreditation_body="UAF",
    status="draft",
    workflow_status="pending_review",
    submitted_via_portal=True,
    personnel={
        "full_time":      ft,
        "part_time":      pt,
        "subcontractors": sub,
        "seasonal":       seas,
        "unskilled":      0,
        "shift_count":    payload.shift_count,
        "shift_same_process": payload.shift_same_process,
        "repetitive_roles": [],
    },
    sites=sites,
    application_data={
        "enms_annual_energy_tj":   payload.enms_annual_energy_tj,
        "enms_num_energy_types":   payload.enms_num_energy_types,
        "enms_num_seus":           payload.enms_num_seus,
        "fsms_food_chain_categories": payload.fsms_food_chain_categories,
        "fsms_haccp_studies":      payload.fsms_haccp_studies,
        "fsms_offsite_storage_count": payload.fsms_offsite_storage_count,
        "fsms_separate_head_office": payload.fsms_separate_head_office,
        "fsms_fssc22000":          payload.fsms_fssc22000,
        "fsms_seasonal_production": payload.fsms_seasonal_production,
        "isms_technical_area":     payload.isms_technical_area,
        "isms_data_role":          payload.isms_data_role,
        "mdqms_device_classes":    payload.mdqms_device_classes,
        "part_time_fte_factor":    0.5,
        "subcontractors_in_scope": True,
    },
)
```

The `Optional` import is already present in the file. `from typing import Optional` is
available through `from pydantic import BaseModel`.

> Note: The `Optional` type from `pydantic` / `typing` should already be imported.
> If not, add `from typing import Optional` at the top of the file.

---

## Change 5 — `backend/calculator/models.py`

### 5a — Add FSMS surcharge fields to `ExtractedFormData`

Inside `ExtractedFormData`, after the `food_chain_categories` field, add:

```python
# FSMS — ISO 22003-1:2022 mandatory on-site add-ons (separate from table base time)
fsms_offsite_storage_count: int = 0        # +0.25 auditor-day per off-site storage facility (§B.2.5)
fsms_separate_head_office: bool = False    # +0.5 auditor-day when HQ separate from production (§B.2.6)
```

---

## Change 6 — `backend/calculator/engine.py`

### 6a — Add FSMS mandatory add-ons in `_lookup_standard()`

Find the `elif _std_match(standard, "ISO 22000") or _std_match(standard, "FSSC 22000"):` branch.

Inside this branch, **after** the `init_t = round(init_t * factor, 2)` line (the food
chain factor application), add the ISO 22003-1:2022 §B.2 mandatory additions:

```python
# ISO 22003-1:2022 §B.2 — mandatory on-site add-ons (before phase split)
iso22003_addon = 0.0
if data.fsms_offsite_storage_count and data.fsms_offsite_storage_count > 0:
    iso22003_addon += round(0.25 * data.fsms_offsite_storage_count, 2)   # §B.2.5: +0.25/off-site storage
if data.fsms_separate_head_office:
    iso22003_addon += 0.5                                                  # §B.2.6: +0.5 separate HQ
if iso22003_addon > 0:
    init_t = round(init_t + iso22003_addon, 2)
```

Then update the `return StandardAuditResult(...)` inside this branch to set `haccp_addition`:

```python
return StandardAuditResult(
    standard=standard, category=f"FSMS · {cat_label}", eps=eps,
    base_init=init_t, base_ph1=ph1, base_ph2=ph2,
    base_surv=surv, base_recert=recert_t,
    base_recert_ph1=r_ph1, base_recert_ph2=r_ph2,
    haccp_addition=iso22003_addon if iso22003_addon > 0 else None,
)
```

(The `haccp_addition` field is already defined in `StandardAuditResult` as `Optional[float] = None`.
We're reusing it here to carry the ISO 22003-1 mandatory add-on total for UI display.)

---

## Change 7 — `frontend/src/app/apply/page.tsx`

**Full replacement.** Replace the entire file content with the following:

```tsx
'use client'

import { useState } from 'react'
import axios from 'axios'

// ── Constants ─────────────────────────────────────────────────────────────────

const STANDARDS = [
  { code: 'QMS',   label: 'ISO 9001:2015',   desc: 'Quality Management' },
  { code: 'EMS',   label: 'ISO 14001:2015',  desc: 'Environmental Management' },
  { code: 'OHSMS', label: 'ISO 45001:2018',  desc: 'Occupational Health & Safety' },
  { code: 'FSMS',  label: 'ISO 22000:2018',  desc: 'Food Safety Management' },
  { code: 'ISMS',  label: 'ISO/IEC 27001:2022', desc: 'Information Security' },
  { code: 'ENMS',  label: 'ISO 50001:2018',  desc: 'Energy Management' },
  { code: 'MDQMS', label: 'ISO 13485:2016',  desc: 'Medical Devices Quality' },
  { code: 'ABMS',  label: 'ISO 37001:2016',  desc: 'Anti-Bribery Management' },
]

const FOOD_CHAIN_CATEGORIES = [
  { code: 'CI',   label: 'CI — Animal farming / perishable animal products' },
  { code: 'CII',  label: 'CII — Perishable plant products (fresh produce)' },
  { code: 'CIII', label: 'CIII — Processed perishable / ready-to-eat' },
  { code: 'CIV',  label: 'CIV — Ambient-stable food (bakery, confectionery, beverages, dried)' },
  { code: 'C0',   label: 'C0 — Slaughter / primary processing of animal products' },
  { code: 'D',    label: 'D — Production of animal feed / pet food' },
  { code: 'E',    label: 'E — Catering / food service / restaurant' },
  { code: 'FI',   label: 'FI — Food retail' },
  { code: 'FII',  label: 'FII — Food wholesale / distribution / brokerage' },
  { code: 'G',    label: 'G — Food storage / cold-chain logistics' },
  { code: 'I',    label: 'I — Food packaging materials / food contact materials' },
  { code: 'K',    label: 'K — Food chemicals / additives / ingredient manufacture' },
  { code: 'BIII', label: 'BIII — Plant pre-processing (sorting, cleaning, packing whole plants)' },
]

const MDQMS_DEVICE_CLASSES = [
  'Class I (low risk)', 'Class IIa (medium risk)', 'Class IIb (medium-high risk)',
  'Class III (high risk)', 'In-vitro diagnostics (IVD)', 'Active implantable devices',
]

const MDQMS_TERRITORIES = [
  'EU MDR 2017/745', 'EU IVDR 2017/746', 'FDA 21 CFR 820',
  'ISO 13485 only (non-regulatory)', 'MDSAP (multi-country)',
]

// ── Form state type ───────────────────────────────────────────────────────────

interface FormState {
  // Company
  company_name: string; company_address: string; city: string; country: string
  phone: string; website: string
  // Contact
  representative_name: string; representative_email: string
  // Certification
  standards: string[]; audit_type: string; scope_description: string
  // Personnel — IAF MD5
  full_time_employees: string; part_time_employees: string
  subcontractor_employees: string; seasonal_employees: string
  shift_count: string; shift_same_process: boolean
  has_additional_sites: boolean; additional_site_count: string
  // EnMS (ISO 50001)
  enms_annual_energy_tj: string; enms_num_energy_types: string; enms_num_seus: string
  // FSMS (ISO 22000 / FSSC 22000)
  fsms_food_chain_categories: string[]; fsms_haccp_studies: string
  fsms_offsite_storage_count: string; fsms_separate_head_office: boolean
  fsms_fssc22000: boolean; fsms_seasonal_production: boolean
  // ISMS (ISO 27001)
  isms_technical_area: string; isms_data_role: string
  // MDQMS (ISO 13485)
  mdqms_device_classes: string[]; mdqms_regulatory_territories: string[]
}

const INITIAL: FormState = {
  company_name: '', company_address: '', city: '', country: '',
  phone: '', website: '',
  representative_name: '', representative_email: '',
  standards: [], audit_type: 'initial', scope_description: '',
  full_time_employees: '', part_time_employees: '',
  subcontractor_employees: '', seasonal_employees: '',
  shift_count: '1', shift_same_process: false,
  has_additional_sites: false, additional_site_count: '',
  enms_annual_energy_tj: '', enms_num_energy_types: '', enms_num_seus: '',
  fsms_food_chain_categories: [], fsms_haccp_studies: '',
  fsms_offsite_storage_count: '', fsms_separate_head_office: false,
  fsms_fssc22000: false, fsms_seasonal_production: false,
  isms_technical_area: '', isms_data_role: '',
  mdqms_device_classes: [], mdqms_regulatory_territories: [],
}

// ── Helpers ───────────────────────────────────────────────────────────────────

function toggleArr<T>(arr: T[], val: T): T[] {
  return arr.includes(val) ? arr.filter(x => x !== val) : [...arr, val]
}

function pInt(s: string): number { return parseInt(s) || 0 }
function pFloat(s: string): number | null {
  const n = parseFloat(s); return isNaN(n) ? null : n
}

// ── Shared components ─────────────────────────────────────────────────────────

const inputCls = "w-full border border-gray-200 rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-[#1A4731]/30 focus:border-[#1A4731]"
const sectionHdCls = "text-sm font-semibold text-gray-700 uppercase tracking-wide mb-4"

function Field({ label, hint, children }: { label: string; hint?: string; children: React.ReactNode }) {
  return (
    <div>
      <label className="block text-sm font-medium text-gray-700 mb-1">{label}</label>
      {hint && <p className="text-xs text-gray-400 mb-1">{hint}</p>}
      {children}
    </div>
  )
}

function SectionPanel({ title, icon, children }: { title: string; icon: string; children: React.ReactNode }) {
  return (
    <div className="rounded-xl border border-blue-100 bg-blue-50/40 p-5">
      <h3 className="flex items-center gap-2 text-sm font-semibold text-blue-900 mb-4">
        <span className="text-base">{icon}</span>{title}
      </h3>
      <div className="space-y-4">{children}</div>
    </div>
  )
}

// ── Main page ─────────────────────────────────────────────────────────────────

export default function ApplyPage() {
  const [form, setForm] = useState<FormState>(INITIAL)
  const [loading, setLoading] = useState(false)
  const [success, setSuccess] = useState(false)
  const [error, setError] = useState('')

  const sel = (patch: Partial<FormState>) => setForm(f => ({ ...f, ...patch }))
  const hasStd = (code: string) => form.standards.includes(code)

  function toggleStandard(code: string) {
    sel({ standards: toggleArr(form.standards, code) })
  }

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault()
    setError('')
    if (form.standards.length === 0) { setError('Please select at least one standard.'); return }
    if (!form.representative_email) { setError('Email address is required.'); return }

    setLoading(true)
    try {
      const apiBase = process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8000'
      await axios.post(`${apiBase}/apply`, {
        company_name:      form.company_name,
        company_address:   form.company_address,
        city:              form.city,
        country:           form.country,
        phone:             form.phone,
        website:           form.website,
        representative_name:  form.representative_name,
        representative_email: form.representative_email,
        standards:         form.standards,
        audit_type:        form.audit_type,
        scope_description: form.scope_description,
        // Personnel
        full_time_employees:      pInt(form.full_time_employees),
        part_time_employees:      pInt(form.part_time_employees),
        subcontractor_employees:  pInt(form.subcontractor_employees),
        seasonal_employees:       pInt(form.seasonal_employees),
        shift_count:              pInt(form.shift_count) || 1,
        shift_same_process:       form.shift_same_process,
        has_additional_sites:     form.has_additional_sites,
        additional_site_count:    pInt(form.additional_site_count),
        // EnMS
        ...(hasStd('ENMS') && {
          enms_annual_energy_tj:  pFloat(form.enms_annual_energy_tj),
          enms_num_energy_types:  pInt(form.enms_num_energy_types) || null,
          enms_num_seus:          pInt(form.enms_num_seus) || null,
        }),
        // FSMS
        ...((hasStd('FSMS')) && {
          fsms_food_chain_categories: form.fsms_food_chain_categories,
          fsms_haccp_studies:      pInt(form.fsms_haccp_studies) || null,
          fsms_offsite_storage_count: pInt(form.fsms_offsite_storage_count),
          fsms_separate_head_office: form.fsms_separate_head_office,
          fsms_fssc22000:          form.fsms_fssc22000,
          fsms_seasonal_production: form.fsms_seasonal_production,
        }),
        // ISMS
        ...(hasStd('ISMS') && {
          isms_technical_area: form.isms_technical_area || null,
          isms_data_role:      form.isms_data_role || null,
        }),
        // MDQMS
        ...(hasStd('MDQMS') && {
          mdqms_device_classes:           form.mdqms_device_classes,
          mdqms_regulatory_territories:   form.mdqms_regulatory_territories,
        }),
      })
      setSuccess(true)
    } catch (err: unknown) {
      const detail = (err as { response?: { data?: { detail?: string } } })?.response?.data?.detail
      setError(detail || 'Submission failed. Please try again.')
    } finally {
      setLoading(false)
    }
  }

  if (success) {
    return (
      <div className="min-h-screen bg-gray-50 flex items-center justify-center p-6">
        <div className="bg-white rounded-xl shadow-sm border p-10 max-w-md text-center">
          <div className="w-16 h-16 bg-green-100 rounded-full flex items-center justify-center mx-auto mb-4">
            <svg className="w-8 h-8 text-green-700" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M5 13l4 4L19 7" />
            </svg>
          </div>
          <h2 className="text-xl font-bold text-gray-900 mb-2">Application Submitted</h2>
          <p className="text-gray-600 mb-6">
            Thank you. We have received your application and will review it shortly.
            Login credentials have been sent to your email address.
          </p>
          <a href="/login" className="inline-block bg-[#1A4731] text-white px-6 py-2.5 rounded-lg text-sm font-medium">
            Go to Portal Login
          </a>
        </div>
      </div>
    )
  }

  return (
    <div className="min-h-screen bg-gray-50 py-10 px-4">
      <div className="max-w-2xl mx-auto">
        {/* Header */}
        <div className="text-center mb-8">
          <h1 className="text-2xl font-bold text-[#1A4731]">IFC Global LLC</h1>
          <p className="text-gray-500 mt-1">Certification Application Form</p>
        </div>

        <form onSubmit={handleSubmit} className="space-y-6">

          {/* ── 1. Company Information ─────────────────────────────────── */}
          <div className="bg-white rounded-xl shadow-sm border p-6 space-y-4">
            <h2 className={sectionHdCls}>Company Information</h2>
            <Field label="Company Name *">
              <input className={inputCls} value={form.company_name}
                onChange={e => sel({ company_name: e.target.value })} required />
            </Field>
            <Field label="Company Address *">
              <input className={inputCls} value={form.company_address}
                onChange={e => sel({ company_address: e.target.value })} required />
            </Field>
            <div className="grid grid-cols-2 gap-4">
              <Field label="City">
                <input className={inputCls} value={form.city} onChange={e => sel({ city: e.target.value })} />
              </Field>
              <Field label="Country">
                <input className={inputCls} value={form.country} onChange={e => sel({ country: e.target.value })} />
              </Field>
            </div>
            <div className="grid grid-cols-2 gap-4">
              <Field label="Phone">
                <input className={inputCls} type="tel" value={form.phone} onChange={e => sel({ phone: e.target.value })} />
              </Field>
              <Field label="Website">
                <input className={inputCls} type="url" placeholder="https://" value={form.website}
                  onChange={e => sel({ website: e.target.value })} />
              </Field>
            </div>
          </div>

          {/* ── 2. Contact Person ─────────────────────────────────────── */}
          <div className="bg-white rounded-xl shadow-sm border p-6 space-y-4">
            <h2 className={sectionHdCls}>Contact Person</h2>
            <Field label="Full Name *">
              <input className={inputCls} value={form.representative_name}
                onChange={e => sel({ representative_name: e.target.value })} required />
            </Field>
            <Field label="Email Address *" hint="Your portal login credentials will be sent to this address.">
              <input className={inputCls} type="email" value={form.representative_email}
                onChange={e => sel({ representative_email: e.target.value })} required />
            </Field>
          </div>

          {/* ── 3. Standards Requested ────────────────────────────────── */}
          <div className="bg-white rounded-xl shadow-sm border p-6">
            <h2 className={sectionHdCls}>Standards Requested *</h2>
            <div className="grid grid-cols-1 gap-2">
              {STANDARDS.map(s => (
                <label key={s.code} className={`flex items-center gap-3 p-3 rounded-lg border cursor-pointer transition-colors ${
                  hasStd(s.code) ? 'border-[#1A4731] bg-[#1A4731]/5' : 'border-gray-200 hover:bg-gray-50'
                }`}>
                  <input type="checkbox" checked={hasStd(s.code)} onChange={() => toggleStandard(s.code)}
                    className="w-4 h-4 accent-[#1A4731]" />
                  <div>
                    <span className="text-sm font-medium text-gray-800">{s.label}</span>
                    <span className="text-xs text-gray-500 ml-2">— {s.desc}</span>
                  </div>
                </label>
              ))}
            </div>
          </div>

          {/* ── 4. Audit Type ─────────────────────────────────────────── */}
          <div className="bg-white rounded-xl shadow-sm border p-6">
            <h2 className={sectionHdCls}>Audit Type *</h2>
            <div className="grid grid-cols-3 gap-3">
              {[
                { v: 'initial',          l: 'Initial Certification' },
                { v: 'surveillance',     l: 'Surveillance' },
                { v: 'recertification',  l: 'Recertification' },
              ].map(opt => (
                <label key={opt.v} className={`p-3 rounded-lg border text-center cursor-pointer text-sm transition-colors ${
                  form.audit_type === opt.v ? 'bg-[#1A4731] text-white border-[#1A4731]' : 'bg-white text-gray-700 hover:bg-gray-50'
                }`}>
                  <input type="radio" name="audit_type" value={opt.v} checked={form.audit_type === opt.v}
                    onChange={e => sel({ audit_type: e.target.value })} className="hidden" />
                  {opt.l}
                </label>
              ))}
            </div>
          </div>

          {/* ── 5. Scope ──────────────────────────────────────────────── */}
          <div className="bg-white rounded-xl shadow-sm border p-6">
            <h2 className={sectionHdCls}>What Does Your Company Do? *</h2>
            <p className="text-xs text-gray-400 mb-3">
              Describe your main activities (e.g. "Manufacturing and sales of dried fruits").
            </p>
            <textarea className={`${inputCls} h-24 resize-none`}
              value={form.scope_description}
              onChange={e => sel({ scope_description: e.target.value })} required />
          </div>

          {/* ── 6. Personnel ──────────────────────────────────────────── */}
          <div className="bg-white rounded-xl shadow-sm border p-6 space-y-4">
            <h2 className={sectionHdCls}>Personnel</h2>
            <p className="text-xs text-gray-500 -mt-2 mb-2">
              Accurate personnel data is required to calculate your audit duration per IAF MD5.
            </p>
            <div className="grid grid-cols-2 gap-4">
              <Field label="Full-time employees *" hint="Permanent workforce">
                <input className={inputCls} type="number" min="0" value={form.full_time_employees}
                  onChange={e => sel({ full_time_employees: e.target.value })} required />
              </Field>
              <Field label="Part-time employees" hint="Counted as 0.5 FTE each">
                <input className={inputCls} type="number" min="0" value={form.part_time_employees}
                  onChange={e => sel({ part_time_employees: e.target.value })} />
              </Field>
              <Field label="Subcontractors (in scope)" hint="Working under your management system">
                <input className={inputCls} type="number" min="0" value={form.subcontractor_employees}
                  onChange={e => sel({ subcontractor_employees: e.target.value })} />
              </Field>
              <Field label="Seasonal employees (peak)" hint="Maximum headcount during peak season">
                <input className={inputCls} type="number" min="0" value={form.seasonal_employees}
                  onChange={e => sel({ seasonal_employees: e.target.value })} />
              </Field>
            </div>

            <div className="grid grid-cols-2 gap-4">
              <Field label="Number of work shifts">
                <select className={inputCls} value={form.shift_count}
                  onChange={e => sel({ shift_count: e.target.value })}>
                  <option value="1">1 shift</option>
                  <option value="2">2 shifts</option>
                  <option value="3">3 shifts</option>
                </select>
              </Field>
              {parseInt(form.shift_count) > 1 && (
                <Field label="Shifts run the same process">
                  <label className="flex items-center gap-2 mt-2 cursor-pointer">
                    <input type="checkbox" checked={form.shift_same_process}
                      onChange={e => sel({ shift_same_process: e.target.checked })}
                      className="w-4 h-4 accent-[#1A4731]" />
                    <span className="text-sm text-gray-700">Yes, same work in each shift</span>
                  </label>
                </Field>
              )}
            </div>

            {/* Additional sites */}
            <label className="flex items-center gap-2 cursor-pointer">
              <input type="checkbox" checked={form.has_additional_sites}
                onChange={e => sel({ has_additional_sites: e.target.checked })}
                className="w-4 h-4 accent-[#1A4731]" />
              <span className="text-sm text-gray-700">We have additional sites / branches</span>
            </label>
            {form.has_additional_sites && (
              <Field label="Number of additional sites">
                <input className={inputCls} type="number" min="1" value={form.additional_site_count}
                  onChange={e => sel({ additional_site_count: e.target.value })} />
              </Field>
            )}
          </div>

          {/* ── 7. Standard-specific sections (dynamic) ───────────────── */}

          {/* ISO 50001 — EnMS Energy Profile */}
          {hasStd('ENMS') && (
            <SectionPanel title="ISO 50001 — Energy Management System Details" icon="⚡">
              <p className="text-xs text-blue-700 -mt-2 mb-2">
                Required to calculate audit duration using the ISO 50003 K-factor method.
              </p>
              <div className="grid grid-cols-1 gap-4">
                <Field
                  label="Annual energy consumption (TJ)"
                  hint="Total energy used by all sites in scope, per year"
                >
                  <select className={inputCls} value={form.enms_annual_energy_tj}
                    onChange={e => sel({ enms_annual_energy_tj: e.target.value })}>
                    <option value="">— Select range —</option>
                    <option value="10">≤ 20 TJ (small facility)</option>
                    <option value="100">20–200 TJ (medium)</option>
                    <option value="1000">200–2,000 TJ (large industrial)</option>
                    <option value="5000">&gt; 2,000 TJ (very large / heavy industry)</option>
                  </select>
                </Field>
                <Field
                  label="Number of energy types (sources)"
                  hint="e.g. electricity, natural gas, diesel, steam = 4"
                >
                  <select className={inputCls} value={form.enms_num_energy_types}
                    onChange={e => sel({ enms_num_energy_types: e.target.value })}>
                    <option value="">— Select —</option>
                    <option value="1">1 energy type</option>
                    <option value="2">2 energy types</option>
                    <option value="3">3 energy types</option>
                    <option value="4">4 or more energy types</option>
                  </select>
                </Field>
                <Field
                  label="Number of Significant Energy Uses (SEUs)"
                  hint="Equipment / processes that account for the majority (≥80%) of energy consumption"
                >
                  <select className={inputCls} value={form.enms_num_seus}
                    onChange={e => sel({ enms_num_seus: e.target.value })}>
                    <option value="">— Select —</option>
                    <option value="2">1–3 SEUs</option>
                    <option value="5">4–6 SEUs</option>
                    <option value="8">7–10 SEUs</option>
                    <option value="12">11–15 SEUs</option>
                    <option value="20">&gt; 15 SEUs</option>
                  </select>
                </Field>
              </div>
            </SectionPanel>
          )}

          {/* ISO 22000 / FSSC 22000 — FSMS Details */}
          {hasStd('FSMS') && (
            <SectionPanel title="ISO 22000 — Food Safety Management System Details" icon="🍽️">
              <p className="text-xs text-blue-700 -mt-2 mb-2">
                Required for audit duration calculation per ISO 22003-1:2022.
              </p>

              {/* Food chain categories */}
              <div>
                <label className="block text-sm font-medium text-gray-700 mb-2">
                  Food chain categories in scope *
                </label>
                <p className="text-xs text-gray-500 mb-2">Select all that apply.</p>
                <div className="space-y-1.5 max-h-64 overflow-y-auto pr-1">
                  {FOOD_CHAIN_CATEGORIES.map(cat => (
                    <label key={cat.code} className="flex items-start gap-2 cursor-pointer group">
                      <input type="checkbox"
                        checked={form.fsms_food_chain_categories.includes(cat.code)}
                        onChange={() => sel({ fsms_food_chain_categories: toggleArr(form.fsms_food_chain_categories, cat.code) })}
                        className="mt-0.5 w-4 h-4 accent-[#1A4731] shrink-0" />
                      <span className="text-xs text-gray-700 group-hover:text-gray-900">{cat.label}</span>
                    </label>
                  ))}
                </div>
              </div>

              <div className="grid grid-cols-2 gap-4">
                <Field label="Number of HACCP / food safety studies" hint="Distinct HACCP plans in scope">
                  <input className={inputCls} type="number" min="0" value={form.fsms_haccp_studies}
                    onChange={e => sel({ fsms_haccp_studies: e.target.value })} />
                </Field>
                <Field label="Off-site storage facilities in scope" hint="+0.25 audit day each (ISO 22003-1 §B.2.5)">
                  <input className={inputCls} type="number" min="0" value={form.fsms_offsite_storage_count}
                    onChange={e => sel({ fsms_offsite_storage_count: e.target.value })} />
                </Field>
              </div>

              <div className="space-y-2">
                {[
                  { key: 'fsms_separate_head_office' as const, label: 'Head office is separate from production site (+0.5 audit day)' },
                  { key: 'fsms_fssc22000' as const,            label: 'Applying for FSSC 22000 certification scheme (+1.0 day reporting surcharge)' },
                  { key: 'fsms_seasonal_production' as const,  label: 'Seasonal production (production stops for part of the year)' },
                ].map(({ key, label }) => (
                  <label key={key} className="flex items-center gap-2 cursor-pointer">
                    <input type="checkbox" checked={form[key] as boolean}
                      onChange={e => sel({ [key]: e.target.checked } as Partial<FormState>)}
                      className="w-4 h-4 accent-[#1A4731]" />
                    <span className="text-sm text-gray-700">{label}</span>
                  </label>
                ))}
              </div>
            </SectionPanel>
          )}

          {/* ISO 27001 — ISMS Details */}
          {hasStd('ISMS') && (
            <SectionPanel title="ISO/IEC 27001 — Information Security Management System Details" icon="🔐">
              <p className="text-xs text-blue-700 -mt-2 mb-2">
                Used for EPS calculation per ISO/IEC 27006-1:2024 and technical area classification.
              </p>
              <Field
                label="Technical area"
                hint="Your organization's primary ISMS technical domain per ISO/IEC 27006-1"
              >
                <select className={inputCls} value={form.isms_technical_area}
                  onChange={e => sel({ isms_technical_area: e.target.value })}>
                  <option value="">— Select —</option>
                  <option value="A">A — Standard IT (office-type: desktops, servers, cloud, HR/finance systems)</option>
                  <option value="B">B — Industrial / OT systems (ICS, SCADA, manufacturing IT)</option>
                  <option value="C">C — Telecom / service provider infrastructure</option>
                  <option value="D">D — Specialized (data centres, crypto, medical devices, critical infrastructure)</option>
                </select>
              </Field>
              <Field label="Data role under GDPR / data protection law">
                <select className={inputCls} value={form.isms_data_role}
                  onChange={e => sel({ isms_data_role: e.target.value })}>
                  <option value="">— Select —</option>
                  <option value="Controller">Data Controller (you decide the purpose of data processing)</option>
                  <option value="Processor">Data Processor (you process data on behalf of others)</option>
                  <option value="Both">Both Controller and Processor</option>
                </select>
              </Field>
            </SectionPanel>
          )}

          {/* ISO 13485 — MDQMS Details */}
          {hasStd('MDQMS') && (
            <SectionPanel title="ISO 13485 — Medical Devices Quality System Details" icon="🏥">
              <div>
                <label className="block text-sm font-medium text-gray-700 mb-2">
                  Medical device class(es) in scope
                </label>
                <div className="space-y-1.5">
                  {MDQMS_DEVICE_CLASSES.map(cls => (
                    <label key={cls} className="flex items-center gap-2 cursor-pointer">
                      <input type="checkbox"
                        checked={form.mdqms_device_classes.includes(cls)}
                        onChange={() => sel({ mdqms_device_classes: toggleArr(form.mdqms_device_classes, cls) })}
                        className="w-4 h-4 accent-[#1A4731]" />
                      <span className="text-sm text-gray-700">{cls}</span>
                    </label>
                  ))}
                </div>
              </div>
              <div>
                <label className="block text-sm font-medium text-gray-700 mb-2">
                  Regulatory framework(s) in scope
                </label>
                <div className="space-y-1.5">
                  {MDQMS_TERRITORIES.map(t => (
                    <label key={t} className="flex items-center gap-2 cursor-pointer">
                      <input type="checkbox"
                        checked={form.mdqms_regulatory_territories.includes(t)}
                        onChange={() => sel({ mdqms_regulatory_territories: toggleArr(form.mdqms_regulatory_territories, t) })}
                        className="w-4 h-4 accent-[#1A4731]" />
                      <span className="text-sm text-gray-700">{t}</span>
                    </label>
                  ))}
                </div>
              </div>
            </SectionPanel>
          )}

          {/* ── 8. Error + Submit ──────────────────────────────────────── */}
          <div className="bg-white rounded-xl shadow-sm border p-6 space-y-4">
            {error && (
              <div className="bg-red-50 border border-red-200 text-red-700 text-sm rounded-lg p-3">
                {error}
              </div>
            )}
            <button
              type="submit" disabled={loading}
              className="w-full bg-[#1A4731] text-white py-3 rounded-lg font-medium hover:bg-[#143828] transition-colors disabled:opacity-60"
            >
              {loading ? 'Submitting…' : 'Submit Application'}
            </button>
            <p className="text-xs text-center text-gray-400">
              Already have an account?{' '}
              <a href="/login" className="text-[#1A4731] underline">Sign in here</a>
            </p>
          </div>

        </form>
      </div>
    </div>
  )
}
```

---

## Change 8 — `frontend/src/app/(app)/clients/new/page.tsx`

### 8a — Expand `Step2Data` interface

Find the `interface Step2Data` definition. **Replace it** with:

```typescript
interface Step2Data {
  full_time: number; part_time: number; subcontractors: number; seasonal: number
  shift_1_count: number; shift_2_count: number; shift_3_count: number
  shift_same_process: boolean
  multiSite: boolean; sites: SiteRow[]
  pairIntegration: Record<string, 'Full' | 'Partial' | 'None'>
  // EnMS (ISO 50001)
  enms_annual_energy_tj: string
  enms_num_energy_types: string
  enms_num_seus: string
  // FSMS (ISO 22000 / FSSC 22000)
  fsms_food_chain_categories: string[]
  fsms_haccp_studies: string
  fsms_offsite_storage_count: string
  fsms_separate_head_office: boolean
  fsms_fssc22000: boolean
  fsms_seasonal_production: boolean
  // ISMS (ISO 27001)
  isms_technical_area: string
  isms_data_role: string
  // MDQMS (ISO 13485)
  mdqms_device_classes: string[]
  mdqms_regulatory_territories: string[]
}
```

### 8b — Update `DEFAULT_S2`

Find `const DEFAULT_S2: Step2Data = { ... }`. **Replace it** with:

```typescript
const DEFAULT_S2: Step2Data = {
  full_time: 0, part_time: 0, subcontractors: 0, seasonal: 0,
  shift_1_count: 0, shift_2_count: 0, shift_3_count: 0,
  shift_same_process: false,
  multiSite: false, sites: [{ _key: '1', address: '', employee_count: 0 }],
  pairIntegration: {},
  enms_annual_energy_tj: '', enms_num_energy_types: '', enms_num_seus: '',
  fsms_food_chain_categories: [], fsms_haccp_studies: '',
  fsms_offsite_storage_count: '', fsms_separate_head_office: false,
  fsms_fssc22000: false, fsms_seasonal_production: false,
  isms_technical_area: '', isms_data_role: '',
  mdqms_device_classes: [], mdqms_regulatory_territories: [],
}
```

### 8c — Add standard-specific panels inside `Step2`

Find the end of the `Step2` function — specifically the closing `</div>` of the
integration-level section (around line 425 in the original). The `Step2` function
signature already has `standards: string[]` as a prop.

Just **before** the final `</div>` that closes the main container of `Step2`
(i.e., after the multi-site / integration section and before the `return` ends),
add these conditional panels:

```tsx
{/* ── EnMS panel — ISO 50001 ───────────────────────────────── */}
{standards.includes('ENMS') && (
  <div className="rounded-xl border border-blue-100 bg-blue-50/40 p-5 space-y-4">
    <p className="text-sm font-semibold text-blue-900">⚡ ISO 50001 — Energy Profile</p>
    <p className="text-xs text-blue-700">
      Required for the ISO 50003 K-factor calculation. Used to select the correct audit time table.
    </p>
    <div className="grid grid-cols-2 gap-4">
      <div>
        <label className={lblCls}>Annual energy consumption</label>
        <select className={inputCls} value={data.enms_annual_energy_tj}
          onChange={e => onChange({ enms_annual_energy_tj: e.target.value })}>
          <option value="">— Select range —</option>
          <option value="10">≤ 20 TJ</option>
          <option value="100">20–200 TJ</option>
          <option value="1000">200–2,000 TJ</option>
          <option value="5000">&gt; 2,000 TJ</option>
        </select>
      </div>
      <div>
        <label className={lblCls}>Number of energy types</label>
        <select className={inputCls} value={data.enms_num_energy_types}
          onChange={e => onChange({ enms_num_energy_types: e.target.value })}>
          <option value="">— Select —</option>
          <option value="1">1</option>
          <option value="2">2</option>
          <option value="3">3</option>
          <option value="4">4 or more</option>
        </select>
      </div>
      <div>
        <label className={lblCls}>Number of Significant Energy Uses (SEUs)</label>
        <select className={inputCls} value={data.enms_num_seus}
          onChange={e => onChange({ enms_num_seus: e.target.value })}>
          <option value="">— Select —</option>
          <option value="2">1–3 SEUs</option>
          <option value="5">4–6 SEUs</option>
          <option value="8">7–10 SEUs</option>
          <option value="12">11–15 SEUs</option>
          <option value="20">&gt; 15 SEUs</option>
        </select>
      </div>
    </div>
  </div>
)}

{/* ── FSMS panel — ISO 22000 ───────────────────────────────── */}
{standards.includes('FSMS') && (
  <div className="rounded-xl border border-blue-100 bg-blue-50/40 p-5 space-y-4">
    <p className="text-sm font-semibold text-blue-900">🍽️ ISO 22000 — Food Safety Details</p>
    <div>
      <label className={lblCls}>Food chain categories in scope</label>
      <p className="text-xs text-gray-500 mb-2">Select all that apply (ISO 22003-1:2022 Annex B).</p>
      <div className="grid grid-cols-1 gap-1 max-h-52 overflow-y-auto">
        {[
          { code: 'CI',   label: 'CI — Animal farming / perishable animal products' },
          { code: 'CII',  label: 'CII — Perishable plant (fresh produce)' },
          { code: 'CIII', label: 'CIII — Processed perishable / ready-to-eat' },
          { code: 'CIV',  label: 'CIV — Ambient-stable food (bakery, confectionery, beverages)' },
          { code: 'C0',   label: 'C0 — Slaughter / abattoir' },
          { code: 'D',    label: 'D — Animal feed' },
          { code: 'E',    label: 'E — Catering / food service' },
          { code: 'FI',   label: 'FI — Food retail' },
          { code: 'FII',  label: 'FII — Food wholesale / brokerage' },
          { code: 'G',    label: 'G — Food storage / cold-chain logistics' },
          { code: 'I',    label: 'I — Food packaging / food contact materials' },
          { code: 'K',    label: 'K — Food additives / ingredients' },
          { code: 'BIII', label: 'BIII — Plant pre-processing' },
        ].map(cat => (
          <label key={cat.code} className="flex items-center gap-2 cursor-pointer py-0.5">
            <input type="checkbox"
              checked={data.fsms_food_chain_categories.includes(cat.code)}
              onChange={() => onChange({
                fsms_food_chain_categories: data.fsms_food_chain_categories.includes(cat.code)
                  ? data.fsms_food_chain_categories.filter(c => c !== cat.code)
                  : [...data.fsms_food_chain_categories, cat.code]
              })}
              className="w-4 h-4 accent-[#1A4731] shrink-0" />
            <span className="text-xs text-gray-700">{cat.label}</span>
          </label>
        ))}
      </div>
    </div>
    <div className="grid grid-cols-2 gap-4">
      <div>
        <label className={lblCls}>HACCP studies</label>
        <input className={inputCls} type="number" min="0" placeholder="0"
          value={data.fsms_haccp_studies}
          onChange={e => onChange({ fsms_haccp_studies: e.target.value })} />
      </div>
      <div>
        <label className={lblCls}>Off-site storage facilities in scope</label>
        <input className={inputCls} type="number" min="0" placeholder="0"
          value={data.fsms_offsite_storage_count}
          onChange={e => onChange({ fsms_offsite_storage_count: e.target.value })} />
        <p className="text-xs text-gray-400 mt-1">+0.25 audit day each (ISO 22003-1 §B.2.5)</p>
      </div>
    </div>
    <div className="space-y-2">
      {([
        { key: 'fsms_separate_head_office', label: 'Head office separate from production site (+0.5 day)' },
        { key: 'fsms_fssc22000',            label: 'FSSC 22000 scheme (+1.0 day reporting surcharge)' },
        { key: 'fsms_seasonal_production',  label: 'Seasonal production' },
      ] as { key: keyof Step2Data; label: string }[]).map(({ key, label }) => (
        <label key={String(key)} className="flex items-center gap-2 cursor-pointer">
          <input type="checkbox" checked={data[key] as boolean}
            onChange={e => onChange({ [key]: e.target.checked })}
            className="w-4 h-4 accent-[#1A4731]" />
          <span className="text-sm text-gray-700">{label}</span>
        </label>
      ))}
    </div>
  </div>
)}

{/* ── ISMS panel — ISO 27001 ───────────────────────────────── */}
{standards.includes('ISMS') && (
  <div className="rounded-xl border border-blue-100 bg-blue-50/40 p-5 space-y-4">
    <p className="text-sm font-semibold text-blue-900">🔐 ISO 27001 — ISMS Details</p>
    <div className="grid grid-cols-1 gap-4">
      <div>
        <label className={lblCls}>Technical area (ISO/IEC 27006-1:2024)</label>
        <select className={inputCls} value={data.isms_technical_area}
          onChange={e => onChange({ isms_technical_area: e.target.value })}>
          <option value="">— Select —</option>
          <option value="A">A — Standard IT (office systems, cloud, ERP)</option>
          <option value="B">B — Industrial / OT (ICS, SCADA, manufacturing IT)</option>
          <option value="C">C — Telecom / service provider infrastructure</option>
          <option value="D">D — Specialized (data centres, medical devices, critical infrastructure)</option>
        </select>
      </div>
      <div>
        <label className={lblCls}>Data role</label>
        <select className={inputCls} value={data.isms_data_role}
          onChange={e => onChange({ isms_data_role: e.target.value })}>
          <option value="">— Select —</option>
          <option value="Controller">Data Controller</option>
          <option value="Processor">Data Processor</option>
          <option value="Both">Both Controller and Processor</option>
        </select>
      </div>
    </div>
  </div>
)}

{/* ── MDQMS panel — ISO 13485 ──────────────────────────────── */}
{standards.includes('MDQMS') && (
  <div className="rounded-xl border border-blue-100 bg-blue-50/40 p-5 space-y-4">
    <p className="text-sm font-semibold text-blue-900">🏥 ISO 13485 — Medical Device Details</p>
    <div className="grid grid-cols-1 gap-1">
      {['Class I (low risk)', 'Class IIa', 'Class IIb', 'Class III (high risk)', 'IVD', 'Active implants'].map(cls => (
        <label key={cls} className="flex items-center gap-2 cursor-pointer">
          <input type="checkbox"
            checked={data.mdqms_device_classes.includes(cls)}
            onChange={() => onChange({
              mdqms_device_classes: data.mdqms_device_classes.includes(cls)
                ? data.mdqms_device_classes.filter(c => c !== cls)
                : [...data.mdqms_device_classes, cls]
            })}
            className="w-4 h-4 accent-[#1A4731]" />
          <span className="text-sm text-gray-700">{cls}</span>
        </label>
      ))}
    </div>
  </div>
)}
```

### 8d — Update the `shift_same_process` row in `Step2`'s existing personnel section

Inside `Step2`, find the existing shift count inputs (the three `shift_1_count`,
`shift_2_count`, `shift_3_count` rows). After those inputs, add a checkbox for
`shift_same_process` if there are multiple shifts:

```tsx
{(data.shift_1_count > 0 && data.shift_2_count > 0) && (
  <label className="flex items-center gap-2 cursor-pointer col-span-full mt-1">
    <input type="checkbox" checked={data.shift_same_process}
      onChange={e => onChange({ shift_same_process: e.target.checked })}
      className="w-4 h-4 accent-[#1A4731]" />
    <span className="text-sm text-gray-700">
      All shifts perform the same process (IAF MD5 repetitive reduction may apply)
    </span>
  </label>
)}
```

### 8e — Update the `mutate` payload in `NewClientPage`

In `NewClientPage`, find the `mutationFn: async () => { ... }` inside the `useMutation` call.
After the existing `integration_level` spread, add:

```typescript
application_data: {
  enms_annual_energy_tj:         s2.enms_annual_energy_tj   ? parseFloat(s2.enms_annual_energy_tj)   : null,
  enms_num_energy_types:         s2.enms_num_energy_types    ? parseInt(s2.enms_num_energy_types)     : null,
  enms_num_seus:                 s2.enms_num_seus            ? parseInt(s2.enms_num_seus)             : null,
  fsms_food_chain_categories:    s2.fsms_food_chain_categories,
  fsms_haccp_studies:            s2.fsms_haccp_studies       ? parseInt(s2.fsms_haccp_studies)        : null,
  fsms_offsite_storage_count:    s2.fsms_offsite_storage_count ? parseInt(s2.fsms_offsite_storage_count) : 0,
  fsms_separate_head_office:     s2.fsms_separate_head_office,
  fsms_fssc22000:                s2.fsms_fssc22000,
  fsms_seasonal_production:      s2.fsms_seasonal_production,
  isms_technical_area:           s2.isms_technical_area || null,
  isms_data_role:                s2.isms_data_role || null,
  mdqms_device_classes:          s2.mdqms_device_classes,
  mdqms_regulatory_territories:  s2.mdqms_regulatory_territories,
  part_time_fte_factor:          0.5,
  subcontractors_in_scope:       true,
},
```

Also update the existing `personnel` object inside the payload to include `shift_same_process`:

```typescript
personnel: {
  full_time:          s2.full_time,
  part_time:          s2.part_time,
  subcontractors:     s2.subcontractors,
  seasonal:           s2.seasonal,
  shift_1_count:      s2.shift_1_count,
  shift_2_count:      s2.shift_2_count,
  shift_3_count:      s2.shift_3_count,
  shift_same_process: s2.shift_same_process,   // ← ADD
},
```

---

## Verification Checklist

### Backend
- [ ] `GET /audit-sets/{id}` response includes `application_data` field (non-null for any
  recently created audit set with FSMS/ENMS/ISMS standards selected) ✅
- [ ] `PUT /audit-sets/{id}/planning` with `{ "application_data": { "enms_annual_energy_tj": 100, "enms_num_energy_types": 3, "enms_num_seus": 5 } }` updates the field and a subsequent recalculation uses it ✅
- [ ] ISO 50001 audit set — calc result shows correct K-factor (e.g. TJ=100, types=3, SEU=5 → K≈1.225 → Medium complexity) ✅
- [ ] ISO 22000 audit set with `fsms_offsite_storage_count=2` — `base_init` is 0.50 days higher than without it ✅
- [ ] ISO 22000 audit set with `fsms_separate_head_office=true` — `base_init` is 0.50 days higher ✅
- [ ] Part-time FTE conversion: `{ full_time: 10, part_time: 4 }` → `total_employees=12` (not 14); audit time changes accordingly ✅
- [ ] Subcontractors NOT in scope: `{ subcontractors_in_scope: false }` → subcontractors excluded from EPS ✅
- [ ] `POST /apply` with `fsms_food_chain_categories: ["CI", "CIV"]` stores them in `application_data` ✅
- [ ] Fresh install (no prior DB): `create_tables()` runs cleanly, `application_data` column exists ✅
- [ ] Existing DB (Railway): running new code doesn't break existing rows — `_safe_add_column` is idempotent ✅

### Frontend — Public form (`/apply`)
- [ ] Default view: no EnMS / FSMS / ISMS / MDQMS sections visible ✅
- [ ] Check ISO 50001 → EnMS panel appears with 3 dropdowns (energy TJ, types, SEUs) ✅
- [ ] Uncheck ISO 50001 → EnMS panel disappears ✅
- [ ] Check ISO 22000 → FSMS panel appears with food chain checkboxes, HACCP count, off-site count, 3 boolean toggles ✅
- [ ] Check ISO 27001 → ISMS panel appears with technical area + data role selects ✅
- [ ] Check ISO 13485 → MDQMS panel appears with device class checkboxes ✅
- [ ] Improved personnel section visible with full-time, part-time, subcontractors, seasonal, shift count inputs ✅
- [ ] Multi-shift "same process" checkbox appears only when shift count > 1 ✅
- [ ] Submit with ISO 50001 data → `POST /apply` body includes `enms_annual_energy_tj`, etc. ✅
- [ ] Submit → success screen → "Go to Portal Login" ✅

### Frontend — Internal form (`/clients/new`)
- [ ] Standards selected in Step 1 propagate to Step 2 ✅
- [ ] Step 2 with ISO 50001 in standards → EnMS panel renders at bottom of personnel section ✅
- [ ] Step 2 with ISO 22000 → FSMS panel renders ✅
- [ ] Step 2 with ISO 27001 → ISMS panel renders ✅
- [ ] Final payload sent to `POST /audit-sets/` includes `application_data` object ✅
- [ ] Newly created audit set → plan page → PlanOverview → man-day recalculation uses the EnMS/FSMS data ✅
