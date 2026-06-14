# Portal 51 — FR.218 Reviewer Logic: Conditional Signing + FSMS/ISMS Appointment

## Background

FR.218 (Certification Application Review Form) has three signature columns in its DOCX template:
- **Planning Officer** `[SIG:CB_PLANNER]` — always required
- **Reviewer Auditor/Technical Expert** `[SIG:CB_REVIEWER]` — **only for FSMS and ISMS audits**
- **Certification Manager** `[SIG:CB_CERT_MANAGER]` — always required

Currently there are **four bugs**:

### Bug 1 — `_needs_reviewer()` never returns True
The function checks for `"22000"` or `"27001"` in the joined standard string, but the `audit_sets.standards` JSON column stores **codes** (`"FSMS"`, `"ISMS"`, `"QMS"`), not ISO numbers. So `_needs_reviewer` always returns False.

### Bug 2 — CB_REVIEWER slot always shown
`DOC_SIG_SLOTS["fr218_review"]` is always `["cb_planner", "cb_cert_manager"]` regardless of standards. No `cb_reviewer` is ever seeded. But the DOCX template always has `[SIG:CB_REVIEWER]`, so the viewer renders it as "Awaiting signature" even for ISO 9001 — there's no DB record, so nothing gates it properly.

### Bug 3 — Certification Manager can't sign `cb_cert_manager` slots
`_shared_slot_eligible("cb_cert_manager")` returns `role in ("admin", "executive")`. The actual DB role is `"certification_manager"`. So certification managers can never sign CB_CERT_MANAGER slots on any document.

Also `CB_ROLES = {"admin", "planner", "officer", "executive", "gm"}` omits `"certification_manager"` — this blocks cert managers from several CB-role checks throughout the viewer.

### Bug 4 — No FSMS/ISMS reviewer appointment flow
For FSMS/ISMS audits, an auditor must be appointed as the **Application Reviewer** at audit-set creation/edit time. This reviewer must:
- Be stored on the audit set as `fr218_reviewer_id`
- See the FR.218 document in their auditor portal
- Be the only auditor who can sign the `CB_REVIEWER` slot on FR.218

## What To Change

---

### 1. `backend/audit_set/db_models.py`

**Add `fr218_reviewer_id` and `fr218_reviewer_name` to `AuditSet`.**

In the `AuditSet` class, after the `application_data` column (~line 163), add:

```python
# ── FR.218 Application Reviewer (FSMS/ISMS only) ─────────────────────────────
# auditor_id (FK to auditors.auditors.id) of the appointed application reviewer.
# Required when any standard in `standards` is FSMS or ISMS.
fr218_reviewer_id   = Column(String, nullable=True)
fr218_reviewer_name = Column(String, nullable=True)
```

**In `create_tables()`**, add both migration columns:

```python
_safe_add_column("audit_sets", "fr218_reviewer_id VARCHAR")
_safe_add_column("audit_sets", "fr218_reviewer_name VARCHAR")
```

---

### 2. `backend/audit_set/documents_router.py`

#### 2a. Fix `_needs_reviewer()`

Replace the existing function:

```python
def _needs_reviewer(audit_set: AuditSet) -> bool:
    """FSMS/ISMS audits require a committee reviewer slot on FR.218 and stage reports.

    Standards are stored as codes ("FSMS", "ISMS") or legacy ISO strings ("ISO 22000").
    """
    standards = audit_set.standards or []
    if isinstance(standards, str):
        standards = [standards]
    joined = " ".join(str(s).upper() for s in standards)
    # Match code-style ("FSMS", "ISMS") and legacy ISO-number style ("22000", "27001")
    return any(
        kw in joined
        for kw in ("FSMS", "ISMS", "22000", "27001")
    )
```

#### 2b. Fix fr218_review slot seeding

In the `release_document` endpoint, the slot-seeding block currently reads:

```python
slot_labels = list(DOC_SIG_SLOTS.get(document_type, []))
if document_type in ("stage1_report", "stage2_report") and _needs_reviewer(audit_set):
    slot_labels.append("reviewer")
```

Replace with:

```python
slot_labels = list(DOC_SIG_SLOTS.get(document_type, []))
if document_type in ("stage1_report", "stage2_report") and _needs_reviewer(audit_set):
    slot_labels.append("reviewer")
if document_type == "fr218_review" and _needs_reviewer(audit_set):
    # Insert cb_reviewer between cb_planner (idx 0) and cb_cert_manager (idx 1)
    slot_labels = ["cb_planner", "cb_reviewer", "cb_cert_manager"]
```

#### 2c. Add fr218_review to AUDITOR_VISIBLE_TYPES

So the appointed reviewer auditor can see the document from their portal:

```python
AUDITOR_VISIBLE_TYPES = {
    "audit_plan", "meeting_form", "nc_form",
    "stage1_report", "stage2_report", "certificate", "audit_upload",
    "fr218_review",   # visible to the appointed application reviewer (FSMS/ISMS only)
}
```

---

### 3. `backend/audit_set/viewer_router.py`

#### 3a. Fix `CB_ROLES` — add `certification_manager`

```python
CB_ROLES = {"admin", "planner", "officer", "executive", "gm", "certification_manager"}
```

#### 3b. Fix `_shared_slot_eligible` — fix `cb_cert_manager` and add `cb_reviewer` for fr218

Replace the existing `_shared_slot_eligible` function:

```python
def _shared_slot_eligible(
    role_label: str,
    doc: AuditSetSharedDocument,
    current_user: PlatformUser,
    db: Session,
) -> bool:
    """True if current_user may claim an unassigned shared-doc signature slot."""
    role = current_user.role
    if role_label == "gm":
        return role in ("gm", "admin")
    if role_label == "cb_planner":
        return role in ("planner", "admin")
    if role_label == "cb_cert_manager":
        # Bug fix: include "certification_manager" (was incorrectly "executive" only)
        return role in ("admin", "certification_manager", "executive")
    if role_label == "cb_reviewer":
        # For FR.218: only the appointed fr218_reviewer auditor may sign this slot.
        # For audit reports: fall through to committee membership check below.
        if doc.document_type == "fr218_review":
            if role == "admin":
                return True
            if role != "auditor" or not current_user.auditor_id:
                return False
            audit_set = db.query(AuditSet).filter_by(id=doc.audit_set_id).first()
            return audit_set is not None and audit_set.fr218_reviewer_id == current_user.auditor_id
        # For other doc types: fall through (committee membership checked separately)
        return False
    if role_label == "org_rep":
        return role == "client" and current_user.audit_set_id == doc.audit_set_id
    if role_label == "assigned_auditor":
        return (
            role == "auditor"
            and current_user.auditor_id is not None
            and doc.assigned_auditor_id == current_user.auditor_id
        )
    if role_label == "lead_auditor":
        if role == "admin":
            return True
        if role != "auditor" or not current_user.auditor_id:
            return False
        stage = _find_stage(db, doc.audit_set_id, doc.stage_type)
        return stage is not None and stage.lead_auditor_id == current_user.auditor_id
    if role_label == "reviewer":
        member = db.query(AuditSetCommitteeMember).filter_by(
            audit_set_id=doc.audit_set_id, user_id=current_user.id, role="reviewer",
        ).first()
        return member is not None
    return False
```

#### 3c. Add `AuditSet` to the imports in viewer_router if not already present

The `_shared_slot_eligible` fix above queries `AuditSet`. Confirm `AuditSet` is imported from `audit_set.db_models`. If not, add it.

---

### 4. `backend/audit_set/` — New endpoint: Set FR.218 Reviewer

Find the router file where `PATCH /audit-sets/{audit_set_id}` or audit-set update endpoints live (likely `audit_set_router.py` or `router.py` inside the `audit_set/` folder). Add a new endpoint:

```python
class FR218ReviewerUpdate(BaseModel):
    fr218_reviewer_id:   Optional[str] = None
    fr218_reviewer_name: Optional[str] = None

@router.patch("/{audit_set_id}/fr218-reviewer", status_code=200)
def set_fr218_reviewer(
    audit_set_id: str,
    body: FR218ReviewerUpdate,
    db: Session = Depends(get_db),
    current_user: PlatformUser = Depends(require_cb_user),
):
    """Set (or clear) the appointed Application Reviewer for FR.218.
    Only applicable when the audit set has FSMS or ISMS standards.
    """
    audit_set = db.query(AuditSet).filter_by(id=audit_set_id).first()
    if not audit_set:
        raise HTTPException(404, "Audit set not found")
    audit_set.fr218_reviewer_id   = body.fr218_reviewer_id
    audit_set.fr218_reviewer_name = body.fr218_reviewer_name
    db.commit()
    return {"fr218_reviewer_id": audit_set.fr218_reviewer_id,
            "fr218_reviewer_name": audit_set.fr218_reviewer_name}
```

If `require_cb_user` doesn't exist, use whatever dependency is already used for planner/admin-only endpoints in this router.

---

### 5. Audit Set API response — expose `fr218_reviewer_id` and `fr218_reviewer_name`

Find where the audit set detail response is serialized (the schema or the response dict in the GET endpoint). Add `fr218_reviewer_id` and `fr218_reviewer_name` to the response so the frontend can read them.

---

### 6. Frontend — Audit Set Detail Page: FR.218 Reviewer Appointment

**File: `frontend/src/app/(app)/clients/[id]/page.tsx`**

The detail page shows audit set info and has editable fields. Add a section that appears **only when `standards` includes `"FSMS"` or `"ISMS"`**:

#### 6a. In the `AuditSetDetail` type/interface, add:

```typescript
fr218_reviewer_id:   string | null
fr218_reviewer_name: string | null
```

#### 6b. Add a helper to detect if FR.218 reviewer is needed:

```typescript
function needsFr218Reviewer(standards: string[]): boolean {
  return standards.some(s => ['FSMS', 'ISMS'].includes(s))
}
```

#### 6c. Add reviewer appointment UI

Near the section where auditor assignments, stages, or shared documents are shown, render:

```tsx
{needsFr218Reviewer(auditSet.standards ?? []) && (
  <div className="mt-4 rounded-xl border bg-white p-4">
    <h3 className="mb-2 text-sm font-semibold text-gray-700">
      Application Reviewer (FR.218) — Required for FSMS/ISMS
    </h3>
    <p className="mb-3 text-xs text-gray-500">
      Appoint the auditor/technical expert who will review the application
      and sign FR.218. They will see the document in their auditor portal.
    </p>
    <FR218ReviewerPicker
      auditSetId={auditSet.id}
      currentReviewerId={auditSet.fr218_reviewer_id}
      currentReviewerName={auditSet.fr218_reviewer_name}
      onSaved={(id, name) => setAuditSet(prev => prev
        ? { ...prev, fr218_reviewer_id: id, fr218_reviewer_name: name }
        : prev
      )}
    />
  </div>
)}
```

#### 6d. Implement `FR218ReviewerPicker` component

Create a small inline component (or put it inline in the page) that:
1. Fetches `GET /auditors` to get the auditor list
2. Renders a `<select>` with all auditors
3. On change, calls `PATCH /audit-sets/{id}/fr218-reviewer` with `{ fr218_reviewer_id, fr218_reviewer_name }`
4. Shows a success confirmation

```tsx
function FR218ReviewerPicker({
  auditSetId, currentReviewerId, currentReviewerName, onSaved,
}: {
  auditSetId: string
  currentReviewerId: string | null
  currentReviewerName: string | null
  onSaved: (id: string | null, name: string | null) => void
}) {
  const [auditors, setAuditors] = useState<{ id: string; name: string }[]>([])
  const [selected, setSelected] = useState(currentReviewerId ?? '')
  const [saving, setSaving] = useState(false)
  const [msg, setMsg] = useState('')

  useEffect(() => {
    api.get('/auditors').then(r => setAuditors(r.data)).catch(() => {})
  }, [])

  async function save() {
    setSaving(true)
    try {
      const aud = auditors.find(a => a.id === selected) ?? null
      await api.patch(`/audit-sets/${auditSetId}/fr218-reviewer`, {
        fr218_reviewer_id:   aud?.id ?? null,
        fr218_reviewer_name: aud?.name ?? null,
      })
      onSaved(aud?.id ?? null, aud?.name ?? null)
      setMsg('Saved')
    } catch {
      setMsg('Error saving')
    } finally {
      setSaving(false)
    }
  }

  return (
    <div className="flex items-center gap-3">
      <select
        value={selected}
        onChange={e => setSelected(e.target.value)}
        className="rounded-lg border px-3 py-1.5 text-sm focus:outline-none focus:ring-2 focus:ring-[#1A4731]/30"
      >
        <option value="">— Select reviewer —</option>
        {auditors.map(a => (
          <option key={a.id} value={a.id}>{a.name}</option>
        ))}
      </select>
      <button
        type="button"
        onClick={save}
        disabled={saving}
        className="rounded-lg bg-[#1A4731] px-3 py-1.5 text-xs font-medium text-white disabled:opacity-40"
      >
        {saving ? 'Saving…' : 'Assign'}
      </button>
      {currentReviewerName && (
        <span className="text-xs text-gray-500">Current: {currentReviewerName}</span>
      )}
      {msg && <span className="text-xs text-green-600">{msg}</span>}
    </div>
  )
}
```

---

### 7. Frontend — Auditor Portal: Show FR.218 when appointed as reviewer

**File: `frontend/src/app/(auditor)/auditor/audit/[id]/page.tsx`**

The auditor portal shows an audit assignment. For FSMS/ISMS audits where this auditor is the appointed reviewer, they need to see the FR.218 document.

#### 7a. Add `fr218_reviewer_id` to `AssignmentDetail` interface:

```typescript
fr218_reviewer_id: string | null
```

#### 7b. Add a Documents tab section for FR.218

In the Documents tab rendering (wherever audit documents are shown), check if the current auditor is the fr218 reviewer:

```tsx
{assignment.fr218_reviewer_id === currentAuditorId && (
  <div className="mt-4 rounded-xl border border-blue-200 bg-blue-50 p-4">
    <h3 className="mb-2 text-sm font-semibold text-blue-800">
      Application Review (FR.218) — Your Signature Required
    </h3>
    <p className="text-xs text-blue-600 mb-3">
      You are appointed as the Application Reviewer for this FSMS/ISMS audit.
      Please review and sign FR.218 after the Planning Officer has signed.
    </p>
    <FR218ReviewerDocumentView auditSetId={assignment.id} />
  </div>
)}
```

#### 7c. Implement `FR218ReviewerDocumentView`

A small component that:
1. Fetches `GET /audit-sets/{auditSetId}/documents` 
2. Filters for `document_type === "fr218_review"`
3. If found, shows an "Open to Sign" link to `/auditor/viewer/shared_doc/{doc.id}`
4. If not yet uploaded, shows "Not yet uploaded by the CB"

```tsx
function FR218ReviewerDocumentView({ auditSetId }: { auditSetId: string }) {
  const [doc, setDoc] = useState<{ id: string; label: string; status: string } | null>(null)
  const [loading, setLoading] = useState(true)

  useEffect(() => {
    api.get(`/audit-sets/${auditSetId}/documents`)
      .then(r => {
        const fr218 = (r.data as { id: string; label: string; document_type: string; status: string }[])
          .find(d => d.document_type === 'fr218_review')
        setDoc(fr218 ?? null)
      })
      .finally(() => setLoading(false))
  }, [auditSetId])

  if (loading) return <p className="text-xs text-gray-400">Loading…</p>
  if (!doc) return <p className="text-xs text-gray-400">FR.218 not yet uploaded by the CB.</p>

  return (
    <a
      href={`/auditor/viewer/shared_doc/${doc.id}`}
      className="inline-block rounded-lg bg-blue-700 px-3 py-1.5 text-xs font-medium text-white hover:bg-blue-800"
    >
      Open FR.218 to Review & Sign
    </a>
  )
}
```

---

### 8. Viewer frontend — CB_REVIEWER slot on FR.218 for non-FSMS/ISMS

**File: `frontend/src/components/viewer/` (wherever signature slot overlays are rendered)**

When rendering a `CB_REVIEWER` signature slot on a `shared_doc` of type `fr218_review`, and the slot status is "pending" with NO `AuditDocumentSignature` record (slot count = 0), the viewer should render it as **"Not Required"** (grey, non-interactive) rather than "Awaiting signature" (amber).

Look for where the viewer fetches slot statuses and renders signature overlays. Add a check:

```typescript
// If document is fr218_review and CB_REVIEWER has no DB slot (status === "pending"
// but the reason is "not applicable for this standard"), show it as N/A.
if (sigKey === 'CB_REVIEWER' && documentType === 'shared_doc' && slotStatus === 'pending') {
  // Check if there's actually a slot record. If the backend returned no slot record
  // for this sig_key, it means the standard doesn't require a reviewer.
  // The backend already returns status="pending" for missing slots.
  // To distinguish "missing slot" vs "slot exists but waiting": the backend should
  // return a special status — see backend fix below.
}
```

**Backend enhancement for this**: In `_check_slot_status` for shared_doc (viewer_router.py), when the `AuditDocumentSignature` lookup returns None for a slot on an `fr218_review` document, return a special status `"not_applicable"` instead of `"pending"`:

Find the shared_doc slot status section in `_check_slot_status`. After the `sig_record` lookup, before returning `_result("pending")`, add:

```python
if sig_record is None:
    # No DB slot seeded for this sig_key on this document.
    # For fr218_review CB_REVIEWER: this means FSMS/ISMS reviewer not required.
    if doc and doc.document_type == "fr218_review" and role_label == "cb_reviewer":
        return _result("not_applicable")
    return _result("pending")
```

Then in the frontend viewer, render `"not_applicable"` slots with grey styling and "Not required for this standard" label.

---

## Commit Message

```
Portal 51: FR.218 reviewer — conditional slots, FSMS/ISMS appointment, cert-manager role fix

- Fix _needs_reviewer() to match standard codes (FSMS/ISMS) not just ISO numbers
- Seed cb_reviewer slot on fr218_review only when FSMS/ISMS standard present
- Add fr218_reviewer_id/name to AuditSet model + PATCH endpoint to set it
- Fix _shared_slot_eligible: certification_manager can now sign cb_cert_manager
- Fix CB_ROLES: add certification_manager so cert managers pass CB role checks
- CB_REVIEWER on fr218_review: only fr218_reviewer auditor can sign
- FR.218 added to AUDITOR_VISIBLE_TYPES so reviewer auditor can see it
- Viewer: return "not_applicable" for CB_REVIEWER on non-FSMS/ISMS fr218_review
- Frontend: FR.218 reviewer picker in audit set detail (shown only for FSMS/ISMS)
- Frontend: auditor portal shows FR.218 + sign link when appointed as reviewer
```

## Files Changed Summary

| File | Change |
|------|--------|
| `backend/audit_set/db_models.py` | Add `fr218_reviewer_id`, `fr218_reviewer_name` to `AuditSet`; add `_safe_add_column` migration calls |
| `backend/audit_set/documents_router.py` | Fix `_needs_reviewer()` for codes; fix fr218 slot seeding; add `fr218_review` to `AUDITOR_VISIBLE_TYPES` |
| `backend/audit_set/viewer_router.py` | Fix `CB_ROLES`; fix `cb_cert_manager` eligibility; add `cb_reviewer` fr218 logic; add `"not_applicable"` status for missing fr218 reviewer slot |
| `backend/audit_set/[router].py` | Add `PATCH /{id}/fr218-reviewer` endpoint |
| `backend/audit_set/[schema].py` | Add `fr218_reviewer_id`, `fr218_reviewer_name` to audit set response schema |
| `frontend/src/app/(app)/clients/[id]/page.tsx` | Add FR.218 reviewer picker (FSMS/ISMS only) |
| `frontend/src/app/(auditor)/auditor/audit/[id]/page.tsx` | Show FR.218 sign link when auditor is appointed reviewer |
| `frontend/src/app/(app)/viewer/[type]/[id]/page.tsx` (or viewer component) | Render `not_applicable` slots as grey/N/A |
