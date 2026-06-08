# Augment Task: Editable Standards & EA Codes on Auditor Detail Page

## Context

This is Certiva — a Next.js 14 (App Router) + FastAPI platform for ISO certification bodies.
The auditor detail page is at `frontend/src/app/(app)/auditors/[id]/page.tsx`.

The extraction system now deliberately excludes standards that have only training evidence and no documented auditing experience. This means users need a way to manually add standards and EA codes after the fact. There is currently no edit form on the detail page.

---

## What Needs To Be Done

**File to change:** `frontend/src/app/(app)/auditors/[id]/page.tsx` only.
**Do not add new npm packages. Do not change any backend files.**

### The backend `PUT` endpoint

`PUT /auditors/{id}` accepts the full `AuditorCreateSchema` body and replaces the auditor record:
```json
{
  "name": "string",
  "email": "string or null",
  "phone": "string or null",
  "mobile": "string or null",
  "role": "Lead Auditor | Auditor | Technical Expert",
  "active_since": "YYYY-MM-DD or null",
  "ea_codes": ["EA 3", "EA 18"],
  "accreditation_bodies": ["UAF", "TURKAK"],
  "standard_qualifications": [
    {
      "standard_code": "ISO 9001",
      "accreditation_body": "UAF",
      "technical_depth": "Lead Auditor",
      "experience_years": 5
    }
  ],
  "education": [],
  "languages": [],
  "work_experience": [],
  "training_records": []
}
```
Returns the updated auditor. On success, invalidate the `['auditor', id]` React Query cache.

---

### Task — Add "Edit" mode to the QualifiedStandards section

In the `QualifiedStandards` component (currently read-only), add an **"Edit"** button in the section header. When clicked, it switches the section into edit mode showing an inline form. When the user saves or cancels, it returns to the read-only card grid.

**Edit mode layout:**

**1. EA codes field** at the top of the edit section:
- Label: "EA Codes"
- A text input where the user types codes comma-separated (e.g. `EA 3, EA 18, EA 29`)
- Pre-populated with the auditor's current `ea_codes` joined as a comma-separated string
- On save, split by comma, trim whitespace, filter blanks → send as array

**2. Standard qualifications table** — a list of editable rows, one per qualification:

Each row has four inline inputs:
| Field | Input type | Placeholder / options |
|-------|-----------|----------------------|
| Standard code | `<input type="text">` | e.g. `ISO 9001` |
| Accreditation body | `<input type="text">` | e.g. `UAF` |
| Technical depth | `<select>` | Lead Auditor / Team Auditor / Technical Expert |
| Experience years | `<input type="number" min="0">` | e.g. `5` |
| (delete) | `<button>` with `<Trash2 size={14}>` | removes the row |

Below the rows, an **"+ Add standard"** link/button appends a new blank row.

**3. Save and Cancel buttons** at the bottom of the edit section.

**Save logic:**
1. Build the updated payload by taking the current `data` (the fetched `AuditorResponse`) and spreading all existing fields, then overriding only `ea_codes` and `standard_qualifications` with the edited values.
2. Validate: each qualification row must have a non-empty `standard_code` — if any row is empty, show an inline error `"Standard code is required for each row."` and do not submit.
3. Call `PUT /auditors/{id}` with the full merged payload.
4. On success: invalidate `['auditor', id]`, exit edit mode.
5. On error: show the backend error message in red below the Save button.

**The section header in edit mode** should show:
```
Qualified standards          [Cancel]  [Save]
```
With the Save button using the Certiva green `#1A4731`.

**Important:** The `QualifiedStandards` component currently only receives `{ a: AuditorResponse }`. To support editing, it will need access to the `id` and `queryClient`. Either pass them as additional props from the main page component, or move the edit logic into the main `AuditorDetailPage` component and pass down setters. Use whichever approach is cleaner — but keep it in the same file.

---

## Styling Rules

- `inputCls` and `lblCls` constants are already defined at the top of the file — use them for all inputs
- Primary color: `#1A4731` for Save button
- Error: `text-red-600` text, `border-red-300` border
- Loading: `<Loader2 size={14} className="animate-spin" />` from lucide-react (already imported)
- `Trash2` is already imported in the file
- `Plus` is already imported in the file

---

## Do Not Change

- Any other section on the detail page (ProfileOverview, EligibilityChecker, AuditHistory, WitnessPanel)
- `frontend/src/lib/api.ts`
- `frontend/src/lib/auth.tsx`
- `frontend/src/components/layout/`
- Any backend files
- `frontend/src/types/index.ts` — only if strictly necessary (type additions only, no modifications to existing types)
