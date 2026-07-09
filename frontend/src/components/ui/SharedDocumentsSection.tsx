'use client'

import { useEffect, useRef, useState } from 'react'
import api from '@/lib/api'
import { useAuth } from '@/lib/auth'
import type { StageResponse } from '@/types'

interface SharedDoc {
  id: string
  label: string
  document_type: string
  direction: 'cb_to_client' | 'auditor_to_cb' | 'client_to_cb'
  status: 'pending_cb_signature' | 'released' | 'signed' | 'uploaded'
  stage_type: string | null
  assigned_auditor_id: string | null
  released_at: string | null
  signed_at: string | null
  signed_by: string | null
  cb_sig_status: 'pending' | 'signed' | null
  cb_sig_id: string | null
}

// DOC_TYPES is computed inside the component based on auditType — see below.

// Document types tagged to a specific stage when released.
const STAGE_SCOPED_TYPES = new Set(['team_info'])

const STAGE_LABELS: Record<string, string> = {
  stage_1:      'Stage 1',
  stage_2:      'Stage 2',
  surveillance: 'Surveillance',
}

interface TeamMember { id: string; name: string }

// Collect {id, name} of every assigned team member on a stage (lead + auditors + TEs).
function stageTeam(stage: StageResponse | undefined): TeamMember[] {
  if (!stage) return []
  const out: TeamMember[] = []
  const seen = new Set<string>()
  const push = (id?: unknown, name?: unknown) => {
    if (typeof id !== 'string' || !id || seen.has(id)) return
    seen.add(id)
    out.push({ id, name: typeof name === 'string' && name ? name : id })
  }
  push(stage.lead_auditor_id ?? undefined, stage.lead_auditor_name ?? undefined)
  for (const list of [stage.auditors, stage.technical_experts]) {
    for (const m of (list ?? [])) {
      if (m && typeof m === 'object') {
        const o = m as { id?: unknown; name?: unknown }
        push(o.id, o.name)
      }
    }
  }
  return out
}

function fmtDate(iso: string | null): string {
  if (!iso) return '—'
  return new Date(iso).toLocaleDateString('en-GB', {
    day: 'numeric', month: 'short', year: 'numeric',
  })
}

export function SharedDocumentsSection({
  auditSetId,
  stages = [],
  auditType = null,
  onDocumentReleased,
}: {
  auditSetId: string
  stages?: StageResponse[]
  auditType?: string | null
  onDocumentReleased?: () => void
}) {
  // Document types available in the release form, filtered by audit type.
  const DOC_TYPES = (() => {
    const isSurveillance = (auditType ?? '').startsWith('surveillance')
    if (isSurveillance) {
      return [
        { value: 'surveillance_notification', label: 'Surveillance Notification (FR.234)' },
        { value: 'team_info',                 label: 'Audit Team Info (FR.224)' },
        { value: 'review_decision',           label: 'Review & Decision (FR.233)' },
        { value: 'certificate',               label: 'Certificate' },
      ]
    }
    // Initial certification / recertification / unset
    return [
      { value: 'quotation',       label: 'Quotation (FR.220)' },
      { value: 'agreement',       label: 'Agreement (FR.221)' },
      { value: 'fr218_review',    label: 'Application Review (FR.218)' },
      { value: 'audit_programme', label: 'Audit Programme (FR.222)' },
      // Portal 55 — FR.223 is uploaded by the Lead Auditor from their portal,
      // not released by the Planner. The Planner can still view it once uploaded.
      { value: 'team_info',       label: 'Audit Team Info (FR.224)' },
      { value: 'review_decision', label: 'Review & Decision (FR.233)' },
      { value: 'certificate',     label: 'Certificate' },
    ]
  })()

  const [docs, setDocs]     = useState<SharedDoc[]>([])
  const [loading, setLoading] = useState(true)
  const [showForm, setShowForm] = useState(false)
  const [label, setLabel]     = useState('')
  const [docType, setDocType] = useState(() => {
    const isSurveillance = (auditType ?? '').startsWith('surveillance')
    return isSurveillance ? 'surveillance_notification' : 'quotation'
  })
  const [stageType, setStageType] = useState('')
  const [auditorId, setAuditorId] = useState('')
  const [file, setFile]       = useState<File | null>(null)
  const [submitting, setSubmitting] = useState(false)
  const [error, setError]     = useState('')
  const [releaseDate, setReleaseDate] = useState(() => new Date().toISOString().slice(0, 10))
  const fileRef = useRef<HTMLInputElement>(null)

  const { user }                           = useAuth()
  const [deletingId, setDeletingId]        = useState<string | null>(null)  // doc id pending confirm
  const [deleteError, setDeleteError]      = useState<string>('')
  const [deleteLoading, setDeleteLoading]  = useState(false)

  const canDelete = (
    user?.role === 'admin'
    || user?.role === 'planner'
    || user?.role === 'planner_us'
  )

  async function deleteDoc(docId: string) {
    setDeleteError('')
    setDeleteLoading(true)
    try {
      const deletedDoc = docs.find((doc) => doc.id === docId)
      await api.delete(`/audit-sets/${auditSetId}/documents/${docId}`)
      setDeletingId(null)
      await load()
      if (deletedDoc?.document_type === 'fr233') {
        window.dispatchEvent(new CustomEvent('certiva:fr233-updated', {
          detail: { auditSetId },
        }))
      }
    } catch (err: unknown) {
      const detail = (err as { response?: { data?: { detail?: string } } })
        ?.response?.data?.detail
      setDeleteError(detail || 'Failed to delete document.')
    } finally {
      setDeleteLoading(false)
    }
  }

  const stageScoped   = STAGE_SCOPED_TYPES.has(docType)
  const selectedStage = stages.find((s) => s.stage_type === stageType)
  const teamOptions   = docType === 'team_info' ? stageTeam(selectedStage) : []

  async function load() {
    try {
      const r = await api.get<SharedDoc[]>(`/audit-sets/${auditSetId}/documents`)
      setDocs(r.data)
      if (r.data.some((doc) => doc.document_type === 'certificate')) {
        onDocumentReleased?.()
      }
    } catch {
      // A GET failure after a successful release must not surface as
      // "Failed to release document." — keep errors isolated.
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => { load() }, [auditSetId])

  async function release() {
    setError('')
    if (!label.trim()) { setError('Label is required.'); return }
    if (!file)         { setError('Please select a file to upload.'); return }
    if (stageScoped && !stageType) { setError('Please select a stage.'); return }
    if (docType === 'team_info' && !auditorId) {
      setError('FR.224 is per-auditor — please select the assigned auditor.'); return
    }
    setSubmitting(true)
    try {
      const fd = new FormData()
      fd.append('label', label.trim())
      fd.append('document_type', docType)
      fd.append('release_date', releaseDate)
      if (stageScoped && stageType) fd.append('stage_type', stageType)
      if (docType === 'team_info' && auditorId) fd.append('assigned_auditor_id', auditorId)
      fd.append('file', file)
      await api.post(`/audit-sets/${auditSetId}/documents/release`, fd, {
        headers: { 'Content-Type': 'multipart/form-data' },
      })
      const releasedFR233 = docType === 'review_decision'
      setLabel(''); setFile(null)
      setDocType((auditType ?? '').startsWith('surveillance') ? 'surveillance_notification' : 'quotation')
      setStageType(''); setAuditorId('')
      setReleaseDate(new Date().toISOString().slice(0, 10))
      if (fileRef.current) fileRef.current.value = ''
      setShowForm(false)
      await load()
      if (releasedFR233) {
        window.dispatchEvent(new CustomEvent('certiva:fr233-updated', {
          detail: { auditSetId },
        }))
      }
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
    <div id="shared-documents" className="mt-8 scroll-mt-6">
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
          <div className="grid grid-cols-1 gap-3 md:grid-cols-2">
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
                onChange={(e) => {
                  setDocType(e.target.value)
                  setStageType('')
                  setAuditorId('')
                }}
                className="mt-1 w-full rounded-lg border px-3 py-1.5 text-sm focus:outline-none focus:ring-2 focus:ring-[#1A4731]/30"
              >
                {DOC_TYPES.map((t) => (
                  <option key={t.value} value={t.value}>{t.label}</option>
                ))}
              </select>
            </div>
            {stageScoped && (
              <div>
                <label className="block text-xs font-medium text-gray-500">Stage</label>
                <select
                  value={stageType}
                  onChange={(e) => { setStageType(e.target.value); setAuditorId('') }}
                  className="mt-1 w-full rounded-lg border px-3 py-1.5 text-sm focus:outline-none focus:ring-2 focus:ring-[#1A4731]/30"
                >
                  <option value="">— Select stage —</option>
                  {(stages.length > 0
                    ? stages.map((s) => s.stage_type)
                    : ['stage_1', 'stage_2']
                  ).map((st) => (
                    <option key={st} value={st}>{STAGE_LABELS[st] ?? st}</option>
                  ))}
                </select>
              </div>
            )}
            {docType === 'team_info' && (
              <div>
                <label className="block text-xs font-medium text-gray-500">Assigned auditor</label>
                <select
                  value={auditorId}
                  onChange={(e) => setAuditorId(e.target.value)}
                  className="mt-1 w-full rounded-lg border px-3 py-1.5 text-sm focus:outline-none focus:ring-2 focus:ring-[#1A4731]/30"
                >
                  <option value="">— Select auditor —</option>
                  {teamOptions.map((m) => (
                    <option key={m.id} value={m.id}>{m.name}</option>
                  ))}
                </select>
                {stageType && teamOptions.length === 0 && (
                  <p className="mt-1 text-[11px] text-amber-600">
                    No auditors assigned to this stage yet — assign the audit team first.
                  </p>
                )}
              </div>
            )}
            <div>
              <label className="block text-xs font-medium text-gray-500">Release date</label>
              <input
                type="date"
                value={releaseDate}
                onChange={(e) => setReleaseDate(e.target.value)}
                className="mt-1 w-full rounded-lg border px-3 py-1.5 text-sm focus:outline-none focus:ring-2 focus:ring-[#1A4731]/30"
              />
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
          <>
          <ul className="divide-y">
            {docs.map((d) => (
              <li key={d.id} className="flex items-center justify-between px-4 py-3">
                <div>
                  <p className="text-sm font-medium text-gray-800">{d.label}</p>
                  <p className="mt-0.5 text-xs text-gray-400">
                    {d.direction === 'auditor_to_cb' ? 'Auditor upload'
                      : d.direction === 'client_to_cb' ? 'Client upload'
                      : 'Released'}
                    {' · '}{fmtDate(d.released_at)}
                    {d.stage_type && ` · ${STAGE_LABELS[d.stage_type] ?? d.stage_type}`}
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
                    {d.document_type === 'certificate'
                      ? 'Issued'
                      : d.status === 'signed'
                      ? '✓ Signed'
                      : d.status === 'uploaded'
                      ? 'Uploaded'
                      : d.status === 'pending_cb_signature'
                      ? 'Pending release'
                      : 'Awaiting Signature'}
                  </span>
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
                  {canDelete && (
                    deletingId === d.id ? (
                      <span className="flex items-center gap-1">
                        <span className="text-xs text-gray-500">Delete?</span>
                        <button
                          type="button"
                          disabled={deleteLoading}
                          onClick={() => deleteDoc(d.id)}
                          className="rounded px-2 py-0.5 text-xs font-medium text-white disabled:opacity-50"
                          style={{ background: '#DC2626' }}
                        >
                          {deleteLoading ? '…' : 'Yes'}
                        </button>
                        <button
                          type="button"
                          onClick={() => { setDeletingId(null); setDeleteError('') }}
                          className="rounded border border-gray-300 px-2 py-0.5 text-xs text-gray-600 hover:bg-gray-50"
                        >
                          No
                        </button>
                      </span>
                    ) : (
                      <button
                        type="button"
                        onClick={() => { setDeletingId(d.id); setDeleteError('') }}
                        className="rounded-lg border border-red-200 px-2.5 py-1 text-xs text-red-600 hover:bg-red-50"
                      >
                        Delete
                      </button>
                    )
                  )}
                </div>
              </li>
            ))}
          </ul>
            {deleteError && (
              <p className="px-4 py-2 text-xs text-red-600 border-t border-red-100 bg-red-50">
                {deleteError}
              </p>
            )}
          </>
        )}
      </div>
    </div>
  )
}
