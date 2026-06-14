# Portal 52 — Viewer Signing Fixes: Dashboard Routing + CB_PLANNER Detection

## Two Bugs to Fix

---

## Bug 1 — Dashboard "Sign" button routes to OTP modal instead of viewer

### Root Cause

`PendingSignaturesWidget.tsx` has this routing logic:

```typescript
const INTERNAL_TYPES = new Set(['FR218', 'FR222'])
const isViewer = (
  sig.document_type === 'quotation' ||
  sig.document_type === 'agreement' ||
  (sig.document_type === 'FR222' && !!sig.document_id)
)
```

`AuditDocumentSignature.document_type` stores `"fr218_review"` (the shared doc type string), not `"FR218"`. So:
- `INTERNAL_TYPES.has("fr218_review")` → **False**
- `isViewer` → **False**
- Falls to `!isInternal && !isViewer` → **OTP modal** — wrong

### Fix — `frontend/src/components/ui/PendingSignaturesWidget.tsx`

Replace the `isViewer` constant with a broader check: any document that has a `document_id` (i.e., a backing PDF in the viewer) should route to the viewer. This covers fr218_review, audit_programme, and any future viewer-backed types.

```typescript
// Any PDF-backed shared document goes through the Certiva viewer.
// Viewer URL: /viewer/shared_doc/{document_id}
const isViewer = !!sig.document_id && [
  'quotation',
  'agreement',
  'fr218_review',
  'audit_programme',
  'FR222',
].includes(sig.document_type)
```

Also remove the dead `INTERNAL_TYPES` constant — it is no longer used after this change.

The rendered button for `isViewer` docs already exists and is correct:
```tsx
{isViewer && sig.document_id && (
  <a href={`/viewer/shared_doc/${sig.document_id}`} ...>
    Open to Sign
  </a>
)}
```

No other changes needed in this file.

---

## Bug 2 — CB_PLANNER slot never shows in the viewer (literal `[SIG:CB_PLANNER]` text visible)

### Root Cause

`GET /viewer/signing-status` only returns statuses for `DocumentSignatureField` rows, which are written by pdfplumber when `GET /viewer/prepare` runs.

When the FR.218 DOCX is converted to PDF by LibreOffice, the text `[SIG:CB_PLANNER]` in the Planning Officer table cell is sometimes split across multiple PDF text objects (e.g., `[SIG:CB_` and `PLANNER]` as separate text streams). Pdfplumber's regex scan (`\[SIG:[A-Z_]+\]`) cannot match split text, so no `DocumentSignatureField` row is written for `CB_PLANNER`. No row → no status returned → no overlay rendered → raw text stays visible.

`CB_REVIEWER` and `CB_CERT_MANAGER` happened to parse cleanly; `CB_PLANNER` did not.

### Fix — Two-part change

#### Part A: `backend/audit_set/viewer_router.py` — extend `viewer_signing_status`

The endpoint currently only covers sig keys from `DocumentSignatureField`. Extend it to ALSO include any sig keys from `AuditDocumentSignature` records (the DB slots seeded at upload time). For those additional keys, return their status even though pdfplumber didn't detect a position.

Find `viewer_signing_status` (around line 938). Replace its body:

```python
@router.get("/signing-status")
def viewer_signing_status(
    document_type: str          = Query(...),
    doc_id:        str          = Query(...),
    db:            Session      = Depends(get_db),
    auth_db:       Session      = Depends(get_auth_db),
    current_user:  PlatformUser = Depends(get_current_user),
):
    """
    Returns the signing status for every sig field on a document.
    Sources:
      1. DocumentSignatureField rows (written by pdfplumber during /prepare)
      2. AuditDocumentSignature rows (DB slots seeded at upload time)
    The union ensures slots that pdfplumber missed still appear in the response.
    Status values: signed | current_user | pending | blocked | not_applicable
    """
    docx_path = _resolve_docx_path(document_type, doc_id, db)

    # Source 1 — pdfplumber-detected sig keys (have a PDF position)
    pdf_sig_keys = {
        row.sig_key
        for row in db.query(DocumentSignatureField.sig_key)
            .filter(
                DocumentSignatureField.docx_path == docx_path,
                DocumentSignatureField.sig_key != "__none__",
            )
            .distinct()
            .all()
    }

    # Source 2 — DB slot records seeded at upload time
    db_sig_keys = set()
    if document_type == "shared_doc":
        slot_rows = db.query(AuditDocumentSignature.signer_role_label).filter_by(
            document_id=doc_id,
        ).all()
        for row in slot_rows:
            mapped = ROLE_TO_SIG.get(row.signer_role_label)
            if mapped:
                db_sig_keys.add(mapped)

    all_sig_keys = pdf_sig_keys | db_sig_keys

    fields = [
        _get_field_status(sk, document_type, doc_id, current_user, db, auth_db)
        for sk in sorted(all_sig_keys)   # sorted for stable ordering
    ]

    return {
        "document_type": document_type,
        "doc_id":        doc_id,
        "fields":        fields,
    }
```

Make sure `AuditDocumentSignature` is imported in `viewer_router.py` — it should already be (it's used elsewhere in the file).

#### Part B: `frontend/src/components/CertivaDocumentViewer.tsx` — fallback signing panel

When a slot has status `"current_user"` but is NOT in `rawFields` (no detected PDF position), the overlay is never rendered at a position on the page. Add a fallback panel below the PDF canvas that lists all unpositioned "current_user" slots and lets the user sign from there.

In the `CertivaDocumentViewer` component, add this logic after the `currentFields` computation:

```typescript
// Slots that are ready for the current user to sign but have no detected PDF position.
// These appear in signatureOverrides (from signing-status) but not in rawFields (from prepare).
const detectedSigKeys = new Set(rawFields.map(f => f.sig_key))
const unpositionedSignable = signatureOverrides.filter(
  ov => ov.status === 'current_user' && !detectedSigKeys.has(ov.sig_key)
)
```

Then, in the JSX, after the `{/* Canvas + overlays */}` block, add a fallback signing panel:

```tsx
{/* Fallback signing panel: slots ready to sign but not detected in PDF position */}
{unpositionedSignable.length > 0 && (
  <div className="w-full max-w-3xl rounded-xl border-2 border-dashed border-[#1A4731] bg-[#F0FAF4] p-4 shadow-sm">
    <p className="mb-3 text-sm font-semibold text-[#1A4731]">
      ✍ Your signature is required on this document
    </p>
    <div className="flex flex-wrap gap-2">
      {unpositionedSignable.map(ov => (
        <button
          key={ov.sig_key}
          type="button"
          onClick={() => onSignatureClick?.(ov.sig_key)}
          className="flex items-center gap-2 rounded-lg border-2 border-[#1A4731] bg-white
            px-4 py-2 text-sm font-medium text-[#1A4731] shadow-sm
            hover:bg-[#1A4731] hover:text-white transition-all animate-pulse"
        >
          <PenLine size={14} />
          Sign as {sigLabel(ov.sig_key)}
        </button>
      ))}
    </div>
  </div>
)}
```

Place this **between** the canvas block and the legend block. The `PenLine` icon is already imported. `sigLabel` is already defined in the file.

This panel is also the sign entry point when CB_PLANNER IS detected at the right PDF position (the overlay covers the text AND this panel appears below) — but if pdfplumber eventually fixes detection, both paths work fine simultaneously.

---

## Commit Message

```
Portal 52: fix viewer signing — dashboard routing + undetected slot fallback

- PendingSignaturesWidget: route fr218_review + audit_programme to viewer
  instead of OTP modal; clean up unused INTERNAL_TYPES constant
- viewer_signing_status: union PDF-detected keys with AuditDocumentSignature
  DB slots so pdfplumber-missed fields (e.g. CB_PLANNER) still get statuses
- CertivaDocumentViewer: fallback signing panel for current_user slots with
  no detected PDF position — shows animated "Sign as X" button below PDF
```

## Files Changed

| File | Change |
|------|--------|
| `frontend/src/components/ui/PendingSignaturesWidget.tsx` | `isViewer` includes `fr18_review`, `audit_programme`; remove `INTERNAL_TYPES` |
| `backend/audit_set/viewer_router.py` | `viewer_signing_status` — union PDF + DB slot sig keys |
| `frontend/src/components/CertivaDocumentViewer.tsx` | Fallback signing panel for unpositioned `current_user` slots |
