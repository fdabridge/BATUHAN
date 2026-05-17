# Augment Task: Fix Auditor PDF Extraction + Manual Entry Fallback

## What Is Happening

The auditor registration slide-over (`frontend/src/app/(app)/auditors/page.tsx`) uploads a PDF to `POST /auditors/ingest`. The backend uses Claude to extract profile fields from the document text and return JSON. The problem is Claude occasionally returns malformed JSON (trailing commas, unescaped newline characters inside strings, etc.), causing a Python `json.JSONDecodeError` which surfaces in the UI as a red error message like "Expecting ',' delimiter: line 162 column 6".

## Backend Fix Already Applied

Two changes have already been made to the backend that should fix the JSON parsing:

**`backend/requirements.txt`** — added `json-repair==0.30.3`

**`backend/auditors/extractor.py`** — the JSON parsing section now uses:
```python
from json_repair import repair_json
result = json.loads(repair_json(raw))
```

These changes are committed. The backend will rebuild on Railway with the new package. **Do not revert these changes.**

## What Still Needs To Be Done

### Task 1 — Verify the extraction error is properly surfaced in the UI

In `frontend/src/app/(app)/auditors/page.tsx`, when `POST /auditors/ingest` returns a 422 or 500, the error message shown to the user is currently the raw Python exception string (e.g., "Expecting ',' delimiter: line 162..."). This is not user-friendly.

The backend returns `{"detail": "...error message..."}` on failure. Update the error display in the `AddAuditorPanel` component to show a friendly message:

**If extraction fails, show:**
> "Could not extract fields from this document. You can fill in the details manually below."

And immediately transition to **Step 2 (the manual entry form)** with all fields blank — so the user can type the information themselves instead of being stuck.

### Task 2 — Add a "Skip upload / enter manually" option

In Step 1 (the file upload step), add a text link below the file picker:
> "Skip upload and enter details manually →"

Clicking this skips the extraction entirely and goes straight to Step 2 with a blank form. This is important for cases where there is no document, or the document is in a format Claude struggles with.

### Task 3 — Improve the Step 2 preview form

The current Step 2 form shows name, role, email, EA codes, and a qualifications table. Make the following improvements:

**3a. Add `accreditation_body` to the qualifications table.**

Each qualification row should have three columns: Standard Code, Accreditation Body, Technical Depth. The `accreditation_body` field exists in `AuditorIngestResult` in `frontend/src/types/index.ts` (it may need to be added there if missing). The `POST /auditors/` endpoint accepts `standard_qualifications` as an array of `{standard_code, accreditation_body, technical_depth, experience_years}`.

**3b. Make EA codes user-friendly.**

Currently EA codes are comma-edited as a single string. Keep this as-is — it works fine.

**3c. Add an `active_since` date field.**

A simple `<input type="date">` for when the auditor joined the CB. Maps to `active_since` in the create payload.

**3d. Validation before saving.**

Before calling `POST /auditors/`, validate that at minimum:
- `name` is not empty
- At least one qualification exists with a `standard_code`

Show inline errors if these are missing.

## API Reference

### POST /auditors/ingest
- Multipart form-data, field name: `file`
- On success: returns JSON matching `AuditorIngestResult` type
- On failure: returns `{"detail": "error string"}` with 4xx/5xx status

### POST /auditors/
Request body shape (`AuditorCreateSchema`):
```json
{
  "name": "string",
  "email": "string or null",
  "phone": "string or null",
  "mobile": "string or null",
  "role": "Lead Auditor | Auditor | Technical Expert",
  "active_since": "YYYY-MM-DD or null",
  "ea_codes": ["29", "30"],
  "accreditation_bodies": ["UAF", "TURKAK"],
  "standard_qualifications": [
    {
      "standard_code": "QMS",
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
On success: returns the created auditor with HTTP 201. Invalidate `['auditors-dashboard']` and `['auditors-active']` React Query caches.

## Styling Rules

- Use existing Certiva green `#1A4731` for primary actions
- Error states: `text-red-500` + `border-red-300`
- "Skip" link: `text-sm text-certiva-primary underline cursor-pointer` 
- No new npm packages
- Keep all changes inside `frontend/src/app/(app)/auditors/page.tsx` and `frontend/src/types/index.ts` only

## Do Not Change

- `backend/auditors/extractor.py` — already fixed
- `backend/requirements.txt` — already updated
- Any other backend files
- Sidebar, Topbar, auth, api lib
