'use client'

import { useCallback, useEffect, useRef, useState } from 'react'
import { PenLine, Upload, Trash2, Save, RotateCcw, CheckCircle } from 'lucide-react'
import api from '@/lib/api'

// ── Types ─────────────────────────────────────────────────────────────────────

interface ExistingSig {
  image_data: string
  source: 'drawn' | 'uploaded'
  updated_at: string
}

type Tab = 'draw' | 'upload'

// ── White background removal ──────────────────────────────────────────────────

function removeWhiteBackground(file: File): Promise<string> {
  return new Promise((resolve, reject) => {
    const reader = new FileReader()
    reader.onerror = reject
    reader.onload = (e) => {
      const src = e.target?.result as string
      const img = new Image()
      img.onerror = reject
      img.onload = () => {
        const MAX_W = 600
        const MAX_H = 200
        let w = img.naturalWidth
        let h = img.naturalHeight
        if (w > MAX_W) { h = Math.round(h * MAX_W / w); w = MAX_W }
        if (h > MAX_H) { w = Math.round(w * MAX_H / h); h = MAX_H }

        const canvas = document.createElement('canvas')
        canvas.width  = w
        canvas.height = h
        const ctx = canvas.getContext('2d')!

        ctx.fillStyle = '#ffffff'
        ctx.fillRect(0, 0, w, h)
        ctx.drawImage(img, 0, 0, w, h)

        const imageData = ctx.getImageData(0, 0, w, h)
        const d = imageData.data
        for (let i = 0; i < d.length; i += 4) {
          if (d[i] > 220 && d[i + 1] > 220 && d[i + 2] > 220) {
            d[i + 3] = 0
          }
        }
        ctx.clearRect(0, 0, w, h)
        ctx.putImageData(imageData, 0, 0)

        resolve(canvas.toDataURL('image/png'))
      }
      img.src = src
    }
    reader.readAsDataURL(file)
  })
}

// ── Draw pad ──────────────────────────────────────────────────────────────────

function DrawPad({ onReady }: { onReady: (getDataUrl: () => string | null) => void }) {
  const canvasRef  = useRef<HTMLCanvasElement>(null)
  const isDrawing  = useRef(false)
  const hasStrokes = useRef(false)
  const lastPos    = useRef<{ x: number; y: number } | null>(null)

  const getCtx = () => canvasRef.current?.getContext('2d') ?? null

  const getPos = (e: MouseEvent | TouchEvent): { x: number; y: number } | null => {
    const canvas = canvasRef.current
    if (!canvas) return null
    const rect = canvas.getBoundingClientRect()
    const src  = 'touches' in e ? e.touches[0] : e
    return {
      x: (src.clientX - rect.left) * (canvas.width  / rect.width),
      y: (src.clientY - rect.top)  * (canvas.height / rect.height),
    }
  }

  useEffect(() => {
    const canvas = canvasRef.current
    if (!canvas) return
    const dpr  = window.devicePixelRatio || 1
    const rect = canvas.getBoundingClientRect()
    canvas.width  = rect.width  * dpr
    canvas.height = rect.height * dpr
    const ctx = canvas.getContext('2d')!
    ctx.scale(dpr, dpr)
    ctx.lineWidth   = 2.5
    ctx.lineCap     = 'round'
    ctx.lineJoin    = 'round'
    ctx.strokeStyle = '#1A4731'

    onReady(() => {
      if (!hasStrokes.current) return null
      return canvas.toDataURL('image/png')
    })
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  const startDraw = useCallback((e: MouseEvent | TouchEvent) => {
    e.preventDefault()
    isDrawing.current = true
    lastPos.current   = getPos(e)
  }, [])

  const draw = useCallback((e: MouseEvent | TouchEvent) => {
    e.preventDefault()
    if (!isDrawing.current) return
    const ctx = getCtx()
    const pos = getPos(e)
    if (!ctx || !pos || !lastPos.current) return
    ctx.beginPath()
    ctx.moveTo(lastPos.current.x, lastPos.current.y)
    ctx.lineTo(pos.x, pos.y)
    ctx.stroke()
    lastPos.current    = pos
    hasStrokes.current = true
  }, [])

  const stopDraw = useCallback(() => {
    isDrawing.current = false
    lastPos.current   = null
  }, [])

  const clearCanvas = () => {
    const canvas = canvasRef.current
    const ctx    = getCtx()
    if (!canvas || !ctx) return
    const dpr  = window.devicePixelRatio || 1
    const rect = canvas.getBoundingClientRect()
    ctx.clearRect(0, 0, rect.width * dpr, rect.height * dpr)
    hasStrokes.current = false
  }

  useEffect(() => {
    const canvas = canvasRef.current
    if (!canvas) return
    canvas.addEventListener('mousedown',  startDraw as EventListener)
    canvas.addEventListener('mousemove',  draw      as EventListener)
    canvas.addEventListener('mouseup',    stopDraw)
    canvas.addEventListener('mouseleave', stopDraw)
    canvas.addEventListener('touchstart', startDraw as EventListener, { passive: false })
    canvas.addEventListener('touchmove',  draw      as EventListener, { passive: false })
    canvas.addEventListener('touchend',   stopDraw)
    return () => {
      canvas.removeEventListener('mousedown',  startDraw as EventListener)
      canvas.removeEventListener('mousemove',  draw      as EventListener)
      canvas.removeEventListener('mouseup',    stopDraw)
      canvas.removeEventListener('mouseleave', stopDraw)
      canvas.removeEventListener('touchstart', startDraw as EventListener)
      canvas.removeEventListener('touchmove',  draw      as EventListener)
      canvas.removeEventListener('touchend',   stopDraw)
    }
  }, [startDraw, draw, stopDraw])

  return (
    <div>
      <canvas
        ref={canvasRef}
        className="w-full cursor-crosshair rounded-lg border-2 border-dashed border-gray-300 bg-white"
        style={{ height: 150, touchAction: 'none' }}
      />
      <button
        type="button"
        onClick={clearCanvas}
        className="mt-2 flex items-center gap-1.5 text-sm text-gray-400 hover:text-gray-600"
      >
        <RotateCcw size={14} />
        Clear
      </button>
    </div>
  )
}

// ── Main component ────────────────────────────────────────────────────────────

export function SignatureSettings() {
  const [existing,      setExisting]      = useState<ExistingSig | null | 'loading'>('loading')
  const [activeTab,     setActiveTab]     = useState<Tab>('draw')
  const [uploadPreview, setUploadPreview] = useState<string | null>(null)
  const [isSaving,      setIsSaving]      = useState(false)
  const [isDeleting,    setIsDeleting]    = useState(false)
  const [statusMsg,     setStatusMsg]     = useState<{ type: 'ok' | 'err'; text: string } | null>(null)

  const getDrawDataUrl = useRef<(() => string | null) | null>(null)

  useEffect(() => {
    api.get('/me/signature')
      .then((r) => setExisting(r.data ?? null))
      .catch(() => setExisting(null))
  }, [])

  const handleFileChange = async (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0]
    if (!file) return
    if (file.size > 8 * 1024 * 1024) {
      setStatusMsg({ type: 'err', text: 'File too large. Maximum 8 MB.' })
      return
    }
    try {
      const processed = await removeWhiteBackground(file)
      setUploadPreview(processed)
      setStatusMsg(null)
    } catch {
      setStatusMsg({ type: 'err', text: 'Could not process the image. Please try a JPG or PNG file.' })
    }
  }

  const handleSave = async () => {
    let imageData: string | null = null
    const source: 'drawn' | 'uploaded' = activeTab === 'draw' ? 'drawn' : 'uploaded'

    if (activeTab === 'draw') {
      imageData = getDrawDataUrl.current?.() ?? null
      if (!imageData) {
        setStatusMsg({ type: 'err', text: 'Please draw your signature before saving.' })
        return
      }
    } else {
      imageData = uploadPreview
      if (!imageData) {
        setStatusMsg({ type: 'err', text: 'Please upload an image first.' })
        return
      }
    }

    setIsSaving(true)
    setStatusMsg(null)
    try {
      await api.post('/me/signature', { image_data: imageData, source })
      const r = await api.get('/me/signature')
      setExisting(r.data ?? null)
      setStatusMsg({ type: 'ok', text: 'Signature saved successfully.' })
    } catch (err: unknown) {
      const msg = (err as { response?: { data?: { detail?: string } } })?.response?.data?.detail ?? 'Failed to save signature.'
      setStatusMsg({ type: 'err', text: msg })
    } finally {
      setIsSaving(false)
    }
  }

  const handleDelete = async () => {
    if (!confirm('Remove your saved signature?')) return
    setIsDeleting(true)
    try {
      await api.delete('/me/signature')
      setExisting(null)
      setUploadPreview(null)
      setStatusMsg({ type: 'ok', text: 'Signature removed.' })
    } catch {
      setStatusMsg({ type: 'err', text: 'Failed to remove signature.' })
    } finally {
      setIsDeleting(false)
    }
  }

  if (existing === 'loading') {
    return <p className="text-sm text-gray-400">Loading…</p>
  }

  return (
    <div className="mx-auto max-w-xl space-y-6">
      <div>
        <h2 className="text-lg font-semibold text-gray-900">My Signature</h2>
        <p className="mt-1 text-sm text-gray-500">
          This signature will be placed on documents you sign in the Certiva portal. Draw it
          with your mouse or trackpad, or upload a photo of your handwritten signature.
        </p>
      </div>

      {existing && (
        <div className="rounded-xl border border-gray-200 bg-white p-4">
          <p className="mb-2 text-xs font-medium uppercase tracking-wide text-gray-400">
            Current saved signature
          </p>
          <div className="flex items-center justify-between gap-4">
            <img
              src={existing.image_data}
              alt="Your saved signature"
              className="h-16 max-w-[300px] object-contain"
              style={{ background: 'repeating-conic-gradient(#f0f0f0 0% 25%, #fff 0% 50%) 0 0 / 12px 12px' }}
            />
            <button
              type="button"
              onClick={handleDelete}
              disabled={isDeleting}
              className="flex items-center gap-1.5 rounded-lg border border-red-200 px-3 py-1.5
                text-sm text-red-500 hover:bg-red-50 disabled:opacity-50"
            >
              <Trash2 size={14} />
              {isDeleting ? 'Removing…' : 'Remove'}
            </button>
          </div>
          <p className="mt-2 text-xs text-gray-400">
            Saved {new Date(existing.updated_at).toLocaleDateString()} · source: {existing.source}
          </p>
        </div>
      )}

      <div className="rounded-xl border border-gray-200 bg-white">
        <div className="flex border-b border-gray-100">
          {([['draw', 'Draw', PenLine], ['upload', 'Upload photo', Upload]] as const).map(([tab, label, Icon]) => (
            <button
              key={tab}
              type="button"
              onClick={() => { setActiveTab(tab); setStatusMsg(null) }}
              className={[
                'flex flex-1 items-center justify-center gap-2 py-3 text-sm font-medium transition-colors',
                activeTab === tab
                  ? 'border-b-2 border-[#1A4731] text-[#1A4731]'
                  : 'text-gray-400 hover:text-gray-600',
              ].join(' ')}
            >
              <Icon size={16} />
              {label}
            </button>
          ))}
        </div>

        <div className="p-5">
          {activeTab === 'draw' && (
            <div className="space-y-3">
              <p className="text-xs text-gray-400">
                Draw your signature in the box below using your mouse or finger.
              </p>
              <DrawPad onReady={(fn) => { getDrawDataUrl.current = fn }} />
            </div>
          )}

          {activeTab === 'upload' && (
            <div className="space-y-3">
              <p className="text-xs text-gray-400">
                Upload a JPG or PNG photo of your handwritten signature on white paper.
                The white background will be removed automatically.
              </p>
              <label className="flex cursor-pointer flex-col items-center justify-center rounded-lg
                border-2 border-dashed border-gray-300 bg-gray-50 p-6 transition-colors hover:border-gray-400">
                <Upload size={24} className="mb-2 text-gray-400" />
                <span className="text-sm text-gray-500">Click to select an image</span>
                <span className="mt-1 text-xs text-gray-400">JPG, PNG — max 8 MB</span>
                <input
                  type="file"
                  accept="image/jpeg,image/png"
                  className="sr-only"
                  onChange={handleFileChange}
                />
              </label>
              {uploadPreview && (
                <div className="rounded-lg border border-gray-200 p-3">
                  <p className="mb-2 text-xs font-medium text-gray-400">Preview (background removed)</p>
                  <img
                    src={uploadPreview}
                    alt="Processed signature preview"
                    className="h-20 max-w-full object-contain"
                    style={{ background: 'repeating-conic-gradient(#f0f0f0 0% 25%, #fff 0% 50%) 0 0 / 12px 12px' }}
                  />
                </div>
              )}
            </div>
          )}

          {statusMsg && (
            <div className={[
              'mt-3 flex items-center gap-2 rounded-lg px-3 py-2 text-sm',
              statusMsg.type === 'ok'
                ? 'bg-emerald-50 text-emerald-700'
                : 'bg-red-50 text-red-600',
            ].join(' ')}>
              {statusMsg.type === 'ok' && <CheckCircle size={15} />}
              {statusMsg.text}
            </div>
          )}

          <button
            type="button"
            onClick={handleSave}
            disabled={isSaving}
            className="mt-4 flex w-full items-center justify-center gap-2 rounded-lg py-2.5
              text-sm font-medium text-white transition-opacity disabled:opacity-60"
            style={{ background: '#1A4731' }}
          >
            <Save size={16} />
            {isSaving ? 'Saving…' : existing ? 'Update Signature' : 'Save Signature'}
          </button>
        </div>
      </div>
    </div>
  )
}
