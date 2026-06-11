# Prompt 26 — PDF Flattening + Final Document Delivery

## Context

This is the Certiva platform. This is the **final prompt** in the 6-prompt DocuSign-like signing plan:

- Prompt 21: `[SIG:PARTY]` placeholders injected into DOCX templates.
- Prompt 22: User signature profile (draw/upload).
- Prompt 23: DOCX → PDF pipeline, pdfplumber coordinate extraction.
- Prompt 24: In-portal PDF viewer with signature overlay boxes.
- Prompt 25: Visual signing + OTP commit — `VisualSignaturePlacement` table, `/viewer/sign/*` endpoints, `SignatureConfirmDialog` modal.
- **Prompt 26 (this one)**: PDF flattening — embed placed signature images into the PDF permanently, expose a "Download Signed PDF" endpoint, and wire the viewer into the client and auditor portals.

**The problem with the current state**: when a user downloads a document after signing it in the viewer, the downloaded PDF still contains the gray `[SIG:...]` placeholder text — the signature overlays are browser-only. Prompt 26 fixes this: the download endpoint returns a **flattened PDF** with signature images burned into the document at the placeholder positions, with the placeholder text whited out.

**Coordinate system note**: pdfplumber stores coordinates as `top-left origin, y increases downward` (same as PyMuPDF's default page coordinates). The `x0, y0, x1, y1` values in `document_signature_fields` can be used directly with `fitz.Rect()` — no coordinate inversion needed.

**Dependency note**: `PyMuPDF==1.24.10` is **already in `requirements.txt`**. No new Python packages are needed.

---

## Files to change — summary

| # | File | Action |
|---|------|--------|
| 1 | `backend/audit_set/pdf_flattener.py` | **New file** — PyMuPDF signature embedding |
| 2 | `backend/audit_set/viewer_router.py` | Add `GET /viewer/download-signed` endpoint |
| 3 | `frontend/src/app/(app)/viewer/[type]/[id]/page.tsx` | Add "Download Signed PDF" button to header |
| 4 | `frontend/src/app/(client)/client/viewer/[type]/[id]/page.tsx` | **New file** — client portal viewer |
| 5 | `frontend/src/app/(auditor)/auditor/viewer/[type]/[id]/page.tsx` | **New file** — auditor portal viewer |
| 6 | `frontend/src/app/(client)/client/documents/page.tsx` | Add "Open" button linking to `/client/viewer/shared_doc/${id}` |
| 7 | `frontend/src/app/(auditor)/auditor/audit/[id]/page.tsx` | Add "Open" buttons in NC form and audit report sections |

---

## 1. `backend/audit_set/pdf_flattener.py` (new file)

```python
"""
Certiva — PDF flattening (Prompt 26).

Embeds placed signature images into the PDF at the coordinates of each
[SIG:KEY] placeholder, whiting out the placeholder text first.

Uses PyMuPDF (fitz), which is already in requirements.txt.

Coordinate system
-----------------
pdfplumber (used in doc_converter.py) stores coordinates as:
  x0, y0 = left, top   (top-left origin, y increases downward)
  x1, y1 = right, bottom

PyMuPDF uses the SAME coordinate convention for its fitz.Rect objects on
a standard page, so pdfplumber coordinates can be passed to fitz.Rect
directly without inversion.
"""
from __future__ import annotations

import base64
import os
from typing import TYPE_CHECKING

import fitz  # PyMuPDF

if TYPE_CHECKING:
    from sqlalchemy.orm import Session


# Minimum overlay dimensions in PDF points (1 pt = 1/72 inch)
SIG_MIN_W = 140.0
SIG_MIN_H = 28.0

# Padding around the [SIG:...] text bounding box for the whiteout rect
WHITEOUT_PAD = 4.0


def flatten_document(
    document_type: str,
    doc_id: str,
    db: "Session",
) -> bytes:
    """
    Return a flattened PDF with all completed VisualSignaturePlacements
    burned in. Falls back to the raw converted PDF if no visual signatures
    exist yet (e.g. document was signed via the old OTP button before
    Prompt 25 was deployed).

    Raises FileNotFoundError if /viewer/prepare has not been called yet.
    """
    from audit_set.db_models import DocumentSignatureField, VisualSignaturePlacement

    # ── Resolve paths ─────────────────────────────────────────────────────────
    docx_path = _resolve_docx_path(document_type, doc_id, db)
    pdf_path  = os.path.splitext(docx_path)[0] + ".pdf"

    if not os.path.exists(pdf_path):
        raise FileNotFoundError(
            "PDF not found. Open the document in the viewer first to trigger conversion."
        )

    # ── Get completed placements (with signature images) ──────────────────────
    placements = (
        db.query(VisualSignaturePlacement)
        .filter(
            VisualSignaturePlacement.document_type == document_type,
            VisualSignaturePlacement.doc_id == doc_id,
            VisualSignaturePlacement.signed_at.isnot(None),
            VisualSignaturePlacement.signature_image.isnot(None),
        )
        .all()
    )

    if not placements:
        # No visual placements — return original converted PDF as-is
        with open(pdf_path, "rb") as f:
            return f.read()

    placement_map = {p.sig_key: p for p in placements}

    # ── Get field coordinates ─────────────────────────────────────────────────
    fields = (
        db.query(DocumentSignatureField)
        .filter(
            DocumentSignatureField.docx_path == docx_path,
            DocumentSignatureField.sig_key.in_(list(placement_map.keys())),
        )
        .all()
    )
    if not fields:
        with open(pdf_path, "rb") as f:
            return f.read()

    field_map = {f.sig_key: f for f in fields}

    # ── Open PDF and embed signatures ─────────────────────────────────────────
    doc = fitz.open(pdf_path)

    for sig_key, placement in placement_map.items():
        field = field_map.get(sig_key)
        if not field:
            continue

        page_idx = field.page_number   # 0-indexed
        if page_idx >= len(doc):
            continue

        page = doc[page_idx]

        # Decode the base64 PNG data-URL
        img_data = placement.signature_image
        if img_data.startswith("data:"):
            img_data = img_data.split(",", 1)[1]
        try:
            img_bytes = base64.b64decode(img_data)
        except Exception:
            continue   # skip broken image, don't abort the whole document

        # ── Compute overlay rectangle ─────────────────────────────────────────
        x0, y0, x1, y1 = field.x0, field.y0, field.x1, field.y1
        cx = (x0 + x1) / 2.0
        cy = (y0 + y1) / 2.0

        sig_w = max(SIG_MIN_W, (x1 - x0) + 40.0)
        sig_h = max(SIG_MIN_H, (y1 - y0) + 10.0)

        overlay_rect = fitz.Rect(
            cx - sig_w / 2.0,
            cy - sig_h / 2.0,
            cx + sig_w / 2.0,
            cy + sig_h / 2.0,
        )

        # ── White-out the [SIG:...] placeholder text ──────────────────────────
        placeholder_rect = fitz.Rect(
            x0 - WHITEOUT_PAD,
            y0 - WHITEOUT_PAD,
            x1 + WHITEOUT_PAD,
            y1 + WHITEOUT_PAD,
        )
        # Draw a white filled rectangle with no visible border
        page.draw_rect(
            placeholder_rect,
            color=(1.0, 1.0, 1.0),
            fill=(1.0, 1.0, 1.0),
            width=0,
        )

        # ── Insert signature image ────────────────────────────────────────────
        # The PNG images from Prompt 22 have a transparent background
        # (white pixels were converted to alpha=0 by removeWhiteBackground).
        # insert_image() preserves transparency.
        try:
            page.insert_image(overlay_rect, stream=img_bytes)
        except Exception:
            # Fallback: print signer's name as italic text if image fails
            page.insert_text(
                (overlay_rect.x0 + 4, overlay_rect.y0 + overlay_rect.height / 2 + 4),
                f"[Signed]",
                fontsize=9,
                color=(0.1, 0.27, 0.19),
            )

    # ── Serialize ─────────────────────────────────────────────────────────────
    # garbage=4 → remove unused objects; deflate=True → compress streams
    result = doc.tobytes(garbage=4, deflate=True)
    doc.close()
    return result


# ── Internal helper ───────────────────────────────────────────────────────────

def _resolve_docx_path(document_type: str, doc_id: str, db: "Session") -> str:
    """Map (document_type, doc_id) → absolute DOCX file path."""
    from audit_set.db_models import AuditSetAuditReport, AuditSetNCForm, AuditSetSharedDocument

    path: str | None = None
    if document_type == "shared_doc":
        doc = db.query(AuditSetSharedDocument).filter_by(id=doc_id).first()
        path = doc.file_path if doc else None
    elif document_type == "audit_report":
        doc = db.query(AuditSetAuditReport).filter_by(id=doc_id).first()
        path = doc.file_path if doc else None
    elif document_type == "nc_form":
        doc = db.query(AuditSetNCForm).filter_by(id=doc_id).first()
        path = doc.file_path if doc else None

    if not path:
        raise FileNotFoundError("Document not found or has no file")

    return os.path.abspath(path)
```

---

## 2. `backend/audit_set/viewer_router.py` — add download-signed endpoint

### 2a. Add to the imports section

```python
from fastapi.responses import Response
from audit_set.pdf_flattener import flatten_document
```

### 2b. New endpoint — add after `serve_viewer_pdf`

```python
@router.get("/download-signed")
def download_signed_pdf(
    document_type: str          = Query(...),
    doc_id:        str          = Query(...),
    db:            Session      = Depends(get_db),
    auth_db:       Session      = Depends(get_auth_db),
    current_user:  PlatformUser = Depends(get_current_user),
):
    """
    Returns a flattened PDF with all completed VisualSignaturePlacements
    burned in. Falls back to the raw converted PDF if no visual placements
    exist (e.g. documents signed via the old OTP button only).

    Requires the document to have been prepared first (/viewer/prepare).
    Accessible by any authenticated user (CB, auditor, client) — the
    backend already enforces access control at the signing layer.
    """
    try:
        pdf_bytes = flatten_document(document_type, doc_id, db)
    except FileNotFoundError as exc:
        raise HTTPException(
            404,
            "PDF not ready. Open the document in the viewer first.",
        ) from exc
    except Exception as exc:
        raise HTTPException(500, f"Failed to generate signed PDF: {exc}") from exc

    doc_label = _get_doc_label(document_type, doc_id, db)
    safe_name = "".join(c if c.isalnum() or c in " .-" else "_" for c in doc_label)[:60]
    filename  = f"{safe_name}_signed.pdf"

    return Response(
        content=pdf_bytes,
        media_type="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )
```

---

## 3. `frontend/src/app/(app)/viewer/[type]/[id]/page.tsx` — add download button

Replace the file with (key changes: import `Download`, add download function, add button in header):

```tsx
'use client'

import { useCallback, useEffect, useState } from 'react'
import { useParams, useRouter } from 'next/navigation'
import { ArrowLeft, Download } from 'lucide-react'
import api from '@/lib/api'
import {
  CertivaDocumentViewer,
  type DocumentType,
  type SignatureOverride,
} from '@/components/CertivaDocumentViewer'
import { SignatureConfirmDialog } from '@/components/SignatureConfirmDialog'

const VALID_TYPES: DocumentType[] = ['shared_doc', 'audit_report', 'nc_form']

export default function ViewerPage() {
  const params = useParams()
  const router = useRouter()
  const documentType = params.type as DocumentType
  const docId        = params.id   as string

  const [overrides,    setOverrides]    = useState<SignatureOverride[]>([])
  const [activeSigKey, setActiveSigKey] = useState<string | null>(null)
  const [docPrepared,  setDocPrepared]  = useState(false)
  const [downloading,  setDownloading]  = useState(false)

  const loadStatus = useCallback(async () => {
    try {
      const r = await api.get('/viewer/signing-status', {
        params: { document_type: documentType, doc_id: docId },
      })
      setOverrides(r.data.fields ?? [])
    } catch {
      // fail silently — boxes default to "pending"
    }
  }, [documentType, docId])

  useEffect(() => {
    if (docPrepared) loadStatus()
  }, [docPrepared, loadStatus])

  async function downloadSigned() {
    setDownloading(true)
    try {
      const r = await api.get('/viewer/download-signed', {
        params:       { document_type: documentType, doc_id: docId },
        responseType: 'blob',
      })
      const url = window.URL.createObjectURL(r.data as Blob)
      const a   = document.createElement('a')
      a.href     = url
      a.download = `document_signed.pdf`
      document.body.appendChild(a)
      a.click()
      a.remove()
      window.URL.revokeObjectURL(url)
    } catch {
      alert('Could not download signed PDF. Please try again.')
    } finally {
      setDownloading(false)
    }
  }

  if (!VALID_TYPES.includes(documentType)) {
    return (
      <div className="p-8 text-sm text-red-600">
        Unknown document type: <code>{documentType}</code>
      </div>
    )
  }

  return (
    <div className="flex min-h-screen flex-col">
      {/* Header */}
      <div className="sticky top-0 z-10 flex items-center gap-3 border-b bg-white px-6 py-3 shadow-sm">
        <button
          type="button"
          onClick={() => router.back()}
          className="flex items-center gap-1.5 text-sm text-gray-500 hover:text-gray-800"
        >
          <ArrowLeft size={16} />
          Back
        </button>
        <span className="text-sm font-medium text-gray-700 capitalize">
          {documentType.replace(/_/g, ' ')}
        </span>
        <button
          type="button"
          onClick={downloadSigned}
          disabled={downloading || !docPrepared}
          className="ml-auto flex items-center gap-1.5 rounded-lg bg-[#1A4731] px-3 py-1.5
            text-sm font-medium text-white hover:bg-[#1A4731]/90
            disabled:cursor-not-allowed disabled:opacity-40 transition-all"
        >
          <Download size={14} />
          {downloading ? 'Generating…' : 'Download Signed PDF'}
        </button>
      </div>

      {/* PDF Viewer */}
      <CertivaDocumentViewer
        documentType={documentType}
        docId={docId}
        signatureOverrides={overrides}
        onSignatureClick={(sigKey) => setActiveSigKey(sigKey)}
        onPrepared={() => setDocPrepared(true)}
      />

      {/* Signing dialog */}
      <SignatureConfirmDialog
        isOpen={activeSigKey !== null}
        sigKey={activeSigKey ?? ''}
        documentType={documentType}
        docId={docId}
        onClose={() => setActiveSigKey(null)}
        onSigned={(sk) => {
          setActiveSigKey(null)
          loadStatus()
        }}
      />
    </div>
  )
}
```

---

## 4. `frontend/src/app/(client)/client/viewer/[type]/[id]/page.tsx` (new file)

Identical viewer experience in the client portal layout. Create at this exact path:

```tsx
'use client'

import { useCallback, useEffect, useState } from 'react'
import { useParams, useRouter } from 'next/navigation'
import { ArrowLeft, Download } from 'lucide-react'
import api from '@/lib/api'
import {
  CertivaDocumentViewer,
  type DocumentType,
  type SignatureOverride,
} from '@/components/CertivaDocumentViewer'
import { SignatureConfirmDialog } from '@/components/SignatureConfirmDialog'

const VALID_TYPES: DocumentType[] = ['shared_doc', 'audit_report', 'nc_form']

export default function ClientViewerPage() {
  const params = useParams()
  const router = useRouter()
  const documentType = params.type as DocumentType
  const docId        = params.id   as string

  const [overrides,    setOverrides]    = useState<SignatureOverride[]>([])
  const [activeSigKey, setActiveSigKey] = useState<string | null>(null)
  const [docPrepared,  setDocPrepared]  = useState(false)
  const [downloading,  setDownloading]  = useState(false)

  const loadStatus = useCallback(async () => {
    try {
      const r = await api.get('/viewer/signing-status', {
        params: { document_type: documentType, doc_id: docId },
      })
      setOverrides(r.data.fields ?? [])
    } catch {
      // fail silently
    }
  }, [documentType, docId])

  useEffect(() => {
    if (docPrepared) loadStatus()
  }, [docPrepared, loadStatus])

  async function downloadSigned() {
    setDownloading(true)
    try {
      const r = await api.get('/viewer/download-signed', {
        params:       { document_type: documentType, doc_id: docId },
        responseType: 'blob',
      })
      const url = window.URL.createObjectURL(r.data as Blob)
      const a   = document.createElement('a')
      a.href     = url
      a.download = 'document_signed.pdf'
      document.body.appendChild(a)
      a.click()
      a.remove()
      window.URL.revokeObjectURL(url)
    } catch {
      alert('Could not download signed PDF. Please try again.')
    } finally {
      setDownloading(false)
    }
  }

  if (!VALID_TYPES.includes(documentType)) {
    return (
      <div className="p-8 text-sm text-red-600">
        Unknown document type: <code>{documentType}</code>
      </div>
    )
  }

  return (
    <div className="flex min-h-screen flex-col">
      {/* Header */}
      <div className="sticky top-0 z-10 flex items-center gap-3 border-b bg-white px-6 py-3 shadow-sm">
        <button
          type="button"
          onClick={() => router.back()}
          className="flex items-center gap-1.5 text-sm text-gray-500 hover:text-gray-800"
        >
          <ArrowLeft size={16} />
          Back
        </button>
        <span className="text-sm font-medium text-gray-700 capitalize">
          {documentType.replace(/_/g, ' ')}
        </span>
        <button
          type="button"
          onClick={downloadSigned}
          disabled={downloading || !docPrepared}
          className="ml-auto flex items-center gap-1.5 rounded-lg bg-[#1A4731] px-3 py-1.5
            text-sm font-medium text-white hover:bg-[#1A4731]/90
            disabled:cursor-not-allowed disabled:opacity-40 transition-all"
        >
          <Download size={14} />
          {downloading ? 'Generating…' : 'Download Signed PDF'}
        </button>
      </div>

      {/* PDF Viewer */}
      <CertivaDocumentViewer
        documentType={documentType}
        docId={docId}
        signatureOverrides={overrides}
        onSignatureClick={(sigKey) => setActiveSigKey(sigKey)}
        onPrepared={() => setDocPrepared(true)}
      />

      {/* Signing dialog */}
      <SignatureConfirmDialog
        isOpen={activeSigKey !== null}
        sigKey={activeSigKey ?? ''}
        documentType={documentType}
        docId={docId}
        onClose={() => setActiveSigKey(null)}
        onSigned={(sk) => {
          setActiveSigKey(null)
          loadStatus()
        }}
      />
    </div>
  )
}
```

---

## 5. `frontend/src/app/(auditor)/auditor/viewer/[type]/[id]/page.tsx` (new file)

Identical structure; create at this exact path:

```tsx
'use client'

import { useCallback, useEffect, useState } from 'react'
import { useParams, useRouter } from 'next/navigation'
import { ArrowLeft, Download } from 'lucide-react'
import api from '@/lib/api'
import {
  CertivaDocumentViewer,
  type DocumentType,
  type SignatureOverride,
} from '@/components/CertivaDocumentViewer'
import { SignatureConfirmDialog } from '@/components/SignatureConfirmDialog'

const VALID_TYPES: DocumentType[] = ['shared_doc', 'audit_report', 'nc_form']

export default function AuditorViewerPage() {
  const params = useParams()
  const router = useRouter()
  const documentType = params.type as DocumentType
  const docId        = params.id   as string

  const [overrides,    setOverrides]    = useState<SignatureOverride[]>([])
  const [activeSigKey, setActiveSigKey] = useState<string | null>(null)
  const [docPrepared,  setDocPrepared]  = useState(false)
  const [downloading,  setDownloading]  = useState(false)

  const loadStatus = useCallback(async () => {
    try {
      const r = await api.get('/viewer/signing-status', {
        params: { document_type: documentType, doc_id: docId },
      })
      setOverrides(r.data.fields ?? [])
    } catch { /* silent */ }
  }, [documentType, docId])

  useEffect(() => {
    if (docPrepared) loadStatus()
  }, [docPrepared, loadStatus])

  async function downloadSigned() {
    setDownloading(true)
    try {
      const r = await api.get('/viewer/download-signed', {
        params:       { document_type: documentType, doc_id: docId },
        responseType: 'blob',
      })
      const url = window.URL.createObjectURL(r.data as Blob)
      const a   = document.createElement('a')
      a.href = url; a.download = 'document_signed.pdf'
      document.body.appendChild(a); a.click(); a.remove()
      window.URL.revokeObjectURL(url)
    } catch {
      alert('Could not download signed PDF. Please try again.')
    } finally {
      setDownloading(false)
    }
  }

  if (!VALID_TYPES.includes(documentType)) {
    return (
      <div className="p-8 text-sm text-red-600">
        Unknown document type: <code>{documentType}</code>
      </div>
    )
  }

  return (
    <div className="flex min-h-screen flex-col">
      <div className="sticky top-0 z-10 flex items-center gap-3 border-b bg-white px-6 py-3 shadow-sm">
        <button
          type="button"
          onClick={() => router.back()}
          className="flex items-center gap-1.5 text-sm text-gray-500 hover:text-gray-800"
        >
          <ArrowLeft size={16} />
          Back
        </button>
        <span className="text-sm font-medium text-gray-700 capitalize">
          {documentType.replace(/_/g, ' ')}
        </span>
        <button
          type="button"
          onClick={downloadSigned}
          disabled={downloading || !docPrepared}
          className="ml-auto flex items-center gap-1.5 rounded-lg bg-[#1A4731] px-3 py-1.5
            text-sm font-medium text-white hover:bg-[#1A4731]/90
            disabled:cursor-not-allowed disabled:opacity-40 transition-all"
        >
          <Download size={14} />
          {downloading ? 'Generating…' : 'Download Signed PDF'}
        </button>
      </div>

      <CertivaDocumentViewer
        documentType={documentType}
        docId={docId}
        signatureOverrides={overrides}
        onSignatureClick={(sigKey) => setActiveSigKey(sigKey)}
        onPrepared={() => setDocPrepared(true)}
      />

      <SignatureConfirmDialog
        isOpen={activeSigKey !== null}
        sigKey={activeSigKey ?? ''}
        documentType={documentType}
        docId={docId}
        onClose={() => setActiveSigKey(null)}
        onSigned={(sk) => {
          setActiveSigKey(null)
          loadStatus()
        }}
      />
    </div>
  )
}
```

---

## 6. `frontend/src/app/(client)/client/documents/page.tsx` — add "Open" button

### Context

The page currently shows each shared document with a **Download** button (uses `downloadDoc()` to fetch via `api.get()` as a blob). Add an **"Open"** button beside it that navigates to the client portal viewer.

### Change: add a `router` import and the "Open" button

At the top of the file, the existing imports likely include `useRouter` from `next/navigation` — if not, add it. Ensure it is imported and called:

```tsx
// Ensure these imports are present:
import { useRouter } from 'next/navigation'

// In the component body, add:
const router = useRouter()
```

### In the document list render, add the "Open" link next to each Download button

Find the section that renders each document row (it iterates over `docs` and shows a Download button). Add an "Open" link immediately before the Download button:

```tsx
{/* ADD THIS — "Open" navigates to the client portal viewer */}
<a
  href={`/client/viewer/shared_doc/${d.id}`}
  className="inline-flex items-center gap-1.5 rounded-lg border border-[#1A4731] px-3 py-1.5
    text-sm font-medium text-[#1A4731] hover:bg-[#1A4731]/5 transition-colors"
>
  Open
</a>

{/* existing Download button stays here */}
<button
  type="button"
  onClick={() => downloadDoc(d.id, d.label)}
  ...
>
  Download
</button>
```

The "Open" link uses a plain `<a href>` (not `router.push`) so it works without JavaScript and opens in the same tab. The client layout enforces authentication — unauthenticated users are redirected to `/login` before reaching the viewer.

---

## 7. `frontend/src/app/(auditor)/auditor/audit/[id]/page.tsx` — add "Open" buttons

### Context

The auditor audit detail page shows audit reports and NC forms with download buttons. Add "Open" links to both sections so auditors can sign via the viewer.

### NC Forms section

Find the section that renders NC forms. After (or before) any existing Download/Sign button for each NC form, add:

```tsx
<a
  href={`/auditor/viewer/nc_form/${nc.id}`}
  className="inline-flex items-center gap-1.5 rounded-lg border border-[#1A4731] px-3 py-1.5
    text-sm font-medium text-[#1A4731] hover:bg-[#1A4731]/5 transition-colors"
>
  Open
</a>
```

### Audit Reports section

Find the section that renders audit reports. After any existing Download/Sign button for each report, add:

```tsx
<a
  href={`/auditor/viewer/audit_report/${report.id}`}
  className="inline-flex items-center gap-1.5 rounded-lg border border-[#1A4731] px-3 py-1.5
    text-sm font-medium text-[#1A4731] hover:bg-[#1A4731]/5 transition-colors"
>
  Open
</a>
```

---

## Coordinate system — implementation note

`pdf_flattener.py` uses pdfplumber coordinates directly with PyMuPDF. This works because:

1. `doc_converter.py` stores `word["top"]` as `y0` and `word["bottom"]` as `y1`. In pdfplumber, `"top"` is measured from the **top of the page** (top-left origin, y increases downward).

2. PyMuPDF's `fitz.Rect(x0, y0, x1, y1)` also uses **top-left origin, y increases downward** for page coordinates. This is PyMuPDF's default rendered coordinate space.

3. Therefore: `fitz.Rect(field.x0, field.y0, field.x1, field.y1)` correctly addresses the right location on the page — no coordinate inversion required.

---

## What is NOT changing

- `requirements.txt` — PyMuPDF (`fitz`) already present. No new packages needed.
- No changes to existing signing endpoints (`/viewer/sign/*`, `/viewer/prepare`, `/viewer/pdf`).
- No changes to the DOCX templates or `doc_converter.py`.
- No changes to the CB portal `(app)/viewer/[type]/[id]/page.tsx` except adding the Download Signed PDF button.
- The old OTP-based signing buttons (on portal pages) remain — they are not removed. The viewer is an additional signing path.

---

## Verification checklist

1. `GET /viewer/download-signed?document_type=shared_doc&doc_id=<id>` (after signing in viewer):
   - Returns a PDF.
   - Opening the PDF shows the signature image at the correct cell position.
   - The `[SIG:CB_PLANNER]` gray text is NOT visible (whited out).
2. `GET /viewer/download-signed` for a document with no visual placements:
   - Returns the original converted PDF (no error, no flattening attempt).
3. Client portal: clicking "Open" on a document navigates to `/client/viewer/shared_doc/<id>`, shows the PDF with the CLIENT signature box pulsing green (if not yet signed).
4. Auditor portal: clicking "Open" on an NC form navigates to `/auditor/viewer/nc_form/<id>`, shows the LEAD_AUDITOR signature box.
5. After signing in the client or auditor viewer, "Download Signed PDF" returns a PDF with the placed signature image embedded.
6. Downloading before signing returns the original PDF without placeholder text visible (the whiteout only happens when an image is placed — if no placement exists, the raw PDF is returned as-is with the light gray text).

---

## Commit message

```
feat(viewer): PDF flattening + final document delivery (Prompt 26)

Backend:
- audit_set/pdf_flattener.py: new module — flatten_document() uses
  PyMuPDF (already in requirements.txt) to embed VisualSignaturePlacement
  images at DocumentSignatureField coordinates; white-fills [SIG:...] area
  first; falls back to raw PDF when no visual placements exist
- audit_set/viewer_router.py: GET /viewer/download-signed — calls
  flatten_document, returns flattened PDF as application/pdf attachment

Frontend:
- app/(app)/viewer/[type]/[id]/page.tsx: "Download Signed PDF" button in
  header (enabled after /viewer/prepare completes); uses api.get blob +
  object URL pattern
- app/(client)/client/viewer/[type]/[id]/page.tsx: new — client portal
  viewer with same signing flow + Download Signed PDF button
- app/(auditor)/auditor/viewer/[type]/[id]/page.tsx: new — auditor portal
  viewer with same signing flow + Download Signed PDF button
- app/(client)/client/documents/page.tsx: "Open" link to client viewer
  beside each document's Download button
- app/(auditor)/auditor/audit/[id]/page.tsx: "Open" links in NC form and
  audit report sections linking to auditor viewer
```
