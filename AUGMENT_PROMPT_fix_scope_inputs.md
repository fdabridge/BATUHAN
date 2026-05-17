# Augment Task: Fix Scope Category Inputs for Category-Based Standards

## The Problem

The Add auditor modal and the auditor detail edit form show an "EA codes (comma-separated)" text input for every standard — including ISO 22000, FSSC 22000, ISO 13485, ISO 50001, ISO 37001, and ISO 37301. These standards do NOT use EA codes. They each have their own classification system. The UI must show the right input for each standard. This is the ONLY thing this prompt changes.

The `scope_category` column already exists on `AuditorStandardQualification`. The data must be stored in `scope_category`, not `ea_codes`, for these standards.

---

## Classification system per standard (authoritative)

| Standard | Field to use | Input type | Values |
|----------|-------------|------------|--------|
| ISO 9001 | `ea_codes` (list) + `scope_category` | EA codes: text input; Scope: dropdown | EA 1–39; High / Medium / Low |
| ISO 14001 | `ea_codes` (list) + `scope_category` | EA codes: text input; Scope: dropdown | EA 1–39; High / Medium / Low / Limited |
| ISO 45001 | `ea_codes` (list) + `scope_category` | EA codes: text input; Scope: dropdown | EA 1–39; High / Medium / Low |
| ISO 27001 | `ea_codes` (list) | EA codes: text input only | EA 1–39; no scope_category |
| ISO 22000 | `scope_category` only | Multi-select tag buttons | BIII, C0, CI, CII, CIII, CIV, D, E, FI, FII, G, I, K |
| FSSC 22000 | `scope_category` only | Multi-select tag buttons | BIII, C0, CI, CII, CIII, CIV, D, E, FI, FII, G, I, K |
| ISO 13485 | `scope_category` only | Multi-select tag buttons | A1.1, A1.2, A1.3, A1.4, A1.5, A1.6, A1.7, A2.1, A2.2, A2.3, A2.4 |
| ISO 50001 | `ea_codes` (list) + `scope_category` | EA codes: text input; Scope: dropdown | EA 1–39; Low / Medium / High |
| ISO 37001 | `scope_category` only | Dropdown | Public / Private / Third sector/NGO |
| ISO 37301 | `scope_category` only | Dropdown | Public / Private / Third sector/NGO |

For ISO 22000, FSSC 22000, and ISO 13485: the `ea_codes` field must be set to `[]` — do not show an EA codes input.

---

## Changes Required

### File 1: `frontend/src/app/(app)/auditors/page.tsx` (Add auditor modal)

The qualification rows in the review/edit modal currently show:
```
"EA codes for {standard} (comma-separated)" → <input type="text">
```
for every standard. Replace this with a `ScopeInput` component that renders the correct input based on the standard:

```tsx
const FOOD_CHAIN_CATEGORIES = ['BIII','C0','CI','CII','CIII','CIV','D','E','FI','FII','G','I','K']
const MEDICAL_DEVICE_TAS = ['A1.1','A1.2','A1.3','A1.4','A1.5','A1.6','A1.7','A2.1','A2.2','A2.3','A2.4']
const EA_CODE_STANDARDS = ['9001','14001','45001','27001','50001']
const FOOD_STANDARDS = ['22000','fssc']
const MEDICAL_STANDARDS = ['13485']
const SECTOR_STANDARDS = ['37001','37301']

function getStandardType(code: string): 'ea' | 'food' | 'medical' | 'sector' {
  const c = code.toLowerCase()
  if (FOOD_STANDARDS.some(s => c.includes(s))) return 'food'
  if (MEDICAL_STANDARDS.some(s => c.includes(s))) return 'medical'
  if (SECTOR_STANDARDS.some(s => c.includes(s))) return 'sector'
  return 'ea'
}

function ScopeInput({ standardCode, eaCodes, scopeCategory, onChangeEA, onChangeScope }: {
  standardCode: string
  eaCodes: string[]
  scopeCategory: string
  onChangeEA: (v: string[]) => void
  onChangeScope: (v: string) => void
}) {
  const type = getStandardType(standardCode)
  const c = standardCode.toLowerCase()

  // Risk/complexity dropdown label
  const riskLabel = c.includes('14001') ? 'EMS complexity'
    : c.includes('45001') ? 'OH&S risk level'
    : c.includes('50001') ? 'Energy complexity'
    : 'Risk category'
  const riskOptions = c.includes('14001')
    ? ['High','Medium','Low','Limited']
    : ['High','Medium','Low']

  if (type === 'food') {
    // ISO 22000 / FSSC 22000 — food chain category multi-select
    const selected = scopeCategory.split(',').map(s => s.trim()).filter(Boolean)
    return (
      <div className="mt-2">
        <label className="block text-xs text-gray-400 mb-1">Food chain categories</label>
        <div className="flex flex-wrap gap-1">
          {FOOD_CHAIN_CATEGORIES.map(cat => {
            const active = selected.includes(cat)
            return (
              <button key={cat} type="button"
                className="rounded px-2 py-0.5 text-xs border transition-colors"
                style={active
                  ? { background: '#1A4731', color: 'white', borderColor: '#1A4731' }
                  : { background: 'white', color: '#374151', borderColor: '#D1D5DB' }}
                onClick={() => {
                  const next = active ? selected.filter(x => x !== cat) : [...selected, cat]
                  onChangeScope(next.join(', '))
                }}>
                {cat}
              </button>
            )
          })}
        </div>
      </div>
    )
  }

  if (type === 'medical') {
    // ISO 13485 — technical area multi-select
    const selected = scopeCategory.split(',').map(s => s.trim()).filter(Boolean)
    return (
      <div className="mt-2">
        <label className="block text-xs text-gray-400 mb-1">Technical areas (MD)</label>
        <div className="flex flex-wrap gap-1">
          {MEDICAL_DEVICE_TAS.map(ta => {
            const active = selected.includes(ta)
            return (
              <button key={ta} type="button"
                className="rounded px-2 py-0.5 text-xs border transition-colors"
                style={active
                  ? { background: '#5B21B6', color: 'white', borderColor: '#5B21B6' }
                  : { background: 'white', color: '#374151', borderColor: '#D1D5DB' }}
                onClick={() => {
                  const next = active ? selected.filter(x => x !== ta) : [...selected, ta]
                  onChangeScope(next.join(', '))
                }}>
                {ta}
              </button>
            )
          })}
        </div>
      </div>
    )
  }

  if (type === 'sector') {
    // ISO 37001 / ISO 37301 — sector dropdown
    return (
      <div className="mt-2">
        <label className="block text-xs text-gray-400 mb-1">Sector type</label>
        <select
          className="w-full rounded border border-gray-200 px-2 py-1.5 text-sm"
          value={scopeCategory}
          onChange={e => onChangeScope(e.target.value)}>
          <option value="">— Select —</option>
          <option>Public</option>
          <option>Private</option>
          <option>Third sector/NGO</option>
        </select>
      </div>
    )
  }

  // EA-code standards (ISO 9001, 14001, 45001, 27001, 50001)
  return (
    <div className="mt-2 space-y-2">
      <div>
        <label className="block text-xs text-gray-400 mb-1">EA codes for {standardCode} (comma-separated)</label>
        <input
          type="text"
          className="w-full rounded border border-gray-200 px-2 py-1.5 text-sm"
          placeholder="e.g. EA 3, EA 9"
          value={eaCodes.join(', ')}
          onChange={e => onChangeEA(e.target.value.split(',').map(s => s.trim()).filter(Boolean))}
        />
      </div>
      {!c.includes('27001') && (
        <div>
          <label className="block text-xs text-gray-400 mb-1">{riskLabel}</label>
          <select
            className="w-full rounded border border-gray-200 px-2 py-1.5 text-sm"
            value={scopeCategory}
            onChange={e => onChangeScope(e.target.value)}>
            <option value="">— Select —</option>
            {riskOptions.map(o => <option key={o}>{o}</option>)}
          </select>
        </div>
      )}
    </div>
  )
}
```

In each qualification row in the modal, replace the current EA codes text input with:
```tsx
<ScopeInput
  standardCode={q.standard_code}
  eaCodes={q.ea_codes ?? []}
  scopeCategory={q.scope_category ?? ''}
  onChangeEA={v => updateQual(idx, { ea_codes: v })}
  onChangeScope={v => updateQual(idx, { scope_category: v })}
/>
```

When building the save payload: for food/medical/sector standards, set `ea_codes: []` and put the user's selection in `scope_category`. For EA-code standards, set `ea_codes` from the text input and `scope_category` from the dropdown.

---

### File 2: `frontend/src/app/(app)/auditors/[id]/page.tsx` (Qualification cards display)

The qualification cards currently show nothing for ISO 22000, FSSC 22000, ISO 13485, ISO 50001, ISO 37001, ISO 37301 — only role/accreditation body/years. Add a `scopeLabel()` function (if not already present) and call it in each card.

```tsx
function scopeLabel(standardCode: string, scopeCategory: string | null | undefined, eaCodes?: string[]): React.ReactNode {
  if (!scopeCategory && (!eaCodes || eaCodes.length === 0)) return null
  const c = standardCode.toLowerCase()

  // Food chain categories — amber tags
  if (c.includes('22000') || c.includes('fssc')) {
    if (!scopeCategory) return null
    const cats = scopeCategory.split(',').map(s => s.trim()).filter(Boolean)
    if (cats.length === 0) return null
    return (
      <div className="mt-1.5 flex flex-wrap gap-1">
        {cats.map(cat => (
          <span key={cat} className="rounded px-1.5 py-0.5 text-xs font-medium"
            style={{ background: '#FEF3C7', color: '#92400E' }}>
            {cat}
          </span>
        ))}
      </div>
    )
  }

  // Medical device TAs — purple tags
  if (c.includes('13485')) {
    if (!scopeCategory) return null
    const tas = scopeCategory.split(',').map(s => s.trim()).filter(Boolean)
    if (tas.length === 0) return null
    return (
      <div className="mt-1.5 flex flex-wrap gap-1">
        {tas.map(ta => (
          <span key={ta} className="rounded px-1.5 py-0.5 text-xs font-medium"
            style={{ background: '#EDE9FE', color: '#5B21B6' }}>
            {ta}
          </span>
        ))}
      </div>
    )
  }

  // Sector type (37001, 37301) — blue tag
  if (c.includes('37001') || c.includes('37301')) {
    if (!scopeCategory) return null
    return (
      <span className="mt-1.5 inline-block rounded px-1.5 py-0.5 text-xs font-medium"
        style={{ background: '#DBEAFE', color: '#1E40AF' }}>
        {scopeCategory}
      </span>
    )
  }

  // EA-code standards — grey EA chips + risk badge
  const colorMap: Record<string, { bg: string; color: string }> = {
    'High':    { bg: '#FEE2E2', color: '#991B1B' },
    'Medium':  { bg: '#FEF3C7', color: '#92400E' },
    'Low':     { bg: '#F0FAF4', color: '#1A4731' },
    'Limited': { bg: '#F3F4F6', color: '#6B7280' },
  }
  const riskStyle = scopeCategory ? (colorMap[scopeCategory] ?? { bg: '#F3F4F6', color: '#6B7280' }) : null

  return (
    <div className="mt-1.5 space-y-1">
      {eaCodes && eaCodes.length > 0 && (
        <div className="flex flex-wrap gap-1">
          {eaCodes.map(code => (
            <span key={code} className="rounded px-1.5 py-0.5 text-xs font-mono"
              style={{ background: '#F3F4F6', color: '#374151', border: '1px solid #E5E7EB' }}>
              {code}
            </span>
          ))}
        </div>
      )}
      {riskStyle && (
        <span className="inline-block rounded px-1.5 py-0.5 text-xs font-medium"
          style={riskStyle}>
          {scopeCategory}
        </span>
      )}
    </div>
  )
}
```

Call it in each qualification card:
```tsx
{scopeLabel(q.standard_code, q.scope_category, q.ea_codes)}
```

Also update the **edit form rows** (in the QualifiedStandards edit mode) to use the same `ScopeInput` component defined above instead of the current EA-codes-only text input.

---

### File 3: `frontend/src/app/(app)/auditors/[id]/page.tsx` (Edit form)

In the QualifiedStandards edit mode rows, replace the current per-row "EA codes" text input with the `ScopeInput` component (same component defined above). The props are the same: pass the row's `standard_code`, `ea_codes`, `scope_category`, and the row update functions.

---

## Files to Change

- `frontend/src/app/(app)/auditors/page.tsx` — Add auditor modal: replace EA codes input with `ScopeInput` component
- `frontend/src/app/(app)/auditors/[id]/page.tsx` — Add `scopeLabel()`, update qualification cards display, update edit form rows

## Do Not Change

- Any backend files
- `frontend/src/types/index.ts` (no new types needed)
- `frontend/src/lib/api.ts`
- Any other frontend files

## Priority

1. `ScopeInput` component — shared by modal and edit form
2. Add auditor modal — replace existing EA codes inputs with `ScopeInput`
3. `scopeLabel()` function — add to detail page
4. Qualification cards — call `scopeLabel()` in each card
5. Edit form rows — replace existing EA codes input with `ScopeInput`

Complete all five in order.
