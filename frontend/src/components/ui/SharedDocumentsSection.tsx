'use client'

import { useEffect, useRef, useState } from 'react'
import api from '@/lib/api'

interface SharedDoc {
  id: string
  label: string
  document_type: string
  direction: 'cb_to_client' | 'auditor_to_cb'
  status: 'pending_cb_signature' | 'released' | 'signed' | 'uploaded'
  released_at: string | null
  signed_at: string | null
  signed_by: string | null
  cb_sig_status: 'pending' | 'signed' | null
  cb_sig_id: string | null
}

const DOC_TYPES = [
  { value: 'quotation',   label: 'Quotation' },
  { value: 'agreement',   label: 'Agreement' },
  { value: 'certificate', label: 'Certificate' },
]

function fmtDate(iso: string | null): string {
  if (!iso) return '—'
  return new Date(iso).toLocaleDateString('en-GB', {
    day: 'numeric', month: 'short', year: 'numeric',
  })
}

export function SharedDocumentsSection({ auditSetId }: { auditSetId: string }) {
  const [docs, setDocs]     = useState<SharedDoc[]>([])
  const [loading, setLoading] = useState(true)
  const [showForm, setShowForm] = useState(false)
  const [label, setLabel]     = useState('')
  const [docType, setDocType] = useState('quotation')
  const [file, setFile]       = useState<File | null>(null)
  const [submitting, setSubmitting] = useState(false)
  const [error, setError]     = useState('')
  const fileRef = useRef<HTMLInputElement>(null)

  async function load() {
    try {
      const r = await api.get<SharedDoc[]>(`/audit-sets/${auditSetId}/documents`)
      setDocs(r.data)
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => { load() }, [auditSetId])

  async function release() {
    setError('')
    if (!label.trim()) { setError('Label is required.'); return }
    if (!file)         { setError('Please select a file to upload.'); return }
    setSubmitting(true)
    try {
      const fd = new FormData()
      fd.append('label', label.trim())
      fd.append('document_type', docType)
      fd.append('file', file)
      await api.post(`/audit-sets/${auditSetId}/documents/release`, fd, {
        headers: { 'Content-Type': 'multipart/form-data' },
      })
      setLabel(''); setFile(null); setDocType('quotation')
      if (fileRef.current) fileRef.current.value = ''
      setShowForm(false)
      await load()
    } catch (err: unknown) {
      const detail = (err as { response?: { data?: { detail?: string } } })
        ?.response?.data?.detail
      setError(detail || 'Failed to release document.')
    } finally {
      setSubmitting(false)
    }
  }

  async function downloadDoc(docId: string, docLabel: string) {
    try {
      const r = await api.get(
        `/audit-sets/${auditSetId}/documents/${docId}/download`,
        { responseType: 'blob' },
      )
      const url = window.URL.createObjectURL(r.data as Blob)
      const a = document.createElement('a')
      a.href = url
      a.download = docLabel
      document.body.appendChild(a)
      a.click()
      a.remove()
      window.URL.revokeObjectURL(url)
    } catch {
      alert('Could not download document.')
    }
  }

  return (
    <div className="mt-8">
      <div className="mb-3 flex items-center justify-between">
        <h2 className="text-sm font-semibold uppercase tracking-wide text-gray-700">
          Shared Documents
        </h2>
        <button
          type="button"
          onClick={() => setShowForm((s) => !s)}
          className="rounded-lg bg-[#1A4731] px-3 py-1.5 text-xs font-medium text-white hover:bg-[#143828]"
        >
          {showForm ? 'Cancel' : '+ Release Document'}
        </button>
      </div>

      {showForm && (
        <div className="mb-4 rounded-xl border bg-white p-4">
          <div className="grid grid-cols-1 gap-3 md:grid-cols-3">
            <div>
              <label className="block text-xs font-medium text-gray-500">Label</label>
              <input
                value={label}
                onChange={(e) => setLabel(e.target.value)}
                placeholder="Quotation (FR.220)"
                className="mt-1 w-full rounded-lg border px-3 py-1.5 text-sm focus:outline-none focus:ring-2 focus:ring-[#1A4731]/30"
              />
            </div>
            <div>
              <label className="block text-xs font-medium text-gray-500">Type</label>
              <select
                value={docType}
                onChange={(e) => setDocType(e.target.value)}
                className="mt-1 w-full rounded-lg border px-3 py-1.5 text-sm focus:outline-none focus:ring-2 focus:ring-[#1A4731]/30"
              >
                {DOC_TYPES.map((t) => (
                  <option key={t.value} value={t.value}>{t.label}</option>
                ))}
              </select>
            </div>
            <div>
              <label className="block text-xs font-medium text-gray-500">File</label>
              <input
                ref={fileRef}
                type="file"
                accept=".docx,.pdf"
                onChange={(e) => setFile(e.target.files?.[0] ?? null)}
                className="mt-1 w-full rounded-lg border px-3 py-1.5 text-sm text-gray-700 file:mr-2 file:rounded file:border-0 file:bg-gray-100 file:px-2 file:py-0.5 file:text-xs focus:outline-none"
              />
            </div>
          </div>
          {error && <p className="mt-2 text-xs text-red-500">{error}</p>}
          <button
            type="button"
            onClick={release}
            disabled={submitting}
            className="mt-3 rounded-lg bg-[#1A4731] px-4 py-1.5 text-sm font-medium text-white disabled:opacity-40"
          >
            {submitting ? 'Uploading…' : 'Release to Client'}
          </button>
        </div>
      )}

      <div className="rounded-xl border bg-white">
        {loading ? (
          <p className="p-6 text-sm text-gray-400">Loading…</p>
        ) : docs.length === 0 ? (
          <p className="p-6 text-sm text-gray-400">No documents released yet.</p>
        ) : (
          <ul className="divide-y">
            {docs.map((d) => (
              <li key={d.id} className="flex items-center justify-between px-4 py-3">
                <div>
                  <p className="text-sm font-medium text-gray-800">{d.label}</p>
                  <p className="mt-0.5 text-xs text-gray-400">
                    {d.direction === 'auditor_to_cb' ? 'Auditor upload' : 'Released'}
                    {' · '}{fmtDate(d.released_at)}
                    {d.signed_at && ` · Signed ${fmtDate(d.signed_at)}`}
                  </p>
                </div>
                <div className="flex items-center gap-2">
                  {d.cb_sig_status && (
                    <span className={`rounded-full px-2 py-0.5 text-xs font-semibold ${
                      d.cb_sig_status === 'signed'
                        ? 'bg-blue-100 text-blue-700'
                        : 'bg-amber-100 text-amber-800'
                    }`}>
                      {d.cb_sig_status === 'signed' ? 'CB ✓' : 'CB Signing…'}
                    </span>
                  )}
                  <span
                    className={`rounded-full px-2 py-0.5 text-xs font-semibold ${
                      d.status === 'signed'                 ? 'bg-green-100 text-green-700'
                      : d.status === 'uploaded'             ? 'bg-blue-100 text-blue-700'
                      : d.status === 'pending_cb_signature' ? 'bg-gray-100 text-gray-500'
                      : 'bg-amber-100 text-amber-700'
                    }`}
                  >
                    {d.status === 'signed'
                      ? '✓ Signed'
                      : d.status === 'uploaded'
                      ? 'Uploaded'
                      : d.status === 'pending_cb_signature'
                      ? 'Pending release'
                      : 'Awaiting Signature'}
                  </span>
                  <button
                    type="button"
                    onClick={() => downloadDoc(d.id, d.label)}
                    className="rounded-lg border border-gray-300 px-2.5 py-1 text-xs text-gray-700 hover:bg-gray-50"
                  >
                    Download
                  </button>
                </div>
              </li>
            ))}
          </ul>
        )}
      </div>
    </div>
  )
}
