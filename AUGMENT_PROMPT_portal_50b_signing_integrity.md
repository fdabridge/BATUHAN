# AUGMENT PROMPT — Portal 50b: Document Signing Integrity

## Problem Statement

An AB (accreditation body) inspector will download any "signed" document and
expect to see an embedded signature image inside it. Currently, several signing
flows record a DB timestamp without ever touching the PDF file. Result: the
document says "signed" on the dashboard but the downloaded PDF has no visible
signature inside it.

The required invariant:
> Every document that shows "signed" status MUST have a downloadable PDF
> with the signer's signature image physically embedded at the correct location.

The only signing path that satisfies this invariant is:
```
signer opens document in viewer
  → sees [SIG:...] placeholder overlay
  → clicks overlay
  → POST /viewer/sign/confirm embeds signature image into PDF
  → PDF is permanently modified, signature visible forever
```

All other signing paths ("direct sign" buttons that call */sign/direct or
*/sign-direct endpoints) must be eliminated from the frontend for
documents that have a DOCX/PDF file.

---

## Diagnostic Map — What Is Broken and Where

Read these files first to confirm each finding before touching anything.

### Category A — Documents WITH files, but bypass buttons exist

These documents already go through the viewer correctly when the "Open"/"Open to
Sign" link is used. The problem is a competing "Sign [X]" button that bypasses
the viewer entirely.

| Document | Broken component | Bypass endpoint called | Viewer link present? |
|---|---|---|---|
| NC Form (FR.230) — lead auditor | `auditor/audit/[id]/page.tsx` NC forms tab | `POST .../nc-forms/{id}/sign/la/direct` | Yes — `href="/auditor/viewer/nc_form/{id}"` |
| Audit Report — lead auditor | `auditor/audit/[id]/page.tsx` reports tab | `POST .../audit-reports/{id}/sign/la/direct` | Yes — `href="/auditor/viewer/audit_report/{r.id}"` |
| NC Form (FR.230) — client sign | `NCFormClientSection.tsx` | `POST /client/my-audit-set/nc-forms/{id}/sign/direct` | Client viewer exists at `/client/viewer/nc_form/{id}` |

**Fix for Category A:** Remove the "Sign NC Form" / "Sign Report" buttons and
date-pickers from the cards that show them. Keep the "Open" / "Open to Review"
viewer links — those are the signing path.

### Category B — FR.222 (Audit Programme) dual-path conflict

**Current state (broken):**

Path 1 (correct): CB uploads audit programme DOCX via Shared Documents
  → `AuditSetSharedDocument` created with `document_type = "audit_programme"`
  → `documents_router.py` seeds `cb_planner` + `cb_cert_manager` slots with
    `document_id = doc.id` pointing at the uploaded file
  → Signing goes through viewer (`/viewer/shared_doc/{id}`) → PDF gets
    signature embedded ✓

Path 2 (broken): CB clicks "Initiate Audit Programme Signing" in
  `InternalApprovalsSection.tsx`
  → `POST /audit-sets/{id}/signatures/create-fr222` creates
    `AuditDocumentSignature` slots with `document_id = None`
  → "Sign" button in `InternalApprovalsSection.tsx` calls `sign-direct`
  → No PDF file exists, no PDF is ever modified ✗

The user described this exactly: "I can either upload audit program from the
CB portal OR initiate audit programme signing."

**Fix for Category B (FR.222):**

1. In `InternalApprovalsSection.tsx`: Remove the "Initiate Audit Programme
   Signing" button entirely. FR.222 is signed only via the uploaded document.

2. In `InternalApprovalsSection.tsx`: For FR.222 slots that DO have a
   `document_id`, change the "Sign" button to an "Open to Sign" link:
   ```tsx
   // BEFORE (broken)
   <button onClick={() => openDirectSign(slot)}>Sign</button>
   
   // AFTER (correct)
   <a href={`/viewer/shared_doc/${slot.document_id}`}>Open to Sign</a>
   ```
   Only show this link when `slot.document_id` is non-null. If `document_id`
   is null, show "Upload audit programme document first" (disabled state).

3. In `PendingSignaturesWidget.tsx`: Extend `isViewer` to include FR.222 when
   `document_id` is present:
   ```tsx
   // BEFORE
   const isViewer = sig.document_type === 'quotation' || sig.document_type === 'agreement'
   
   // AFTER
   const isViewer = (
     sig.document_type === 'quotation' ||
     sig.document_type === 'agreement' ||
     (sig.document_type === 'FR222' && !!sig.document_id)
   )
   ```
   The viewer URL for FR.222 is `/viewer/shared_doc/${sig.document_id}`.
   For `isInternal` FR.222 slots with `document_id = null`, show a disabled
   "Awaiting document upload" badge instead of a "Sign" button.

4. Do NOT delete the `create-fr222` backend endpoint or the `sign-direct`
   backend endpoint. Just remove the frontend UI that calls them.

### Category C — FR.218 (Application Review) — no file exists

**Current state (broken):**

`pipeline_triggers.py → seed_fr218_slots()` creates `AuditDocumentSignature`
slots with `document_id = None`. There is no FR.218 DOCX file in the system.
When CB Planner and Cert Manager click "Sign" in `InternalApprovalsSection.tsx`,
they call `sign-direct`. The DB records `signed_at`. But there is no downloadable
document at all — not even an unsigned one.

**Fix for Category C (FR.218):**

Add FR.218 as an uploadable document type that requires file-backed signing.

**Step C.1 — Add `fr218_review` to the document vocabulary**

In `backend/audit_set/documents_router.py`:

```python
# ALLOWED_DOC_TYPES — add:
"fr218_review",     # FR.218 — Application Review (CB only, internal)

# CB_ONLY_DOC_TYPES (if such a set exists) — add fr218_review

# DOC_SIG_SLOTS — add:
"fr218_review": ["cb_planner", "cb_cert_manager"],
```

**Step C.2 — Update pipeline_triggers.py**

Remove the auto-seed of standalone FR.218 slots (the slots with
`document_id = None`). The new flow: CB must upload the filled FR.218 DOCX
via Shared Documents → system seeds slots with `document_id` → signing via
viewer.

In `pipeline_triggers.py`:
- Remove `seed_fr218_slots()` and its call from `_trigger_fr218_phase()`
- `_trigger_fr218_phase()` should still advance status to `fr218_in_progress`
  but leave slot seeding to the document upload flow (which already seeds
  them when `document_type == "fr218_review"`)
- `check_fr218_completion()` must now check slots linked to an
  `fr218_review` document, not standalone FR.218 slots. Update the query:
  ```python
  def check_fr218_completion(audit_set_id: str, triggered_by: str, db: Session):
      """Advance fr218_in_progress → fr218_complete once all fr218_review
      signature slots are fully signed."""
      audit_set = db.query(AuditSet).filter_by(id=audit_set_id).first()
      if not audit_set or audit_set.workflow_status != "fr218_in_progress":
          return
      # Find the fr218_review shared document
      fr218_doc = (
          db.query(AuditSetSharedDocument)
          .filter_by(audit_set_id=audit_set_id, document_type="fr218_review")
          .first()
      )
      if not fr218_doc:
          return  # not yet uploaded
      remaining = (
          db.query(AuditDocumentSignature)
          .filter_by(document_id=fr218_doc.id, required=True)
          .filter(AuditDocumentSignature.signed_at.is_(None))
          .count()
      )
      if remaining > 0:
          return
      audit_set.workflow_status = "fr218_complete"
      db.add(AuditSetStatusEvent(
          audit_set_id=audit_set_id,
          from_status="fr218_in_progress",
          to_status="fr218_complete",
          triggered_by=triggered_by,
          notes="FR.218 Application Review fully signed via viewer",
      ))
      db.commit()
  ```
  Call `check_fr218_completion` from `_commit_existing_signing_record` in
  `viewer_router.py` when `document_type == "shared_doc"` and
  `doc.document_type == "fr218_review"` and `remaining_all == 0`.
  You already have a `completion_map` dict for stage reports — add the
  fr218 case alongside it.

**Step C.3 — Remove FR.218 from InternalApprovalsSection.tsx**

The "Internal Approvals" widget currently shows FR.218 slots from the old
auto-seeded (no-document) system. Once the new upload-based flow is in place,
FR.218 signing is visible in the shared documents list (like quotation/agreement).
Remove FR.218 from `InternalApprovalsSection.tsx` entirely.

Also remove it from `PendingSignaturesWidget.tsx` (filter out `document_type === "FR218"`
with `document_id === null`).

**Step C.4 — Gate: FR.218 must be uploaded before fr218_complete**

The workflow gate for `fr218_complete` is already enforced by
`check_fr218_completion` — it only advances when the doc is uploaded AND fully
signed. No additional gate needed.

**Step C.5 — CB UI hint**

When `workflow_status == "fr218_in_progress"` and no `fr18_review` doc has been
uploaded, show a hint in the shared documents section or a banner:
"Upload the completed FR.218 Application Review form to continue."

### Category D — Declarations (FR.215) — no file, must generate PDF

**Current state:** `AuditSetImpartialityDeclaration` has no `file_path`
column. The auditor sees declaration text inline, checks a box, clicks
"Sign Declaration" → calls `sign/direct` → DB records `signed_at`. No PDF
exists.

**Fix for Category D (FR.215 Declarations):**

When the auditor signs the declaration via `sign/direct`, auto-generate a
one-page PDF signing certificate and store its path on the record.

**Step D.1 — Add `file_path` and `file_name` columns to `AuditSetImpartialityDeclaration`**

Alembic migration:
```sql
ALTER TABLE audit_set_impartiality_declarations
  ADD COLUMN file_path  VARCHAR NULL,
  ADD COLUMN file_name  VARCHAR NULL;
```

**Step D.2 — PDF generation function**

Create `backend/audit_set/declaration_pdf.py`:

```python
"""Generate a signed PDF certificate for an impartiality declaration."""
from __future__ import annotations
import base64
import io
import os
from datetime import datetime
from typing import Optional

from reportlab.lib.pagesizes import A4
from reportlab.lib.units import mm
from reportlab.pdfgen import canvas


DECLARATION_LINES = [
    "I have no personal, financial, or professional interest in the outcome of this audit.",
    "I have no relationships with the auditee that could compromise my impartiality.",
    "I will conduct the audit objectively and in accordance with audit procedures.",
    "I will maintain confidentiality of all information obtained during the audit.",
    "I acknowledge that any conflict of interest must be disclosed immediately to the CB.",
]


def generate_declaration_pdf(
    *,
    member_name: str,
    member_role: str,
    stage_type: str,
    audit_plan_number: Optional[int],
    company_name: str,
    signed_at: datetime,
    signature_image_b64: Optional[str],
    output_path: str,
) -> None:
    """Render a declaration signing certificate to output_path."""
    os.makedirs(os.path.dirname(output_path), exist_ok=True)
    buf = io.BytesIO()
    c = canvas.Canvas(buf, pagesize=A4)
    W, H = A4

    margin = 20 * mm
    y = H - margin

    # Header
    c.setFont("Helvetica-Bold", 14)
    c.drawString(margin, y, "IFC Global LLC — Certiva")
    y -= 8 * mm
    c.setFont("Helvetica-Bold", 11)
    c.drawString(margin, y, "FR.215  Impartiality Declaration — Signing Certificate")
    y -= 6 * mm
    c.setStrokeColorRGB(0.1, 0.28, 0.19)
    c.setLineWidth(1)
    c.line(margin, y, W - margin, y)
    y -= 8 * mm

    # Audit details
    c.setFont("Helvetica", 10)
    ref = f"#{audit_plan_number}" if audit_plan_number else "N/A"
    for label, value in [
        ("Audit Set",  f"{ref} — {company_name}"),
        ("Stage",      stage_type.replace("_", " ").title()),
        ("Declarant",  member_name),
        ("Role",       member_role),
    ]:
        c.setFont("Helvetica-Bold", 10)
        c.drawString(margin, y, f"{label}:")
        c.setFont("Helvetica", 10)
        c.drawString(margin + 38 * mm, y, value)
        y -= 6 * mm
    y -= 4 * mm

    # Declaration text
    c.setFont("Helvetica-Bold", 10)
    c.drawString(margin, y, f"I, {member_name}, hereby declare that:")
    y -= 7 * mm
    c.setFont("Helvetica", 9)
    for line in DECLARATION_LINES:
        c.drawString(margin + 4 * mm, y, f"✓  {line}")
        y -= 5.5 * mm
    y -= 6 * mm

    # Confirmation line
    c.setFont("Helvetica", 10)
    c.drawString(margin, y, "The above declaration has been confirmed and accepted by the declarant.")
    y -= 10 * mm

    # Signature box
    c.setFont("Helvetica-Bold", 10)
    c.drawString(margin, y, "Digital Signature:")
    y -= 4 * mm
    box_h = 22 * mm
    c.rect(margin, y - box_h, 60 * mm, box_h)
    if signature_image_b64:
        try:
            img_data = base64.b64decode(signature_image_b64)
            img_buf  = io.BytesIO(img_data)
            c.drawImage(img_buf,  # type: ignore[arg-type]
                        margin + 2 * mm, y - box_h + 2 * mm,
                        width=56 * mm, height=box_h - 4 * mm,
                        preserveAspectRatio=True, anchor="c")
        except Exception:
            c.setFont("Helvetica-Oblique", 8)
            c.drawString(margin + 4 * mm, y - box_h / 2, "(signature image unavailable)")

    # Date and name below signature box
    c.setFont("Helvetica", 9)
    date_str = signed_at.strftime("%d %B %Y, %H:%M UTC")
    c.drawString(margin, y - box_h - 5 * mm, f"Signed:  {member_name}")
    c.drawString(margin, y - box_h - 10 * mm, f"Date:    {date_str}")

    c.showPage()
    c.save()

    with open(output_path, "wb") as f:
        f.write(buf.getvalue())
```

**Step D.3 — Call generate_declaration_pdf from declaration_router.py**

In `declaration_router.py`, `sign_declaration_direct()`, after `db.commit()`:

```python
# Generate PDF signing certificate
try:
    from audit_set.declaration_pdf import generate_declaration_pdf
    from auth.db_models import PlatformUser as _PU
    from audit_set.db_models import AuditSet as _AS

    audit_set  = db.query(_AS).filter_by(id=audit_set_id).first()
    signer_user = db_auth.query(_PU).filter_by(id=decl.signed_by).first() if decl.signed_by else None
    sig_image   = signer_user.signature_image if signer_user else None

    from config import settings
    out_path = os.path.join(
        settings.STORAGE_BASE_PATH,
        audit_set_id, "declarations",
        f"FR215_declaration_{decl.id}.pdf",
    )
    generate_declaration_pdf(
        member_name=decl.member_name,
        member_role=decl.member_role,
        stage_type=decl.stage_type,
        audit_plan_number=audit_set.plan_number if audit_set else None,
        company_name=audit_set.company_name if audit_set else "",
        signed_at=decl.signed_at,
        signature_image_b64=sig_image,
        output_path=out_path,
    )
    decl.file_path = out_path
    decl.file_name = f"FR215_declaration_{decl.member_name.replace(' ', '_')}.pdf"
    db.commit()
except Exception:
    pass  # PDF generation failure must never break the signing flow
```

Note: `declaration_router.py` may not have a reference to `auth_db`. If it uses a
single `db` session, query `PlatformUser` from the same session (all models should
be importable from auth.db_models).

**Step D.4 — Add a download endpoint for declarations**

In `declaration_router.py`:

```python
@router.get("/audit-sets/{audit_set_id}/declarations/{did}/download-certificate")
def download_declaration_certificate(
    audit_set_id: str,
    did:          str,
    db:           Session = Depends(get_db),
    current_user: PlatformUser = Depends(get_current_user),
):
    decl = db.query(AuditSetImpartialityDeclaration).filter_by(
        id=did, audit_set_id=audit_set_id
    ).first()
    if not decl:
        raise HTTPException(404, "Declaration not found")
    if not decl.signed_at:
        raise HTTPException(400, "Not yet signed")
    if not decl.file_path or not os.path.exists(decl.file_path):
        raise HTTPException(404, "Signing certificate PDF not found")
    from fastapi.responses import FileResponse
    return FileResponse(
        decl.file_path,
        media_type="application/pdf",
        filename=decl.file_name or f"FR215_declaration_{did}.pdf",
    )
```

**Step D.5 — Frontend: add download link after declaration signing**

In `auditor/audit/[id]/page.tsx` declarations tab:

After a declaration has `is_signed = true`, show a "Download Certificate" link
that calls `GET /audit-sets/{auditSetId}/declarations/{id}/download-certificate`
as a blob download. Keep the existing "Sign Declaration" button + checkbox
for unsigned declarations (the DB-only direct sign is acceptable for declarations
since the PDF is now generated after signing).

### Category E — Client Assessments (FR.211) — deferred

`AuditSetAuditorAssessment` has no file. The client rates each auditor and signs.
This is a form-based record. Generate a PDF signing certificate using the same
pattern as Category D. Defer to a future prompt — assessments are lower priority
for AB inspection than the documents above.

---

## Files to Touch

| File | Change |
|---|---|
| `frontend/src/app/(auditor)/auditor/audit/[id]/page.tsx` | Remove "Sign NC Form" button + date-picker from pending NC forms card. Remove "Sign Report" button + date-picker from pending reports card. Keep "Open" viewer links. |
| `frontend/src/components/ui/NCFormClientSection.tsx` | Replace "Sign NC Form" button with `<a href="/client/viewer/nc_form/{f.id}">Open to Sign</a>` |
| `frontend/src/components/ui/InternalApprovalsSection.tsx` | Remove "Initiate Audit Programme Signing" button. For FR.222 slots with `document_id`: change "Sign" to `<a href="/viewer/shared_doc/{slot.document_id}">Open to Sign</a>`. Remove FR.218 section entirely. |
| `frontend/src/components/ui/PendingSignaturesWidget.tsx` | Extend `isViewer` to include FR.222 with `document_id`. Filter out FR.218 slots with null `document_id`. |
| `backend/audit_set/documents_router.py` | Add `"fr218_review"` to `ALLOWED_DOC_TYPES` and `DOC_SIG_SLOTS` |
| `backend/audit_set/pipeline_triggers.py` | Remove `seed_fr218_slots()`. Update `check_fr218_completion()` to check viewer-based slots linked to an `fr218_review` doc. |
| `backend/audit_set/viewer_router.py` | In `_commit_existing_signing_record`, when `doc.document_type == "fr218_review"` and `remaining_all == 0`, call `check_fr218_completion()`. |
| `backend/audit_set/db_models.py` | Add `file_path`, `file_name` to `AuditSetImpartialityDeclaration`. Add Alembic migration. |
| `backend/audit_set/declaration_router.py` | Call `generate_declaration_pdf` after sign. Add download-certificate endpoint. |
| `backend/audit_set/declaration_pdf.py` | NEW — PDF generation function using reportlab. |

**Do NOT touch:**
- `viewer_router.py` — `_resolve_docx_path`, `_assert_can_sign`, `_get_field_status`, `sign_confirm` for `shared_doc | audit_report | nc_form` — already correct
- `documents_router.py` — existing `DOC_SIG_SLOTS` for other doc types — already correct
- `nc_router.py` — keep `sign/la/direct` endpoint (leave backend, remove frontend button)
- `report_router.py` — keep `sign/la/direct` and `sign/review/direct` endpoints (leave backend, remove frontend buttons)
- `signatures_router.py` — keep `sign-direct` endpoint (leave backend, remove frontend buttons)

---

## Critical: NC forms tab in auditor portal — exact change

In `auditor/audit/[id]/page.tsx`, the NC forms pending card currently has
this structure:

```tsx
{/* Pending NC form card — BEFORE */}
<div className="rounded-xl border border-amber-200 bg-amber-50 p-4">
  <div className="mb-3 flex items-start justify-between">
    ...title...
    <div className="flex items-center gap-2">
      <a href={`/auditor/viewer/nc_form/${f.id}`}>Open</a>   {/* KEEP */}
      <button onClick={() => download(...)}>Download</button>   {/* KEEP */}
    </div>
  </div>
  <div className="flex items-end gap-3">      {/* REMOVE this whole block */}
    <div>
      <label>Signing date</label>
      <input type="date" ... />
    </div>
    <button onClick={() => handleSign(f.id)}>Sign NC Form</button>
  </div>
  {signErrs[f.id] && ...}
</div>

{/* Pending NC form card — AFTER */}
<div className="rounded-xl border border-amber-200 bg-amber-50 p-4">
  <div className="flex items-start justify-between">
    ...title...
    <div className="flex items-center gap-2">
      <a href={`/auditor/viewer/nc_form/${f.id}`}
         className="rounded-lg bg-[#1A4731] px-3 py-1.5 text-xs font-medium text-white hover:bg-[#143828]">
        Open to Sign
      </a>
      <button onClick={() => download(...)}>Download</button>
    </div>
  </div>
</div>
```

Remove the `handleSign`, `signing`, `signErrs`, `signDates` state and the
`handleSign` async function from the NC forms component if they are only used
by the removed button. Clean up unused imports.

---

## Critical: Audit reports tab in auditor portal — exact change

Same pattern. Pending audit report cards have a "Sign Report" button + date
picker. The viewer links at `/auditor/viewer/audit_report/{r.id}` already exist.

Remove: date-picker + "Sign Report" button.
Promote: "Open to Review" or "Open to Sign" viewer link as the primary action,
styled as a solid button (not just a text link).

Clean up `handleSignReport`, `reportSigning`, `reportSignErrs`, `reportSignDates`
state and functions if they are only used by the removed button.

---

## Verification sequence

After deploying, verify each document type:

### NC Form (FR.230)
1. As CB Planner: upload NC form DOCX for a stage
2. As Lead Auditor: log in → audit → NC forms tab → "Open to Sign" present ✓,
   NO "Sign NC Form" button ✓
3. Click "Open to Sign" → viewer opens → `[SIG:LEAD_AUDITOR]` slot visible
4. Sign via viewer → click "Download Signed PDF"
5. Open the downloaded PDF → **lead auditor signature image visible** ✓
6. As Client: NC form appears in client portal → "Open to Sign" link →
   `/client/viewer/nc_form/{id}` → client signs → PDF has both signatures ✓

### Audit Report (FR.231/232)
1. Upload audit report DOCX
2. As Lead Auditor: reports tab → "Open to Sign" present, NO "Sign Report" button ✓
3. Sign via viewer → PDF has LA signature ✓
4. As Committee Reviewer: signs via viewer → PDF has both signatures ✓

### FR.222 (Audit Programme)
1. **Wrong path removed:** No "Initiate Audit Programme Signing" button visible ✓
2. CB uploads audit_programme DOCX via Shared Documents
3. Slots seeded with `document_id` pointing to the uploaded file
4. In Internal Approvals: "Open to Sign" link (not direct Sign button) ✓
5. CB Planner opens viewer → signs → PDF has CP signature ✓
6. Cert Manager opens viewer → signs → PDF has both signatures ✓

### FR.218 (Application Review)
1. No standalone sign buttons in Internal Approvals for FR.218 ✓
2. CB uploads FR.218 DOCX via Shared Documents as `fr218_review` type
3. `cb_planner` + `cb_cert_manager` slots seeded with `document_id`
4. Both sign via viewer → PDF has embedded signatures ✓
5. Workflow advances to `fr218_complete` after both sign ✓

### Declaration (FR.215)
1. Auditor signs declaration via "Sign Declaration" button + checkbox ✓ (unchanged)
2. After signing: "Download Certificate" link appears ✓
3. Download certificate PDF → page shows declaration text, signer name,
   signature image, date ✓
4. CB can also access the certificate PDF for audit file

---

## reportlab dependency

If reportlab is not in requirements.txt, add it:

```
reportlab==4.2.5
```

Verify it's available in the Railway container:
```bash
pip show reportlab 2>/dev/null || echo "NOT INSTALLED"
```

If not installed, add to `backend/requirements.txt` and ensure the Dockerfile
runs `pip install -r requirements.txt`.

---

## Already-Shipped — Do NOT Rebuild or Revert

These were shipped in commits prior to this prompt and must not be changed:

| Feature | Source |
|---|---|
| `viewer_router.py` — `_resolve_docx_path` handles `shared_doc`, `audit_report`, `nc_form` | Portal 25/26 |
| `viewer_router.py` — `_commit_existing_signing_record` for `shared_doc`, `audit_report`, `nc_form` | Portal 49b |
| `viewer_router.py` — `[SIG:ASSIGNED_AUDITOR]` gating for FR.224 | Portal 49b |
| `documents_router.py` — `DOC_SIG_SLOTS` for `audit_programme`, `team_info`, `quotation`, `agreement`, `nc_form`, `stage1_report`, `stage2_report` | Portal 49b |
| `PendingSignaturesWidget.tsx` — `isViewer` path for `quotation` and `agreement` | Portal 49b |
| `auditor/audit/[id]/page.tsx` — `AuditorSharedDocsView` component with amber card + viewer link for FR.224 | Portal 49b |
| `client/viewer/[type]/[id]/page.tsx` — client viewer supporting `shared_doc`, `audit_report`, `nc_form` | Portal 49b |
| `client/documents/page.tsx` — viewer link for client-side shared docs | Portal 49b |
