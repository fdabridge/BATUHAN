'use client'

import { useEffect, useMemo, useState } from 'react'
import Link from 'next/link'
import { useRouter, useSearchParams } from 'next/navigation'
import { ArrowLeft, BrainCircuit, Check, FileText, Layers3, Loader2, Upload, X, Zap } from 'lucide-react'
import { useMutation, useQuery } from '@tanstack/react-query'
import api from '@/lib/api'
import { normalizeISOStandardCodes } from '@/lib/isoStandards'
import type { AuditSetResponse, JobCreateResponse } from '@/types'

const STANDARDS = [
  { value: 'QMS', label: 'ISO 9001', tone: 'Quality' },
  { value: 'EMS', label: 'ISO 14001', tone: 'Environment' },
  { value: 'OHSMS', label: 'ISO 45001', tone: 'OH&S' },
  { value: 'FSMS', label: 'ISO 22000', tone: 'Food safety' },
  { value: 'ISMS', label: 'ISO 27001', tone: 'Information security' },
  { value: 'MDQMS', label: 'ISO 13485', tone: 'Medical devices' },
  { value: 'ABMS', label: 'ISO 37001', tone: 'Anti-bribery' },
  { value: 'ENMS', label: 'ISO 50001', tone: 'Energy' },
] as const

const REPORT_CONTEXTS = [
  {
    value: 'Stage 1',
    label: 'Stage 1',
    eyebrow: 'Readiness',
    detail: 'Documentation, scope, preparedness, and Stage 2 readiness.',
  },
  {
    value: 'Stage 2',
    label: 'Stage 2',
    eyebrow: 'Certification',
    detail: 'Implementation, effectiveness, findings, and certification recommendation.',
  },
  {
    value: 'Surveillance 1',
    label: 'Surveillance 1',
    eyebrow: 'Continuation',
    detail: 'First surveillance cycle, maintained conformity, and certificate continuation.',
  },
  {
    value: 'Surveillance 2',
    label: 'Surveillance 2',
    eyebrow: 'Continuation',
    detail: 'Second surveillance cycle, trend follow-up, and ongoing certificate validity.',
  },
  {
    value: 'Recertification',
    label: 'Recertification',
    eyebrow: 'Renewal',
    detail: 'Full-cycle review, effectiveness, changes, and renewal recommendation.',
  },
] as const

const BODIES = ['UAF', 'TURKAK'] as const

const inputCls = 'w-full rounded-lg border border-slate-200 bg-white px-3 py-2.5 text-sm text-slate-800 placeholder-slate-400 outline-none focus:border-certiva-primary focus:ring-2 focus:ring-certiva-primary/20'
const labelCls = 'mb-1.5 block text-xs font-semibold uppercase text-slate-500'
const errorCls = 'mt-1 text-xs text-red-500'

interface FormState {
  standards: string[]
  stage: string
  accreditation_body: string
  company_name: string
  scope_tr: string
  scope_en: string
}

function formatApiError(err: unknown, fallback: string): string {
  const detail = (err as { response?: { data?: { detail?: unknown } }; message?: string })?.response?.data?.detail
  if (typeof detail === 'string') return detail
  if (Array.isArray(detail)) {
    const messages = detail.map((item) => {
      if (typeof item === 'string') return item
      if (item && typeof item === 'object') {
        const record = item as { loc?: unknown[]; msg?: unknown }
        const loc = Array.isArray(record.loc) ? record.loc.join('.') : ''
        const msg = typeof record.msg === 'string' ? record.msg : JSON.stringify(item)
        return loc ? `${loc}: ${msg}` : msg
      }
      return String(item)
    }).filter(Boolean)
    if (messages.length) return messages.join('; ')
  }
  if (detail && typeof detail === 'object') return JSON.stringify(detail)
  const message = (err as { message?: string })?.message
  return message || fallback
}

function FileZone({
  id, label, hint, multiple, accept, files, onAdd, onRemove,
}: {
  id: string
  label: string
  hint: string
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
        className="flex cursor-pointer flex-col gap-3 rounded-lg border border-dashed border-slate-300 bg-slate-50/70 px-4 py-5 transition hover:border-certiva-primary hover:bg-emerald-50"
      >
        <span className="flex h-10 w-10 items-center justify-center rounded-lg bg-white text-certiva-primary shadow-sm">
          <Upload size={18} />
        </span>
        <span>
          <span className="block text-sm font-semibold text-slate-800">{label}</span>
          <span className="mt-1 block text-xs text-slate-500">{hint}</span>
        </span>
        <input
          id={id}
          type="file"
          multiple={multiple}
          accept={accept}
          className="hidden"
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
            <li key={`${f.name}-${i}`} className="flex items-center justify-between rounded border border-slate-100 bg-white px-2 py-1.5 text-xs text-slate-700">
              <span className="truncate pr-2">{f.name}</span>
              <button type="button" onClick={() => onRemove(i)} className="text-slate-400 hover:text-red-500">
                <X size={13} />
              </button>
            </li>
          ))}
        </ul>
      )}
    </div>
  )
}

function StandardPicker({
  selected,
  onChange,
}: {
  selected: string[]
  onChange: (next: string[]) => void
}) {
  function toggle(value: string) {
    if (selected.includes(value)) {
      onChange(selected.filter((s) => s !== value))
    } else {
      onChange([...selected, value])
    }
  }

  return (
    <div className="grid gap-2 sm:grid-cols-2 lg:grid-cols-4">
      {STANDARDS.map((std) => {
        const active = selected.includes(std.value)
        return (
          <button
            key={std.value}
            type="button"
            onClick={() => toggle(std.value)}
            className={`min-h-[88px] rounded-lg border p-3 text-left transition ${
              active
                ? 'border-emerald-400 bg-emerald-50 text-emerald-950 shadow-sm'
                : 'border-slate-200 bg-white text-slate-700 hover:border-slate-300'
            }`}
          >
            <span className="flex items-center justify-between gap-2">
              <span className="text-sm font-semibold">{std.label}</span>
              <span className={`flex h-5 w-5 items-center justify-center rounded-full border ${active ? 'border-emerald-500 bg-emerald-500 text-white' : 'border-slate-300 text-transparent'}`}>
                <Check size={12} />
              </span>
            </span>
            <span className="mt-1 block text-xs text-slate-500">{std.value} - {std.tone}</span>
          </button>
        )
      })}
    </div>
  )
}

function ContextPicker({
  value,
  onChange,
}: {
  value: string
  onChange: (next: string) => void
}) {
  return (
    <div className="grid gap-2 md:grid-cols-5">
      {REPORT_CONTEXTS.map((ctx) => {
        const active = value === ctx.value
        return (
          <button
            key={ctx.value}
            type="button"
            onClick={() => onChange(ctx.value)}
            className={`min-h-[126px] rounded-lg border p-3 text-left transition ${
              active
                ? 'border-cyan-300 bg-cyan-50 shadow-sm'
                : 'border-slate-200 bg-white hover:border-slate-300'
            }`}
          >
            <span className="block text-[11px] font-semibold uppercase text-cyan-700">{ctx.eyebrow}</span>
            <span className="mt-1 block text-sm font-semibold text-slate-900">{ctx.label}</span>
            <span className="mt-2 block text-xs leading-5 text-slate-500">{ctx.detail}</span>
          </button>
        )
      })}
    </div>
  )
}

export default function NewReportPage() {
  const router = useRouter()
  const sp = useSearchParams()
  const clientId = sp.get('client_id')

  const [form, setForm] = useState<FormState>({
    standards: [],
    stage: '',
    accreditation_body: 'UAF',
    company_name: '',
    scope_tr: '',
    scope_en: '',
  })
  const [docs, setDocs] = useState<File[]>([])
  const [template, setTemplate] = useState<File[]>([])
  const [errors, setErrors] = useState<Record<string, string>>({})
  const [serverError, setServerError] = useState<string | null>(null)

  const { data: client } = useQuery<AuditSetResponse>({
    queryKey: ['client', clientId],
    queryFn: () => api.get<AuditSetResponse>(`/audit-sets/${clientId}`).then((r) => r.data),
    enabled: !!clientId,
  })

  useEffect(() => {
    if (!client) return
    const clientStandards = normalizeISOStandardCodes(client.standards ?? [])
    const mappedStage =
      client.audit_type === 'surveillance_1' ? 'Surveillance 1'
      : client.audit_type === 'surveillance_2' ? 'Surveillance 2'
      : client.audit_type === 'recertification' ? 'Recertification'
      : ''

    setForm((f) => ({
      ...f,
      standards: f.standards.length ? f.standards : clientStandards,
      stage: f.stage || mappedStage,
      accreditation_body: client.accreditation_body ?? f.accreditation_body,
      company_name: f.company_name || client.company_name,
      scope_tr: f.scope_tr || (client.scope_tr ?? ''),
      scope_en: f.scope_en || (client.scope_en ?? ''),
    }))
  }, [client])

  const selectedLabel = useMemo(() => {
    if (!form.standards.length) return 'No standards selected'
    return form.standards.join(' + ')
  }, [form.standards])

  function validate(): boolean {
    const e: Record<string, string> = {}
    if (form.standards.length === 0) e.standards = 'Select at least one standard'
    if (!form.stage) e.stage = 'Select the report context'
    if (!form.accreditation_body) e.accreditation_body = 'Required'
    if (!form.company_name.trim()) e.company_name = 'Required'
    if (!form.scope_tr.trim()) e.scope_tr = 'Required'
    if (!form.scope_en.trim()) e.scope_en = 'Required'
    if (docs.length === 0) e.docs = 'Upload at least one evidence document'
    if (template.length === 0) e.template = 'Upload a report template'
    setErrors(e)
    return Object.keys(e).length === 0
  }

  const { mutate, isPending } = useMutation<JobCreateResponse>({
    mutationFn: async () => {
      const fd = new FormData()
      form.standards.forEach((standard) => fd.append('standards', standard))
      fd.append('stage', form.stage)
      fd.append('accreditation_body', form.accreditation_body)
      fd.append('language', form.accreditation_body === 'TURKAK' ? 'TR' : 'EN')
      fd.append('org_name', form.company_name.trim())
      fd.append('org_address', client?.company_address?.trim() ?? '')
      fd.append('org_scope_en', form.scope_en.trim())
      fd.append('org_scope_tr', form.scope_tr.trim())
      docs.forEach((f) => fd.append('company_documents', f))
      fd.append('template', template[0])
      const res = await api.post<JobCreateResponse>('/jobs/create', fd, {
        headers: { 'Content-Type': 'multipart/form-data' },
      })
      return res.data
    },
    onSuccess: (data) => {
      const qs = new URLSearchParams({
        standards: form.standards.join(','),
        standard: form.standards[0] ?? '',
        stage: form.stage,
        accreditation_body: form.accreditation_body,
        company: form.company_name,
      })
      if (clientId) qs.set('client_id', clientId)
      router.push(`/reports/${data.job_id}?${qs.toString()}`)
    },
    onError: (err: unknown) => {
      setServerError(formatApiError(err, 'Failed to submit job.'))
    },
  })

  function onSubmit(e: React.FormEvent) {
    e.preventDefault()
    setServerError(null)
    if (validate()) mutate()
  }

  return (
    <div className="min-h-[calc(100vh-52px)] bg-[#07130E] px-5 py-6 text-slate-950">
      <div className="mx-auto max-w-[1180px]">
        <Link href="/certivai/reports" className="mb-5 inline-flex items-center gap-2 text-sm text-emerald-200 hover:text-white">
          <ArrowLeft size={16} />
          Report Generation
        </Link>

        <section className="overflow-hidden rounded-lg border border-white/10 bg-white">
          <div className="bg-[radial-gradient(circle_at_20%_10%,rgba(34,211,238,0.22),transparent_28%),linear-gradient(135deg,#081D15,#0B1720)] px-6 py-7 text-white">
            <div className="flex flex-col justify-between gap-5 lg:flex-row lg:items-end">
              <div>
                <div className="mb-4 inline-flex items-center gap-2 rounded border border-cyan-200/25 bg-white/10 px-3 py-1 text-xs font-semibold text-cyan-100">
                  <BrainCircuit size={14} />
                  Certiv.AI report engine
                </div>
                <h1 className="text-3xl font-semibold">Generate an audit report with full audit context</h1>
                <p className="mt-3 max-w-3xl text-sm leading-6 text-slate-300">
                  Select integrated standards, the exact cycle, accreditation body, evidence, and the target template before the job starts.
                </p>
              </div>
              <div className="grid min-w-[280px] grid-cols-2 gap-2 rounded-lg border border-white/10 bg-white/10 p-3">
                <div>
                  <p className="text-[11px] font-semibold uppercase text-slate-400">Selected</p>
                  <p className="mt-1 text-sm font-semibold text-white">{selectedLabel}</p>
                </div>
                <div>
                  <p className="text-[11px] font-semibold uppercase text-slate-400">Cycle</p>
                  <p className="mt-1 text-sm font-semibold text-white">{form.stage || 'Not selected'}</p>
                </div>
              </div>
            </div>
          </div>

          <form onSubmit={onSubmit} className="space-y-6 p-6">
            {client && (
              <div className="rounded-lg border border-emerald-100 bg-emerald-50 p-4">
                <p className="text-sm font-semibold text-emerald-950">{client.company_name}</p>
                <p className="mt-1 text-xs text-emerald-800">Loaded from certification plan #{client.plan_number}</p>
              </div>
            )}

            <section>
              <div className="mb-3 flex items-center gap-2">
                <Layers3 size={18} className="text-certiva-primary" />
                <div>
                  <h2 className="text-base font-semibold text-slate-900">Integrated standards</h2>
                  <p className="text-xs text-slate-500">Choose every standard covered by this report. Multi-standard jobs are passed to the backend as an integrated audit.</p>
                </div>
              </div>
              <StandardPicker
                selected={form.standards}
                onChange={(standards) => setForm({ ...form, standards })}
              />
              {errors.standards && <p className={errorCls}>{errors.standards}</p>}
            </section>

            <section>
              <div className="mb-3 flex items-center gap-2">
                <Zap size={18} className="text-cyan-700" />
                <div>
                  <h2 className="text-base font-semibold text-slate-900">Report context</h2>
                  <p className="text-xs text-slate-500">This controls the AI instructions. Surveillance and recertification are not treated as Stage 1/Stage 2 reports.</p>
                </div>
              </div>
              <ContextPicker
                value={form.stage}
                onChange={(stage) => setForm({ ...form, stage })}
              />
              {errors.stage && <p className={errorCls}>{errors.stage}</p>}
            </section>

            <section className="grid gap-4 md:grid-cols-2">
              <div>
                <label className={labelCls}>Accreditation body *</label>
                <select
                  className={inputCls}
                  value={form.accreditation_body}
                  onChange={(e) => setForm({ ...form, accreditation_body: e.target.value })}
                >
                  {BODIES.map((b) => <option key={b} value={b}>{b}</option>)}
                </select>
                {errors.accreditation_body && <p className={errorCls}>{errors.accreditation_body}</p>}
              </div>
              <div>
                <label className={labelCls}>Company name *</label>
                <input
                  type="text"
                  className={inputCls}
                  value={form.company_name}
                  onChange={(e) => setForm({ ...form, company_name: e.target.value })}
                />
                {errors.company_name && <p className={errorCls}>{errors.company_name}</p>}
              </div>
            </section>

            <section className="grid gap-4 md:grid-cols-2">
              <div>
                <label className={labelCls}>Company scope (TR) *</label>
                <textarea
                  rows={4}
                  className={inputCls}
                  value={form.scope_tr}
                  onChange={(e) => setForm({ ...form, scope_tr: e.target.value })}
                />
                {errors.scope_tr && <p className={errorCls}>{errors.scope_tr}</p>}
              </div>
              <div>
                <label className={labelCls}>Company scope (EN) *</label>
                <textarea
                  rows={4}
                  className={inputCls}
                  value={form.scope_en}
                  onChange={(e) => setForm({ ...form, scope_en: e.target.value })}
                />
                {errors.scope_en && <p className={errorCls}>{errors.scope_en}</p>}
              </div>
            </section>

            <section className="grid gap-4 lg:grid-cols-2">
              <div>
                <div className="mb-3 flex items-center gap-2">
                  <FileText size={18} className="text-certiva-primary" />
                  <h2 className="text-base font-semibold text-slate-900">Evidence package</h2>
                </div>
                <FileZone
                  id="docs"
                  label="Upload company evidence"
                  hint="PDF, DOCX, DOC, TXT, PNG, JPG, JPEG, TIFF"
                  multiple
                  accept=".pdf,.docx,.doc,.txt,.png,.jpg,.jpeg,.tiff"
                  files={docs}
                  onAdd={(fs) => setDocs((prev) => [...prev, ...fs])}
                  onRemove={(i) => setDocs((prev) => prev.filter((_, idx) => idx !== i))}
                />
                {errors.docs && <p className={errorCls}>{errors.docs}</p>}
              </div>
              <div>
                <div className="mb-3 flex items-center gap-2">
                  <FileText size={18} className="text-cyan-700" />
                  <h2 className="text-base font-semibold text-slate-900">Target template</h2>
                </div>
                <FileZone
                  id="template"
                  label="Upload the blank report template"
                  hint="DOCX template only"
                  multiple={false}
                  accept=".docx"
                  files={template}
                  onAdd={(fs) => setTemplate(fs.slice(0, 1))}
                  onRemove={() => setTemplate([])}
                />
                {errors.template && <p className={errorCls}>{errors.template}</p>}
              </div>
            </section>

            {serverError && (
              <div className="rounded-lg border border-red-200 bg-red-50 p-3 text-sm text-red-700">
                {serverError}
              </div>
            )}

            <div className="flex flex-col gap-3 border-t border-slate-100 pt-5 sm:flex-row sm:items-center sm:justify-between">
              <p className="text-xs leading-5 text-slate-500">
                The job will use {selectedLabel} and {form.stage || 'the selected report context'} for clause, finding, and conclusion logic.
              </p>
              <button
                type="submit"
                disabled={isPending}
                className="inline-flex min-w-[190px] items-center justify-center gap-2 rounded-lg bg-certiva-primary px-5 py-3 text-sm font-semibold text-white disabled:opacity-60 hover:opacity-90"
              >
                {isPending && <Loader2 size={14} className="animate-spin" />}
                Generate report
              </button>
            </div>
          </form>
        </section>
      </div>
    </div>
  )
}
