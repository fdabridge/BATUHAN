'use client'

import { useEffect, useRef, useState } from 'react'
import api from '@/lib/api'

type PdfjsLib = typeof import('pdfjs-dist')
let cachedPdfjs: PdfjsLib | null = null

async function loadPdfjs() {
  if (cachedPdfjs) return cachedPdfjs
  const pdfjs = await import('pdfjs-dist')
  pdfjs.GlobalWorkerOptions.workerSrc =
    `//cdnjs.cloudflare.com/ajax/libs/pdf.js/${pdfjs.version}/pdf.worker.min.js`
  cachedPdfjs = pdfjs
  return pdfjs
}

interface TrainingMaterialViewerProps {
  blobUrl: string | null
  kind: string
  fileName?: string | null
  assignmentId?: string | null
  materialPageCount?: number | null
  initialLastPageSeen?: number
  completed?: boolean
  onCanCompleteChange?: (canComplete: boolean) => void
}

export function TrainingMaterialViewer({
  blobUrl,
  kind,
  fileName,
  assignmentId,
  materialPageCount,
  initialLastPageSeen = 0,
  completed = false,
  onCanCompleteChange,
}: TrainingMaterialViewerProps) {
  const canvasRef = useRef<HTMLCanvasElement | null>(null)
  const [pdfDoc, setPdfDoc] = useState<any>(null)
  const [page, setPage] = useState(Math.max(1, initialLastPageSeen || 1))
  const [pageCount, setPageCount] = useState(materialPageCount || 0)
  const [zoom, setZoom] = useState(1.1)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState('')

  const isPdf = kind === 'pdf'
  const lastPageReached = !isPdf || completed || (!!pageCount && page >= pageCount)

  useEffect(() => {
    onCanCompleteChange?.(lastPageReached)
  }, [lastPageReached, onCanCompleteChange])

  useEffect(() => {
    let cancelled = false
    async function loadPdf() {
      if (!blobUrl || !isPdf) return
      setLoading(true)
      setError('')
      try {
        const [pdfjs, data] = await Promise.all([
          loadPdfjs(),
          fetch(blobUrl).then((r) => r.arrayBuffer()),
        ])
        const doc = await (pdfjs as any).getDocument({ data }).promise
        if (cancelled) return
        setPdfDoc(doc)
        setPageCount(materialPageCount || doc.numPages)
        setPage((current) => Math.min(Math.max(current, 1), materialPageCount || doc.numPages))
      } catch {
        if (!cancelled) setError('Unable to display this PDF training material.')
      } finally {
        if (!cancelled) setLoading(false)
      }
    }
    loadPdf()
    return () => { cancelled = true }
  }, [blobUrl, isPdf, materialPageCount])

  useEffect(() => {
    let cancelled = false
    async function renderPage() {
      if (!pdfDoc || !canvasRef.current) return
      const pdfPage = await pdfDoc.getPage(page)
      if (cancelled) return
      const viewport = pdfPage.getViewport({ scale: zoom })
      const canvas = canvasRef.current
      const ctx = canvas.getContext('2d')
      if (!ctx) return
      canvas.width = viewport.width
      canvas.height = viewport.height
      await pdfPage.render({ canvasContext: ctx, viewport }).promise
    }
    renderPage()
    return () => { cancelled = true }
  }, [pdfDoc, page, zoom])

  useEffect(() => {
    if (!assignmentId || !isPdf || !pageCount) return
    api.post(`/trainings/assignments/${assignmentId}/training-progress`, { page_number: page })
      .catch(() => undefined)
  }, [assignmentId, isPdf, page, pageCount])

  if (!blobUrl) {
    return (
      <div className="flex items-center justify-center p-12 text-sm text-gray-400">
        No training material uploaded for this course.
      </div>
    )
  }

  if (kind === 'video') {
    return (
      <video src={blobUrl} controls className="h-[75vh] w-full rounded-lg bg-black">
        Your browser does not support video playback.
      </video>
    )
  }

  if (!isPdf) {
    return (
      <div className="flex h-[75vh] flex-col items-center justify-center gap-3 text-center">
        <p className="text-sm font-medium text-gray-700">{fileName || 'Training material'}</p>
        <p className="max-w-md text-sm text-gray-400">
          Controlled slide viewing is available for PDF training material. Export PPT/PPTX slides as PDF and upload the PDF version.
        </p>
      </div>
    )
  }

  return (
    <div className="flex h-[75vh] flex-col">
      <div className="flex items-center justify-between border-b border-gray-100 px-4 py-3">
        <div className="text-sm font-medium text-gray-700">
          Page {page} of {pageCount || '...'}
        </div>
        <div className="flex items-center gap-2">
          <button
            type="button"
            onClick={() => setPage((p) => Math.max(1, p - 1))}
            disabled={page <= 1}
            className="rounded border border-gray-200 px-3 py-1 text-sm text-gray-600 disabled:opacity-40"
          >
            Back
          </button>
          <button
            type="button"
            onClick={() => setPage((p) => Math.min(pageCount || p, p + 1))}
            disabled={!pageCount || page >= pageCount}
            className="rounded border border-gray-200 px-3 py-1 text-sm text-gray-600 disabled:opacity-40"
          >
            Next
          </button>
          <button
            type="button"
            onClick={() => setZoom((z) => Math.max(0.6, Number((z - 0.15).toFixed(2))))}
            className="rounded border border-gray-200 px-2.5 py-1 text-sm text-gray-600"
          >
            -
          </button>
          <span className="w-12 text-center text-xs text-gray-400">{Math.round(zoom * 100)}%</span>
          <button
            type="button"
            onClick={() => setZoom((z) => Math.min(2.2, Number((z + 0.15).toFixed(2))))}
            className="rounded border border-gray-200 px-2.5 py-1 text-sm text-gray-600"
          >
            +
          </button>
        </div>
      </div>
      {error ? (
        <div className="flex flex-1 items-center justify-center text-sm text-red-500">{error}</div>
      ) : loading ? (
        <div className="flex flex-1 items-center justify-center text-sm text-gray-400">Loading pages...</div>
      ) : (
        <div className="flex-1 overflow-auto bg-gray-100 p-6">
          <canvas ref={canvasRef} className="mx-auto rounded bg-white shadow" />
        </div>
      )}
    </div>
  )
}
