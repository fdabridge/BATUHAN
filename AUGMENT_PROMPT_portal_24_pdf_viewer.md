# Prompt 24 — In-portal PDF Viewer with Signature Overlay Boxes

## Context

This is the Certiva platform. We are building a DocuSign-like visual signing layer.

- Prompt 21: `[SIG:PARTY]` placeholder text injected into all DOCX templates.
- Prompt 22: Personal signature profiles (drawn or uploaded) stored per user.
- Prompt 23: `doc_converter.py` converts DOCX → PDF, pdfplumber extracts `[SIG:...]` field coordinates, stored in `document_signature_fields`. Endpoints: `GET /viewer/prepare` and `GET /viewer/pdf`.
- **Prompt 24 (this one)**: A `CertivaDocumentViewer` React component that renders a PDF using PDF.js inside the portal and shows clickable overlay boxes at every signature position. A standalone viewer page and "Open" buttons in the documents list.
- Prompt 25: Clicking a box triggers the visual signing + OTP flow, places the user's signature image on the overlay.
- Prompt 26: PDF flattening — embed all placed signatures into the final document.

---

## Confirmed existing state (verified by reading source files)

- `SharedDocumentsSection.tsx` already has a Download button per document — the "Open" button goes next to it, linking to `/viewer/shared_doc/[doc_id]`.
- CB portal has `app/(app)/layout.tsx` with `<Sidebar>` and `<Topbar>`. A new nested route at `app/(app)/viewer/[type]/[id]/page.tsx` will be inside this layout automatically.
- `frontend/package.json` does NOT currently have `pdfjs-dist`. It must be installed.
- `api` is the authenticated axios instance at `@/lib/api`. All API calls use it.
- The backend serves PDFs at `GET /viewer/pdf?document_type=X&doc_id=Y` (Prompt 23).
- The backend returns field coordinates at `GET /viewer/prepare?document_type=X&doc_id=Y` (Prompt 23).
- Signature overlay status (who has signed, whose turn it is) will be passed by the parent component — the viewer itself is stateless about signing state. Prompt 25 wires up the signing action.

---

## Step 0 — Install `pdfjs-dist` (run this first)

In the `frontend/` directory:

```bash
npm install pdfjs-dist@3.11.174
```

Version 3.11.174 is specified explicitly for stability with Next.js 14. Do not use v4.x.

---

## Change 1 of 3 — `frontend/src/components/CertivaDocumentViewer.tsx` (new file)

Create this complete file:

```tsx
'use client'

/**
 * CertivaDocumentViewer — In-portal PDF viewer with signature overlay boxes.
 *
 * Renders a PDF using PDF.js (canvas). Overlays clickable boxes at every
 * [SIG:KEY] position extracted by pdfplumber (from Prompt 23). The parent
 * component controls signing status via the `signatureOverrides` prop;
 * this component only renders and fires callbacks — it contains no signing logic.
 *
 * Usage:
 *   <CertivaDocumentViewer
 *     documentType="shared_doc"
 *     docId="abc123"
 *     signatureOverrides={[
 *       { sig_key: 'CB_PLANNER', status: 'signed', signer_name: 'Elif Yılmaz' },
 *       { sig_key: 'CLIENT', status: 'current_user' },
 *     ]}
 *     onSignatureClick={(sigKey) => openSigningModal(sigKey)}
 *   />
 *
 * Without signatureOverrides, all boxes render as 'pending'.
 * Prompt 25 wires onSignatureClick to the signing modal.
 */

import { useCallback, useEffect, useRef, useState } from 'react'
import {
  ChevronLeft,
  ChevronRight,
  CheckCircle2,
  Clock,
  Loader2,
  PenLine,
  AlertTriangle,
} from 'lucide-react'
import api from '@/lib/api'

// ── Types ─────────────────────────────────────────────────────────────────────

export type DocumentType = 'shared_doc' | 'audit_report' | 'nc_form'

/** Status of a single signature field — provided by the parent. */
export type SigStatus =
  | 'pending'       // Someone else must sign; user is waiting
  | 'current_user'  // It is this user's turn to sign; box is clickable
  | 'signed'        // Already signed

export interface SignatureOverride {
  sig_key:          string
  status:           SigStatus
  signer_name?:     string      // Shown when status === 'signed'
  signature_image?: string      // base64 PNG data URL — placed visually when signed
}

interface CertivaDocumentViewerProps {
  documentType:        DocumentType
  docId:               string
  /** Pass per-key overrides. Keys not listed here default to 'pending'. */
  signatureOverrides?: SignatureOverride[]
  /** Called when the current user clicks their signature box. */
  onSignatureClick?:   (sigKey: string) => void
}

// ── Raw field shape from /viewer/prepare ─────────────────────────────────────

interface RawField {
  sig_key:      string
  page_number:  number   // 0-indexed
  x0: number; y0: number; x1: number; y1: number
  page_width:   number   // PDF points
  page_height:  number
}

// ── Human-readable labels for each sig_key ────────────────────────────────────

const SIG_LABELS: Record<string, string> = {
  CB_PLANNER:      'Planning Officer',
  CB_REVIEWER:     'Committee Reviewer',
  CB_CERT_MANAGER: 'Certification Manager',
  LEAD_AUDITOR:    'Lead Auditor',
  CLIENT:          'Organisation Representative',
  AUDITOR_MEMBER:  'Audit Team Member',
}

function sigLabel(sig_key: string): string {
  return SIG_LABELS[sig_key] ?? sig_key
}

// ── PDF.js loader — dynamic import, CDN worker (avoids Next.js bundler issues) ─

type PdfjsLib = typeof import('pdfjs-dist')
let _pdfjsCache: PdfjsLib | null = null

async function getPdfjsLib(): Promise<PdfjsLib> {
  if (_pdfjsCache) return _pdfjsCache
  const pdfjs = await import('pdfjs-dist')
  // Worker loaded from CDN matching installed version (avoids webpack worker config)
  // @ts-expect-error GlobalWorkerOptions is typed differently across versions
  pdfjs.GlobalWorkerOptions.workerSrc =
    `//cdnjs.cloudflare.com/ajax/libs/pdf.js/3.11.174/pdf.worker.min.js`
  _pdfjsCache = pdfjs
  return pdfjs
}

// ── Overlay box constants ─────────────────────────────────────────────────────

/** Minimum visible box dimensions in CSS pixels */
const BOX_MIN_W = 170
const BOX_MIN_H = 50

// ── SignatureBox sub-component ────────────────────────────────────────────────

interface SignatureBoxProps {
  field:       RawField
  scale:       number
  override:    SignatureOverride
  onClick?:    () => void
}

function SignatureBox({ field, scale, override, onClick }: SignatureBoxProps) {
  // Centre of the placeholder text in canvas-pixel space
  const cx = ((field.x0 + field.x1) / 2) * scale
  const cy = ((field.y0 + field.y1) / 2) * scale

  // Box is generous — much larger than the tiny placeholder text
  const w = Math.max(BOX_MIN_W, (field.x1 - field.x0) * scale + 60)
  const h = Math.max(BOX_MIN_H, (field.y1 - field.y0) * scale + 30)

  const style: React.CSSProperties = {
    position: 'absolute',
    left:     cx - w / 2,
    top:      cy - h / 2,
    width:    w,
    height:   h,
  }

  const { status, signer_name, signature_image } = override

  // ── Signed — show placed signature image (or name fallback) ─────────────────
  if (status === 'signed') {
    return (
      <div style={style} className="pointer-events-none flex flex-col items-center justify-center
        rounded border border-emerald-300 bg-emerald-50/80">
        {signature_image ? (
          <img
            src={signature_image}
            alt={signer_name ?? 'Signature'}
            className="max-h-8 max-w-full object-contain"
          />
        ) : (
          <CheckCircle2 size={16} className="text-emerald-600" />
        )}
        {signer_name && (
          <p className="mt-0.5 text-center text-[10px] font-medium text-emerald-700 leading-tight px-1">
            {signer_name}
          </p>
        )}
      </div>
    )
  }

  // ── Current user's turn — pulsing green "Sign here" button ──────────────────
  if (status === 'current_user') {
    return (
      <button
        type="button"
        onClick={onClick}
        style={style}
        className="flex flex-col items-center justify-center gap-1 rounded border-2 border-dashed
          border-[#1A4731] bg-white/90 text-[#1A4731] shadow-sm transition-all
          hover:bg-[#F0FAF4] active:scale-95 cursor-pointer animate-pulse"
        title={`Sign as ${sigLabel(field.sig_key)}`}
      >
        <PenLine size={16} />
        <span className="text-center text-[11px] font-semibold leading-tight px-1">
          {sigLabel(field.sig_key)}
          <br />
          <span className="font-normal opacity-80">Click to sign</span>
        </span>
      </button>
    )
  }

  // ── Pending — muted "waiting" indicator ─────────────────────────────────────
  return (
    <div style={style} className="pointer-events-none flex flex-col items-center justify-center
      gap-1 rounded border border-dashed border-gray-400 bg-white/70">
      <Clock size={14} className="text-gray-400" />
      <span className="text-center text-[10px] text-gray-400 leading-tight px-1">
        {sigLabel(field.sig_key)}
        <br />
        Awaiting signature
      </span>
    </div>
  )
}

// ── Main component ────────────────────────────────────────────────────────────

export function CertivaDocumentViewer({
  documentType,
  docId,
  signatureOverrides = [],
  onSignatureClick,
}: CertivaDocumentViewerProps) {
  const [viewerState, setViewerState] = useState<'idle' | 'preparing' | 'loading' | 'ready' | 'error'>('idle')
  const [errorMsg,   setErrorMsg]    = useState('')
  const [rawFields,  setRawFields]   = useState<RawField[]>([])
  const [currentPage, setCurrentPage] = useState(1)
  const [totalPages,  setTotalPages]  = useState(0)
  const [pageScale,   setPageScale]   = useState(1)

  const canvasRef    = useRef<HTMLCanvasElement>(null)
  const containerRef = useRef<HTMLDivElement>(null)
  const pdfDocRef    = useRef<any>(null)

  // ── Initial load ───────────────────────────────────────────────────────────

  useEffect(() => {
    let cancelled = false

    async function load() {
      setViewerState('preparing')
      setErrorMsg('')

      try {
        // Step 1: Prepare (may trigger LibreOffice conversion — can take 2–5 s on first open)
        // and load PDF.js library in parallel.
        const [prepareRes, pdfjsLib] = await Promise.all([
          api.get('/viewer/prepare', {
            params: { document_type: documentType, doc_id: docId },
          }),
          getPdfjsLib(),
        ])

        if (cancelled) return
        setRawFields((prepareRes.data.fields as RawField[]) ?? [])
        setViewerState('loading')

        // Step 2: Fetch PDF bytes and load into PDF.js
        const pdfRes = await api.get('/viewer/pdf', {
          params:       { document_type: documentType, doc_id: docId },
          responseType: 'arraybuffer',
        })

        if (cancelled) return

        // eslint-disable-next-line @typescript-eslint/no-explicit-any
        const loadingTask = (pdfjsLib as any).getDocument({ data: pdfRes.data })
        const pdfDoc = await loadingTask.promise

        if (cancelled) return
        pdfDocRef.current = pdfDoc
        setTotalPages(pdfDoc.numPages)
        setCurrentPage(1)
        setViewerState('ready')

      } catch (err: unknown) {
        if (!cancelled) {
          const detail = (err as { response?: { data?: { detail?: string } } })
            ?.response?.data?.detail
          setErrorMsg(detail ?? (err instanceof Error ? err.message : 'Failed to load document.'))
          setViewerState('error')
        }
      }
    }

    load()
    return () => { cancelled = true }
  }, [documentType, docId])

  // ── Render page to canvas ─────────────────────────────────────────────────

  const renderPage = useCallback(async (pageNum: number) => {
    const pdfDoc   = pdfDocRef.current
    const canvas   = canvasRef.current
    const container = containerRef.current
    if (!pdfDoc || !canvas || !container) return

    const page       = await pdfDoc.getPage(pageNum)        // 1-indexed
    const viewport0  = page.getViewport({ scale: 1 })

    // Scale page to fit container width, accounting for device pixel ratio
    const dpr   = window.devicePixelRatio || 1
    const scale = (container.clientWidth / viewport0.width)
    const viewport = page.getViewport({ scale })

    // Physical canvas size (sharp on retina)
    canvas.width  = viewport.width  * dpr
    canvas.height = viewport.height * dpr

    // CSS display size
    canvas.style.width  = `${viewport.width}px`
    canvas.style.height = `${viewport.height}px`

    const ctx = canvas.getContext('2d')!
    ctx.scale(dpr, dpr)

    await page.render({ canvasContext: ctx, viewport }).promise
    setPageScale(scale)

  }, [])

  useEffect(() => {
    if (viewerState === 'ready') {
      renderPage(currentPage)
    }
  }, [viewerState, currentPage, renderPage])

  // ── Fields for the current page ───────────────────────────────────────────

  const currentFields = rawFields.filter(f => f.page_number === currentPage - 1)

  function getOverride(sig_key: string): SignatureOverride {
    return (
      signatureOverrides.find(o => o.sig_key === sig_key) ??
      { sig_key, status: 'pending' }
    )
  }

  // ── Render ────────────────────────────────────────────────────────────────

  return (
    <div className="flex flex-col items-center gap-4 bg-gray-100 p-4 min-h-screen">

      {/* Loading / error states */}
      {viewerState === 'idle' || viewerState === 'preparing' ? (
        <div className="flex flex-col items-center gap-3 py-24">
          <Loader2 size={32} className="animate-spin text-gray-400" />
          <p className="text-sm text-gray-500">
            {viewerState === 'preparing'
              ? 'Preparing document (first open may take a few seconds)…'
              : 'Starting…'}
          </p>
        </div>
      ) : viewerState === 'loading' ? (
        <div className="flex flex-col items-center gap-3 py-24">
          <Loader2 size={32} className="animate-spin text-gray-400" />
          <p className="text-sm text-gray-500">Loading PDF…</p>
        </div>
      ) : viewerState === 'error' ? (
        <div className="flex flex-col items-center gap-3 py-24">
          <AlertTriangle size={32} className="text-red-400" />
          <p className="text-sm font-medium text-red-600">Could not load document.</p>
          <p className="text-xs text-gray-400 max-w-sm text-center">{errorMsg}</p>
        </div>
      ) : null}

      {/* PDF canvas + overlays (visible when ready) */}
      {viewerState === 'ready' && (
        <>
          {/* Page navigation */}
          <div className="flex items-center gap-3 rounded-lg bg-white px-4 py-2 shadow-sm">
            <button
              type="button"
              onClick={() => setCurrentPage(p => Math.max(1, p - 1))}
              disabled={currentPage <= 1}
              className="rounded p-1 text-gray-600 hover:bg-gray-100 disabled:opacity-30"
            >
              <ChevronLeft size={18} />
            </button>
            <span className="text-sm text-gray-700">
              Page <strong>{currentPage}</strong> of <strong>{totalPages}</strong>
            </span>
            <button
              type="button"
              onClick={() => setCurrentPage(p => Math.min(totalPages, p + 1))}
              disabled={currentPage >= totalPages}
              className="rounded p-1 text-gray-600 hover:bg-gray-100 disabled:opacity-30"
            >
              <ChevronRight size={18} />
            </button>
          </div>

          {/* Canvas + signature overlays */}
          <div
            ref={containerRef}
            className="relative w-full max-w-3xl shadow-xl"
            style={{ background: 'white' }}
          >
            <canvas ref={canvasRef} className="block w-full" />

            {/* Signature boxes — absolutely positioned over the canvas */}
            {currentFields.map((field) => (
              <SignatureBox
                key={`${field.sig_key}-${field.page_number}`}
                field={field}
                scale={pageScale}
                override={getOverride(field.sig_key)}
                onClick={
                  getOverride(field.sig_key).status === 'current_user'
                    ? () => onSignatureClick?.(field.sig_key)
                    : undefined
                }
              />
            ))}
          </div>

          {/* Field legend — listed below the page */}
          {rawFields.length > 0 && (
            <div className="w-full max-w-3xl rounded-xl bg-white p-4 shadow-sm">
              <p className="mb-3 text-xs font-semibold uppercase tracking-wide text-gray-400">
                Signatures
              </p>
              <div className="flex flex-wrap gap-3">
                {Array.from(new Set(rawFields.map(f => f.sig_key))).map(sig_key => {
                  const ov = getOverride(sig_key)
                  return (
                    <div key={sig_key} className="flex items-center gap-2">
                      <span className={`h-2.5 w-2.5 rounded-full ${
                        ov.status === 'signed'       ? 'bg-emerald-500'
                        : ov.status === 'current_user' ? 'bg-[#1A4731] animate-pulse'
                        : 'bg-gray-300'
                      }`} />
                      <span className="text-sm text-gray-700">{sigLabel(sig_key)}</span>
                      <span className="text-xs text-gray-400">
                        {ov.status === 'signed'
                          ? (ov.signer_name ? `✓ ${ov.signer_name}` : '✓ Signed')
                          : ov.status === 'current_user'
                          ? 'Your signature'
                          : 'Awaiting'}
                      </span>
                    </div>
                  )
                })}
              </div>
            </div>
          )}
        </>
      )}
    </div>
  )
}
```

---

## Change 2 of 3 — `frontend/src/app/(app)/viewer/[type]/[id]/page.tsx` (new file)

This is a standalone full-page viewer inside the CB portal layout. The URL is `/viewer/shared_doc/[doc_id]` or `/viewer/audit_report/[report_id]` etc.

```tsx
'use client'

import { useParams, useRouter } from 'next/navigation'
import { ArrowLeft } from 'lucide-react'
import { CertivaDocumentViewer, type DocumentType } from '@/components/CertivaDocumentViewer'

export default function ViewerPage() {
  const params = useParams()
  const router = useRouter()
  const documentType = params.type as DocumentType
  const docId        = params.id   as string

  const validTypes: DocumentType[] = ['shared_doc', 'audit_report', 'nc_form']
  if (!validTypes.includes(documentType)) {
    return (
      <div className="p-8 text-sm text-red-600">
        Unknown document type: <code>{documentType}</code>
      </div>
    )
  }

  return (
    <div className="flex min-h-screen flex-col">
      {/* Header bar */}
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
          {documentType.replace('_', ' ')}
        </span>
      </div>

      {/* Viewer */}
      <CertivaDocumentViewer
        documentType={documentType}
        docId={docId}
        onSignatureClick={(sigKey) => {
          // Prompt 25 will replace this with the signing modal
          alert(`Signing flow for [${sigKey}] — will be wired in Prompt 25.`)
        }}
      />
    </div>
  )
}
```

---

## Change 3 of 3 — `frontend/src/components/ui/SharedDocumentsSection.tsx`

### Add an "Open" button next to "Download"

Find the existing "Download" button in the document list (near the bottom of the file):

```tsx
                  <button
                    type="button"
                    onClick={() => downloadDoc(d.id, d.label)}
                    className="rounded-lg border border-gray-300 px-2.5 py-1 text-xs text-gray-700 hover:bg-gray-50"
                  >
                    Download
                  </button>
```

Replace it with (adds "Open" button before "Download"):

```tsx
                  <a
                    href={`/viewer/shared_doc/${d.id}`}
                    className="rounded-lg border border-[#1A4731] px-2.5 py-1 text-xs
                      font-medium text-[#1A4731] hover:bg-[#F0FAF4]"
                  >
                    Open
                  </a>
                  <button
                    type="button"
                    onClick={() => downloadDoc(d.id, d.label)}
                    className="rounded-lg border border-gray-300 px-2.5 py-1 text-xs text-gray-700 hover:bg-gray-50"
                  >
                    Download
                  </button>
```

The `<a>` tag uses a standard link (full page navigation to the viewer). No additional imports needed.

---

## What is NOT changing

- No backend files changed (viewer_router.py from Prompt 23 is already in place).
- No other frontend pages modified.
- The existing OTP signing flow (Prompt 11–19) is untouched — the viewer is additive.
- `signatureOverrides` defaults to empty array → all boxes render as "pending" (gray clocks). The parent passes real signing state in Prompt 25.
- No changes to auditor or client portals in this prompt. Prompt 25 will add the viewer to those portals when signing is wired up.

---

## Verification checklist

1. `npm install pdfjs-dist@3.11.174` completes without error.
2. `npx tsc --noEmit` passes (no TypeScript errors).
3. Navigate to `/viewer/shared_doc/[a_valid_doc_id]` in the CB portal:
   - Loading spinner shows "Preparing document…" during first-time conversion.
   - PDF renders correctly on the canvas after loading.
   - Signature overlay boxes appear at the correct positions with gray "Awaiting signature" labels.
   - Page navigation (prev/next) works.
   - Legend section below the page lists all signature roles.
4. On second open of the same document: loading is fast (< 1 second — cache hit from DB and disk).
5. "Open" button appears next to "Download" in `SharedDocumentsSection`.
6. Clicking "Open" navigates to the viewer page.
7. `Back` button in the viewer header returns to the previous page.

---

## Note: signature overlay box positioning accuracy

The overlay boxes are positioned using bounding-box coordinates from pdfplumber. These coordinates represent the centre of the `[SIG:KEY]` placeholder text (8pt light gray). The boxes are deliberately oversized (min 170×50px) to cover the full signature area in the table cell. The exact visual placement can be tuned by adjusting `BOX_MIN_W`, `BOX_MIN_H`, and the `+60 / +30` padding constants in `getOverlayStyle` inside `SignatureBox`.

If boxes appear offset, check that `pageScale` is calculated correctly after `renderPage` sets `canvas.style.width`. The overlay `position: absolute` coordinates are in CSS pixels (post-scale), so `field.x0 * pageScale` gives the correct CSS pixel position.

---

## Commit message

```
feat(portal): in-portal PDF viewer with signature overlay boxes (Prompt 24)

- frontend: npm install pdfjs-dist@3.11.174
- components/CertivaDocumentViewer.tsx: PDF.js canvas renderer, clickable
  signature overlay boxes (SignatureBox sub-component), 3 visual states:
  signed (green, signature image), current_user (pulsing green "Click to sign"),
  pending (gray clock). Dynamic scale-to-width, DPR-aware canvas, page nav,
  signature legend. Loads PDF.js via dynamic import with CDN worker.
- app/(app)/viewer/[type]/[id]/page.tsx: standalone CB portal viewer page
  at /viewer/shared_doc|audit_report|nc_form/[id]. Back button, type validation.
- components/ui/SharedDocumentsSection.tsx: add "Open" link button next to
  "Download" for each document → navigates to /viewer/shared_doc/[id]
```
