'use client'

/**
 * CertivaDocumentViewer — In-portal PDF viewer with signature overlay boxes.
 *
 * Renders a PDF using PDF.js (canvas). Overlays clickable boxes at every
 * [SIG:KEY] position extracted by pdfplumber (Prompt 23). The parent
 * controls signing status via `signatureOverrides`; this component only
 * renders and fires callbacks — it contains no signing logic.
 */

import { useCallback, useEffect, useRef, useState } from 'react'
import {
  ChevronLeft, ChevronRight, CheckCircle2, Clock, Lock,
  Loader2, PenLine, AlertTriangle,
} from 'lucide-react'
import api from '@/lib/api'

// ── Types ─────────────────────────────────────────────────────────────────────

export type DocumentType = 'shared_doc' | 'audit_report' | 'nc_form'

export type SigStatus = 'pending' | 'current_user' | 'signed' | 'blocked' | 'not_applicable'

export interface SignatureOverride {
  sig_key:          string
  status:           SigStatus
  signer_name?:     string
  signature_image?: string
}

interface CertivaDocumentViewerProps {
  documentType:        DocumentType
  docId:               string
  signatureOverrides?: SignatureOverride[]
  onSignatureClick?:   (sigKey: string) => void
  onPrepared?:         () => void
}

interface RawField {
  sig_key:     string
  page_number: number
  x0: number; y0: number; x1: number; y1: number
  page_width:  number
  page_height: number
}

// ── Labels ────────────────────────────────────────────────────────────────────

const SIG_LABELS: Record<string, string> = {
  CB_PLANNER:         'Planning Officer',
  CB_REVIEWER:        'Committee Reviewer',
  CB_CERT_MANAGER:    'Certification Manager',
  LEAD_AUDITOR:       'Lead Auditor',
  CLIENT:             'Organisation Representative',
  AUDITOR_MEMBER:     'Audit Team Member',
  GM:                 'General Manager',
  COMMITTEE_CHAIR:    'Committee Chairperson',
  COMMITTEE_MEMBER_1: 'Committee Member 1',
  COMMITTEE_MEMBER_2: 'Committee Member 2',
  CERT_MANAGER_FR233: 'Certification Manager (FR.233)',
}
function sigLabel(key: string) {
  if (SIG_LABELS[key]) return SIG_LABELS[key]
  // Portal 49a Part 2: dynamic ORG_OPENING_<uuid> / ORG_CLOSING_<uuid> keys.
  if (key.startsWith('ORG_OPENING_'))  return 'Organisation Attendee (Opening)'
  if (key.startsWith('ORG_CLOSING_'))  return 'Organisation Attendee (Closing)'
  return key
}

// ── PDF.js lazy loader (CDN worker — avoids Next.js bundler issues) ────────────

type PdfjsLib = typeof import('pdfjs-dist')
let _pdfjs: PdfjsLib | null = null
async function getPdfjsLib(): Promise<PdfjsLib> {
  if (_pdfjs) return _pdfjs
  const pdfjs = await import('pdfjs-dist')
  pdfjs.GlobalWorkerOptions.workerSrc =
    '//cdnjs.cloudflare.com/ajax/libs/pdf.js/3.11.174/pdf.worker.min.js'
  _pdfjs = pdfjs
  return pdfjs
}

// ── Overlay constants ─────────────────────────────────────────────────────────

const BOX_MIN_W = 170
const BOX_MIN_H = 50

// ── SignatureBox ──────────────────────────────────────────────────────────────

function SignatureBox({
  field, scale, override, onClick,
}: {
  field: RawField; scale: number; override: SignatureOverride; onClick?: () => void
}) {
  const cx = ((field.x0 + field.x1) / 2) * scale
  const cy = ((field.y0 + field.y1) / 2) * scale
  const w  = Math.max(BOX_MIN_W, (field.x1 - field.x0) * scale + 60)
  const h  = Math.max(BOX_MIN_H, (field.y1 - field.y0) * scale + 30)

  const style: React.CSSProperties = {
    position: 'absolute', left: cx - w / 2, top: cy - h / 2, width: w, height: h,
  }

  const { status, signer_name, signature_image } = override

  if (status === 'signed') {
    return (
      <div style={style} className="pointer-events-none flex flex-col items-center justify-center
        rounded border border-emerald-300 bg-emerald-50/80">
        {signature_image
          ? <img src={signature_image} alt={signer_name ?? 'Signature'} className="max-h-8 max-w-full object-contain" />
          : <CheckCircle2 size={16} className="text-emerald-600" />}
        {signer_name && (
          <p className="mt-0.5 text-center text-[10px] font-medium text-emerald-700 leading-tight px-1">
            {signer_name}
          </p>
        )}
      </div>
    )
  }

  if (status === 'current_user') {
    return (
      <button type="button" onClick={onClick} style={style}
        className="flex flex-col items-center justify-center gap-1 rounded border-2 border-dashed
          border-[#1A4731] bg-white/90 text-[#1A4731] shadow-sm transition-all
          hover:bg-[#F0FAF4] active:scale-95 cursor-pointer animate-pulse"
        title={`Sign as ${sigLabel(field.sig_key)}`}
      >
        <PenLine size={16} />
        <span className="text-center text-[11px] font-semibold leading-tight px-1">
          {sigLabel(field.sig_key)}<br />
          <span className="font-normal opacity-80">Click to sign</span>
        </span>
      </button>
    )
  }

  if (status === 'blocked') {
    return (
      <div style={style} className="pointer-events-none flex flex-col items-center justify-center
        gap-1 rounded border border-dashed border-gray-300 bg-gray-50/80">
        <Lock size={13} className="text-gray-300" />
        <span className="text-center text-[10px] text-gray-400 leading-tight px-1">
          {sigLabel(field.sig_key)}<br />Waiting for prior signer
        </span>
      </div>
    )
  }

  if (status === 'not_applicable') {
    return (
      <div style={style} className="pointer-events-none flex flex-col items-center justify-center
        gap-1 rounded border border-dashed border-gray-200 bg-gray-50/60">
        <span className="text-center text-[10px] text-gray-300 leading-tight px-1">
          {sigLabel(field.sig_key)}<br />Not required for this standard
        </span>
      </div>
    )
  }

  return (
    <div style={style} className="pointer-events-none flex flex-col items-center justify-center
      gap-1 rounded border border-dashed border-gray-400 bg-white/70">
      <Clock size={14} className="text-gray-400" />
      <span className="text-center text-[10px] text-gray-400 leading-tight px-1">
        {sigLabel(field.sig_key)}<br />Awaiting signature
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
  onPrepared,
}: CertivaDocumentViewerProps) {
  const [viewerState, setViewerState] = useState<'idle' | 'preparing' | 'loading' | 'ready' | 'error'>('idle')
  const [errorMsg,    setErrorMsg]    = useState('')
  const [rawFields,   setRawFields]   = useState<RawField[]>([])
  const [currentPage, setCurrentPage] = useState(1)
  const [totalPages,  setTotalPages]  = useState(0)
  const [pageScale,   setPageScale]   = useState(1)

  const canvasRef    = useRef<HTMLCanvasElement>(null)
  const containerRef = useRef<HTMLDivElement>(null)
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  const pdfDocRef    = useRef<any>(null)

  // ── Load on mount ──────────────────────────────────────────────────────────
  useEffect(() => {
    let cancelled = false
    async function load() {
      setViewerState('preparing')
      setErrorMsg('')
      try {
        const [prepareRes, pdfjsLib] = await Promise.all([
          api.get('/viewer/prepare', { params: { document_type: documentType, doc_id: docId } }),
          getPdfjsLib(),
        ])
        if (cancelled) return
        setRawFields((prepareRes.data.fields as RawField[]) ?? [])
        onPrepared?.()
        setViewerState('loading')

        const pdfRes = await api.get('/viewer/pdf', {
          params: { document_type: documentType, doc_id: docId },
          responseType: 'arraybuffer',
        })
        if (cancelled) return

        // eslint-disable-next-line @typescript-eslint/no-explicit-any
        const pdfDoc = await (pdfjsLib as any).getDocument({ data: pdfRes.data }).promise
        if (cancelled) return
        pdfDocRef.current = pdfDoc
        setTotalPages(pdfDoc.numPages)
        setCurrentPage(1)
        setViewerState('ready')
      } catch (err: unknown) {
        if (!cancelled) {
          const detail = (err as { response?: { data?: { detail?: string } } })?.response?.data?.detail
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
    const pdfDoc    = pdfDocRef.current
    const canvas    = canvasRef.current
    const container = containerRef.current
    if (!pdfDoc || !canvas || !container) return

    const page      = await pdfDoc.getPage(pageNum)
    const viewport0 = page.getViewport({ scale: 1 })
    const dpr       = window.devicePixelRatio || 1
    const scale     = container.clientWidth / viewport0.width
    const viewport  = page.getViewport({ scale })

    canvas.width        = viewport.width  * dpr
    canvas.height       = viewport.height * dpr
    canvas.style.width  = `${viewport.width}px`
    canvas.style.height = `${viewport.height}px`

    const ctx = canvas.getContext('2d')!
    ctx.scale(dpr, dpr)
    await page.render({ canvasContext: ctx, viewport }).promise
    setPageScale(scale)
  }, [])

  useEffect(() => {
    if (viewerState === 'ready') renderPage(currentPage)
  }, [viewerState, currentPage, renderPage])

  // ── Fields for current page ───────────────────────────────────────────────
  const currentFields = rawFields.filter(f => f.page_number === currentPage - 1)
  function getOverride(sig_key: string): SignatureOverride {
    return signatureOverrides.find(o => o.sig_key === sig_key) ?? { sig_key, status: 'pending' }
  }

  // Slots ready for current user to sign but with no detected PDF position.
  // These come from signing-status (signatureOverrides) but were missed by pdfplumber.
  const detectedSigKeys = new Set(rawFields.map(f => f.sig_key))
  const unpositionedSignable = signatureOverrides.filter(
    ov => ov.status === 'current_user' && !detectedSigKeys.has(ov.sig_key)
  )

  // ── Render ────────────────────────────────────────────────────────────────
  return (
    <div className="flex flex-col items-center gap-4 bg-gray-100 p-4 min-h-screen">

      {(viewerState === 'idle' || viewerState === 'preparing') && (
        <div className="flex flex-col items-center gap-3 py-24">
          <Loader2 size={32} className="animate-spin text-gray-400" />
          <p className="text-sm text-gray-500">
            {viewerState === 'preparing'
              ? 'Preparing document (first open may take a few seconds)…'
              : 'Starting…'}
          </p>
        </div>
      )}

      {viewerState === 'loading' && (
        <div className="flex flex-col items-center gap-3 py-24">
          <Loader2 size={32} className="animate-spin text-gray-400" />
          <p className="text-sm text-gray-500">Loading PDF…</p>
        </div>
      )}

      {viewerState === 'error' && (
        <div className="flex flex-col items-center gap-3 py-24">
          <AlertTriangle size={32} className="text-red-400" />
          <p className="text-sm font-medium text-red-600">Could not load document.</p>
          <p className="text-xs text-gray-400 max-w-sm text-center">{errorMsg}</p>
        </div>
      )}

      {viewerState === 'ready' && (
        <>
          {/* Page navigation */}
          <div className="flex items-center gap-3 rounded-lg bg-white px-4 py-2 shadow-sm">
            <button type="button" onClick={() => setCurrentPage(p => Math.max(1, p - 1))}
              disabled={currentPage <= 1}
              className="rounded p-1 text-gray-600 hover:bg-gray-100 disabled:opacity-30">
              <ChevronLeft size={18} />
            </button>
            <span className="text-sm text-gray-700">
              Page <strong>{currentPage}</strong> of <strong>{totalPages}</strong>
            </span>
            <button type="button" onClick={() => setCurrentPage(p => Math.min(totalPages, p + 1))}
              disabled={currentPage >= totalPages}
              className="rounded p-1 text-gray-600 hover:bg-gray-100 disabled:opacity-30">
              <ChevronRight size={18} />
            </button>
          </div>

          {/* Canvas + overlays */}
          <div ref={containerRef} className="relative w-full max-w-3xl shadow-xl" style={{ background: 'white' }}>
            <canvas ref={canvasRef} className="block w-full" />
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

          {/* Fallback signing panel: slots ready to sign but not detected in PDF */}
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

          {/* Legend */}
          {(rawFields.length > 0 || signatureOverrides.length > 0) && (
            <div className="w-full max-w-3xl rounded-xl bg-white p-4 shadow-sm">
              <p className="mb-3 text-xs font-semibold uppercase tracking-wide text-gray-400">Signatures</p>
              <div className="flex flex-wrap gap-3">
                {Array.from(new Set([
                  ...rawFields.map(f => f.sig_key),
                  ...signatureOverrides.map(o => o.sig_key),
                ])).map(sig_key => {
                  const ov = getOverride(sig_key)
                  return (
                    <div key={sig_key} className="flex items-center gap-2">
                      <span className={`h-2.5 w-2.5 rounded-full ${
                        ov.status === 'signed'          ? 'bg-emerald-500'
                        : ov.status === 'current_user'  ? 'bg-[#1A4731] animate-pulse'
                        : ov.status === 'blocked'       ? 'bg-gray-200'
                        : ov.status === 'not_applicable'? 'bg-gray-100'
                        : 'bg-gray-300'
                      }`} />
                      <span className={`text-sm ${ov.status === 'not_applicable' ? 'text-gray-300' : 'text-gray-700'}`}>{sigLabel(sig_key)}</span>
                      <span className="text-xs text-gray-400">
                        {ov.status === 'signed'
                          ? (ov.signer_name ? `✓ ${ov.signer_name}` : '✓ Signed')
                          : ov.status === 'current_user'   ? 'Your signature'
                          : ov.status === 'blocked'        ? 'Waiting for prior signer'
                          : ov.status === 'not_applicable' ? 'Not required'
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
