'use client'

import { useEffect, useMemo, useRef, useState } from 'react'
import { CalendarPlus, Check, Download, Loader2, Plus, Trash2, Wand2 } from 'lucide-react'
import api from '@/lib/api'
import { apiErrorMessage } from '@/lib/apiError'
import {
  CertivAIFileDrop,
  CertivAINotice,
  CertivAISection,
  CertivAIStepBar,
  CertivAIToolHeader,
  CertivAIToolShell,
} from '@/components/certivai/CertivAIWorkspace'

type DayWindow = {
  date: string
  start_time: string
  end_time: string
  lunch_start: string
  lunch_end: string
  site: string
}

type AuditPlanJob = {
  audit_plan_job_id: string
  state: 'QUEUED' | 'GENERATING' | 'ASSEMBLING' | 'COMPLETE' | 'FAILED'
  error_message?: string | null
  filename?: string | null
}

const STANDARD_OPTIONS = [
  'ISO 9001:2015', 'ISO 14001:2015', 'ISO 45001:2018', 'ISO 22000:2018',
  'ISO 27001:2022', 'ISO 13485:2016', 'ISO 37001:2016', 'ISO 50001:2018',
]

const AUDIT_TYPES = [
  'Stage 1', 'Stage 2', 'Surveillance 1', 'Surveillance 2', 'Scope Extension',
  'Surveillance 1 + Scope Extension', 'Recertification',
]

const inputClass = 'w-full rounded-xl border border-slate-200 bg-white px-3 py-2.5 text-sm text-slate-800 outline-none transition placeholder:text-slate-400 focus:border-certiva-leaf focus:ring-2 focus:ring-certiva-leaf/15'
const labelClass = 'mb-1.5 block text-xs font-semibold text-slate-600'
const LAST_AUDIT_PLAN_JOB_KEY = 'certivai_last_audit_plan_job'

const emptyDay = (): DayWindow => ({
  date: '', start_time: '09:00', end_time: '17:00',
  lunch_start: '13:00', lunch_end: '14:00', site: '',
})

function toggleValue(values: string[], value: string): string[] {
  return values.includes(value) ? values.filter((item) => item !== value) : [...values, value]
}

function dayError(day: DayWindow): string | null {
  if (!day.date || !day.start_time || !day.end_time) return 'Date, start, and end time are required.'
  if (day.start_time >= day.end_time) return 'End time must be later than start time.'
  if (day.lunch_start >= day.lunch_end) return 'Lunch end must be later than lunch start.'
  if (day.lunch_start < day.start_time || day.lunch_end > day.end_time) return 'Lunch must be inside the audit window.'
  return null
}

export default function CertivAIAuditPlanPage() {
  const [template, setTemplate] = useState<File | null>(null)
  const [standards, setStandards] = useState<string[]>(['ISO 9001:2015'])
  const [auditType, setAuditType] = useState('Stage 2')
  const [eaCode, setEaCode] = useState('')
  const [category, setCategory] = useState('')
  const [scope, setScope] = useState('')
  const [orgName, setOrgName] = useState('')
  const [address, setAddress] = useState('')
  const [days, setDays] = useState<DayWindow[]>([emptyDay()])
  const [job, setJob] = useState<AuditPlanJob | null>(null)
  const [submitting, setSubmitting] = useState(false)
  const [error, setError] = useState('')
  const [successName, setSuccessName] = useState('')
  const downloadedJob = useRef<string | null>(null)

  const dayErrors = useMemo(() => days.map(dayError), [days])
  const allDaysValid = dayErrors.every((value) => !value)
  const busy = submitting || Boolean(job && !['COMPLETE', 'FAILED'].includes(job.state))
  const currentStep = busy || successName ? 2 : template ? 1 : 0

  const updateDay = (index: number, patch: Partial<DayWindow>) => {
    setDays((current) => current.map((day, dayIndex) => dayIndex === index ? { ...day, ...patch } : day))
  }

  useEffect(() => {
    const savedJobId = window.sessionStorage.getItem(LAST_AUDIT_PLAN_JOB_KEY)
    if (savedJobId) {
      setJob({ audit_plan_job_id: savedJobId, state: 'QUEUED' })
    }
  }, [])

  useEffect(() => {
    if (!job || ['COMPLETE', 'FAILED'].includes(job.state)) return
    let cancelled = false
    const poll = async () => {
      try {
        const response = await api.get<AuditPlanJob>(`/audit-plan/jobs/${job.audit_plan_job_id}`)
        if (!cancelled) setJob(response.data)
      } catch (pollError: unknown) {
        if (cancelled) return
        const status = (pollError as { response?: { status?: number } })?.response?.status
        if (status === 404) {
          window.sessionStorage.removeItem(LAST_AUDIT_PLAN_JOB_KEY)
          setJob({ audit_plan_job_id: job.audit_plan_job_id, state: 'FAILED' })
          setError('The saved audit-plan job has expired. Start a new generation.')
          return
        }
        setError(await apiErrorMessage(pollError, 'Could not read audit-plan progress.', 'audit-plan service'))
      }
    }
    void poll()
    const timer = window.setInterval(poll, 2500)
    return () => {
      cancelled = true
      window.clearInterval(timer)
    }
  }, [job?.audit_plan_job_id, job?.state])

  useEffect(() => {
    if (!job) return
    if (job.state === 'FAILED') {
      setError(job.error_message || 'Audit-plan generation failed. Review the inputs and try again.')
      return
    }
    if (job.state !== 'COMPLETE' || downloadedJob.current === job.audit_plan_job_id) return
    downloadedJob.current = job.audit_plan_job_id
    const download = async () => {
      try {
        const response = await api.get(`/audit-plan/jobs/${job.audit_plan_job_id}/download`, { responseType: 'blob' })
        const href = URL.createObjectURL(response.data as Blob)
        const filename = job.filename || 'AuditPlan_CertivAI.docx'
        const link = document.createElement('a')
        link.href = href
        link.download = filename
        document.body.appendChild(link)
        link.click()
        link.remove()
        URL.revokeObjectURL(href)
        setSuccessName(filename)
        window.sessionStorage.removeItem(LAST_AUDIT_PLAN_JOB_KEY)
      } catch (downloadError: unknown) {
        downloadedJob.current = null
        setError(await apiErrorMessage(downloadError, 'The audit plan is ready but could not be downloaded.', 'audit-plan service'))
      }
    }
    void download()
  }, [job])

  const submit = async () => {
    setError('')
    setSuccessName('')
    setJob(null)
    downloadedJob.current = null
    if (!template) return setError('Upload the controlled FR.223 DOCX template first.')
    if (!standards.length) return setError('Select at least one standard.')
    const invalidIndex = dayErrors.findIndex(Boolean)
    if (invalidIndex >= 0) return setError(`Day ${invalidIndex + 1}: ${dayErrors[invalidIndex]}`)

    const form = new FormData()
    form.append('template', template)
    form.append('standards', JSON.stringify(standards))
    form.append('audit_type', auditType)
    form.append('ea_code', eaCode)
    form.append('category', category)
    form.append('scope', scope)
    form.append('org_name', orgName)
    form.append('address', address)
    form.append('day_windows', JSON.stringify(days))

    setSubmitting(true)
    try {
      const response = await api.post<AuditPlanJob>('/audit-plan/jobs', form, {
        headers: { 'Content-Type': 'multipart/form-data' },
      })
      window.sessionStorage.setItem(LAST_AUDIT_PLAN_JOB_KEY, response.data.audit_plan_job_id)
      setJob(response.data)
    } catch (submitError: unknown) {
      setError(await apiErrorMessage(submitError, 'Could not start audit-plan generation.', 'audit-plan service'))
    } finally {
      setSubmitting(false)
    }
  }

  const statusText = submitting
    ? 'Uploading and validating the FR.223 template…'
    : job?.state === 'QUEUED'
      ? 'Queued safely. The job no longer depends on one long browser request.'
      : job?.state === 'GENERATING'
        ? 'Building and validating the clause schedule…'
        : job?.state === 'ASSEMBLING'
          ? 'Writing the verified schedule into the controlled template…'
          : ''

  return (
    <CertivAIToolShell>
      <CertivAIToolHeader
        eyebrow="Plan with controlled inputs"
        title="Audit Plan Generator"
        description="Build a validated FR.223 schedule as a background job. Exact day windows and FR.222 clause coverage remain enforced even if the browser connection changes."
        icon={<Wand2 size={22} />}
        aside={
          <div className="min-w-48 text-xs text-white/60">
            <p className="font-semibold text-white">{standards.length} standard{standards.length === 1 ? '' : 's'} · {days.length} day{days.length === 1 ? '' : 's'}</p>
            <p className="mt-1">{auditType}</p>
          </div>
        }
      />
      <CertivAIStepBar steps={['Upload template', 'Set audit context', 'Generate & download']} current={currentStep} />

      <div className="mt-5 grid gap-5 xl:grid-cols-[minmax(0,1fr)_340px]">
        <div className="space-y-5">
          <CertivAISection title="1. Controlled template" description="Use the pre-filled FR.223 for this audit. The generator only fills the schedule area.">
            <CertivAIFileDrop
              id="audit-plan-template"
              title={template ? 'Replace FR.223 template' : 'Choose FR.223 DOCX template'}
              description="DOCX or DOC · maximum 20 MB"
              accept=".doc,.docx"
              files={template ? [template] : []}
              onAdd={(files) => setTemplate(files[0] ?? null)}
              onRemove={() => setTemplate(null)}
            />
          </CertivAISection>

          <CertivAISection title="2. Standards and audit context" description="Select every standard in the audit. Integrated schedules use the combined FR.222 mapping.">
            <div className="grid gap-2 sm:grid-cols-2 lg:grid-cols-4">
              {STANDARD_OPTIONS.map((standard) => {
                const active = standards.includes(standard)
                return (
                  <button
                    key={standard}
                    type="button"
                    onClick={() => setStandards((current) => toggleValue(current, standard))}
                    className={[
                      'flex items-center justify-between rounded-xl border px-3 py-3 text-left text-sm font-semibold transition',
                      active ? 'border-certiva-leaf bg-certiva-mist text-certiva-green' : 'border-slate-200 bg-white text-slate-600 hover:border-slate-300',
                    ].join(' ')}
                  >
                    {standard}
                    <span className={`flex h-5 w-5 items-center justify-center rounded-full ${active ? 'bg-certiva-green text-white' : 'border border-slate-300 text-transparent'}`}><Check size={12} /></span>
                  </button>
                )
              })}
            </div>

            <div className="mt-5 grid gap-4 md:grid-cols-3">
              <label><span className={labelClass}>Audit type</span><select value={auditType} onChange={(event) => setAuditType(event.target.value)} className={inputClass}>{AUDIT_TYPES.map((type) => <option key={type}>{type}</option>)}</select></label>
              <label><span className={labelClass}>EA / IAF code</span><input value={eaCode} onChange={(event) => setEaCode(event.target.value)} placeholder="e.g. EA 19, EA 29" className={inputClass} /></label>
              <label><span className={labelClass}>Category / technical area</span><input value={category} onChange={(event) => setCategory(event.target.value)} placeholder="e.g. A.1.1 or CI" className={inputClass} /></label>
            </div>
            <label className="mt-4 block"><span className={labelClass}>Certification scope and process context</span><textarea value={scope} onChange={(event) => setScope(event.target.value)} rows={4} placeholder="Paste the approved scope and important process details." className={inputClass} /></label>
            <details className="mt-4 rounded-xl border border-slate-200 bg-slate-50 px-4 py-3">
              <summary className="cursor-pointer text-sm font-semibold text-slate-700">Template data overrides</summary>
              <div className="mt-4 grid gap-4 md:grid-cols-2">
                <label><span className={labelClass}>Organisation name</span><input value={orgName} onChange={(event) => setOrgName(event.target.value)} placeholder="Only if the template value needs correction" className={inputClass} /></label>
                <label><span className={labelClass}>Head office address</span><input value={address} onChange={(event) => setAddress(event.target.value)} placeholder="Only if the template value needs correction" className={inputClass} /></label>
              </div>
            </details>
          </CertivAISection>

          <CertivAISection
            title="3. Exact audit windows"
            description="Each day is authoritative. The generated schedule cannot move outside these hours."
            action={<button type="button" onClick={() => setDays((current) => [...current, emptyDay()])} className="inline-flex items-center gap-2 rounded-xl bg-certiva-green px-3 py-2 text-sm font-semibold text-white hover:bg-certiva-mid"><Plus size={15} /> Add day</button>}
          >
            <div className="space-y-3">
              {days.map((day, index) => (
                <div key={index} className="rounded-xl border border-slate-200 bg-slate-50/70 p-4">
                  <div className="mb-3 flex items-center justify-between">
                    <span className="inline-flex items-center gap-2 text-sm font-semibold text-slate-800"><CalendarPlus size={16} className="text-certiva-mid" /> Day {index + 1}</span>
                    <button type="button" onClick={() => setDays((current) => current.length === 1 ? current : current.filter((_, dayIndex) => dayIndex !== index))} disabled={days.length === 1} className="rounded-lg p-1.5 text-slate-400 hover:bg-red-50 hover:text-red-600 disabled:opacity-25" aria-label={`Remove day ${index + 1}`}><Trash2 size={15} /></button>
                  </div>
                  <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-5">
                    <label><span className={labelClass}>Date</span><input type="date" value={day.date} onChange={(event) => updateDay(index, { date: event.target.value })} className={inputClass} /></label>
                    <label><span className={labelClass}>Start</span><input type="time" value={day.start_time} onChange={(event) => updateDay(index, { start_time: event.target.value })} className={inputClass} /></label>
                    <label><span className={labelClass}>End</span><input type="time" value={day.end_time} onChange={(event) => updateDay(index, { end_time: event.target.value })} className={inputClass} /></label>
                    <label><span className={labelClass}>Lunch start</span><input type="time" value={day.lunch_start} onChange={(event) => updateDay(index, { lunch_start: event.target.value })} className={inputClass} /></label>
                    <label><span className={labelClass}>Lunch end</span><input type="time" value={day.lunch_end} onChange={(event) => updateDay(index, { lunch_end: event.target.value })} className={inputClass} /></label>
                  </div>
                  <label className="mt-3 block"><span className={labelClass}>Site for this day</span><input value={day.site} onChange={(event) => updateDay(index, { site: event.target.value })} placeholder="Leave blank to use the head office address" className={inputClass} /></label>
                  {dayErrors[index] && <p className="mt-2 text-xs font-medium text-red-600">{dayErrors[index]}</p>}
                </div>
              ))}
            </div>
          </CertivAISection>
        </div>

        <aside className="space-y-4 xl:sticky xl:top-5 xl:self-start">
          <div className="rounded-2xl border border-emerald-950/10 bg-white p-5 shadow-sm">
            <p className="text-xs font-bold uppercase tracking-[0.14em] text-certiva-mid">Generation summary</p>
            <dl className="mt-4 space-y-3 text-sm">
              <div className="flex justify-between gap-4"><dt className="text-slate-500">Template</dt><dd className="max-w-44 truncate font-semibold text-slate-800">{template?.name || 'Missing'}</dd></div>
              <div className="flex justify-between gap-4"><dt className="text-slate-500">Standards</dt><dd className="font-semibold text-slate-800">{standards.length}</dd></div>
              <div className="flex justify-between gap-4"><dt className="text-slate-500">Audit days</dt><dd className="font-semibold text-slate-800">{days.length}</dd></div>
              <div className="flex justify-between gap-4"><dt className="text-slate-500">Windows</dt><dd className={`font-semibold ${allDaysValid ? 'text-certiva-mid' : 'text-red-600'}`}>{allDaysValid ? 'Valid' : 'Needs attention'}</dd></div>
            </dl>
            <button type="button" onClick={submit} disabled={busy} className="mt-5 inline-flex w-full items-center justify-center gap-2 rounded-xl bg-certiva-green px-4 py-3 text-sm font-semibold text-white transition hover:bg-certiva-mid disabled:cursor-wait disabled:opacity-60">
              {busy ? <Loader2 size={17} className="animate-spin" /> : <Download size={17} />}
              {busy ? 'Generating…' : 'Generate audit plan'}
            </button>
            <p className="mt-3 text-xs leading-5 text-slate-500">The job continues safely in the background after it has been queued.</p>
          </div>
          {statusText && <CertivAINotice tone="info">{statusText}</CertivAINotice>}
          {error && <CertivAINotice tone="error">{error}</CertivAINotice>}
          {successName && <CertivAINotice tone="success">Generated and downloaded: <strong>{successName}</strong></CertivAINotice>}
        </aside>
      </div>
    </CertivAIToolShell>
  )
}
