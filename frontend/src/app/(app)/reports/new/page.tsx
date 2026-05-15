'use client'

import { useEffect, useState } from 'react'
import { useRouter, useSearchParams } from 'next/navigation'
import { Loader2, Upload, X } from 'lucide-react'
import { useMutation, useQuery } from '@tanstack/react-query'
import api from '@/lib/api'
import type { AuditSetResponse, JobCreateResponse } from '@/types'

// ── Constants ─────────────────────────────────────────────────────────────────

const STANDARDS = ['QMS', 'EMS', 'OHSMS', 'FSMS', 'ISMS', 'MDQMS', 'ABMS', 'ENMS'] as const
const STAGES    = ['Stage 1', 'Stage 2'] as const
const BODIES    = ['UAF', 'TURKAK'] as const

const inputCls = 'w-full rounded-lg border border-gray-200 px-3 py-2 text-sm text-gray-800 placeholder-gray-400 outline-none focus:border-certiva-primary focus:ring-2 focus:ring-certiva-primary/20'
const lblCls   = 'mb-1 block text-xs font-medium text-gray-500'
const errCls   = 'mt-1 text-xs text-red-500'

// ── File drop zone ────────────────────────────────────────────────────────────

function FileZone({
  id, label, multiple, accept, files, onAdd, onRemove,
}: {
  id: string
  label: string
  multiple: boolean
  accept: string
  files: File[]
  onAdd: (fs: File[]) => void
  onRemove: (i: number) => void
}) {
  return (
    <div>
      <label
        htmlFor={id}
        className="flex cursor-pointer flex-col items-center justify-center gap-2 rounded-lg border border-dashed border-gray-300 px-4 py-6 hover:border-certiva-primary hover:bg-gray-50"
      >
        <Upload size={20} className="text-gray-400" />
        <span className="text-sm text-gray-600">{label}</span>
        <input
          id={id} type="file" multiple={multiple} accept={accept} className="hidden"
          onChange={(e) => {
            const list = Array.from(e.target.files ?? [])
            if (list.length) onAdd(list)
            e.target.value = ''
          }}
        />
      </label>
      {files.length > 0 && (
        <ul className="mt-2 space-y-1">
          {files.map((f, i) => (
            <li key={i} className="flex items-center justify-between rounded border border-gray-100 bg-gray-50 px-2 py-1 text-xs text-gray-700">
              <span className="truncate pr-2">{f.name}</span>
              <button type="button" onClick={() => onRemove(i)} className="text-gray-400 hover:text-red-500">
                <X size={13} />
              </button>
            </li>
          ))}
        </ul>
      )}
    </div>
  )
}

// ── Main page ─────────────────────────────────────────────────────────────────

interface FormState {
  standard: string; stage: string; accreditation_body: string
  company_name: string; scope_tr: string; scope_en: string
}

export default function NewReportPage() {
  const router = useRouter()
  const sp = useSearchParams()
  const clientId = sp.get('client_id')

  const [form, setForm] = useState<FormState>({
    standard: '', stage: '', accreditation_body: 'UAF',
    company_name: '', scope_tr: '', scope_en: '',
  })
  const [docs, setDocs]         = useState<File[]>([])
  const [template, setTemplate] = useState<File[]>([])
  const [errors, setErrors]     = useState<Record<string, string>>({})
  const [serverError, setServerError] = useState<string | null>(null)

  // Pre-fill from client_id query param
  const { data: client } = useQuery<AuditSetResponse>({
    queryKey: ['client', clientId],
    queryFn: () => api.get<AuditSetResponse>(`/audit-sets/${clientId}`).then((r) => r.data),
    enabled: !!clientId,
  })

  useEffect(() => {
    if (!client) return
    setForm((f) => ({
      ...f,
      standard:           f.standard           || (client.standards?.[0] ?? ''),
      accreditation_body: client.accreditation_body ?? f.accreditation_body,
      company_name:       f.company_name       || client.company_name,
      scope_tr:           f.scope_tr           || (client.scope_tr ?? ''),
      scope_en:           f.scope_en           || (client.scope_en ?? ''),
    }))
  }, [client])

  function validate(): boolean {
    const e: Record<string, string> = {}
    if (!form.standard)            e.standard = 'Required'
    if (!form.stage)               e.stage = 'Required'
    if (!form.accreditation_body)  e.accreditation_body = 'Required'
    if (!form.company_name.trim()) e.company_name = 'Required'
    if (!form.scope_tr.trim())     e.scope_tr = 'Required'
    if (!form.scope_en.trim())     e.scope_en = 'Required'
    if (docs.length === 0)         e.docs = 'Upload at least one document'
    if (template.length === 0)     e.template = 'Upload a report template'
    setErrors(e)
    return Object.keys(e).length === 0
  }

  const { mutate, isPending } = useMutation<JobCreateResponse>({
    mutationFn: async () => {
      const fd = new FormData()
      fd.append('standards', form.standard)
      fd.append('stage', form.stage)
      fd.append('accreditation_body', form.accreditation_body)
      fd.append('language', form.accreditation_body === 'TURKAK' ? 'TR' : 'EN')
      fd.append('org_name', form.company_name)
      fd.append('org_address', `EN: ${form.scope_en}\nTR: ${form.scope_tr}`)
      docs.forEach((f) => fd.append('company_documents', f))
      // Backend currently requires sample_reports — reuse company docs as references
      docs.forEach((f) => fd.append('sample_reports', f))
      fd.append('template', template[0])
      const res = await api.post<JobCreateResponse>('/jobs/create', fd)
      return res.data
    },
    onSuccess: (data) => {
      const qs = new URLSearchParams({
        standard: form.standard,
        stage:    form.stage,
        accreditation_body: form.accreditation_body,
        company:  form.company_name,
      })
      if (clientId) qs.set('client_id', clientId)
      router.push(`/reports/${data.job_id}?${qs.toString()}`)
    },
    onError: (err: unknown) => {
      const detail = (err as { response?: { data?: { detail?: string } } })?.response?.data?.detail
      setServerError(detail ?? 'Failed to submit job.')
    },
  })


  function onSubmit(e: React.FormEvent) {
    e.preventDefault()
    setServerError(null)
    if (validate()) mutate()
  }

  return (
    <div className="mx-auto max-w-[680px] py-4">
      <div className="rounded-lg border border-gray-100 bg-white p-6">
        {client && (
          <p className="mb-2" style={{ fontSize: 13, color: '#6B7280' }}>
            Generating report for: {client.company_name}
          </p>
        )}
        <h1 className="mb-6 text-gray-800" style={{ fontSize: 22, fontWeight: 500 }}>New AI report</h1>

        <form onSubmit={onSubmit} className="space-y-4">
          <div className="grid grid-cols-2 gap-4">
            <div>
              <label className={lblCls}>Standard *</label>
              <select className={inputCls} value={form.standard}
                onChange={(e) => setForm({ ...form, standard: e.target.value })}>
                <option value="">Select…</option>
                {STANDARDS.map((s) => <option key={s} value={s}>{s}</option>)}
              </select>
              {errors.standard && <p className={errCls}>{errors.standard}</p>}
            </div>
            <div>
              <label className={lblCls}>Audit stage *</label>
              <select className={inputCls} value={form.stage}
                onChange={(e) => setForm({ ...form, stage: e.target.value })}>
                <option value="">Select…</option>
                {STAGES.map((s) => <option key={s} value={s}>{s}</option>)}
              </select>
              {errors.stage && <p className={errCls}>{errors.stage}</p>}
            </div>
          </div>

          <div>
            <label className={lblCls}>Accreditation body *</label>
            <select className={inputCls} value={form.accreditation_body}
              onChange={(e) => setForm({ ...form, accreditation_body: e.target.value })}>
              {BODIES.map((b) => <option key={b} value={b}>{b}</option>)}
            </select>
            {errors.accreditation_body && <p className={errCls}>{errors.accreditation_body}</p>}
          </div>

          <div>
            <label className={lblCls}>Company name *</label>
            <input type="text" className={inputCls} value={form.company_name}
              onChange={(e) => setForm({ ...form, company_name: e.target.value })} />
            {errors.company_name && <p className={errCls}>{errors.company_name}</p>}
          </div>

          <div>
            <label className={lblCls}>Company scope (TR) *</label>
            <textarea rows={3} className={inputCls} value={form.scope_tr}
              onChange={(e) => setForm({ ...form, scope_tr: e.target.value })} />
            {errors.scope_tr && <p className={errCls}>{errors.scope_tr}</p>}
          </div>

          <div>
            <label className={lblCls}>Company scope (EN) *</label>
            <textarea rows={3} className={inputCls} value={form.scope_en}
              onChange={(e) => setForm({ ...form, scope_en: e.target.value })} />
            {errors.scope_en && <p className={errCls}>{errors.scope_en}</p>}
          </div>

          <div className="border-t border-gray-100 pt-4">
            <p className="mb-1 text-sm font-medium text-gray-700">Upload documents</p>
            <p className="mb-3 text-xs text-gray-500">
              Upload company documents (manuals, procedures, records) and the blank report template.
              Accepted: .docx, .pdf, .xlsx
            </p>
            <div className="space-y-3">
              <div>
                <FileZone
                  id="docs" label="Company documents — click to select" multiple
                  accept=".docx,.pdf,.xlsx" files={docs}
                  onAdd={(fs) => setDocs((prev) => [...prev, ...fs])}
                  onRemove={(i) => setDocs((prev) => prev.filter((_, idx) => idx !== i))}
                />
                {errors.docs && <p className={errCls}>{errors.docs}</p>}
              </div>
              <div>
                <FileZone
                  id="template" label="Report template (.docx) — click to select" multiple={false}
                  accept=".docx" files={template}
                  onAdd={(fs) => setTemplate(fs.slice(0, 1))}
                  onRemove={() => setTemplate([])}
                />
                {errors.template && <p className={errCls}>{errors.template}</p>}
              </div>
            </div>
          </div>

          {serverError && (
            <div className="rounded-lg border border-red-200 bg-red-50 p-3 text-sm text-red-700">
              {serverError}
            </div>
          )}

          <button
            type="submit" disabled={isPending}
            className="flex w-full items-center justify-center gap-2 rounded-lg px-4 py-2.5 text-sm font-medium text-white disabled:opacity-60 hover:opacity-90"
            style={{ background: '#1A4731' }}
          >
            {isPending && <Loader2 size={14} className="animate-spin" />}
            Generate report
          </button>
        </form>
      </div>
    </div>
  )
}
