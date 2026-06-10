'use client'

import { useEffect, useState } from 'react'
import { useParams } from 'next/navigation'
import api from '@/lib/api'
import { MessageThread } from '@/components/ui/MessageThread'

const STANDARD_NAMES: Record<string, string> = {
  QMS:   'ISO 9001:2015',
  EMS:   'ISO 14001:2015',
  OHSMS: 'ISO 45001:2018',
  FSMS:  'ISO 22000:2018',
  ISMS:  'ISO/IEC 27001:2022',
  ENMS:  'ISO 50001:2018',
  MDQMS: 'ISO 13485:2016',
  ABMS:  'ISO 37001:2016',
}

interface Stage {
  stage_type:        string
  stage_order:       number
  audit_date_start:  string | null
  audit_date_end:    string | null
  lead_auditor_name: string | null
  audit_days:        number | null
  status:            string
}

interface AssignmentDetail {
  id:                     string
  plan_number:            number
  client_reference:       string | null
  company_name:           string
  company_address:        string
  email:                  string
  phone:                  string
  representative:         string
  standards:              string[]
  audit_type:             string
  scope_en:               string | null
  non_applicable_clauses: string | null
  ea_code:                string | null
  ea_category:            string | null
  accreditation_body:     string | null
  workflow_status:        string | null
  stages:                 Stage[]
}

type Tab = 'overview' | 'messages' | 'upload' | 'attendees' | 'nc_forms'

function AuditorAttendeesView({ auditSetId }: { auditSetId: string }) {
  const [attendees, setAttendees] = useState<{
    id: string; stage_label: string; full_name: string; title: string | null
    email: string; opening_signed: boolean; closing_signed: boolean
    stage_type: string
  }[]>([])
  const [loading, setLoading] = useState(true)
  const [form, setForm]       = useState({ stage_type: 'stage_1', full_name: '', title: '', email: '' })
  const [busy, setBusy]       = useState(false)
  const [addMsg, setAddMsg]   = useState('')

  const STAGE_OPTS = [
    { value: 'stage_1',         label: 'Stage 1' },
    { value: 'stage_2',         label: 'Stage 2' },
    { value: 'surveillance',    label: 'Surveillance' },
    { value: 'recertification', label: 'Recertification' },
  ]

  useEffect(() => {
    api.get(`/audit-sets/${auditSetId}/meeting-attendees`)
      .then(r => setAttendees(r.data as typeof attendees))
      .finally(() => setLoading(false))
  }, [auditSetId])

  async function handleAdd(e: React.FormEvent) {
    e.preventDefault()
    setBusy(true)
    setAddMsg('')
    try {
      const r = await api.post(`/audit-sets/${auditSetId}/meeting-attendees`, {
        stage_type: form.stage_type,
        full_name:  form.full_name.trim(),
        title:      form.title.trim() || null,
        email:      form.email.trim(),
      })
      setAttendees(prev => [...prev, r.data as typeof attendees[0]])
      setForm({ stage_type: 'stage_1', full_name: '', title: '', email: '' })
      setAddMsg('Attendee added and invite sent.')
    } catch (err: unknown) {
      const detail = (err as { response?: { data?: { detail?: string } } })?.response?.data?.detail
      setAddMsg(detail || 'Failed to add attendee')
    } finally {
      setBusy(false)
    }
  }

  if (loading) return <p className="text-sm text-gray-400">Loading…</p>

  const grouped = attendees.reduce<Record<string, typeof attendees>>((acc, a) => {
    acc[a.stage_type] = acc[a.stage_type] || []
    acc[a.stage_type].push(a)
    return acc
  }, {})

  return (
    <div className="space-y-4">
      <div className="rounded-xl border bg-white p-5">
        <p className="mb-3 text-sm font-medium text-gray-700">Add Meeting Attendee</p>
        <form onSubmit={handleAdd} className="space-y-3">
          <div className="grid grid-cols-2 gap-3">
            <select
              value={form.stage_type}
              onChange={e => setForm(f => ({ ...f, stage_type: e.target.value }))}
              className="rounded-lg border px-3 py-2 text-sm"
            >
              {STAGE_OPTS.map(s => <option key={s.value} value={s.value}>{s.label}</option>)}
            </select>
            <input
              value={form.full_name} required placeholder="Full Name *"
              onChange={e => setForm(f => ({ ...f, full_name: e.target.value }))}
              className="rounded-lg border px-3 py-2 text-sm"
            />
            <input
              value={form.title} placeholder="Title / Role"
              onChange={e => setForm(f => ({ ...f, title: e.target.value }))}
              className="rounded-lg border px-3 py-2 text-sm"
            />
            <input
              type="email" value={form.email} required placeholder="Email *"
              onChange={e => setForm(f => ({ ...f, email: e.target.value }))}
              className="rounded-lg border px-3 py-2 text-sm"
            />
          </div>
          <button
            type="submit" disabled={busy}
            className="rounded-lg bg-[#1A4731] px-4 py-2 text-sm text-white disabled:opacity-40"
          >
            {busy ? 'Adding…' : 'Add & Send Invite'}
          </button>
          {addMsg && <p className="text-xs text-gray-500">{addMsg}</p>}
        </form>
      </div>

      {Object.entries(grouped).map(([stage, list]) => (
        <div key={stage} className="rounded-xl border bg-white">
          <div className="border-b px-4 py-2">
            <p className="text-xs font-semibold uppercase tracking-wide text-gray-400">
              {STAGE_OPTS.find(s => s.value === stage)?.label ?? stage}
            </p>
          </div>
          <div className="divide-y divide-gray-50">
            {list.map(a => (
              <div key={a.id} className="flex items-center justify-between px-4 py-3">
                <div>
                  <p className="text-sm font-medium">{a.full_name}
                    {a.title && <span className="ml-1 text-xs text-gray-400">— {a.title}</span>}
                  </p>
                  <p className="text-xs text-gray-400">{a.email}</p>
                </div>
                <div className="flex gap-2">
                  <span className={`rounded-full px-2 py-0.5 text-xs font-medium ${a.opening_signed ? 'bg-green-100 text-green-700' : 'bg-gray-100 text-gray-400'}`}>
                    {a.opening_signed ? 'Opening ✓' : 'Opening —'}
                  </span>
                  <span className={`rounded-full px-2 py-0.5 text-xs font-medium ${a.closing_signed ? 'bg-green-100 text-green-700' : 'bg-gray-100 text-gray-400'}`}>
                    {a.closing_signed ? 'Closing ✓' : 'Closing —'}
                  </span>
                </div>
              </div>
            ))}
          </div>
        </div>
      ))}
      {attendees.length === 0 && (
        <p className="py-8 text-center text-sm text-gray-400">No attendees registered yet.</p>
      )}
    </div>
  )
}

function AuditorNCFormsView({ auditSetId }: { auditSetId: string }) {
  const [forms, setForms]   = useState<{
    id: string; stage_type: string; label: string; file_name: string | null; status: string;
    la_signed_at: string | null;
  }[]>([])
  const [loading, setLoading] = useState(true)
  const [otpState, setOtpState] = useState<Record<string, 'idle' | 'otp_sent' | 'done'>>({})
  const [otpValues, setOtpValues] = useState<Record<string, string>>({})
  const [messages, setMessages]   = useState<Record<string, string>>({})
  const [busy, setBusy]           = useState<Record<string, boolean>>({})

  const STAGE_LABELS: Record<string, string> = {
    stage_1: 'Stage 1', stage_2: 'Stage 2', surveillance: 'Surveillance',
    recertification: 'Recertification',
  }

  useEffect(() => {
    api.get(`/audit-sets/${auditSetId}/nc-forms`)
      .then(r => setForms(r.data as typeof forms))
      .finally(() => setLoading(false))
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [auditSetId])

  async function download(id: string, fileName: string | null) {
    const r = await api.get(`/audit-sets/${auditSetId}/nc-forms/${id}/download`, {
      responseType: 'blob',
    })
    const url = window.URL.createObjectURL(new Blob([r.data as Blob]))
    const a   = document.createElement('a')
    a.href = url; a.download = fileName || 'nc_form.docx'
    document.body.appendChild(a); a.click(); a.remove()
    window.URL.revokeObjectURL(url)
  }

  async function requestOtp(id: string) {
    setBusy(b => ({ ...b, [id]: true }))
    setMessages(m => ({ ...m, [id]: '' }))
    try {
      await api.post(`/audit-sets/${auditSetId}/nc-forms/${id}/sign/la/request-otp`)
      setOtpState(s => ({ ...s, [id]: 'otp_sent' }))
    } catch (err: unknown) {
      const detail = (err as { response?: { data?: { detail?: string } } })?.response?.data?.detail
      setMessages(m => ({ ...m, [id]: detail || 'Failed to send code' }))
    } finally {
      setBusy(b => ({ ...b, [id]: false }))
    }
  }

  async function verifyOtp(id: string) {
    setBusy(b => ({ ...b, [id]: true }))
    setMessages(m => ({ ...m, [id]: '' }))
    try {
      await api.post(
        `/audit-sets/${auditSetId}/nc-forms/${id}/sign/la/verify?otp=${otpValues[id] ?? ''}`,
      )
      setOtpState(s => ({ ...s, [id]: 'done' }))
      setForms(prev => prev.map(f => f.id === id
        ? { ...f, status: 'pending_client', la_signed_at: new Date().toISOString() }
        : f
      ))
    } catch (err: unknown) {
      const detail = (err as { response?: { data?: { detail?: string } } })?.response?.data?.detail
      setMessages(m => ({ ...m, [id]: detail || 'Invalid code' }))
    } finally {
      setBusy(b => ({ ...b, [id]: false }))
    }
  }

  if (loading) return <p className="text-sm text-gray-400">Loading…</p>

  const pending = forms.filter(f => f.status === 'pending_la')
  const completed = forms.filter(f => f.status !== 'pending_la')

  return (
    <div className="space-y-4">
      {forms.length === 0 && (
        <p className="py-8 text-center text-sm text-gray-400">No NC forms for your stages.</p>
      )}

      {pending.length > 0 && (
        <div>
          <p className="mb-2 text-xs font-semibold uppercase tracking-wide text-amber-600">
            Awaiting Your Signature
          </p>
          <div className="space-y-3">
            {pending.map(f => {
              const state = otpState[f.id] || 'idle'
              return (
                <div key={f.id} className="rounded-xl border border-amber-200 bg-amber-50 p-4">
                  <div className="mb-3 flex items-start justify-between">
                    <div>
                      <p className="font-medium text-gray-800">{f.label}</p>
                      <p className="text-xs text-gray-400">
                        {STAGE_LABELS[f.stage_type] ?? f.stage_type}
                      </p>
                    </div>
                    <button
                      type="button"
                      onClick={() => download(f.id, f.file_name)}
                      className="text-xs text-[#1A4731] underline"
                    >
                      Download
                    </button>
                  </div>
                  {state === 'idle' && (
                    <button
                      type="button"
                      onClick={() => requestOtp(f.id)}
                      disabled={busy[f.id]}
                      className="rounded-lg bg-[#1A4731] px-4 py-2 text-sm text-white disabled:opacity-40"
                    >
                      {busy[f.id] ? 'Sending…' : 'Sign NC Form'}
                    </button>
                  )}
                  {state === 'otp_sent' && (
                    <div className="flex items-center gap-3">
                      <input
                        className="w-36 rounded-lg border px-3 py-2 text-center font-mono text-lg tracking-widest"
                        placeholder="000000" maxLength={6}
                        value={otpValues[f.id] ?? ''}
                        onChange={e => setOtpValues(v => ({
                          ...v, [f.id]: e.target.value.replace(/\D/g, ''),
                        }))}
                      />
                      <button
                        type="button"
                        onClick={() => verifyOtp(f.id)}
                        disabled={(otpValues[f.id] ?? '').length !== 6 || busy[f.id]}
                        className="rounded-lg bg-[#1A4731] px-4 py-2 text-sm text-white disabled:opacity-40"
                      >
                        {busy[f.id] ? '…' : 'Confirm'}
                      </button>
                      <button
                        type="button"
                        onClick={() => requestOtp(f.id)}
                        className="text-xs text-gray-400 underline"
                      >
                        Resend
                      </button>
                    </div>
                  )}
                  {state === 'done' && (
                    <p className="text-sm text-green-600 font-medium">Signed ✓ — client has been notified.</p>
                  )}
                  {messages[f.id] && (
                    <p className="mt-1 text-xs text-red-500">{messages[f.id]}</p>
                  )}
                </div>
              )
            })}
          </div>
        </div>
      )}

      {completed.length > 0 && (
        <div>
          <p className="mb-2 text-xs font-semibold uppercase tracking-wide text-gray-400">
            Signed
          </p>
          <div className="rounded-xl border bg-white divide-y divide-gray-50">
            {completed.map(f => (
              <div key={f.id} className="flex items-center justify-between px-4 py-3">
                <div>
                  <p className="text-sm font-medium text-gray-800">{f.label}</p>
                  <p className="text-xs text-gray-400">
                    {STAGE_LABELS[f.stage_type] ?? f.stage_type} ·{' '}
                    {f.status === 'complete' ? 'Both parties signed' : 'Awaiting client'}
                  </p>
                </div>
                <button
                  type="button"
                  onClick={() => download(f.id, f.file_name)}
                  className="text-xs text-[#1A4731] underline"
                >
                  Download
                </button>
              </div>
            ))}
          </div>
        </div>
      )}
    </div>
  )
}


export default function AuditorAuditDetail() {
  const { id } = useParams<{ id: string }>()
  const [data, setData]   = useState<AssignmentDetail | null>(null)
  const [tab, setTab]     = useState<Tab>('overview')
  const [downloading, setDownloading] = useState(false)
  const [uploading, setUploading]     = useState(false)
  const [uploadLabel, setUploadLabel] = useState('')
  const [uploadFile, setUploadFile]   = useState<File | null>(null)
  const [uploadMsg, setUploadMsg]     = useState('')

  useEffect(() => {
    api.get<AssignmentDetail>(`/auditor/my-assignments/${id}`)
      .then((r) => setData(r.data))
  }, [id])

  async function handleDownload() {
    if (!data) return
    setDownloading(true)
    try {
      const res = await api.get(`/audit-sets/${id}/download`, { responseType: 'blob' })
      const blob = new Blob([res.data])
      const url  = window.URL.createObjectURL(blob)
      const a    = document.createElement('a')
      a.href     = url
      a.download = `${data.plan_number || 'audit-set'}.zip`
      document.body.appendChild(a)
      a.click()
      a.remove()
      window.URL.revokeObjectURL(url)
    } catch (e: unknown) {
      const detail = (e as { response?: { data?: { detail?: string } } })
        ?.response?.data?.detail
      alert(detail || 'Download failed')
    } finally {
      setDownloading(false)
    }
  }

  async function handleUpload() {
    if (!uploadFile || !uploadLabel.trim()) return
    setUploading(true)
    setUploadMsg('')
    try {
      const form = new FormData()
      form.append('file', uploadFile)
      await api.post(
        `/audit-sets/${id}/documents/upload?label=${encodeURIComponent(uploadLabel)}`,
        form,
        { headers: { 'Content-Type': 'multipart/form-data' } },
      )
      setUploadMsg('Document uploaded successfully.')
      setUploadFile(null)
      setUploadLabel('')
    } catch (e: unknown) {
      const detail = (e as { response?: { data?: { detail?: string } } })
        ?.response?.data?.detail
      setUploadMsg(detail || 'Upload failed')
    } finally {
      setUploading(false)
    }
  }

  if (!data) {
    return <div className="p-8 text-sm text-gray-400">Loading…</div>
  }

  return (
    <div className="mx-auto max-w-3xl p-6">
      {/* Header */}
      <div className="mb-6">
        <h1 className="text-xl font-bold text-gray-900">{data.company_name}</h1>
        <p className="mt-0.5 text-sm text-gray-400">{data.company_address}</p>
        <div className="mt-2 flex flex-wrap gap-2">
          {(data.standards || []).map((s) => (
            <span key={s} className="rounded bg-blue-50 px-2 py-0.5 text-xs text-blue-700">
              {STANDARD_NAMES[s] || s}
            </span>
          ))}
        </div>
      </div>

      {/* Tabs */}
      <div className="mb-6 flex w-fit gap-1 rounded-lg bg-gray-100 p-1">
        {(['overview', 'messages', 'upload', 'attendees', 'nc_forms'] as const).map((t) => (
          <button
            key={t}
            type="button"
            onClick={() => setTab(t)}
            className={`rounded-md px-4 py-1.5 text-sm font-medium capitalize transition-colors ${
              tab === t
                ? 'bg-white text-gray-900 shadow-sm'
                : 'text-gray-500 hover:text-gray-700'
            }`}
          >
            {t === 'upload' ? 'Upload Documents'
              : t === 'attendees' ? 'Attendees'
              : t === 'nc_forms' ? 'NC Forms'
              : t}
          </button>
        ))}
      </div>

      {/* Overview tab */}
      {tab === 'overview' && (
        <div className="space-y-4">
          <div className="grid grid-cols-2 gap-4 rounded-xl border bg-white p-5 text-sm">
            <div>
              <p className="mb-1 text-xs uppercase tracking-wide text-gray-400">Contact</p>
              <p className="font-medium">{data.representative || '—'}</p>
              <p className="text-gray-500">{data.email}</p>
              <p className="text-gray-500">{data.phone}</p>
            </div>
            <div>
              <p className="mb-1 text-xs uppercase tracking-wide text-gray-400">Accreditation</p>
              <p className="font-medium">{data.accreditation_body || '—'}</p>
              <p className="text-gray-500">{data.audit_type?.replace('_', ' ')}</p>
            </div>
          </div>

          {data.scope_en && (
            <div className="rounded-xl border bg-white p-5">
              <p className="mb-2 text-xs uppercase tracking-wide text-gray-400">Scope</p>
              <p className="text-sm text-gray-700">{data.scope_en}</p>
            </div>
          )}

          {data.non_applicable_clauses && (
            <div className="rounded-xl border bg-white p-5">
              <p className="mb-2 text-xs uppercase tracking-wide text-gray-400">
                Non-Applicable Clauses
              </p>
              <p className="text-sm text-gray-700">{data.non_applicable_clauses}</p>
            </div>
          )}

          <div className="rounded-xl border bg-white p-5">
            <p className="mb-3 text-xs uppercase tracking-wide text-gray-400">Audit Stages</p>
            <div className="space-y-2">
              {(data.stages || []).map((s, i) => (
                <div key={i} className="flex items-center justify-between text-sm">
                  <span className="capitalize text-gray-700">
                    {s.stage_type?.replace('_', ' ')}
                  </span>
                  <span className="text-gray-500">
                    {s.audit_date_start
                      ? new Date(s.audit_date_start).toLocaleDateString('en-GB', {
                          day: 'numeric', month: 'short', year: 'numeric',
                        })
                      : 'TBD'}
                    {s.audit_date_end && s.audit_date_end !== s.audit_date_start
                      ? ` – ${new Date(s.audit_date_end).toLocaleDateString('en-GB', {
                          day: 'numeric', month: 'short',
                        })}`
                      : ''}
                  </span>
                </div>
              ))}
            </div>
          </div>

          <button
            type="button"
            onClick={handleDownload}
            disabled={downloading}
            className="block w-full rounded-xl bg-[#1A4731] py-3 text-center font-medium text-white transition-colors hover:bg-[#143828] disabled:opacity-40"
          >
            {downloading ? 'Preparing package…' : 'Download Audit Package'}
          </button>
        </div>
      )}

      {/* Messages tab */}
      {tab === 'messages' && (
        <div className="overflow-hidden rounded-xl border bg-white" style={{ height: 500 }}>
          <MessageThread
            fetchUrl={`/auditor/my-assignments/${id}/messages`}
            postUrl={`/auditor/my-assignments/${id}/messages`}
          />
        </div>
      )}

      {/* Upload tab */}
      {tab === 'upload' && (
        <div className="space-y-4 rounded-xl border bg-white p-6">
          <p className="text-sm text-gray-600">
            Upload your completed audit documents here. The CB team will be notified.
          </p>
          <div>
            <label className="mb-1 block text-sm font-medium text-gray-700">
              Document Label
            </label>
            <input
              className="w-full rounded-lg border px-3 py-2 text-sm"
              placeholder="e.g. Stage 2 Audit Report, FR.222 filled"
              value={uploadLabel}
              onChange={(e) => setUploadLabel(e.target.value)}
            />
          </div>
          <div>
            <label className="mb-1 block text-sm font-medium text-gray-700">File</label>
            <input
              type="file"
              onChange={(e) => setUploadFile(e.target.files?.[0] || null)}
              className="text-sm"
            />
          </div>
          <button
            type="button"
            onClick={handleUpload}
            disabled={!uploadFile || !uploadLabel.trim() || uploading}
            className="rounded-lg bg-[#1A4731] px-6 py-2.5 text-sm text-white disabled:opacity-40"
          >
            {uploading ? 'Uploading…' : 'Upload Document'}
          </button>
          {uploadMsg && <p className="text-sm text-gray-600">{uploadMsg}</p>}
        </div>
      )}

      {/* Attendees tab — Prompt 15 (FR.225 meeting attendance roster) */}
      {tab === 'attendees' && (
        <AuditorAttendeesView auditSetId={id} />
      )}

      {/* NC Forms tab — Prompt 17 (FR.230 Lead Auditor signs first) */}
      {tab === 'nc_forms' && (
        <AuditorNCFormsView auditSetId={id} />
      )}
    </div>
  )
}
