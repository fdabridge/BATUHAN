# Portal 57 — Stage Gate Timing Fix + FR.225 Empty Rows + FR.233 Field Population + FR.233 Upload Flow

## Context

Four issues were found during smoke testing that block the pipeline from completing correctly.
They span the backend gate logic, document packager, field maps, and the committee workflow.

---

## Issue 1 — Stage 2 gate fires at wrong time: checks stage_2 docs before they exist

### Root cause

`backend/audit_set/workflow_router.py`, function `_assert_stage_entry_gate`, handles
both stages in a single function:

```python
def _assert_stage_entry_gate(db, audit_set_id, stage):
    if stage == "stage_1":
        # checks FR.222, Stage 1 FR.224s, Stage 1 FR.223

    # Always runs (for BOTH stage_1 and stage_2):
    team_infos = _stage_docs(db, audit_set_id, "team_info", stage, ...)
    plans      = _stage_docs(db, audit_set_id, "audit_plan", stage, ...)
```

When `to_status == "stage2_in_progress"`, `_assert_stage_entry_gate(db, id, "stage_2")`
is called. This checks that Stage 2 FR.224 (team_info) and FR.223 (audit_plan) already
exist and are signed. But those documents are prepared and uploaded **during**
`stage2_in_progress`, not before it. They cannot exist before Stage 2 starts. The gate
always fails, making it impossible to begin Stage 2.

The gate for `stage1_in_progress` (checking stage_1 docs) is correct and should remain.
The gate for `stage2_in_progress` (checking stage_2 docs) must be removed.

The caller in `update_workflow_status`:

```python
if to_status == "stage1_in_progress":
    _assert_stage_entry_gate(db, audit_set_id, "stage_1")
elif to_status == "stage2_in_progress":
    _assert_stage_entry_gate(db, audit_set_id, "stage_2")   # ← REMOVE THIS
```

### What the stage2_in_progress gate SHOULD check

The CM clicks "Stage 1 appropriate — Begin Stage 2". At that moment, Stage 1 must
be genuinely complete. The correct gate checks Stage 1 outcome documents:

- Stage 1 FR.218 is signed (all required slots filled)
- Stage 1 FR.222 exists (already verified by stage1_in_progress gate)
- All Stage 1 FR.224s are fully signed
- Stage 1 FR.231 is signed by the Lead Auditor (and Appointed Reviewer if applicable)

The Stage 2 FR.224/FR.223 check belongs to the `stage2_complete → committee_review`
gate (those docs must be done before committee review, not before Stage 2 begins).

### Fix — `backend/audit_set/workflow_router.py`

**Step 1:** Remove the `stage2_in_progress` gate call:

```python
# BEFORE
if to_status == "stage1_in_progress":
    _assert_stage_entry_gate(db, audit_set_id, "stage_1")
elif to_status == "stage2_in_progress":
    _assert_stage_entry_gate(db, audit_set_id, "stage_2")

# AFTER
if to_status == "stage1_in_progress":
    _assert_stage_entry_gate(db, audit_set_id, "stage_1")
# (no gate for stage2_in_progress — Stage 2 planning docs are created during the stage)
```

**Step 2:** Add a new `_assert_stage1_complete_gate` function that checks Stage 1
outcome documents are finished. Call it when `to_status == "stage2_in_progress"`:

```python
def _assert_stage1_complete_gate(db: Session, audit_set_id: str) -> None:
    """
    Gate for stage1_complete → stage2_in_progress.
    Verifies Stage 1 is genuinely finished before the CM opens Stage 2.

    Checks:
      • All Stage 1 FR.224 (team_info) documents are fully signed.
      • Stage 1 FR.231 (stage_report) is uploaded and fully signed.
    """
    failures: list[str] = []

    # Stage 1 FR.224s must all be signed
    team_infos = _stage_docs(db, audit_set_id, "team_info", "stage_1", include_null_stage=True)
    if team_infos and any(_unsigned_required_count(db, t.id) for t in team_infos):
        failures.append("Not all Stage 1 FR.224s are fully signed by their assigned auditors")

    # Stage 1 FR.231 (stage report) must exist and be signed
    stage1_reports = _stage_docs(db, audit_set_id, "stage_report", "stage_1", include_null_stage=True)
    if not stage1_reports:
        failures.append("Stage 1 FR.231 Stage Report has not been uploaded")
    elif any(_unsigned_required_count(db, r.id) for r in stage1_reports):
        failures.append("Stage 1 FR.231 Stage Report is not fully signed")

    if failures:
        raise HTTPException(409, "Gate not met: " + "; ".join(failures))
```

Then in `update_workflow_status`:

```python
if to_status == "stage1_in_progress":
    _assert_stage_entry_gate(db, audit_set_id, "stage_1")
elif to_status == "stage2_in_progress":
    _assert_stage1_complete_gate(db, audit_set_id)
```

**Note on document_type values:** Check which `document_type` string the system uses
for the Stage 1 report. In `committee_router.py` the FR.231 upload stores as
`"stage_report"`. Confirm by querying `AuditSetSharedDocument.document_type` values
in the existing code. If the string is different (e.g. `"fr231"` or `"stage1_report"`),
use the correct value. If unsure, make the gate soft: log a warning instead of failing
if zero stage_report docs are found (the FR.222 gate at stage1_in_progress already
caught the most critical check).

**Step 3:** Update the docstring in `_assert_stage_entry_gate` to clarify it only
handles `stage_1` entry:

```python
def _assert_stage_entry_gate(db: Session, audit_set_id: str, stage: str) -> None:
    """
    Portal 49b gate chain — checks before stage1_in_progress may start.

    stage1_in_progress requires:
      • FR.222 (audit_programme) fully signed (CB_PLANNER + CB_CERT_MANAGER)
      • ALL Stage 1 FR.224s (team_info) signed by their assigned auditors
      • FR.223 (audit_plan, Stage 1) signed by ORG_REP

    For stage2_in_progress, see _assert_stage1_complete_gate().
    Stage 2 planning documents (FR.224s, FR.223) are uploaded DURING stage2_in_progress,
    not before it begins.
    """
```

### Fix — `frontend/src/components/ui/WorkflowStatusBar.tsx`

Find the `stage1_complete` entry in `INITIAL_PANELS`. The `body` text currently reads:

```
'The Certification Manager reviews all Stage 1 work (FR.218, FR.222, FR.224s, FR.223,
FR.225, FR.230, FR.231). When satisfied, click "Stage 1 appropriate" to begin Stage 2.
Requires every Stage 2 FR.224 signed by its auditor and the Stage 2 FR.223 signed by
the organisation representative.'
```

Remove the sentence starting "Requires every Stage 2 FR.224…". The new `body`:

```typescript
stage1_complete: {
  heading: 'Stage 1 complete — Certification Manager review',
  body: 'The Certification Manager reviews all Stage 1 work (FR.218, FR.222, FR.224s, FR.223, FR.225, FR.230, FR.231). When satisfied, click "Stage 1 appropriate" to begin Stage 2.',
  cta: { label: 'Stage 1 appropriate — Begin Stage 2', nextStatus: 'stage2_in_progress', allowedRoles: ['admin', 'executive', 'certification_manager'] },
},
```

---

## Issue 2 — FR.225 Opening/Closing Meeting: org_attendees loop renders zero rows

### Root cause

`backend/audit_set/packager.py`, `_resolve_org_attendees()` (lines ~174–206).

The function correctly queries `PlatformUser` with `role="client", audit_set_id=audit_set.id`
and then queries `ClientOrgEmployee` with `client_user_id=client.id`. The FK chain is
correct. However, there are two failure modes:

1. **The `client_org_employees` table does not exist on Railway.** The table was added
   in Portal 49a and uses `Base.metadata.create_all`. If Railway's database was
   provisioned before this model was added and `create_all` was not re-run with the new
   table, the table won't exist. The function catches all exceptions silently and returns
   `[]`, which causes the docxtpl loop to produce zero rows.

2. **No employees are registered.** Even if the table exists, if the client hasn't added
   employees yet the list is empty and the template loop produces zero rows — the form
   looks unprofessional with no placeholder lines.

Additionally, the `sig_key` returned for FR.225 employees is:
```python
{"name": e.full_name, "role": e.role_title, "sig_key": f"ORG_EMP_{e.id}"}
```
But in Portal 49a / Portal 56, the viewer expects `ORG_OPENING_ORG_EMP_{uuid}` and
`ORG_CLOSING_ORG_EMP_{uuid}` as sig keys (with `OPENING`/`CLOSING` prefix). Verify
the FR.225 template's `{%tr for emp in org_attendees %}` placeholder uses `emp.sig_key`
and that the sig_key format matches what `viewer_router.py` `_assert_can_sign` expects.
If the template uses `[SIG:ORG_OPENING_ORG_EMP_{{emp.id}}]` style keys, the dict must
supply `emp.id` not a pre-built sig_key. Check and align them.

### Fix — `backend/audit_set/packager.py`

**Fix 1: Table existence guard**

In `create_tables()` in `db_models.py` (or wherever `Base.metadata.create_all` is
called), confirm the call uses `checkfirst=True`:

```python
Base.metadata.create_all(bind=engine, checkfirst=True)
```

If it already uses `checkfirst=True`, the issue is that `checkfirst=True` skips
existing tables but also creates missing ones — so the table should exist. If it is NOT
`checkfirst=True`, add it. Also add a `_safe_add_column`-style explicit check for the
table just to be safe:

```python
# After create_all, add explicit fallback:
try:
    engine.execute("SELECT 1 FROM client_org_employees LIMIT 1")
except Exception:
    try:
        # Table is missing despite create_all — create it explicitly
        Base.metadata.tables["client_org_employees"].create(bind=engine)
        logger.info("[DB] Explicitly created missing table: client_org_employees")
    except Exception as ex:
        logger.warning("[DB] Could not create client_org_employees: %s", ex)
```

**Fix 2: Blank placeholder fallback in `_resolve_org_attendees`**

After the employee query, if the result list is empty, inject 3 blank placeholder rows
so the FR.225 template loop renders empty signature lines:

```python
employees = (
    db.query(ClientOrgEmployee)
    .filter_by(client_user_id=client.id, is_active=True)
    .order_by(ClientOrgEmployee.created_at)
    .all()
)
if not employees:
    # No registered employees — inject blank rows so FR.225 has placeholder lines
    return [
        {"name": "", "role": "", "sig_key": f"ORG_OPENING_ORG_EMP_BLANK_{i}"}
        for i in range(3)
    ]
return [
    {
        "name":    e.full_name,
        "role":    e.role_title,
        "sig_key": f"ORG_OPENING_ORG_EMP_{e.id}",
    }
    for e in employees
]
```

**Fix 3: Verify sig_key prefix matches viewer**

Open `backend/audit_set/viewer_router.py` and find `_assert_can_sign`. Locate where
`ORG_OPENING_ORG_EMP_*` keys are handled. Confirm the prefix in the sig_key produced
by `_resolve_org_attendees` matches exactly. If the viewer checks for
`ORG_OPENING_ORG_EMP_` but the packager emits `ORG_EMP_`, fix `_resolve_org_attendees`
to emit the correct `ORG_OPENING_ORG_EMP_{e.id}` prefix (as shown in Fix 2 above).

---

## Issue 3 — FR.233 Review and Decision Form: standard fields not populated

### Current state

`backend/audit_set/field_maps.py` has `FR233_MAP` defined (lines ~317–341):

```python
FR233_MAP = {
    "plan_number":            (0, 0, 1),
    "company_name":           (0, 1, 1),
    "company_address":        (0, 2, 1),
    "standards_str":          (0, 3, 1),
    "ea_code":                (0, 4, 1),
    "audit_team_str":         (0, 6, 1),
    "stage_1_date":           (0, 7, 1),
    "stage_2_date":           (0, 7, 3),
    "stage_1_report_date":    (0, 8, 1),
    "stage_2_report_date":    (0, 8, 3),
    "decision_date":          (0, 9, 1),
    "scope_en":               (1, 1, 0),
    ...committee sig slots...
}
```

The map has the right keys, but the rendered FR.233 shows empty cells. This means
`fr233_generator.py` (or `resolver.py`) is not building the context dict that includes
these field values before calling `filler.py` to fill the table cells.

### Root cause candidates

Open `backend/audit_set/fr233_generator.py`. Look at `render_fr233_bytes(audit_set, db)`:

1. Does it call `build_base_context(audit_set, stage)` from `resolver.py`?
   If not, none of the standard fields (`company_name`, `ea_code`, etc.) are in scope.

2. Does it call `filler.fill_document(docx_bytes, FR233_MAP, context)` — passing both
   the map AND the context from `resolver`?

3. Does `resolver.py` `build_base_context` return keys matching `FR233_MAP`? Compare
   key names: if the resolver emits `"org_name"` but FR233_MAP uses `"company_name"`,
   the cell stays blank.

4. Check `audit_team_str`, `stage_1_date`, `stage_2_date`, `stage_1_report_date`,
   `stage_2_report_date`, `decision_date` — these may require a `stage` object.
   `render_fr233_bytes` may be calling `build_base_context` with no stage (or the wrong
   stage), so date fields come out empty.

### Fix — `backend/audit_set/fr233_generator.py`

Read the function. Typical fix:

```python
from audit_set.resolver import build_base_context, build_auditor_scope_strings
from audit_set.field_maps import FR233_MAP
from audit_set.filler import fill_document
from audit_set.db_models import AuditSetStage

def render_fr233_bytes(audit_set, db) -> bytes:
    # Get the stage objects to supply date fields
    stages_by_type = {s.stage_type: s for s in (audit_set.stages or [])}
    # Use stage_2 as the primary stage for FR.233 (committee decision is post-Stage 2)
    stage = stages_by_type.get("stage_2") or stages_by_type.get("stage_1")

    # Build the context the same way the packager does for every other document
    ctx = build_base_context(audit_set, stage)

    # Populate committee member name/EA fields from AuditSetCommitteeMember
    members = (
        db.query(AuditSetCommitteeMember)
        .filter_by(audit_set_id=audit_set.id)
        .order_by(AuditSetCommitteeMember.appointed_at)
        .all()
    )
    if members:
        chair = next((m for m in members if m.role == "decision_maker"), members[0])
        others = [m for m in members if m.id != chair.id]
        ctx["committee_chair_name"]   = chair.user_name
        ctx["committee_chair_ea"]     = ", ".join(chair.ea_codes_at_appointment or [])
        ctx["committee_member1_name"] = others[0].user_name if len(others) > 0 else ""
        ctx["committee_member1_ea"]   = ", ".join(others[0].ea_codes_at_appointment or []) if others else ""
        ctx["committee_member2_name"] = others[1].user_name if len(others) > 1 else ""
        ctx["committee_member2_ea"]   = ", ".join(others[1].ea_codes_at_appointment or []) if len(others) > 1 else ""

    # Load the blank FR.233 template
    template_path = _get_fr233_template_path(audit_set)
    with open(template_path, "rb") as f:
        docx_bytes = f.read()

    # Fill table cells
    filled = fill_document(docx_bytes, FR233_MAP, ctx)
    return filled
```

The exact implementation depends on what `render_fr233_bytes` currently does. Read the
file first, then align it with the pattern above. The key principle: FR.233 must go
through the same `build_base_context` + `fill_document(FR233_MAP)` pipeline that every
other document uses.

Also verify `resolver.py` `build_base_context` returns `"standards_str"` (not
`"standard"` or `"standards"`). Check with:
```python
grep -n "standards_str\|audit_team_str\|stage_1_date\|stage_2_date" backend/audit_set/resolver.py
```
If the resolver uses different key names, either add aliases in `build_base_context` or
update `FR233_MAP` to match the actual keys. Prefer updating the map to match the resolver
rather than adding aliases.

---

## Issue 4 — FR.233: committee should upload the completed document, not generate it

### Current behavior

`FR233Panel.tsx` has a "Generate FR.233" button that calls
`POST /audit-sets/{id}/fr233/generate`. This generates FR.233 from the template using
the packager. But FR.233 is a document the committee fills out offline — they should
upload their completed copy, then sign it online through the viewer.

### Target behavior

1. CB Planner / Admin uploads a completed FR.233 (PDF or DOCX) — no template generation.
2. The uploaded document is stored as a `SharedDocument` with
   `document_type = "committee_decision"` (or keep `"fr233"` — keep consistent with
   existing `AuditSetFR233Record.document_id` linkage).
3. After upload, committee members and then the Certification Manager sign it online
   via the viewer — same signing flow as all other shared docs.
4. The `FR233Panel.tsx` shows the uploaded document and signing status instead of a
   generate button.

### Fix — `backend/audit_set/committee_router.py`

**Keep the existing `POST /fr233/generate` endpoint.** Do not delete it — it may be
useful for testing and for cases where the committee wants a pre-filled template as a
starting point. But mark it as secondary.

**Add a new `POST /fr233/upload` endpoint** that accepts a file upload:

```python
from fastapi import UploadFile, File
import shutil, os
from datetime import datetime

@router.post("/{audit_set_id}/fr233/upload")
async def upload_fr233(
    audit_set_id: str,
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
    current_user: PlatformUser = Depends(get_current_user),
):
    """
    Committee uploads the completed FR.233 Review & Decision Form.
    Stores it as a SharedDocument and upserts the AuditSetFR233Record.
    After upload, committee members sign online via the viewer.
    """
    if current_user.role not in {"admin", "planner", "executive", "certification_manager"}:
        raise HTTPException(403, "Not authorized to upload FR.233")

    audit_set = db.query(AuditSet).filter_by(id=audit_set_id).first()
    if not audit_set:
        raise HTTPException(404, "Audit set not found")

    # Validate file type
    allowed_exts = {".pdf", ".docx"}
    ext = os.path.splitext(file.filename or "")[1].lower()
    if ext not in allowed_exts:
        raise HTTPException(400, "Only PDF and DOCX files are accepted for FR.233")

    settings = get_settings()
    out_dir = os.path.join(settings.storage_base_path, "shared_docs", audit_set_id)
    os.makedirs(out_dir, exist_ok=True)
    out_filename = f"FR233_{audit_set.plan_number or audit_set_id}{ext}"
    out_path = os.path.join(out_dir, out_filename)

    contents = await file.read()
    with open(out_path, "wb") as f:
        f.write(contents)

    # Upsert SharedDocument
    record = db.query(AuditSetFR233Record).filter_by(audit_set_id=audit_set_id).first()
    doc = None
    if record and record.document_id:
        doc = db.query(AuditSetSharedDocument).filter_by(id=record.document_id).first()
    if doc is None:
        doc = AuditSetSharedDocument(
            audit_set_id=audit_set_id,
            label=f"FR.233 Review & Decision — {audit_set.plan_number or ''}".strip(" —"),
            document_type="fr233",
            file_path=out_path,
            direction="cb_to_client",
            status="released",
            released_by=current_user.id,
            released_at=datetime.utcnow(),
        )
        db.add(doc)
        db.flush()
    else:
        doc.file_path = out_path
        doc.released_at = datetime.utcnow()
        # Clear any stale PDF cache
        pdf_path = os.path.splitext(out_path)[0] + ".pdf"
        if os.path.exists(pdf_path):
            try: os.remove(pdf_path)
            except Exception: pass
        from audit_set.db_models import DocumentSignatureField
        db.query(DocumentSignatureField).filter_by(docx_path=os.path.abspath(out_path)).delete()

    if record is None:
        record = AuditSetFR233Record(
            audit_set_id=audit_set_id, document_id=doc.id, status="signing",
        )
        db.add(record)
    else:
        record.document_id = doc.id
        record.status = "signing"

    # Advance workflow to committee_review if still at stage2_complete
    if audit_set.workflow_status in {"stage2_complete", "stage2_in_progress"}:
        old = audit_set.workflow_status
        audit_set.workflow_status = "committee_review"
        from audit_set.db_models import AuditSetStatusEvent
        db.add(AuditSetStatusEvent(
            audit_set_id=audit_set_id, from_status=old, to_status="committee_review",
            triggered_by=current_user.id, notes="FR.233 uploaded; committee review opened",
        ))

    db.commit()
    return {
        "uploaded":     True,
        "document_id":  doc.id,
        "fr233_status": record.status,
    }
```

### Fix — `frontend/src/components/ui/FR233Panel.tsx`

Replace the "Generate FR.233" button with an "Upload FR.233" file input + button.
Keep the "Re-generate" option available as a secondary action (hidden behind a smaller
link/button labeled "Generate from template instead") for admin use.

**New upload state:**

```typescript
const [uploadFile, setUploadFile]   = useState<File | null>(null)
const fileInputRef = useRef<HTMLInputElement>(null)
```

**Replace the `generate()` function with `upload()`:**

```typescript
async function upload() {
  if (!uploadFile) return
  setBusy(true); setError('')
  try {
    const form = new FormData()
    form.append('file', uploadFile)
    await api.post(`/audit-sets/${auditSetId}/fr233/upload`, form, {
      headers: { 'Content-Type': 'multipart/form-data' },
    })
    setUploadFile(null)
    if (fileInputRef.current) fileInputRef.current.value = ''
    await load()
  } catch (e: unknown) {
    const detail = (e as { response?: { data?: { detail?: string } } })?.response?.data?.detail
    setError(detail || 'Upload failed')
  } finally {
    setBusy(false)
  }
}
```

**New button area in the JSX** (replace the existing `canGenerate` button block):

```tsx
{canGenerate && status === 'pending' && (
  <div className="flex items-center gap-2">
    <input
      ref={fileInputRef}
      type="file"
      accept=".pdf,.docx"
      className="hidden"
      id={`fr233-upload-${auditSetId}`}
      onChange={e => setUploadFile(e.target.files?.[0] ?? null)}
    />
    <label
      htmlFor={`fr233-upload-${auditSetId}`}
      className="cursor-pointer rounded-lg border border-gray-300 px-3 py-1.5 text-xs font-medium text-gray-600 hover:bg-gray-50"
    >
      {uploadFile ? uploadFile.name : 'Choose FR.233 file…'}
    </label>
    {uploadFile && (
      <button
        type="button"
        onClick={upload}
        disabled={busy}
        className="rounded-lg bg-[#1A4731] px-3 py-1.5 text-xs font-medium text-white hover:bg-[#143b27] disabled:opacity-40"
      >
        {busy ? 'Uploading…' : 'Upload FR.233'}
      </button>
    )}
  </div>
)}
{canGenerate && status !== 'pending' && (
  <button
    type="button"
    onClick={generate}
    disabled={busy}
    className="rounded-lg border border-gray-300 px-3 py-1.5 text-xs font-medium text-gray-400 hover:bg-gray-50 disabled:opacity-40"
    title="Overwrite with template-generated FR.233 (admin use)"
  >
    {busy ? 'Generating…' : 'Re-generate from template'}
  </button>
)}
```

Keep the existing `generate()` function for the re-generate case. Add `useRef` import.

**Empty state message:** When `status === 'pending'`, change the empty-state div inside
the panel card from "Appoint at least one committee member to enable FR.233 generation."
to:

```tsx
<div className="px-4 py-6 text-center text-xs text-gray-400">
  Upload the completed FR.233 document above to begin committee signing.
</div>
```

And remove the `members.length === 0` conditional that was gating the card on having
members — the upload should be available as soon as the workflow reaches
`stage2_complete`, regardless of whether committee members are appointed yet.

---

## Files to change

| File | Change |
|------|--------|
| `backend/audit_set/workflow_router.py` | Remove `_assert_stage_entry_gate(db, id, "stage_2")` call; add `_assert_stage1_complete_gate()` function and call it for `stage2_in_progress` |
| `frontend/src/components/ui/WorkflowStatusBar.tsx` | Remove Stage 2 doc requirement sentence from `stage1_complete` body text |
| `backend/audit_set/packager.py` | Fix `_resolve_org_attendees()`: verify sig_key prefix matches viewer; add 3 blank placeholder rows when `employees` list is empty |
| `backend/audit_set/db_models.py` | Ensure `Base.metadata.create_all(bind=engine, checkfirst=True)` so `client_org_employees` table is created if missing on Railway |
| `backend/audit_set/fr233_generator.py` | Ensure `render_fr233_bytes` calls `build_base_context(audit_set, stage)` and `fill_document(FR233_MAP, ctx)` — same pipeline as all other documents |
| `backend/audit_set/committee_router.py` | Add `POST /{audit_set_id}/fr233/upload` endpoint — accepts PDF/DOCX, stores as SharedDocument, upserts AuditSetFR233Record |
| `frontend/src/components/ui/FR233Panel.tsx` | Replace "Generate FR.233" primary button with file input + upload button; keep generate as secondary "Re-generate from template" link |

---

## Verification after deploy

### Issue 1 (gate timing)
1. Log in as Certification Manager. Find an audit set at `stage1_complete`.
2. Click "Stage 1 appropriate — Begin Stage 2".
3. Expect: transition succeeds (previously it failed with "Gate not met: No FR.224 team-info
   documents exist for stage_2").
4. Confirm workflow status advances to `stage2_in_progress`.

### Issue 2 (FR.225 empty rows)
1. Create a test client account and add 2 employees via `/client/employees`.
2. Trigger FR.225 generation (have Lead Auditor upload or re-generate the audit package).
3. Open FR.225 in the viewer. Expect: 2 rows with employee names and signature slots.
4. Remove all employees and re-generate. Expect: 3 blank placeholder rows (not zero rows).

### Issue 3 (FR.233 field population)
1. Navigate to an audit set at `committee_review`.
2. Open FR.233 in the viewer (or download the DOCX).
3. Expect: organization name, address, standards, EA code, dates are all filled in.
   Previously all cells were blank.

### Issue 4 (FR.233 upload flow)
1. Navigate to an audit set at `stage2_complete`.
2. In the FR.233 panel, select a completed FR.233 PDF from your local machine.
3. Click "Upload FR.233". Expect: file uploads, document ID appears, status becomes
   `signing`, workflow advances to `committee_review`.
4. Open the document in the viewer. Expect: committee member signature slots are present
   and signable.
5. "Generate FR.233" button should NOT be shown as the primary action. A secondary
   "Re-generate from template" link is acceptable for admin/planner use.

---

## Commit message

```
Portal 57: fix stage gate timing, FR.225 empty rows, FR.233 fields + upload flow

Issue 1 — stage gate timing:
- workflow_router: remove incorrect _assert_stage_entry_gate("stage_2") call
  for stage2_in_progress; Stage 2 FR.224/FR.223 cannot exist before Stage 2 begins
- Add _assert_stage1_complete_gate() checking Stage 1 FR.224s + FR.231 are signed
- WorkflowStatusBar: remove Stage 2 doc requirement from stage1_complete description

Issue 2 — FR.225 org attendees:
- packager _resolve_org_attendees: add 3 blank fallback rows when no employees registered
- packager: verify ORG_OPENING_ORG_EMP_ sig_key prefix aligns with viewer expectations
- db_models: confirm create_all(checkfirst=True) so client_org_employees table is
  created on Railway if it was missing

Issue 3 — FR.233 empty fields:
- fr233_generator: call build_base_context(audit_set, stage) and fill_document(FR233_MAP)
  same pipeline as all other documents; committee member names/EA injected from DB

Issue 4 — FR.233 upload flow:
- committee_router: add POST /{id}/fr233/upload endpoint (PDF/DOCX); stores as
  SharedDocument, upserts AuditSetFR233Record, advances to committee_review
- FR233Panel: replace primary "Generate" button with file picker + upload button;
  keep generate as secondary admin action
```
