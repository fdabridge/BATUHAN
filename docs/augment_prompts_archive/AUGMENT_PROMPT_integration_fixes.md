# Integration Fix — 8 items from audit report

Fix every item below. Each one has the exact file, location, and required change.

---

## FIX 1 — resolver.py: surveillance_1 / surveillance_2 falls to wrong branch

**File:** `backend/audit_set/resolver.py` (or wherever `STAGE_SUBFOLDER` / folder routing lives)
**Line:** ~192

**Current:**
```python
if audit_type == "surveillance":
```

**Fix:**
```python
if audit_type.startswith("surveillance"):
```

That's the entire fix. `"surveillance_1"` and `"surveillance_2"` will now correctly route to the Surveillance folder instead of producing Stage_1 + Stage_2 folders.

---

## FIX 2 — resolver.py: always uses Turkish folder names — add English routing for UAF

**File:** `backend/audit_set/resolver.py`

The `STAGE_SUBFOLDER` mapping (and any other folder/template name lookups) currently always returns Turkish strings. When `accreditation_body == "UAF"`, all folder names and template file references must be English. When `accreditation_body == "TÜRKAK"` or `"TURKAK"`, use Turkish.

Find wherever folder names like `"İlk Belgelendirme/Aşama 1"`, `"Gözetim"`, `"Yeniden Belgelendirme"` are defined and replace with a branching structure:

```python
def get_stage_folder(audit_type: str, stage_type: str, accreditation_body: str) -> str:
    is_uaf = (accreditation_body or "").upper() == "UAF"

    if audit_type.startswith("surveillance"):
        return "Surveillance" if is_uaf else "Gözetim"

    if stage_type == "stage_1":
        return "Initial Certification/Stage 1" if is_uaf else "İlk Belgelendirme/Aşama 1"

    if stage_type == "stage_2":
        if audit_type == "recertification":
            return "Recertification" if is_uaf else "Yeniden Belgelendirme"
        return "Initial Certification/Stage 2" if is_uaf else "İlk Belgelendirme/Aşama 2"

    return "Documents"
```

Apply the same English/Turkish split to any template file name lookups that currently hardcode Turkish filenames. Pass `accreditation_body` from the audit set through to wherever this function is called.

---

## FIX 3 — /download: no pre-flight check — package generated for unplanned audits

**File:** `backend/api/routes/audit_sets.py` — the `download_zip()` / `GET /{id}/download` handler

Before calling `build_audit_set_zip()`, add:

```python
# Require at least one stage to have a lead auditor assigned
stages_with_lead = [s for s in audit_set.stages if s.lead_auditor_name]
if not stages_with_lead:
    raise HTTPException(
        status_code=400,
        detail="Cannot generate audit package: no lead auditor has been assigned to any stage."
    )
```

---

## FIX 4 — /download: status not advanced after package generation

**File:** `backend/api/routes/audit_sets.py` — same download handler, after `build_audit_set_zip()` succeeds

Add before returning the response:

```python
audit_set.status = "active"
db.commit()
```

---

## FIX 5 — /api/auditors/available: zero-coverage auditors not excluded server-side

**File:** `backend/api/routes/auditors.py` — after `covered_scope` is computed for each auditor

Currently all active auditors are returned regardless of coverage. When `required_categories` is provided and non-empty, filter server-side:

```python
if required_scope and any(required_scope.values()):
    # Exclude auditors who cover zero codes across all required standards
    auditors_out = [
        a for a in auditors_out
        if any(len(codes) > 0 for codes in a.covered_scope.values())
    ]
```

Apply this filter before building the response list.

---

## FIX 6 — Frontend: auditorCount ÷ audit_days drives calendar days — not implemented

**File:** `frontend/src/app/(app)/clients/[id]/page.tsx`

### 6A — Update IAF banner to show live formula

Find the IAF banner block (around line 660) and replace with:

```tsx
{stage.audit_days != null && (
  <div className="mb-3 rounded-md px-3 py-2 text-sm" style={{ background: '#F0FAF4', color: '#1A4731' }}>
    <span className="font-medium">IAF MD 5:</span>{' '}
    {stage.audit_days} audit-day{stage.audit_days !== 1 ? 's' : ''} required.
    {auditorCount > 0 ? (
      <span className="ml-2 font-medium">
        ÷ {auditorCount} auditor{auditorCount > 1 ? 's' : ''}{' = '}
        <span>{Math.ceil(stage.audit_days / auditorCount)} calendar day{Math.ceil(stage.audit_days / auditorCount) > 1 ? 's' : ''}</span>
      </span>
    ) : (
      <span className="ml-1 text-xs" style={{ color: '#92400E' }}> — assign auditors to see required calendar days</span>
    )}
  </div>
)}
```

Where `auditorCount` is already computed as:
```typescript
const auditorCount = (edit.lead_auditor_name ? 1 : 0) + edit.auditors.length
// Note: technical_experts do NOT count toward man-days
```

Make sure `teamCount` (used for manDaysCovered) also excludes technical experts from the man-day divisor. Technical experts may be on-site but do not divide the audit-days. `teamCount` for coverage purposes may still include them, but `auditorCount` for the calendar days formula must be lead + additional auditors only.

### 6B — Reactive end-date update when auditors change

Add this `useEffect` inside the stage card component, after the existing mount useEffect:

```typescript
// When auditor count changes: recompute how many calendar days are needed and update end date
useEffect(() => {
  if (!edit.audit_date_start) return
  if (!stage.audit_days)     return
  if (auditorCount === 0)    return
  const calDays = Math.ceil(stage.audit_days / auditorCount)
  const newEnd  = suggestEndDate(edit.audit_date_start, calDays)
  if (newEnd !== edit.audit_date_end) {
    patch({ audit_date_end: newEnd })
  }
}, [auditorCount])  // eslint-disable-line react-hooks/exhaustive-deps
```

### 6C — Validate end date when coordinator manually changes it

When the coordinator manually edits `audit_date_end`, validate:

```typescript
function handleEndDateChange(newEnd: string) {
  patch({ audit_date_end: newEnd })
  if (!edit.audit_date_start || auditorCount === 0 || !stage.audit_days) return
  const actual = workingDaysBetween(edit.audit_date_start, newEnd)
  const required = Math.ceil(stage.audit_days / auditorCount)
  if (actual !== required) {
    // The existing manDayShortfall warning banner will catch and display this
    // No additional action needed — warning is already reactive
  }
}
```

The existing `manDayShortfall` warning already covers this case — it shows whenever `workingDays * auditorCount < stage.audit_days`. No additional UI needed.

---

## FIX 7 — Auditor dropdown label: group covered codes by standard

**File:** `frontend/src/app/(app)/clients/[id]/page.tsx`

Find where the dropdown option label is built from `covered_scope` (around line 712–715). Currently it flattens all codes into one list. Change it to group per standard:

**Current (approximate):**
```typescript
const codesFlat = Object.values(avail.covered_scope ?? {}).flat()
const label = codesFlat.length > 0 ? `${avail.name} — ✓ ${codesFlat.join(', ')}` : avail.name
```

**Replace with:**
```typescript
const coveredEntries = Object.entries(avail.covered_scope ?? {})
  .filter(([, codes]) => codes.length > 0)
  .map(([standard, codes]) => `${codes.join(' ')} (${standard})`)
const label = coveredEntries.length > 0
  ? `${avail.name} — ${coveredEntries.join(' | ')}`
  : avail.name
```

Result examples:
- `Seung Kyu HAN — EA 3 (ISO 9001) | CIV CIII (ISO 22000)`
- `Jane Smith — EA 3 (ISO 9001)`
- `Tom Lee — EA 3 (ISO 9001) (unavailable 19–21 May)`

---

## FIX 8 — TypeScript type: AuditSetPersonnel missing unskilled

**File:** `frontend/src/types/index.ts`

Find the `AuditSetPersonnel` interface and add `unskilled`:

```typescript
export interface AuditSetPersonnel {
  full_time?:      number
  part_time?:      number
  subcontractors?: number
  seasonal?:       number
  unskilled?:      number   // ADD THIS
}
```

---

## DO NOT CHANGE

- `backend/calculator/engine.py` — calculation logic is verified correct
- `computeCoverage()` in the frontend — verified correct
- Stage 2 hard-block logic — verified correct
- IAF MD 11 rates and floor — verified correct
- `covered_scope` computation in `auditors.py` — verified correct

---

## VERIFICATION

After all fixes:

1. Create an audit set with `audit_type = "surveillance_1"`. The download package must produce a `Surveillance` folder, not `Stage_1 + Stage_2`.

2. Create an audit set with `accreditation_body = "UAF"`. The download package folder names must be in English (`Initial Certification/Stage 1`, `Surveillance`, `Recertification`).

3. Try downloading an audit package with no lead auditor assigned — must get HTTP 400.

4. Successfully download a package with all stages planned — `audit_set.status` must be `"active"` after download.

5. On the stage planning card, assign a lead auditor. Banner shows "X audit-days ÷ 1 auditor = X calendar days". Add a second auditor — banner updates to "X audit-days ÷ 2 auditors = Y calendar days" and end date shifts automatically.

6. Auditor dropdown option for an auditor covering ISO 9001 EA 3 and ISO 22000 CIV/CIII must show: `Name — EA 3 (ISO 9001) | CIV CIII (ISO 22000)`.
