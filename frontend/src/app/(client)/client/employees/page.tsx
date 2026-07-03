'use client'

import { useEffect, useRef, useState } from 'react'
import { Loader2, Pencil, Plus, Trash2, Upload, X } from 'lucide-react'
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
                    <button onClick={() => setSigTarget(e)} className="text-gray-400 hover:text-gray-700" aria-label="Upload signature" title="Upload signature">
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
      <div className="w-full max-w-md rounded-lg bg-white shadow-xl">
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

// ── Create modal ──────────────────────────────────────────────────────────────

function CreateModal({ open, onClose, onSuccess }: {
  open: boolean; onClose: () => void; onSuccess: () => void
}) {
  const [fullName, setFullName] = useState('')
  const [role,     setRole]     = useState('')
  const [busy,     setBusy]     = useState(false)
  const [err,      setErr]      = useState<string | null>(null)

  useEffect(() => { if (open) { setFullName(''); setRole(''); setErr(null) } }, [open])

  async function submit(ev: React.FormEvent) {
    ev.preventDefault()
    if (!fullName.trim() || !role.trim()) { setErr('Both fields are required.'); return }
    setBusy(true); setErr(null)
    try {
      await api.post('/org/employees', { full_name: fullName.trim(), role_title: role.trim() })
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
  const fileRef = useRef<HTMLInputElement>(null)
  const [preview,    setPreview]    = useState<string | null>(null)
  const [processing, setProcessing] = useState(false)
  const [busy,       setBusy]       = useState(false)
  const [err,        setErr]        = useState<string | null>(null)

  useEffect(() => {
    if (!target) { setPreview(null); setErr(null) }
  }, [target])

  async function onFile(ev: React.ChangeEvent<HTMLInputElement>) {
    const f = ev.target.files?.[0]
    if (!f) return
    if (!['image/png', 'image/jpeg'].includes(f.type)) {
      setErr('Please upload a JPG or PNG image.')
      return
    }
    if (f.size > MAX_SIGNATURE_FILE_BYTES) {
      setErr('Image is too large. Please use an image under 10 MB.')
      return
    }
    setProcessing(true)
    setErr(null)
    try {
      const processed = await removeWhiteBackground(f)
      setPreview(processed)
    } catch {
      setErr('Could not process the image. Please try a different file.')
    } finally {
      setProcessing(false)
    }
  }

  async function submit() {
    if (!target || !preview) return
    setBusy(true); setErr(null)
    try {
      await api.post(`/org/employees/${target.id}/signature`, { image_data: preview, source: 'uploaded' })
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
          Upload a photo or scan of this person&apos;s handwritten signature. The white
          background will be removed automatically. JPG or PNG accepted.
        </p>
        <input ref={fileRef} type="file" accept="image/jpeg,image/png" onChange={onFile} className="hidden" />
        <button type="button" onClick={() => fileRef.current?.click()}
          className="flex w-full items-center justify-center gap-2 rounded-lg border border-dashed border-gray-300 px-4 py-6 text-sm text-gray-600 hover:border-[#1A4731] hover:text-[#1A4731]">
          <Upload size={16} />
          {processing ? 'Processing…' : preview ? 'Choose a different file' : 'Choose JPG or PNG file'}
        </button>
        {preview && !processing && (
          <div className="rounded border border-gray-100 bg-gray-50 p-3">
            <p className="mb-1 text-xs text-gray-400">Preview (background removed)</p>
            <img
              src={preview}
              alt="Signature preview"
              className="mx-auto max-h-24 object-contain"
              style={{ background: 'repeating-conic-gradient(#f0f0f0 0% 25%, #fff 0% 50%) 0 0 / 12px 12px' }}
            />
          </div>
        )}
        {err && <div className="rounded border border-red-200 bg-red-50 px-3 py-2 text-xs text-red-700">{err}</div>}
        <button type="button" onClick={submit} disabled={busy || !preview || processing}
          className="flex w-full items-center justify-center gap-2 rounded-lg bg-[#1A4731] px-4 py-2 text-sm font-medium text-white hover:opacity-90 disabled:opacity-60">
          {busy && <Loader2 size={14} className="animate-spin" />}
          {busy ? 'Saving…' : 'Save signature'}
        </button>
      </div>
    </Modal>
  )
}
