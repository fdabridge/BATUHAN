'use client'

import { useCallback, useEffect, useRef, useState } from 'react'
import { Loader2, PenLine, Pencil, Plus, RotateCcw, Trash2, Upload, X } from 'lucide-react'
import api from '@/lib/api'
import { removeWhiteBackground, MAX_SIGNATURE_FILE_BYTES } from '@/lib/signatureUtils'

interface OrgEmployee {
  id: string
  full_name: string
  role_title: string
  is_active: boolean
  has_signature: boolean
  signature_source: 'drawn' | 'uploaded' | null
  created_at: string
  updated_at: string
}

const inputCls = 'w-full rounded-lg border border-gray-200 px-3 py-2 text-sm text-gray-800 placeholder-gray-400 outline-none focus:border-[#1A4731] focus:ring-2 focus:ring-[#1A4731]/20'
const lblCls   = 'mb-1 block text-xs font-medium text-gray-500'
type SignatureSource = 'drawn' | 'uploaded'
type SignaturePayload = { image_data: string; source: SignatureSource }

function extractDetail(err: unknown, fallback: string): string {
  const e = err as { response?: { data?: { detail?: string } }; message?: string }
  return e?.response?.data?.detail || e?.message || fallback
}

export default function ClientEmployeesPage() {
  const [list,    setList]    = useState<OrgEmployee[]>([])
  const [loading, setLoading] = useState(true)
  const [error,   setError]   = useState<string | null>(null)

  const [createOpen, setCreateOpen] = useState(false)
  const [editTarget, setEditTarget] = useState<OrgEmployee | null>(null)
  const [sigTarget,  setSigTarget]  = useState<OrgEmployee | null>(null)

  async function load() {
    setLoading(true)
    try {
      const r = await api.get<OrgEmployee[]>('/org/employees')
      setList(r.data)
      setError(null)
    } catch (e) {
      setError(extractDetail(e, 'Failed to load employees.'))
    } finally {
      setLoading(false)
    }
  }
  useEffect(() => { load() }, [])

  async function handleDelete(emp: OrgEmployee) {
    if (!window.confirm(`Remove ${emp.full_name} from your roster?`)) return
    try {
      await api.delete(`/org/employees/${emp.id}`)
      load()
    } catch (e) {
      window.alert(extractDetail(e, 'Failed to delete.'))
    }
  }

  return (
    <div className="p-6">
      <div className="mb-6 flex items-center justify-between">
        <div>
          <h1 className="text-xl font-semibold text-gray-900">Organisation Personnel</h1>
          <p className="mt-1 text-sm text-gray-500">
            Manage the people from your organisation who will attend audits and sign meeting forms.
          </p>
        </div>
        <button
          type="button"
          onClick={() => setCreateOpen(true)}
          className="flex items-center gap-1 rounded-lg bg-[#1A4731] px-3 py-2 text-sm font-medium text-white hover:opacity-90"
        >
          <Plus size={14} /> Add employee
        </button>
      </div>

      <div className="overflow-hidden rounded-lg border border-gray-100 bg-white">
        <table className="w-full text-sm">
          <thead>
            <tr className="border-b border-gray-100 bg-gray-50 text-left text-xs font-medium text-gray-500">
              <th className="px-4 py-3">Name</th>
              <th className="px-4 py-3">Role / Title</th>
              <th className="px-4 py-3">Signature</th>
              <th className="px-4 py-3 text-right">Actions</th>
            </tr>
          </thead>
          <tbody>
            {loading && (
              <tr><td colSpan={4} className="py-10 text-center text-sm text-gray-400">
                <Loader2 size={16} className="mx-auto animate-spin" />
              </td></tr>
            )}
            {!loading && error && (
              <tr><td colSpan={4} className="py-10 text-center text-sm text-red-500">{error}</td></tr>
            )}
            {!loading && !error && list.length === 0 && (
              <tr><td colSpan={4} className="py-10 text-center text-sm text-gray-400">
                No employees yet. Add your first person.
              </td></tr>
            )}
            {list.map((e) => (
              <tr key={e.id} className="border-b border-gray-50 last:border-0">
                <td className="px-4 py-3 font-medium text-gray-800">{e.full_name}</td>
                <td className="px-4 py-3 text-gray-600">{e.role_title}</td>
                <td className="px-4 py-3">
                  {e.has_signature ? (
                    <span className="rounded bg-[#F0FAF4] px-2 py-0.5 text-xs font-medium text-[#1A4731]">
                      ✓ On file
                    </span>
                  ) : (
                    <span className="rounded bg-amber-50 px-2 py-0.5 text-xs font-medium text-amber-700">
                      Missing
                    </span>
                  )}
                </td>
                <td className="px-4 py-3">
                  <div className="flex items-center justify-end gap-2">
                    <button onClick={() => setSigTarget(e)} className="text-gray-400 hover:text-gray-700" aria-label="Set signature" title="Set signature">
                      <Upload size={16} />
                    </button>
                    <button onClick={() => setEditTarget(e)} className="text-gray-400 hover:text-gray-700" aria-label="Edit">
                      <Pencil size={16} />
                    </button>
                    <button onClick={() => handleDelete(e)} className="text-gray-400 hover:text-gray-700" aria-label="Delete">
                      <Trash2 size={16} />
                    </button>
                  </div>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      <CreateModal open={createOpen} onClose={() => setCreateOpen(false)} onSuccess={() => { setCreateOpen(false); load() }} />
      <EditModal   target={editTarget} onClose={() => setEditTarget(null)} onSuccess={() => { setEditTarget(null); load() }} />
      <SignatureModal target={sigTarget} onClose={() => setSigTarget(null)} onSuccess={() => { setSigTarget(null); load() }} />
    </div>
  )
}

// ── Modal shell ───────────────────────────────────────────────────────────────

function Modal({ open, title, onClose, children }: {
  open: boolean; title: string; onClose: () => void; children: React.ReactNode
}) {
  if (!open) return null
  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 p-4">
      <div className="w-full max-w-lg rounded-lg bg-white shadow-xl">
        <div className="flex items-start justify-between border-b border-gray-100 px-5 py-3">
          <h2 className="text-sm font-semibold text-gray-800">{title}</h2>
          <button onClick={onClose} className="text-gray-400 hover:text-gray-700" aria-label="Close">
            <X size={16} />
          </button>
        </div>
        <div className="px-5 py-4">{children}</div>
      </div>
    </div>
  )
}

// ── Signature input ──────────────────────────────────────────────────────────

function SignatureDrawPad({ onReady }: { onReady: (getDataUrl: () => string | null) => void }) {
  const canvasRef = useRef<HTMLCanvasElement>(null)
  const drawing = useRef(false)
  const hasStrokes = useRef(false)
  const last = useRef<{ x: number; y: number } | null>(null)

  const getCtx = () => canvasRef.current?.getContext('2d') ?? null

  const getPoint = (event: MouseEvent | TouchEvent): { x: number; y: number } | null => {
    const canvas = canvasRef.current
    if (!canvas) return null
    const rect = canvas.getBoundingClientRect()
    const source = 'touches' in event ? event.touches[0] : event
    if (!source || rect.width <= 0 || rect.height <= 0) return null
    return {
      x: source.clientX - rect.left,
      y: source.clientY - rect.top,
    }
  }

  function configureCanvas() {
    const canvas = canvasRef.current
    if (!canvas) return
    const dpr = window.devicePixelRatio || 1
    const rect = canvas.getBoundingClientRect()
    canvas.width = Math.max(1, rect.width * dpr)
    canvas.height = Math.max(1, rect.height * dpr)
    const ctx = getCtx()
    if (!ctx) return
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0)
    ctx.lineWidth = 2.5
    ctx.lineCap = 'round'
    ctx.lineJoin = 'round'
    ctx.strokeStyle = '#1A4731'
    hasStrokes.current = false
    last.current = null
  }

  useEffect(() => {
    const frame = window.requestAnimationFrame(configureCanvas)
    onReady(() => {
      if (!hasStrokes.current) return null
      return canvasRef.current?.toDataURL('image/png') ?? null
    })
    return () => window.cancelAnimationFrame(frame)
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  const start = useCallback((event: MouseEvent | TouchEvent) => {
    event.preventDefault()
    drawing.current = true
    last.current = getPoint(event)
  }, [])

  const move = useCallback((event: MouseEvent | TouchEvent) => {
    event.preventDefault()
    if (!drawing.current || !last.current) return
    const ctx = getCtx()
    const next = getPoint(event)
    if (!ctx || !next) return
    ctx.beginPath()
    ctx.moveTo(last.current.x, last.current.y)
    ctx.lineTo(next.x, next.y)
    ctx.stroke()
    last.current = next
    hasStrokes.current = true
  }, [])

  const stop = useCallback(() => {
    drawing.current = false
    last.current = null
  }, [])

  useEffect(() => {
    const canvas = canvasRef.current
    if (!canvas) return
    canvas.addEventListener('mousedown', start as EventListener)
    canvas.addEventListener('mousemove', move as EventListener)
    canvas.addEventListener('mouseup', stop)
    canvas.addEventListener('mouseleave', stop)
    canvas.addEventListener('touchstart', start as EventListener, { passive: false })
    canvas.addEventListener('touchmove', move as EventListener, { passive: false })
    canvas.addEventListener('touchend', stop)
    canvas.addEventListener('touchcancel', stop)
    return () => {
      canvas.removeEventListener('mousedown', start as EventListener)
      canvas.removeEventListener('mousemove', move as EventListener)
      canvas.removeEventListener('mouseup', stop)
      canvas.removeEventListener('mouseleave', stop)
      canvas.removeEventListener('touchstart', start as EventListener)
      canvas.removeEventListener('touchmove', move as EventListener)
      canvas.removeEventListener('touchend', stop)
      canvas.removeEventListener('touchcancel', stop)
    }
  }, [start, move, stop])

  return (
    <div>
      <canvas
        ref={canvasRef}
        className="w-full cursor-crosshair rounded-lg border-2 border-dashed border-gray-300 bg-white"
        style={{ height: 130, touchAction: 'none' }}
      />
      <button
        type="button"
        onClick={configureCanvas}
        className="mt-2 flex items-center gap-1.5 text-xs text-gray-400 hover:text-gray-600"
      >
        <RotateCcw size={13} />
        Clear drawing
      </button>
    </div>
  )
}

function EmployeeSignatureInput({
  registerGetter,
  optional = false,
}: {
  registerGetter: (getter: () => SignaturePayload | null) => void
  optional?: boolean
}) {
  const [tab, setTab] = useState<SignatureSource>('drawn')
  const [uploadPreview, setUploadPreview] = useState<string | null>(null)
  const [processing, setProcessing] = useState(false)
  const [err, setErr] = useState<string | null>(null)
  const drawGetter = useRef<(() => string | null) | null>(null)

  useEffect(() => {
    registerGetter(() => {
      if (tab === 'drawn') {
        const imageData = drawGetter.current?.() ?? null
        return imageData ? { image_data: imageData, source: 'drawn' } : null
      }
      return uploadPreview ? { image_data: uploadPreview, source: 'uploaded' } : null
    })
  }, [registerGetter, tab, uploadPreview])

  async function onFile(ev: React.ChangeEvent<HTMLInputElement>) {
    const file = ev.target.files?.[0]
    if (!file) return
    if (!['image/png', 'image/jpeg'].includes(file.type)) {
      setErr('Please upload a JPG or PNG image.')
      return
    }
    if (file.size > MAX_SIGNATURE_FILE_BYTES) {
      setErr('Image is too large. Please use an image under 10 MB.')
      return
    }
    setProcessing(true)
    setErr(null)
    try {
      setUploadPreview(await removeWhiteBackground(file))
    } catch {
      setErr('Could not process the image. Please try a different file.')
    } finally {
      setProcessing(false)
    }
  }

  return (
    <div className="rounded-lg border border-gray-100 bg-gray-50">
      <div className="flex border-b border-gray-100 bg-white">
        {([
          ['drawn', 'Draw signature', PenLine],
          ['uploaded', 'Upload photo', Upload],
        ] as const).map(([value, label, Icon]) => (
          <button
            key={value}
            type="button"
            onClick={() => { setTab(value); setErr(null) }}
            className={[
              'flex flex-1 items-center justify-center gap-2 py-2.5 text-xs font-medium transition-colors',
              tab === value
                ? 'border-b-2 border-[#1A4731] text-[#1A4731]'
                : 'text-gray-400 hover:text-gray-600',
            ].join(' ')}
          >
            <Icon size={14} />
            {label}
          </button>
        ))}
      </div>
      <div className="space-y-3 p-3">
        <p className="text-xs text-gray-500">
          {optional
            ? 'Optional but recommended: add the employee signature now, so meeting forms can be signed without extra setup later.'
            : "Draw or upload this employee signature. It will be used for that employee's document slots."}
        </p>
        {tab === 'drawn' ? (
          <SignatureDrawPad onReady={(fn) => { drawGetter.current = fn }} />
        ) : (
          <div className="space-y-3">
            <label className="flex cursor-pointer flex-col items-center justify-center rounded-lg border-2 border-dashed border-gray-300 bg-white px-4 py-5 text-center hover:border-[#1A4731]">
              <Upload size={20} className="mb-1 text-gray-400" />
              <span className="text-sm text-gray-600">{processing ? 'Processing…' : 'Choose JPG or PNG file'}</span>
              <span className="text-xs text-gray-400">White background is removed automatically</span>
              <input type="file" accept="image/jpeg,image/png" onChange={onFile} className="sr-only" />
            </label>
            {uploadPreview && !processing && (
              <div className="rounded border border-gray-100 bg-white p-3">
                <p className="mb-1 text-xs text-gray-400">Preview</p>
                <img
                  src={uploadPreview}
                  alt="Signature preview"
                  className="mx-auto max-h-20 object-contain"
                  style={{ background: 'repeating-conic-gradient(#f0f0f0 0% 25%, #fff 0% 50%) 0 0 / 12px 12px' }}
                />
              </div>
            )}
          </div>
        )}
        {err && <div className="rounded border border-red-200 bg-red-50 px-3 py-2 text-xs text-red-700">{err}</div>}
      </div>
    </div>
  )
}

// ── Create modal ──────────────────────────────────────────────────────────────

function CreateModal({ open, onClose, onSuccess }: {
  open: boolean; onClose: () => void; onSuccess: () => void
}) {
  const [fullName, setFullName] = useState('')
  const [role,     setRole]     = useState('')
  const [busy,     setBusy]     = useState(false)
  const [err,      setErr]      = useState<string | null>(null)
  const signatureGetter = useRef<() => SignaturePayload | null>(() => null)

  useEffect(() => { if (open) { setFullName(''); setRole(''); setErr(null) } }, [open])

  async function submit(ev: React.FormEvent) {
    ev.preventDefault()
    if (!fullName.trim() || !role.trim()) { setErr('Both fields are required.'); return }
    setBusy(true); setErr(null)
    try {
      const created = await api.post<OrgEmployee>('/org/employees', {
        full_name: fullName.trim(),
        role_title: role.trim(),
      })
      const signature = signatureGetter.current?.() ?? null
      if (signature) {
        try {
          await api.post(`/org/employees/${created.data.id}/signature`, signature)
        } catch {
          window.alert('Employee was created, but the signature could not be saved. Open the employee row and save the signature again.')
        }
      }
      onSuccess()
    } catch (e) {
      setErr(extractDetail(e, 'Failed to create.'))
    } finally {
      setBusy(false)
    }
  }

  return (
    <Modal open={open} title="Add employee" onClose={onClose}>
      <form onSubmit={submit} className="space-y-3">
        <div>
          <label className={lblCls}>Full name *</label>
          <input className={inputCls} value={fullName} onChange={(e) => setFullName(e.target.value)} />
        </div>
        <div>
          <label className={lblCls}>Role / Title *</label>
          <input className={inputCls} value={role} onChange={(e) => setRole(e.target.value)} placeholder="e.g. Quality Manager" />
        </div>
        <div>
          <label className={lblCls}>Employee signature</label>
          <EmployeeSignatureInput
            optional
            registerGetter={(getter) => { signatureGetter.current = getter }}
          />
        </div>
        {err && <div className="rounded border border-red-200 bg-red-50 px-3 py-2 text-xs text-red-700">{err}</div>}
        <button type="submit" disabled={busy}
          className="flex w-full items-center justify-center gap-2 rounded-lg bg-[#1A4731] px-4 py-2 text-sm font-medium text-white hover:opacity-90 disabled:opacity-60">
          {busy && <Loader2 size={14} className="animate-spin" />}
          {busy ? 'Creating…' : 'Create'}
        </button>
      </form>
    </Modal>
  )
}

// ── Edit modal ────────────────────────────────────────────────────────────────

function EditModal({ target, onClose, onSuccess }: {
  target: OrgEmployee | null; onClose: () => void; onSuccess: () => void
}) {
  const [fullName, setFullName] = useState('')
  const [role,     setRole]     = useState('')
  const [active,   setActive]   = useState(true)
  const [busy,     setBusy]     = useState(false)
  const [err,      setErr]      = useState<string | null>(null)

  useEffect(() => {
    if (target) {
      setFullName(target.full_name)
      setRole(target.role_title)
      setActive(target.is_active)
      setErr(null)
    }
  }, [target])

  async function submit(ev: React.FormEvent) {
    ev.preventDefault()
    if (!target) return
    if (!fullName.trim() || !role.trim()) { setErr('Both fields are required.'); return }
    setBusy(true); setErr(null)
    try {
      await api.patch(`/org/employees/${target.id}`, {
        full_name:  fullName.trim(),
        role_title: role.trim(),
        is_active:  active,
      })
      onSuccess()
    } catch (e) {
      setErr(extractDetail(e, 'Failed to save.'))
    } finally {
      setBusy(false)
    }
  }

  return (
    <Modal open={!!target} title="Edit employee" onClose={onClose}>
      <form onSubmit={submit} className="space-y-3">
        <div>
          <label className={lblCls}>Full name *</label>
          <input className={inputCls} value={fullName} onChange={(e) => setFullName(e.target.value)} />
        </div>
        <div>
          <label className={lblCls}>Role / Title *</label>
          <input className={inputCls} value={role} onChange={(e) => setRole(e.target.value)} />
        </div>
        <label className="flex items-center gap-2 text-sm text-gray-700">
          <input type="checkbox" checked={active} onChange={(e) => setActive(e.target.checked)} />
          Active
        </label>
        {err && <div className="rounded border border-red-200 bg-red-50 px-3 py-2 text-xs text-red-700">{err}</div>}
        <button type="submit" disabled={busy}
          className="flex w-full items-center justify-center gap-2 rounded-lg bg-[#1A4731] px-4 py-2 text-sm font-medium text-white hover:opacity-90 disabled:opacity-60">
          {busy && <Loader2 size={14} className="animate-spin" />}
          {busy ? 'Saving…' : 'Save changes'}
        </button>
      </form>
    </Modal>
  )
}

// ── Signature modal ───────────────────────────────────────────────────────────

function SignatureModal({ target, onClose, onSuccess }: {
  target: OrgEmployee | null; onClose: () => void; onSuccess: () => void
}) {
  const [busy,       setBusy]       = useState(false)
  const [err,        setErr]        = useState<string | null>(null)
  const signatureGetter = useRef<() => SignaturePayload | null>(() => null)

  useEffect(() => {
    if (!target) setErr(null)
  }, [target])

  async function submit() {
    if (!target) return
    const signature = signatureGetter.current?.() ?? null
    if (!signature) {
      setErr('Draw or upload a signature before saving.')
      return
    }
    setBusy(true); setErr(null)
    try {
      await api.post(`/org/employees/${target.id}/signature`, signature)
      onSuccess()
    } catch (e) {
      setErr(extractDetail(e, 'Failed to save signature.'))
    } finally {
      setBusy(false)
    }
  }

  return (
    <Modal open={!!target} title={target ? `Signature — ${target.full_name}` : 'Signature'} onClose={onClose}>
      <div className="space-y-3">
        <p className="text-xs text-gray-500">
          Draw this employee&apos;s signature or upload a photo/scan. This is the signature
          used for that employee&apos;s document slots.
        </p>
        <EmployeeSignatureInput
          registerGetter={(getter) => { signatureGetter.current = getter }}
        />
        {err && <div className="rounded border border-red-200 bg-red-50 px-3 py-2 text-xs text-red-700">{err}</div>}
        <button type="button" onClick={submit} disabled={busy}
          className="flex w-full items-center justify-center gap-2 rounded-lg bg-[#1A4731] px-4 py-2 text-sm font-medium text-white hover:opacity-90 disabled:opacity-60">
          {busy && <Loader2 size={14} className="animate-spin" />}
          {busy ? 'Saving…' : 'Save signature'}
        </button>
      </div>
    </Modal>
  )
}
