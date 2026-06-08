# Augment Task: Fix Stage Planning + Standard-Specific Scope System

## Context

Certiva — Next.js 14 App Router + FastAPI, ISO certification body platform.
There are three independent problems to fix, all related to audit planning and auditor scope.

---

## PROBLEM 1 — Man-day calculation not shown (two root causes)

### Root Cause A: `man_day_result` is null for manually created audit sets

The `AuditSet` model (`backend/audit_set/db_models.py`) has `man_day_result = Column(JSON, nullable=True)`.
When a client is created manually (not through the PDF application form upload + Claude extraction flow),
`man_day_result` stays null. The frontend `ManDaySection` correctly renders "Calculation not available."

**Fix — add a quick-calculate endpoint:**

**File:** `backend/api/routes/audit_sets.py`

Add before the `/{audit_set_id}` GET route:

```python
class QuickCalcPayload(BaseModel):
    effective_employees: int
    standards: list[str]          # e.g. ["ISO 9001", "ISO 14001"]
    audit_type: str               # "Initial" | "Recertification" | "Surveillance"
    risk_category: str = "Medium" # "High" | "Medium" | "Low" — used for QMS/EMS/OHSMS
    integration_yes_count: int = 0  # 0-8 integration level (affects multi-standard reduction)

@router.post("/{audit_set_id}/quick-calculate", response_model=dict)
def quick_calculate(
    audit_set_id: str,
    payload: QuickCalcPayload,
    db: Session = Depends(get_db),
    _: PlatformUser = Depends(require_planner),
):
    """
    Run the IAF MD 5 calculator from manually entered basic data (no PDF upload needed).
    Saves result to man_day_result and effective_employees on the AuditSet.
    Returns the full CalculationResult as a dict.
    """
    from calculator.engine import calculate
    from calculator.models import ExtractedFormData, StandardClassification

    audit_set = db.query(AuditSet).filter(AuditSet.id == audit_set_id).first()
    if not audit_set:
        raise HTTPException(status_code=404, detail="Audit set not found")

    # Build a minimal ExtractedFormData for the engine
    classifications = [
        StandardClassification(
            standard=std,
            sector_name="General",
            category=payload.risk_category,
        )
        for std in payload.standards
    ]

    extracted = ExtractedFormData(
        org_name=audit_set.company_name or "",
        standards=payload.standards,
        audit_type=payload.audit_type,
        scope=audit_set.scope_en or "",
        total_employees=payload.effective_employees,
        office_employees=0,
        repetitive_employees=0,
        integration_yes_count=payload.integration_yes_count,
        classifications=classifications,
    )

    try:
        result = calculate(extracted)
    except Exception as exc:
        raise HTTPException(status_code=422, detail=str(exc))

    result_dict = result.model_dump()
    audit_set.man_day_result = result_dict
    audit_set.effective_employees = payload.effective_employees
    if payload.standards:
        audit_set.standards = payload.standards
    audit_set.audit_type = payload.audit_type.lower()
    db.commit()

    return result_dict
```

### Root Cause B: `ManDaySection` reads wrong data shape

The frontend `ManDaySection` at `frontend/src/app/(app)/clients/[id]/page.tsx` treats
`man_day_result` as `Record<string, ManDayEntry>` and calls `Object.entries(result)`.
But the backend `CalculationResult` is:
```json
{
  "standards": ["ISO 9001", "ISO 14001"],
  "final_ph1": 3.0,
  "final_ph2": 5.0,
  "final_surv1": 2.5,
  "final_recert_ph1": 2.0,
  "final_recert_ph2": 4.0,
  "final_total": 8.0,
  "standard_results": [
    { "standard": "ISO 9001", "base_init": 5.0, "base_ph1": 1.5, "base_ph2": 3.5, "base_surv": 1.5, "base_recert": 3.5, "eps": 45.0, "category": "Medium Risk", ... },
    { "standard": "ISO 14001", "base_init": 6.0, "base_ph1": 2.0, "base_ph2": 4.0, "base_surv": 2.0, "base_recert": 4.0, "eps": 45.0, "category": "Medium Complexity", ... }
  ],
  "integration_reduction": 1.4,
  "reporting_reduction": 1.4,
  "total_employees": 45,
  "eps": 45.0,
  "audit_type": "Initial"
}
```

**Fix — rewrite `ManDaySection` to read the correct shape:**

```tsx
function ManDaySection({ result, auditType }: {
  result: Record<string, unknown> | null
  auditType: string | null
}) {
  const [open, setOpen] = useState(false)
  if (!result) return null  // hide entirely when null — quick-calc widget handles this case

  const stdResults = (result.standard_results as StandardAuditResult[] | undefined) ?? []
  const isInitial = (result.audit_type as string ?? auditType ?? '').toLowerCase().includes('initial')
  const isSurv = (result.audit_type as string ?? auditType ?? '').toLowerCase().includes('surv')

  return (
    <div className="rounded-lg border border-gray-100 bg-white">
      <button type="button" className="flex w-full items-center justify-between px-5 py-4 text-left"
        onClick={() => setOpen(v => !v)}>
        <span className="text-sm font-medium text-gray-700">Man-day calculation (IAF MD 5)</span>
        {open ? <ChevronDown size={16} className="text-gray-400" /> : <ChevronRight size={16} className="text-gray-400" />}
      </button>
      {open && (
        <div className="border-t border-gray-100 px-5 pb-5 pt-4 space-y-4">
          {/* Per-standard breakdown */}
          {stdResults.length > 0 && (
            <table className="w-full text-sm">
              <thead>
                <tr className="text-left text-xs font-medium uppercase tracking-wide text-gray-400">
                  <th className="pb-2 pr-4">Standard</th>
                  <th className="pb-2 pr-4">Category</th>
                  <th className="pb-2 pr-4">EPS</th>
                  <th className="pb-2 pr-4">Base (S1+S2)</th>
                  <th className="pb-2">Surveillance</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-gray-50">
                {stdResults.map((r: StandardAuditResult) => (
                  <tr key={r.standard}>
                    <td className="py-2 pr-4 font-medium">{r.standard}</td>
                    <td className="py-2 pr-4 text-gray-500 text-xs">{r.category}</td>
                    <td className="py-2 pr-4 text-gray-600">{r.eps}</td>
                    <td className="py-2 pr-4 text-gray-600">{r.base_init}</td>
                    <td className="py-2 text-gray-600">{r.base_surv}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}

          {/* Summary totals */}
          <div className="grid grid-cols-2 gap-3 rounded-lg p-3" style={{ background: '#F0FAF4' }}>
            {isInitial && <>
              <div><p className="text-xs text-gray-500">Stage 1</p><p className="font-medium text-certiva-primary">{result.final_ph1 as number} days</p></div>
              <div><p className="text-xs text-gray-500">Stage 2</p><p className="font-medium text-certiva-primary">{result.final_ph2 as number} days</p></div>
              <div><p className="text-xs text-gray-500">Surveillance (each)</p><p className="font-medium text-certiva-primary">{result.final_surv1 as number} days</p></div>
              <div><p className="text-xs text-gray-500">Recertification total</p><p className="font-medium text-certiva-primary">{result.final_recert as number} days</p></div>
            </>}
            {isSurv && <div><p className="text-xs text-gray-500">Surveillance</p><p className="font-medium text-certiva-primary">{result.final_surv1 as number} days</p></div>}
            <div className="col-span-2 border-t border-green-200 pt-2">
              <p className="text-xs text-gray-500">Integration reduction</p>
              <p className="text-sm text-gray-700">-{result.integration_reduction as number} days · Reporting reduction: -{result.reporting_reduction as number} days</p>
            </div>
          </div>
        </div>
      )}
    </div>
  )
}
```

Add `StandardAuditResult` to the TypeScript types in `frontend/src/types/index.ts`:
```typescript
export interface StandardAuditResult {
  standard: string
  category: string
  eps: number
  base_init: number
  base_ph1: number
  base_ph2: number
  base_surv: number
  base_recert: number
  base_recert_ph1: number
  base_recert_ph2: number
  site_addition: number
}
```

### Fix — Add inline quick-calculate widget

When `man_day_result` is null, instead of a hidden section, show an inline form above the stage cards.

**File:** `frontend/src/app/(app)/clients/[id]/page.tsx`

Add a `QuickCalcWidget` component:

```tsx
const STANDARDS_LIST = [
  'ISO 9001', 'ISO 14001', 'ISO 45001', 'ISO 22000', 'FSSC 22000',
  'ISO 27001', 'ISO 50001', 'ISO 37001', 'ISO 13485',
]

function QuickCalcWidget({ auditSetId, currentStandards, auditType, onCalculated }: {
  auditSetId: string
  currentStandards: string[]
  auditType: string | null
  onCalculated: () => void
}) {
  const [employees, setEmployees] = useState('')
  const [standards, setStandards] = useState<string[]>(currentStandards.length ? currentStandards : ['ISO 9001'])
  const [riskCat, setRiskCat] = useState('Medium')
  const [error, setError] = useState<string | null>(null)

  const { mutate, isPending } = useMutation({
    mutationFn: () => api.post(`/audit-sets/${auditSetId}/quick-calculate`, {
      effective_employees: parseInt(employees),
      standards,
      audit_type: auditType ?? 'Initial',
      risk_category: riskCat,
    }),
    onSuccess: () => { setError(null); onCalculated() },
    onError: (e: unknown) => {
      const detail = (e as { response?: { data?: { detail?: string } } })?.response?.data?.detail
      setError(detail ?? 'Calculation failed.')
    },
  })

  return (
    <div className="rounded-lg border border-amber-200 bg-amber-50 p-4">
      <p className="mb-3 text-sm font-medium" style={{ color: '#92400E' }}>
        Man-day calculation not available. Enter basic details to calculate:
      </p>
      <div className="grid grid-cols-3 gap-3">
        <div>
          <label className={lblCls}>Effective employees</label>
          <input type="number" min="1" className={inputCls} value={employees}
            onChange={e => setEmployees(e.target.value)} placeholder="e.g. 45" />
        </div>
        <div>
          <label className={lblCls}>Risk / complexity</label>
          <select className={inputCls} value={riskCat} onChange={e => setRiskCat(e.target.value)}>
            <option>High</option>
            <option>Medium</option>
            <option>Low</option>
          </select>
        </div>
        <div>
          <label className={lblCls}>Standards</label>
          <div className="flex flex-wrap gap-1 mt-1">
            {STANDARDS_LIST.map(s => (
              <button key={s} type="button"
                onClick={() => setStandards(prev => prev.includes(s) ? prev.filter(x => x !== s) : [...prev, s])}
                className="rounded px-2 py-0.5 text-xs border"
                style={standards.includes(s) ? { background: '#1A4731', color: 'white', border: 'none' } : { background: 'white', color: '#374151' }}>
                {s}
              </button>
            ))}
          </div>
        </div>
      </div>
      {error && <p className="mt-2 text-xs text-red-600">{error}</p>}
      <button type="button" disabled={!employees || standards.length === 0 || isPending}
        onClick={() => mutate()}
        className="mt-3 flex items-center gap-1.5 rounded-lg px-4 py-2 text-sm font-medium text-white disabled:opacity-60"
        style={{ background: '#1A4731' }}>
        {isPending && <Loader2 size={14} className="animate-spin" />}
        Calculate man-days
      </button>
    </div>
  )
}
```

Render it inside the audit stages section, **above the stage cards**, when `data.man_day_result` is null:
```tsx
{!data.man_day_result && (
  <QuickCalcWidget
    auditSetId={id}
    currentStandards={(data.standards ?? []) as string[]}
    auditType={data.audit_type ?? null}
    onCalculated={invalidate}
  />
)}
```

Also show the client's EA code and effective employees in a small info bar above the stage cards:
```tsx
<div className="flex items-center gap-4 text-xs text-gray-500 mb-3">
  {data.ea_code && <span>EA code: <strong className="text-gray-800">{data.ea_code}</strong></span>}
  {data.effective_employees && <span>Effective employees: <strong className="text-gray-800">{data.effective_employees}</strong></span>}
  {data.audit_type && <span>Audit type: <strong className="text-gray-800">{data.audit_type}</strong></span>}
</div>
```

Also pass `ManDaySection` the `auditType`:
```tsx
<ManDaySection result={data.man_day_result} auditType={data.audit_type ?? null} />
```

---

## PROBLEM 2 — Suggest dates for stages

After the man-day calculation is available, add a "Suggest dates" button inside each `StageCard`.

**File:** `frontend/src/app/(app)/clients/[id]/page.tsx`

Add a `suggestDates(stageType, recommended, allStages)` function inside `StageCard`:

```typescript
function suggestDates(
  stageType: string,
  recommendedDays: number,
  allStages: StageResponse[],
): { start: string; end: string } {
  // Stage 1: start 3 weeks from today
  // Stage 2: start 4 weeks after Stage 1 end
  // Surveillance: start 11 months after Stage 2 end (or 12 months from cert)
  const addWorkingDays = (from: Date, days: number): Date => {
    const d = new Date(from)
    let added = 0
    while (added < days) {
      d.setDate(d.getDate() + 1)
      if (d.getDay() !== 0 && d.getDay() !== 6) added++
    }
    return d
  }

  const fmt = (d: Date) => d.toISOString().slice(0, 10)
  const today = new Date()

  if (stageType === 'stage_1') {
    const start = addWorkingDays(today, 15)  // ~3 working weeks notification
    const end = addWorkingDays(start, Math.max(1, Math.round(recommendedDays)) - 1)
    return { start: fmt(start), end: fmt(end) }
  }

  if (stageType === 'stage_2') {
    const s1 = allStages.find(s => s.stage_type === 'stage_1')
    const baseDate = s1?.audit_date_end ? new Date(s1.audit_date_end) : addWorkingDays(today, 15)
    const start = addWorkingDays(baseDate, 20)  // ~4 week gap after Stage 1
    const end = addWorkingDays(start, Math.max(1, Math.round(recommendedDays)) - 1)
    return { start: fmt(start), end: fmt(end) }
  }

  // surveillance
  const s2 = allStages.find(s => s.stage_type === 'stage_2')
  const baseDate = s2?.audit_date_end ? new Date(s2.audit_date_end) : today
  const start = addWorkingDays(baseDate, 220)  // ~11 months
  const end = addWorkingDays(start, Math.max(1, Math.round(recommendedDays)) - 1)
  return { start: fmt(start), end: fmt(end) }
}
```

Add the button next to the dates, shown only when `recommended != null`:
```tsx
{recommended != null && (
  <button type="button"
    className="text-xs underline cursor-pointer"
    style={{ color: '#1A4731' }}
    onClick={() => {
      const { start, end } = suggestDates(stage.stage_type, recommended, allStages)
      patch({ audit_date_start: start, audit_date_end: end })
    }}>
    Suggest dates
  </button>
)}
```

### Stage ordering constraint

Enforce that stages are always saved in the correct order: Stage 1 → Stage 2 → Surveillance/Certification.
Add this validation inside `StageCard` before the save call fires:

```typescript
function validateStageOrder(
  stageType: string,
  edit: { audit_date_start: string; audit_date_end: string },
  allStages: StageResponse[],
): string | null {
  const s1 = allStages.find(s => s.stage_type === 'stage_1')
  const s2 = allStages.find(s => s.stage_type === 'stage_2')

  if (stageType === 'stage_2' && s1?.audit_date_end && edit.audit_date_start) {
    if (edit.audit_date_start <= s1.audit_date_end) {
      return 'Stage 2 must start after Stage 1 ends.'
    }
  }

  if (stageType === 'surveillance' && s2?.audit_date_end && edit.audit_date_start) {
    if (edit.audit_date_start <= s2.audit_date_end) {
      return 'Surveillance must start after Stage 2 ends.'
    }
  }

  if (stageType === 'stage_1' && s2?.audit_date_start && edit.audit_date_end) {
    if (edit.audit_date_end >= s2.audit_date_start) {
      return 'Stage 1 must end before Stage 2 starts.'
    }
  }

  return null
}
```

Call it in the save handler:
```typescript
const orderError = validateStageOrder(stage.stage_type, edit, allStages)
if (orderError) {
  setError(orderError)
  return
}
```

Display the error inline (same place as other save errors in the card). Do NOT block the user from typing dates freely — only validate on save.

---

## PROBLEM 3 — Standard-specific scope system for auditor qualifications

Each ISO standard uses a **different** scope classification system. Currently auditors have a flat
`ea_codes` list on the `Auditor` record and `standard_code` + `technical_depth` per qualification —
with no standard-specific scope category stored.

### The correct scope systems per standard:

| Standard | Scope System | What to Store |
|----------|-------------|---------------|
| **ISO 9001** | IAF EA codes 1–39 + Risk Category | `ea_codes` (from auditor profile) + `scope_category`: "High" / "Medium" / "Low" |
| **ISO 14001** | IAF EA codes 1–39 + Complexity | `scope_category`: "High" / "Medium" / "Low" / "Limited" |
| **ISO 45001** | IAF EA codes 1–39 + OH&S Complexity | `scope_category`: "High" / "Medium" / "Low" |
| **ISO 22000** | Food Chain Category (NOT EA codes) | `scope_category`: one or more of: "A-I" / "A-II" / "B-I" / "B-II" / "B-III" / "C0" / "C-I" / "C-II" / "C-III" / "C-IV" / "D" / "E" / "F" / "G" / "H" / "I" / "K" |
| **FSSC 22000** | Same as ISO 22000 food chain categories | same as above |
| **ISO 50001** | Energy complexity (TJ / SEUs / energy types → K factor) | `scope_category`: "Low" / "Medium" / "High" |
| **ISO 37001** | IAF EA codes + sector type | `scope_category`: "Public" / "Private" / "Third sector/NGO" |
| **ISO 13485** | Medical device technical area | `scope_category`: one or more of: "Non-active" / "Active non-implantable" / "Active implantable" / "IVD" / "Sterilization" |
| **ISO 27001** | IAF EA codes | No additional category — just EA codes |

### 3a. Add `scope_category` to the DB model

**File:** `backend/auditors/models.py`

Add one column to `AuditorStandardQualification`:
```python
scope_category = Column(String, nullable=True)
# Stores standard-specific scope classification. Examples:
# ISO 9001: "Medium"
# ISO 22000: "C-I, C-II"   (comma-separated food chain categories)
# ISO 13485: "Non-active, IVD"
# ISO 50001: "High"
# ISO 37001: "Private"
```

Because this is SQLite with `create_tables()` called on startup, the new column will be added
**only if the table doesn't exist yet** (SQLAlchemy `create_all` doesn't alter existing tables).
To handle existing DBs, also run this in `create_tables()`:
```python
def create_tables():
    Base.metadata.create_all(bind=engine)
    # Safe migration: add scope_category if it doesn't exist
    from sqlalchemy import text
    with engine.connect() as conn:
        try:
            conn.execute(text("ALTER TABLE auditor_standard_qualifications ADD COLUMN scope_category TEXT"))
            conn.commit()
        except Exception:
            pass  # column already exists
```

### 3b. Add `scope_category` to schemas

**File:** `backend/auditors/schemas.py`

Add `scope_category: Optional[str] = None` to `StandardQualificationItem` and `AuditorCreateSchema`'s
nested qualification dict.

### 3c. Update extractor to capture scope categories

**File:** `backend/auditors/extractor.py`

Update the `STANDARD QUALIFICATIONS RULES` section of `_SYSTEM_PROMPT` to add:

```
- For ISO 9001, ISO 14001, ISO 45001: include "scope_category" as one of "High", "Medium", or "Low"
  (or "Limited" for ISO 14001). Base this on the sectors/industries in the auditor's documented experience.
- For ISO 22000 or FSSC 22000: include "scope_category" as a comma-separated list of food chain
  category codes from: A-I, A-II, B-I, B-II, B-III, C0, C-I, C-II, C-III, C-IV, D, E, F, G, H, I, K.
  These are the FSMS food chain categories. Match the auditor's documented food sector experience.
  Common: C-I (perishable animal products like meat/dairy), C-II (perishable plant-based),
  C-IV (ambient stable like canned goods), E (catering/restaurants), I (packaging/cleaning agents).
- For ISO 50001: include "scope_category" as "Low", "Medium", or "High" energy complexity.
- For ISO 37001: include "scope_category" as "Public", "Private", or "Third sector/NGO".
- For ISO 13485: include "scope_category" as comma-separated technical areas from:
  Non-active, Active non-implantable, Active implantable, IVD, Sterilization.
- For ISO 27001: omit "scope_category" (not applicable).
```

And add `scope_category` to the standard_qualifications object in the JSON schema description:
```
standard_qualifications (list of {standard_code, accreditation_body, technical_depth, experience_years, scope_category})
```

### 3d. Update the auditor detail qualification display

**File:** `frontend/src/app/(app)/auditors/[id]/page.tsx`

In the `QualifiedStandards` component, update each qualification card to show `scope_category`
with standard-appropriate labels:

```tsx
function scopeLabel(standardCode: string, scopeCategory: string | null | undefined): React.ReactNode {
  if (!scopeCategory) return null
  const std = standardCode.toLowerCase()

  if (std.includes('22000') || std.includes('fssc')) {
    // Food chain categories — show as tags
    const cats = scopeCategory.split(',').map(c => c.trim()).filter(Boolean)
    return (
      <div className="mt-1 flex flex-wrap gap-1">
        {cats.map(c => (
          <span key={c} className="rounded px-1.5 py-0.5 text-xs" style={{ background: '#FEF3C7', color: '#92400E' }}>
            {c}
          </span>
        ))}
      </div>
    )
  }

  if (std.includes('13485')) {
    const areas = scopeCategory.split(',').map(c => c.trim()).filter(Boolean)
    return (
      <div className="mt-1 flex flex-wrap gap-1">
        {areas.map(a => (
          <span key={a} className="rounded px-1.5 py-0.5 text-xs" style={{ background: '#EDE9FE', color: '#5B21B6' }}>
            {a}
          </span>
        ))}
      </div>
    )
  }

  // For 9001, 14001, 45001, 50001, 37001 — show risk/complexity
  const colorMap: Record<string, { bg: string; color: string }> = {
    'High':        { bg: '#FEE2E2', color: '#991B1B' },
    'Medium':      { bg: '#FEF3C7', color: '#92400E' },
    'Low':         { bg: '#F0FAF4', color: '#1A4731' },
    'Limited':     { bg: '#F3F4F6', color: '#6B7280' },
    'Public':      { bg: '#DBEAFE', color: '#1E40AF' },
    'Private':     { bg: '#F0FAF4', color: '#1A4731' },
    'Third sector/NGO': { bg: '#EDE9FE', color: '#5B21B6' },
  }
  const s = colorMap[scopeCategory] ?? { bg: '#F3F4F6', color: '#6B7280' }
  return <span className="mt-1 inline-block rounded px-1.5 py-0.5 text-xs" style={s}>{scopeCategory}</span>
}
```

In the qualification card JSX, add after `technical_depth`:
```tsx
{scopeLabel(code, q.scope_category)}
```

### 3e. Update the edit form for qualifications

**File:** `frontend/src/app/(app)/auditors/[id]/page.tsx`

In the `QualifiedStandards` edit mode (added by the previous prompt), add a `scope_category` field
per row that changes its label and options based on the `standard_code` value in that row:

```tsx
function ScopeCategoryField({ standardCode, value, onChange }: {
  standardCode: string; value: string; onChange: (v: string) => void
}) {
  const std = standardCode.toLowerCase()

  if (std.includes('22000') || std.includes('fssc')) {
    const options = ['A-I','A-II','B-I','B-II','B-III','C0','C-I','C-II','C-III','C-IV','D','E','F','G','H','I','K']
    const selected = value.split(',').map(s => s.trim()).filter(Boolean)
    return (
      <div>
        <label className={lblCls}>Food chain categories (FSMS)</label>
        <div className="flex flex-wrap gap-1 mt-1">
          {options.map(o => (
            <button key={o} type="button"
              onClick={() => {
                const next = selected.includes(o) ? selected.filter(x => x !== o) : [...selected, o]
                onChange(next.join(', '))
              }}
              className="rounded px-2 py-0.5 text-xs border"
              style={selected.includes(o) ? { background: '#1A4731', color: 'white', border: 'none' } : {}}>
              {o}
            </button>
          ))}
        </div>
      </div>
    )
  }

  if (std.includes('13485')) {
    const options = ['Non-active','Active non-implantable','Active implantable','IVD','Sterilization']
    const selected = value.split(',').map(s => s.trim()).filter(Boolean)
    return (
      <div>
        <label className={lblCls}>Technical area (MD)</label>
        <div className="flex flex-wrap gap-1 mt-1">
          {options.map(o => (
            <button key={o} type="button"
              onClick={() => {
                const next = selected.includes(o) ? selected.filter(x => x !== o) : [...selected, o]
                onChange(next.join(', '))
              }}
              className="rounded px-2 py-0.5 text-xs border"
              style={selected.includes(o) ? { background: '#1A4731', color: 'white', border: 'none' } : {}}>
              {o}
            </button>
          ))}
        </div>
      </div>
    )
  }

  if (std.includes('37001')) {
    return (
      <div>
        <label className={lblCls}>Sector type</label>
        <select className={inputCls} value={value} onChange={e => onChange(e.target.value)}>
          <option value="">— Select —</option>
          <option>Public</option>
          <option>Private</option>
          <option>Third sector/NGO</option>
        </select>
      </div>
    )
  }

  if (!std.includes('27001')) {
    // 9001 / 14001 / 45001 / 50001
    const label = std.includes('14001') ? 'Complexity (EMS)' :
                  std.includes('45001') ? 'OH&S Complexity' :
                  std.includes('50001') ? 'Energy Complexity' : 'Risk category (QMS)'
    const options = std.includes('14001')
      ? ['High', 'Medium', 'Low', 'Limited']
      : ['High', 'Medium', 'Low']
    return (
      <div>
        <label className={lblCls}>{label}</label>
        <select className={inputCls} value={value} onChange={e => onChange(e.target.value)}>
          <option value="">— Select —</option>
          {options.map(o => <option key={o}>{o}</option>)}
        </select>
      </div>
    )
  }

  return null  // ISO 27001 — no extra scope field
}
```

Add this inside the qualification edit row (in the edit form added by the previous prompt), after the `experience_years` input.

### 3f. Update auditor list — show scope categories in the Standards pills

**File:** `frontend/src/app/(app)/auditors/page.tsx`

In the `AuditorRow` Standards column, update the pills to show the scope category as a small
sub-label beneath the standard code:

```tsx
{a.qualifications.slice(0, 3).map((q) => (
  <div key={q.standard_code} className="rounded px-1.5 py-0.5 text-xs" style={{ background: '#F0FAF4', color: '#1A4731' }}>
    <div className="font-medium">{q.standard_code}</div>
    {q.scope_category && (
      <div style={{ fontSize: 10, color: '#6B7280' }}>
        {q.scope_category.length > 12 ? q.scope_category.slice(0, 12) + '…' : q.scope_category}
      </div>
    )}
  </div>
))}
```

---

## Files to Change

- `backend/api/routes/audit_sets.py` — add `POST /{id}/quick-calculate`
- `backend/auditors/models.py` — add `scope_category` column + safe migration in `create_tables()`
- `backend/auditors/schemas.py` — add `scope_category` to qualification schemas
- `backend/auditors/extractor.py` — update system prompt for scope category extraction
- `frontend/src/app/(app)/clients/[id]/page.tsx` — fix `ManDaySection`, add `QuickCalcWidget`, add info bar, add suggest-dates
- `frontend/src/app/(app)/auditors/[id]/page.tsx` — add `scopeLabel()`, `ScopeCategoryField()` in edit form
- `frontend/src/app/(app)/auditors/page.tsx` — update Standards pills to show scope_category
- `frontend/src/types/index.ts` — add `StandardAuditResult`, add `scope_category` to qualification types

## Do Not Change

- `backend/calculator/` — do not modify the calculator engine or tables
- `backend/auth/` — do not modify auth
- `frontend/src/lib/api.ts`
- `frontend/src/lib/auth.tsx`
- `frontend/src/components/layout/`
- No new npm packages

## Priority Order

1. Problem 1 root cause B (fix `ManDaySection` data shape) — one component rewrite, immediate fix
2. Problem 1 root cause A (quick-calculate endpoint + widget) — unblocks all manual clients
3. Problem 2 (suggest dates) — builds on #1
4. Problem 3a–3b (DB + schema for scope_category) — foundation for display
5. Problem 3c (extractor update) — improves new uploads
6. Problem 3d–3f (display + edit form) — visible improvement

Complete all tasks in priority order.
