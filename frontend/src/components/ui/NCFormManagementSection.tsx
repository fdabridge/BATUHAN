'use client'

import { useEffect, useRef, useState } from 'react'
import api from '@/lib/api'

interface NCForm {
  id:               string
  stage_type:       string
  label:            string
  file_name:        string | null
  status:           string
  la_signed_at:     string | null
  client_signed_at: string | null
  created_at:       string
}

const STAGE_OPTS = [
  { value: 'stage_1',         label: 'Stage 1' },
  { value: 'stage_2',         label: 'Stage 2' },
  { value: 'surveillance',    label: 'Surveillance' },
  { value: 'recertification', label: 'Recertification' },
]

const STATUS_CONFIG: Record<string, { label: string; chip: string }> = {
  pending_la:     { label: 'Awaiting Lead Auditor',  chip: 'bg-amber-100 text-amber-700' },
  pending_client: { label: 'Awaiting Client',         chip: 'bg-blue-100 text-blue-700' },
  complete:       { label: 'Complete',                chip: 'bg-green-100 text-green-700' },
}

function fmtDate(iso: string | null) {
  if (!iso) return ''
  return new Date(iso).toLocaleDateString('en-GB', { day: 'numeric', month: 'short', year: 'numeric' })
}

export function NCFormManagementSection({
  auditSetId,
  workflowStatus,
}: {
  auditSetId: string
  workflowStatus: string | null
}) {
  const [forms, setForms]       = useState<NCForm[]>([])
  const [loading, setLoading]   = useState(true)
  const [uploading, setUploading] = useState(false)
  const [showUpload, setShowUpload] = useState(false)
  const [stage, setStage]       = useState('stage_1')
  const [label, setLabel]       = useState('')
  const [file, setFile]         = useState<File | null>(null)
  const [uploadMsg, setUploadMsg] = useState('')
  const fileRef = useRef<HTMLInputElement>(null)

  // Show from audit_scheduled / stage1_scheduled onwards
  const relevantStatuses = new Set([
    'stage1_scheduled', 'stage1_in_progress', 'stage1_complete',
    'stage2_scheduled', 'stage2_in_progress',
    'audit_scheduled', 'audit_in_progress', 'under_review', 'certified',
  ])

  async function load() {
    try {
      const r = await api.get<NCForm[]>(`/audit-sets/${auditSetId}/nc-forms`)
      setForms(r.data)
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => {
    if (workflowStatus && relevantStatuses.has(workflowStatus)) load()
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [auditSetId, workflowStatus])

  if (!workflowStatus || !relevantStatuses.has(workflowStatus)) return null

  async function handleUpload(e: React.FormEvent) {
    e.preventDefault()
    if (!file || !label.trim()) return
    setUploading(true)
    setUploadMsg('')
    try {
      const form = new FormData()
      form.append('stage_type', stage)
      form.append('label', label.trim())
      form.append('file', file)
      await api.post(`/audit-sets/${auditSetId}/nc-forms/upload`, form, {
        headers: { 'Content-Type': 'multipart/form-data' },
      })
      setShowUpload(false)
      setLabel('')
      setFile(null)
      if (fileRef.current) fileRef.current.value = ''
      await load()
    } catch (err: unknown) {
      const detail = (err as { response?: { data?: { detail?: string } } })?.response?.data?.detail
      setUploadMsg(detail || 'Upload failed')
    } finally {
      setUploading(false)
    }
  }

  return (
    <div className="mt-6">
      <div className="mb-3 flex items-center justify-between">
        <h2 className="text-sm font-semibold uppercase tracking-wide text-gray-700">
          NC Forms (FR.230)
        </h2>
        <button
          type="button"
          onClick={() => { setShowUpload(!showUpload); setUploadMsg('') }}
          className="rounded-lg border border-[#1A4731] px-3 py-1.5 text-xs font-medium text-[#1A4731] hover:bg-green-50"
        >
          {showUpload ? 'Cancel' : '+ Upload NC Form'}
        </button>
      </div>

      {showUpload && <UploadForm
        stage={stage} setStage={setStage}
        label={label} setLabel={setLabel}
        setFile={setFile} fileRef={fileRef}
        uploading={uploading} uploadMsg={uploadMsg}
        onSubmit={handleUpload}
      />}

      {loading ? (
        <p className="text-xs text-gray-400">Loading…</p>
      ) : forms.length === 0 ? (
        <div className="rounded-xl border bg-white px-4 py-6 text-center text-xs text-gray-400">
          No NC forms yet.
        </div>
      ) : (
        <div className="rounded-xl border bg-white divide-y divide-gray-50">
          {forms.map(f => {
            const cfg = STATUS_CONFIG[f.status] ?? { label: f.status, chip: 'bg-gray-100 text-gray-500' }
            return (
              <div key={f.id} className="flex items-center justify-between px-4 py-3">
                <div className="min-w-0">
                  <p className="text-sm font-medium text-gray-800 truncate">{f.label}</p>
                  <p className="mt-0.5 text-xs text-gray-400">
                    {STAGE_OPTS.find(s => s.value === f.stage_type)?.label ?? f.stage_type}
                    {f.la_signed_at && ` · LA signed ${fmtDate(f.la_signed_at)}`}
                    {f.client_signed_at && ` · Client signed ${fmtDate(f.client_signed_at)}`}
                  </p>
                </div>
                <span className={`ml-4 shrink-0 rounded-full px-2.5 py-0.5 text-xs font-semibold ${cfg.chip}`}>
                  {cfg.label}
                </span>
              </div>
            )
          })}
        </div>
      )}
    </div>
  )
}

interface UploadFormProps {
  stage: string
  setStage: (v: string) => void
  label: string
  setLabel: (v: string) => void
  setFile: (f: File | null) => void
  fileRef: React.RefObject<HTMLInputElement>
  uploading: boolean
  uploadMsg: string
  onSubmit: (e: React.FormEvent) => void
}

function UploadForm({
  stage, setStage, label, setLabel, setFile, fileRef,
  uploading, uploadMsg, onSubmit,
}: UploadFormProps) {
  return (
    <form
      onSubmit={onSubmit}
      className="mb-4 space-y-3 rounded-xl border border-amber-200 bg-amber-50 p-4"
    >
      <div className="grid grid-cols-2 gap-3">
        <div>
          <label className="mb-1 block text-xs font-medium text-gray-600">Stage</label>
          <select
            value={stage}
            onChange={e => setStage(e.target.value)}
            className="w-full rounded-lg border bg-white px-3 py-2 text-sm"
          >
            {STAGE_OPTS.map(s => (
              <option key={s.value} value={s.value}>{s.label}</option>
            ))}
          </select>
        </div>
        <div>
          <label className="mb-1 block text-xs font-medium text-gray-600">NC Reference / Label</label>
          <input
            required
            value={label}
            onChange={e => setLabel(e.target.value)}
            placeholder="e.g. NC-001 Document Control"
            className="w-full rounded-lg border bg-white px-3 py-2 text-sm"
          />
        </div>
      </div>
      <div>
        <label className="mb-1 block text-xs font-medium text-gray-600">File</label>
        <input
          ref={fileRef}
          required
          type="file"
          onChange={e => setFile(e.target.files?.[0] || null)}
          className="text-sm"
        />
      </div>
      <button
        type="submit"
        disabled={uploading || !label.trim()}
        className="rounded-lg bg-[#1A4731] px-4 py-2 text-sm text-white disabled:opacity-40"
      >
        {uploading ? 'Uploading…' : 'Upload & Notify Auditor'}
      </button>
      {uploadMsg && <p className="text-xs text-red-600">{uploadMsg}</p>}
    </form>
  )
}
