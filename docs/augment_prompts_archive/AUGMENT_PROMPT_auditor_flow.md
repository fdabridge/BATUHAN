# Augment Task: Fix Auditor Registration & Smart Assignment Flow

## Context

This is a Next.js 14 (App Router) + FastAPI platform called Certiva for ISO certification bodies. The backend is fully built. The frontend has a critical workflow gap: auditors are currently entered as **free text names** everywhere, completely bypassing the registered auditor database.

---

## What Is Wrong

### Problem 1 — Auditors page has no "Add auditor" button

**File:** `frontend/src/app/(app)/auditors/page.tsx`

The page shows a list of auditors from `GET /auditors/dashboard` but has **no way to add a new auditor**. There is no button, no upload form, nothing. The header section (line 135–138) just shows the title with no action.

The backend already supports a two-step registration flow:
1. `POST /auditors/ingest` — upload a PDF or DOCX (auditor CV / FR.201 form), Claude extracts the profile fields and returns JSON. Nothing is saved yet.
2. `POST /auditors/` — save the extracted (and optionally corrected) profile to the database.

**What needs to be built:** An "Add auditor" button in the header that opens a slide-over/modal with:
- Step 1: File upload area (drag-and-drop or click). Accepts PDF or DOCX. On submit, calls `POST /auditors/ingest` (multipart form-data, field name `file`). Shows a loading spinner while Claude extracts.
- Step 2: The extracted fields come back as JSON. Show them in an editable preview form so the planner can correct any OCR/extraction errors. The key fields to show: `name`, `role` (Lead Auditor / Auditor / Technical Expert), `ea_codes` (array of strings like ["29", "30"]), `qualifications` (array of `{standard_code, accreditation_body, role}`), `active_since` (date string).
- Confirm button calls `POST /auditors/` with the (corrected) JSON body.
- On success, invalidate the `auditors-dashboard` React Query cache so the table refreshes.

---

### Problem 2 — Audit plan page uses free-text auditor names

**File:** `frontend/src/app/(app)/audit-plan/page.tsx`

The "Audit team" section (lines 289–326) renders free text `<input type="text" placeholder="Name">` boxes for auditor names. This is completely wrong — auditors must be selected from the registered pool in the database.

**What needs to be built:**

**2a. Replace free-text name inputs with dropdowns.**

On page load, fetch the registered auditor list: `GET /auditors/?active_only=true`. Returns an array of `AuditorSummarySchema` objects with at minimum: `id`, `name`, `role`.

Replace each auditor name text input with a `<select>` that shows registered auditors. Keep the role `<select>` as-is. The auditor row should look like:
```
[Dropdown: pick auditor name]  [Dropdown: role]  [Remove button]
```

**2b. Add "Suggest clause assignment" button.**

After the user picks auditors and selects a standard, show a **"Suggest assignment"** button below the audit team section. When clicked:
- Collect the selected auditor IDs and the selected `standard_code`.
- Call `POST /auditors/assign-clauses` with body:
  ```json
  { "auditor_ids": ["uuid1", "uuid2"], "standard_code": "QMS" }
  ```
- The response is an array of `{ auditor_id, auditor_name, role, assigned_clauses: [{clause_id, title}] }`.
- Display the suggested assignment below the button as a read-only summary table: one row per auditor, showing their name and which clauses they cover.
- Store this assignment result in state and pass it as the `assignments` array when calling `POST /auditors/generate-audit-plan`.

**2c. Wire assignments into the generate call.**

Currently `buildAssignments()` (lines 74–96) does a manual round-robin split of clauses. Replace this: if the user has run "Suggest assignment", use those results directly as the `assignments` payload. If they haven't, fall back to the current round-robin logic but use the selected auditor names from the dropdown.

---

### Problem 3 — Client detail page uses free-text auditor entry for stages

**File:** `frontend/src/app/(app)/clients/[id]/page.tsx`

The stage edit form uses free-text fields `lead_auditor_name`, `auditors_text`, `tech_experts_text` (lines 37–53, `buildStageEdit`). These are comma-separated name strings.

**What needs to be built:** Replace the lead auditor name text input with a `<select>` dropdown populated from `GET /auditors/?active_only=true`. The auditors and technical experts multi-entry fields can stay as comma-separated text for now (lower priority), but the lead auditor must be a dropdown.

---

## API Reference

All API calls use the axios instance from `@/lib/api` which automatically adds the Bearer token. Base URL is `NEXT_PUBLIC_API_URL`.

### Endpoints to use:

| Method | Path | Purpose |
|--------|------|---------|
| `POST` | `/auditors/ingest` | Upload PDF/DOCX, returns extracted JSON profile |
| `POST` | `/auditors/` | Save auditor profile to DB |
| `GET` | `/auditors/?active_only=true` | List registered auditors for dropdowns |
| `POST` | `/auditors/assign-clauses` | Suggest clause distribution given auditor IDs + standard |
| `POST` | `/auditors/generate-audit-plan` | Generate FR.223 DOCX |

### Ingest response shape (from `POST /auditors/ingest`):
```json
{
  "name": "John Smith",
  "role": "Lead Auditor",
  "ea_codes": ["29", "30"],
  "active_since": "2018-01-01",
  "qualifications": [
    { "standard_code": "QMS", "accreditation_body": "UAF", "role": "Lead Auditor" }
  ]
}
```

### Auditor list item shape (from `GET /auditors/`):
```json
{
  "id": "uuid-string",
  "name": "John Smith",
  "role": "Lead Auditor",
  "is_active": true,
  "ea_codes": ["29"],
  "qualifications": [{ "standard_code": "QMS", "accreditation_body": "UAF", "role": "Lead Auditor" }]
}
```

### Assign-clauses request/response:
```json
// Request
{ "auditor_ids": ["uuid1", "uuid2"], "standard_code": "QMS" }

// Response
[
  {
    "auditor_id": "uuid1",
    "auditor_name": "John Smith",
    "role": "Lead Auditor",
    "assigned_clauses": [{ "clause_id": "8", "title": "Operation" }]
  }
]
```

---

## Styling Rules

- Use the existing `inputCls` and `lblCls` constants already defined in each file.
- Primary color: `#1A4731` (Certiva green). Use `certiva-primary` Tailwind class where available.
- Surface color: `#F0FAF4`. Use `certiva-surface` Tailwind class.
- All modals/slide-overs should be simple fixed overlays — no external component library needed, just Tailwind.
- Loading states use `<Loader2 size={16} className="animate-spin" />` from lucide-react.
- Error states: red border + red text, same pattern as existing forms.
- No new npm packages. Only use what's already in package.json: React, @tanstack/react-query, axios, lucide-react, Tailwind.

---

## Priority Order

1. **Problem 2** (audit plan auditor dropdowns + suggest-assignment) — this is the most broken, planners can't use the system without it.
2. **Problem 1** (add auditor registration modal) — needed to populate the dropdown.
3. **Problem 3** (client detail lead auditor dropdown) — lower priority, do after 1 and 2.

---

## Do Not Change

- `frontend/src/lib/api.ts` — do not modify the axios instance.
- `frontend/src/lib/auth.tsx` — do not modify auth context.
- `frontend/src/components/layout/` — do not modify Sidebar or Topbar.
- Backend files — no backend changes needed, all required endpoints already exist.
- The new client wizard (`/clients/new/page.tsx`) — auditor assignment does not belong there, only after client is created.
