# Augment Task: Per-Standard EA Codes, Qualification Display, and Stage Coverage Validation

## Context

Certiva — Next.js 14 App Router + FastAPI, ISO certification body platform.

Three interconnected problems to fix. They all stem from one root cause:
**EA codes are stored at the auditor level (a flat list) but must exist at the per-standard qualification level.** Without per-standard EA codes, you cannot answer: "Is this auditor qualified to audit ISO 9001 in food sector (EA 3)?" You only know they have EA 3 somewhere, for some standard.

This prompt fixes the data model, the extraction, the display, and the stage planning validation.

---

## PROBLEM 1 — Add/Edit auditor modal: qualification rows do not show standard_code

**File:** `frontend/src/app/(app)/auditors/page.tsx`

In the "Add auditor" review step, the qualification table shows rows with [Accreditation body] [Technical depth] [Years] [Delete] — but NO standard_code. The user cannot tell which row is ISO 9001, which is ISO 22000, etc.

**Fix:** In the qualification review rows, add the standard_code as the first visible element in each row — non-editable, clearly labeled:

```tsx
<div className="flex items-start gap-3 py-2 border-b border-gray-100">
  <div className="w-28 shrink-0 pt-1">
    <span className="font-medium text-sm text-gray-900">{q.standard_code}</span>
  </div>
  {/* existing: accreditation body, technical depth, years, delete */}
</div>
```

Also add an EA codes input per qualification row (comma-separated), so users can correct per-standard EA codes before saving:

```tsx
<div className="mt-1 col-span-full">
  <label className="text-xs text-gray-400">EA codes for {q.standard_code} (comma-separated)</label>
  <input
    type="text"
    className={inputCls}
    value={(q.ea_codes ?? []).join(', ')}
    onChange={e => updateQualEACodes(idx, e.target.value.split(',').map(s => s.trim()).filter(Boolean))}
    placeholder="e.g. EA 3, EA 9"
  />
</div>
```

---

## PROBLEM 2 — Per-standard EA codes: data model, extraction, and display

### 2a. Add `ea_codes` column to `AuditorStandardQualification`

**File:** `backend/auditors/models.py`

```python
class AuditorStandardQualification(Base):
    # existing columns ...
    scope_category = Column(String, nullable=True)
    ea_codes = Column(JSON, nullable=True)
    # e.g. ["EA 3", "EA 9"] for ISO 9001 in food + printing sectors
```

Safe migration in `create_tables()` — add after the existing `scope_category` migration block:

```python
with engine.connect() as conn:
    try:
        conn.execute(text("ALTER TABLE auditor_standard_qualifications ADD COLUMN ea_codes JSON"))
        conn.commit()
    except Exception:
        pass  # column already exists
```

### 2b. Update schemas

**File:** `backend/auditors/schemas.py`

Add `ea_codes: list[str] = []` to `StandardQualificationItem` and any `StandardQualificationCreate` or nested dict used in `AuditorCreateSchema`.

### 2c. Update extractor: extract per-standard EA codes

**File:** `backend/auditors/extractor.py`

**Critical distinction — two completely different scope systems:**

- **EA-code standards** (ISO 9001, ISO 14001, ISO 45001, ISO 27001): scope is defined by IAF EA codes (industry sectors). Add `ea_codes` to these qualification records.
- **Category-based standards** (ISO 22000, FSSC 22000, ISO 13485, ISO 50001, ISO 37001, ISO 37301): these have their OWN classification systems. Do NOT add EA codes to these — they use `scope_category` instead (food chain categories, medical device areas, energy complexity, sector type). Those are already handled separately.

In the `STANDARD QUALIFICATIONS RULES` section of `_SYSTEM_PROMPT`, add:

```
- For standards ISO 9001, ISO 14001, ISO 45001, and ISO 27001 only: include "ea_codes" as a list
  of IAF EA codes (from the official EA 1–39 list) for which the auditor has documented auditing
  experience specifically for THAT standard.
  Example: auditor who did ISO 9001 audits in food factories (EA 3) and printing (EA 9):
    {"standard_code": "ISO 9001", "ea_codes": ["EA 3", "EA 9"], ...}
  If the CV does not specify sectors per standard, fall back to the auditor's overall ea_codes list
  as a default. Apply the same validation: only use codes from EA 1–EA 39.
- For ISO 22000, FSSC 22000, ISO 13485, ISO 50001, ISO 37001, ISO 37301: do NOT include "ea_codes".
  These standards do not use EA codes for scope classification. Their scope is captured in
  "scope_category" (food chain categories, medical device areas, energy complexity, sector type).
  Set "ea_codes": [] for these standards.
```

Update the JSON schema description at the top of the prompt to include `ea_codes` in standard_qualifications:
```
standard_qualifications (list of {standard_code, accreditation_body, technical_depth, experience_years, scope_category, ea_codes})
```

### 2d. Show per-standard EA codes in auditor detail qualification cards

**File:** `frontend/src/app/(app)/auditors/[id]/page.tsx`

In each `QualifiedStandards` qualification card, after `scopeLabel()`, add:

```tsx
{q.ea_codes && q.ea_codes.length > 0 && (
  <div className="mt-1 flex flex-wrap gap-1">
    {q.ea_codes.map((code: string) => (
      <span key={code}
        className="rounded px-1.5 py-0.5 text-xs font-mono"
        style={{ background: '#F3F4F6', color: '#374151', border: '1px solid #E5E7EB' }}>
        {code}
      </span>
    ))}
  </div>
)}
```

If `q.ea_codes` is empty or null, show nothing (don't show the auditor-level ea_codes as a fallback — that would be misleading).

### 2e. Update qualification edit form to include per-standard EA codes

**File:** `frontend/src/app/(app)/auditors/[id]/page.tsx`

In the `QualifiedStandards` edit mode (added by AUGMENT_PROMPT_edit_standards.md), add an EA codes input per row after the `experience_years` input and before `ScopeCategoryField`:

```tsx
<div>
  <label className={lblCls}>EA codes for this standard</label>
  <input
    type="text"
    className={inputCls}
    value={(row.ea_codes ?? []).join(', ')}
    onChange={e => updateRow(idx, {
      ea_codes: e.target.value.split(',').map(s => s.trim()).filter(Boolean)
    })}
    placeholder="e.g. EA 3, EA 9"
  />
</div>
```

When building the save payload, include `ea_codes` on each qualification row.

---

## PROBLEM 3 — Stage planning: team coverage validation

### The correct logic

For each audit stage save, the system must verify:
- For every required standard in the audit set (e.g. ISO 9001, ISO 14001, ISO 45001):
  - At least one person in the team (lead auditor + auditors + technical experts) must have:
    - A qualification for that standard
    - AND the client's EA code in their per-standard `ea_codes` (if per-standard ea_codes exist on file; if the field is empty/null for that qualification, skip the EA check — don't punish old records)
- If any standard is not covered → block save with a specific error

### 3a. Fix standard code mismatch

**File:** `frontend/src/app/(app)/clients/[id]/page.tsx`

The `AuditSetResponse.standards` field may store family labels ("QMS", "EMS", "OHSMS") instead of ISO codes. Add a resolver at the top of the component or file:

```typescript
const ISO_LABEL_MAP: Record<string, string> = {
  'QMS': 'ISO 9001',
  'EMS': 'ISO 14001',
  'OHSMS': 'ISO 45001',
  'FSMS': 'ISO 22000',
  'FSSC 22000': 'FSSC 22000',
  'ISMS': 'ISO 27001',
  'EnMS': 'ISO 50001',
  'ABMS': 'ISO 37001',
  'MDMS': 'ISO 13485',
  'CMS': 'ISO 37301',
}

function resolveStandards(raw: string[]): string[] {
  return raw.map(s => ISO_LABEL_MAP[s] ?? s)
}
```

Use `resolveStandards(data.standards ?? [])` everywhere standards are passed to availability queries or coverage checks.

### 3b. Change Auditors and Technical Experts from free-text to multi-select

**File:** `frontend/src/app/(app)/clients/[id]/page.tsx`

Currently the edit state for a stage has:
```typescript
auditors: string         // "Name A, Name B"
technical_experts: string
```

Change to:
```typescript
auditors: { id: string; name: string }[]
technical_experts: { id: string; name: string }[]
```

Initialize from the existing saved data: if `stage.auditors` is an array of objects with `{id, name}`, use that. If it's a legacy string, parse the names and set IDs to empty strings.

Replace both text inputs with a tag-select pattern:

```tsx
{/* Auditors multi-select */}
<div>
  <label className={lblCls}>Auditors</label>
  {/* Selected tags */}
  <div className="flex flex-wrap gap-1 mb-1 min-h-[24px]">
    {edit.auditors.map(a => (
      <span key={a.id || a.name}
        className="flex items-center gap-1 rounded-full px-2 py-0.5 text-xs"
        style={{ background: '#F0FAF4', color: '#1A4731', border: '1px solid #BBF7D0' }}>
        {a.name}
        <button type="button" className="ml-1 text-gray-400 hover:text-red-500"
          onClick={() => patch({ auditors: edit.auditors.filter(x => (x.id || x.name) !== (a.id || a.name)) })}>
          ×
        </button>
      </span>
    ))}
  </div>
  {/* Add from available list */}
  <select className={inputCls} value=""
    onChange={e => {
      const found = (availableAuditors ?? auditors).find(a => a.id === e.target.value || a.name === e.target.value)
      if (found && !edit.auditors.find(x => (x.id || x.name) === (found.id || found.name))) {
        patch({ auditors: [...edit.auditors, { id: found.id ?? '', name: found.name }] })
      }
    }}>
    <option value="">+ Add auditor…</option>
    {(availableAuditors ?? auditors)
      .filter(a => !edit.auditors.find(x => (x.id || x.name) === (a.id || a.name)))
      .filter(a => a.name !== edit.lead_auditor_name)
      .map(a => (
        <option key={a.id ?? a.name} value={a.id ?? a.name}>{a.name}</option>
      ))}
  </select>
</div>
```

Apply the same pattern for Technical experts.

When saving, serialize auditors back to the backend as the existing `{id, name}` array format that `AuditSetStage.auditors` already stores.

### 3c. Coverage check helper

**Two completely different scope systems — the check must respect this:**

- **EA-code standards** (ISO 9001, 14001, 45001, 27001): match auditor's per-standard `ea_codes` against the client's EA code.
- **Category-based standards** (ISO 22000, FSSC 22000, 13485, 50001, 37001, 37301): match auditor's `scope_category` against the client's scope category for that standard. If no category is stored on either side, just verify the auditor has the qualification — don't block.

Add inside `StageCard`:

```typescript
// Standards that use IAF EA codes for scope
const EA_CODE_STANDARDS = ['9001', '14001', '45001', '27001']

// Standards that use their own category systems (NOT EA codes)
const CATEGORY_STANDARDS = ['22000', 'fssc', '13485', '50001', '37001', '37301']

function standardUsesCodes(std: string): 'ea' | 'category' | 'unknown' {
  const n = std.toLowerCase().replace('iso ', '').replace(/\s/g, '')
  if (EA_CODE_STANDARDS.some(s => n.includes(s))) return 'ea'
  if (CATEGORY_STANDARDS.some(s => n.includes(s))) return 'category'
  return 'unknown'
}

interface CoverageResult {
  standard: string
  covered: boolean
  coveredBy: string | null
  reason: string | null   // shown in the UI when not covered
}

function computeCoverage(
  requiredStandards: string[],
  clientEACode: string | null,
  teamMembers: { id: string; name: string }[],
  allAuditors: AuditorAvailabilityItem[],
): CoverageResult[] {
  return requiredStandards.map(std => {
    const stdNorm = std.toLowerCase().replace('iso ', '').replace(/\s/g, '')
    const scopeType = standardUsesCodes(std)

    const cover = allAuditors
      .filter(a => teamMembers.some(m => m.id ? m.id === a.id : m.name === a.name))
      .find(a => {
        const qual = a.standard_qualifications.find(q => {
          const qNorm = q.standard_code.toLowerCase().replace('iso ', '').replace(/\s/g, '')
          return qNorm === stdNorm || qNorm.startsWith(stdNorm) || stdNorm.startsWith(qNorm)
        })
        if (!qual) return false   // auditor doesn't have this standard at all

        if (scopeType === 'ea') {
          // EA-code standards: check per-standard ea_codes vs client EA code
          if (!clientEACode) return true
          const qualEA = qual.ea_codes
          if (!qualEA || qualEA.length === 0) return true  // no ea_codes stored — don't block old records
          const clientNum = clientEACode.replace(/[^0-9]/g, '')
          return qualEA.some(c => c.replace(/[^0-9]/g, '') === clientNum)
        }

        if (scopeType === 'category') {
          // Category-based standards: don't check EA codes at all
          // Auditor has the qualification — that's sufficient for now
          // (scope_category matching is a future enhancement requiring client-side category storage)
          return true
        }

        return true  // unknown standard type — just check qualification exists
      })

    let reason: string | null = null
    if (!cover) {
      if (scopeType === 'ea' && clientEACode) {
        reason = `needs qualification + ${clientEACode}`
      } else {
        reason = 'no qualified team member'
      }
    }

    return {
      standard: std,
      covered: !!cover,
      coveredBy: cover?.name ?? null,
      reason,
    }
  })
}
```

### 3d. Compute team and show coverage summary

Inside `StageCard`, compute the full team and coverage results:

```typescript
const teamMembers = [
  ...(edit.lead_auditor_name ? [{ id: edit.lead_auditor_id ?? '', name: edit.lead_auditor_name }] : []),
  ...edit.auditors,
  ...edit.technical_experts,
]

const resolvedStandards = resolveStandards(standards ?? [])

const coverageResults = (resolvedStandards.length > 0 && (availableAuditors ?? []).length > 0)
  ? computeCoverage(resolvedStandards, eaCode, teamMembers, availableAuditors ?? [])
  : []

const allCovered = coverageResults.length === 0 || coverageResults.every(r => r.covered)
```

Show the coverage summary below the technical experts field, above the Save button:

```tsx
{coverageResults.length > 0 && (
  <div className={`rounded-md p-3 text-sm ${allCovered
    ? 'border border-green-200'
    : 'border border-red-200'}`}
    style={{ background: allCovered ? '#F0FAF4' : '#FEF2F2' }}>
    <p className="font-medium mb-1" style={{ color: allCovered ? '#1A4731' : '#991B1B' }}>
      {allCovered ? '✓ All standards covered' : '✗ Coverage incomplete — cannot save'}
    </p>
    {coverageResults.map(r => (
      <div key={r.standard} className="flex items-center gap-2 text-xs mt-0.5">
        <span style={{ color: r.covered ? '#1A4731' : '#991B1B' }}>
          {r.covered ? '✓' : '✗'} {r.standard}
          {r.coveredBy ? ` — ${r.coveredBy}` : r.reason ? ` — ${r.reason}` : ` — no qualified team member`}
        </span>
      </div>
    ))}
  </div>
)}
```

### 3e. Block save if coverage is incomplete

In the `StageCard` save handler, before the API call:

```typescript
if (coverageResults.length > 0 && !allCovered) {
  const missing = coverageResults.filter(r => !r.covered).map(r => r.standard).join(', ')
  setError(`Cannot save: ${missing} ${missing.includes(',') ? 'are' : 'is'} not covered by any qualified team member.`)
  return
}
```

If `standards` is empty or `man_day_result` is null, skip the coverage check entirely and allow save.

### 3f. Update `AuditorAvailabilityItem` type to include per-standard EA codes

**File:** `frontend/src/types/index.ts`

```typescript
export interface AuditorAvailabilityItem {
  id: string
  name: string
  role: string | null
  ea_codes: string[]
  standard_qualifications: {
    standard_code: string
    technical_depth: string
    ea_codes: string[]          // per-standard EA codes — may be [] for old records
    scope_category: string | null
  }[]
  available: boolean
  conflict_detail: string | null
}
```

### 3g. Backend: include per-standard ea_codes in availability response

**File:** `backend/api/routes/auditors.py`

In the `GET /auditors/available` route, when building the `standard_qualifications` list for each auditor in the response, include `ea_codes`:

```python
"standard_qualifications": [
    {
        "standard_code": q.standard_code,
        "technical_depth": q.technical_depth,
        "ea_codes": q.ea_codes or [],
        "scope_category": q.scope_category,
    }
    for q in auditor.standard_qualifications
],
```

Also update `AuditorAvailabilityItem` Pydantic schema in `auditors/schemas.py`:
```python
class AuditorAvailabilityItem(BaseModel):
    id: str
    name: str
    role: Optional[str]
    ea_codes: list[str]
    standard_qualifications: list[dict]   # [{standard_code, technical_depth, ea_codes, scope_category}]
    available: bool
    conflict_detail: Optional[str]
```

---

## Files to Change

- `backend/auditors/models.py` — add `ea_codes` JSON to `AuditorStandardQualification`, safe migration
- `backend/auditors/schemas.py` — add `ea_codes: list[str] = []` to qualification schema + availability item
- `backend/auditors/extractor.py` — add per-standard EA code extraction instructions to system prompt
- `backend/api/routes/auditors.py` — include per-standard `ea_codes` in availability response
- `frontend/src/types/index.ts` — update `AuditorAvailabilityItem` with per-standard ea_codes
- `frontend/src/app/(app)/auditors/page.tsx` — fix qualification review rows: show standard_code + ea_codes input
- `frontend/src/app/(app)/auditors/[id]/page.tsx` — show per-standard ea_codes in cards; add ea_codes input in edit form
- `frontend/src/app/(app)/clients/[id]/page.tsx` — resolveStandards(), multi-select auditors/TEs, coverage check, block save

## Do Not Change

- `backend/calculator/` — do not touch
- `backend/audit_set/db_models.py` — do not change DB models
- `frontend/src/lib/api.ts`
- `frontend/src/lib/auth.tsx`
- `frontend/src/components/layout/`
- No new npm packages

## Priority Order

1. Problem 2a–2c (DB + schema + extractor for per-standard EA codes) — data foundation everything else depends on
2. Problem 3g (backend availability response includes per-standard ea_codes) — feeds the frontend
3. Problem 3f (frontend type update) — type safety
4. Problem 3a (fix standard code mismatch with resolveStandards) — unblocks availability filter
5. Problem 3b (auditor/TE multi-select) — required for coverage check to have IDs
6. Problem 3c–3e (coverage computation, display, save block) — the core safety gate
7. Problem 2d–2e (display + edit ea_codes per standard in auditor detail) — visibility
8. Problem 1 (fix modal qualification rows to show standard_code) — display fix

Complete all tasks in priority order. Do not skip any.
