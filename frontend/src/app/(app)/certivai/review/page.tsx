'use client'

import { useEffect, useMemo, useState } from 'react'
import api from '@/lib/api'
import { apiErrorMessage } from '@/lib/apiError'
import { Check, Download, FileSearch, Loader2, ShieldCheck } from 'lucide-react'
import {
  CertivAIFileDrop,
  CertivAINotice,
  CertivAISection,
  CertivAIStepBar,
  CertivAIToolHeader,
  CertivAIToolShell,
} from '@/components/certivai/CertivAIWorkspace'

type ReviewProfile = {
  code: string
  display_name: string
  governing_standard: string
  reference_basis: string[]
  required_report_elements: string[]
}

type ReviewReferences = {
  profiles: ReviewProfile[]
  standards: string[]
  stages: string[]
  file_types: string[]
}

type ReviewStatus = {
  review_job_id: string
  state: string
  standard_code: string
  accreditation_body: string
  error_message?: string | null
}

type ReviewFinding = {
  clause_id: string
  clause_title: string
  finding_type: string
  severity: 'CRITICAL' | 'MAJOR' | 'MINOR' | 'WARNING' | 'OK'
  description: string
  suggestion: string
  quote: string
}

type ReviewSummary = {
  review_job_id: string
  standard_code: string
  stage: string
  accreditation_body: string
  total_findings: number
  critical_count: number
  major_count: number
  minor_count: number
  warning_count: number
  findings: ReviewFinding[]
  overall_assessment: string
}

const FALLBACK_REFERENCES: ReviewReferences = {
  profiles: [{
    code: 'UAF',
    display_name: 'UAF (United Accreditation Foundation)',
    governing_standard: 'ISO/IEC 17021-1:2015',
    reference_basis: [
      'ISO/IEC 17021-1:2015 certification report controls',
      'UAF accreditation profile and internal certification procedures',
      'Selected management-system clause maps',
    ],
    required_report_elements: ['audit_scope', 'audit_objectives', 'audit_criteria', 'findings_per_clause_with_evidence'],
  }],
  standards: ['QMS', 'EMS', 'OHSMS', 'FSMS', 'MDQMS', 'ISMS', 'ABMS', 'ENMS'],
  stages: ['Stage 1', 'Stage 2', 'Surveillance 1', 'Surveillance 2', 'Recertification'],
  file_types: ['.pdf', '.docx'],
}

const STATE_COPY: Record<string, string> = {
  QUEUED: 'Queued safely',
  PREPROCESSING: 'Reading and checking the report',
  REVIEWING: 'Comparing evidence and requirements',
  ANNOTATING: 'Preparing the annotated document',
  COMPLETE: 'Review complete',
  FAILED: 'Review failed',
}

const SEVERITY_STYLES: Record<ReviewFinding['severity'], string> = {
  CRITICAL: 'border-red-200 bg-red-50 text-red-900',
  MAJOR: 'border-orange-200 bg-orange-50 text-orange-900',
  MINOR: 'border-amber-200 bg-amber-50 text-amber-900',
  WARNING: 'border-sky-200 bg-sky-50 text-sky-900',
  OK: 'border-emerald-200 bg-emerald-50 text-emerald-900',
}

const inputClass = 'w-full rounded-xl border border-slate-200 bg-white px-3 py-2.5 text-sm text-slate-800 outline-none focus:border-certiva-leaf focus:ring-2 focus:ring-certiva-leaf/15'
const labelClass = 'mb-1.5 block text-xs font-semibold text-slate-600'

export default function CertivAIReviewPage() {
  const [references, setReferences] = useState<ReviewReferences>(FALLBACK_REFERENCES)
  const [selectedStandards, setSelectedStandards] = useState<string[]>(['QMS'])
  const [stage, setStage] = useState('Stage 2')
  const [profileCode, setProfileCode] = useState('UAF')
  const [report, setReport] = useState<File | null>(null)
  const [jobId, setJobId] = useState<string | null>(null)
  const [status, setStatus] = useState<ReviewStatus | null>(null)
  const [summary, setSummary] = useState<ReviewSummary | null>(null)
  const [busy, setBusy] = useState(false)
  const [message, setMessage] = useState<string | null>(null)
  const [downloading, setDownloading] = useState(false)

  useEffect(() => {
    let alive = true
    api.get<ReviewReferences>('/review/references')
      .then((response) => {
        if (!alive) return
        setReferences(response.data)
        const available = response.data.standards.length ? response.data.standards : FALLBACK_REFERENCES.standards
        setSelectedStandards((current) => current.filter((item) => available.includes(item)).length ? current.filter((item) => available.includes(item)) : [available[0]])
        if (response.data.profiles.length) setProfileCode(response.data.profiles.find((profile) => profile.code === 'UAF')?.code || response.data.profiles[0].code)
      })
      .catch(() => setReferences(FALLBACK_REFERENCES))
    return () => { alive = false }
  }, [])

  useEffect(() => {
    if (!jobId || summary || status?.state === 'FAILED' || status?.state === 'COMPLETE') return
    let alive = true
    const poll = async () => {
      try {
        const response = await api.get<ReviewStatus>(`/review/${jobId}/status`)
        if (!alive) return
        if (response.data.state === 'COMPLETE') {
          const result = await api.get<ReviewSummary>(`/review/${jobId}/download/review-summary`)
          if (alive) {
            setStatus(response.data)
            setSummary(result.data)
            setMessage(null)
          }
        } else if (response.data.state === 'FAILED') {
          setStatus(response.data)
          setMessage(response.data.error_message || 'Review failed. Check the file and try again.')
        } else {
          setStatus(response.data)
          setMessage(null)
        }
      } catch {
        if (alive) setMessage('The progress check was interrupted. Certiv.AI will keep trying automatically.')
      }
    }
    void poll()
    const timer = window.setInterval(poll, 3500)
    return () => {
      alive = false
      window.clearInterval(timer)
    }
  }, [jobId, status?.state, summary])

  const selectedProfile = useMemo(
    () => references.profiles.find((profile) => profile.code === profileCode) || references.profiles[0],
    [references.profiles, profileCode],
  )
  const actionable = useMemo(() => (summary?.findings || []).filter((finding) => finding.finding_type !== 'OK'), [summary])
  const okCount = useMemo(() => (summary?.findings || []).filter((finding) => finding.finding_type === 'OK').length, [summary])
  const hasDocxSource = Boolean(report?.name.toLowerCase().endsWith('.docx'))
  const standardLabel = selectedStandards.join(' + ')
  const running = Boolean(status && !['COMPLETE', 'FAILED'].includes(status.state))
  const currentStep = jobId ? 2 : report ? 1 : 0

  function toggleStandard(item: string) {
    setSelectedStandards((current) => current.includes(item)
      ? current.length === 1 ? current : current.filter((value) => value !== item)
      : [...current, item])
  }

  async function submitReview() {
    setMessage(null)
    if (!report) return setMessage('Choose a completed audit report PDF or DOCX first.')
    if (!selectedStandards.length) return setMessage('Select at least one standard.')
    const name = report.name.toLowerCase()
    if (!name.endsWith('.pdf') && !name.endsWith('.docx')) return setMessage('Report Review accepts PDF or DOCX only.')

    setBusy(true)
    setSummary(null)
    setStatus(null)
    setJobId(null)
    const form = new FormData()
    form.append('report', report)
    selectedStandards.forEach((item) => form.append('standards', item))
    form.append('stage', stage)
    form.append('accreditation_body', profileCode)
    try {
      const response = await api.post<{ review_job_id: string; state: string }>('/review/submit', form, { headers: { 'Content-Type': 'multipart/form-data' } })
      setJobId(response.data.review_job_id)
      setStatus({ review_job_id: response.data.review_job_id, state: response.data.state, standard_code: standardLabel, accreditation_body: profileCode })
    } catch (error: unknown) {
      setMessage(await apiErrorMessage(error, 'Could not submit the report for review.', 'report-review service'))
    } finally {
      setBusy(false)
    }
  }

  async function downloadAnnotatedReport() {
    if (!jobId) return
    setDownloading(true)
    setMessage(null)
    try {
      const response = await api.get(`/review/${jobId}/download/annotated-report`, { responseType: 'blob' })
      const href = URL.createObjectURL(response.data)
      const link = document.createElement('a')
      link.href = href
      link.download = `certivai_review_${jobId}.docx`
      document.body.appendChild(link)
      link.click()
      link.remove()
      URL.revokeObjectURL(href)
    } catch (error: unknown) {
      setMessage(await apiErrorMessage(error, 'Could not download the annotated report.', 'report-review service'))
    } finally {
      setDownloading(false)
    }
  }

  return (
    <CertivAIToolShell>
      <CertivAIToolHeader
        eyebrow="Review against controlled references"
        title="Report Review"
        description="Check a completed report against the selected accreditation profile, audit cycle, integrated standard clause maps, and evidence requirements."
        icon={<FileSearch size={22} />}
        aside={<div className="min-w-44 text-xs text-white/60"><p className="font-semibold text-white">{standardLabel}</p><p className="mt-1">{stage} · {profileCode}</p></div>}
      />
      <CertivAIStepBar steps={['Choose report', 'Set review basis', 'Review & resolve']} current={currentStep} />

      <div className="mt-5 grid gap-5 lg:grid-cols-[minmax(0,1fr)_360px]">
        <div className="space-y-5">
          <CertivAISection title="1. Completed report" description="Upload the exact report to be assessed. Searchable files produce the most reliable evidence review.">
            <CertivAIFileDrop
              id="review-report"
              title={report ? 'Replace completed report' : 'Choose completed report'}
              description="PDF or DOCX · DOCX also supports an annotated download"
              accept=".pdf,.docx"
              files={report ? [report] : []}
              onAdd={(files) => setReport(files[0] ?? null)}
              onRemove={() => setReport(null)}
            />
          </CertivAISection>

          <CertivAISection title="2. Review basis" description="Select every standard in the report and the exact audit cycle.">
            <div className="grid grid-cols-2 gap-2 sm:grid-cols-4">
              {references.standards.map((item) => {
                const active = selectedStandards.includes(item)
                return (
                  <button key={item} type="button" onClick={() => toggleStandard(item)} className={`flex items-center justify-between rounded-xl border px-3 py-3 text-sm font-semibold transition ${active ? 'border-certiva-leaf bg-certiva-mist text-certiva-green' : 'border-slate-200 text-slate-600 hover:border-slate-300'}`}>
                    {item}<span className={`flex h-5 w-5 items-center justify-center rounded-full ${active ? 'bg-certiva-green text-white' : 'border border-slate-300 text-transparent'}`}><Check size={12} /></span>
                  </button>
                )
              })}
            </div>
            <div className="mt-4 grid gap-4 sm:grid-cols-2">
              <label><span className={labelClass}>Audit type</span><select value={stage} onChange={(event) => setStage(event.target.value)} className={inputClass}>{references.stages.map((item) => <option key={item}>{item}</option>)}</select></label>
              <label><span className={labelClass}>Accreditation profile</span><select value={profileCode} onChange={(event) => setProfileCode(event.target.value)} className={inputClass}>{references.profiles.map((profile) => <option key={profile.code} value={profile.code}>{profile.display_name}</option>)}</select></label>
            </div>
          </CertivAISection>
        </div>

        <aside className="space-y-4 lg:sticky lg:top-5 lg:self-start">
          <div className="rounded-2xl border border-emerald-950/10 bg-white p-5 shadow-sm">
            <div className="flex items-center gap-3"><ShieldCheck size={20} className="text-certiva-mid" /><div><p className="text-sm font-semibold text-slate-900">{selectedProfile?.display_name || 'Reference profile'}</p><p className="text-xs text-slate-500">{selectedProfile?.governing_standard}</p></div></div>
            <ul className="mt-4 space-y-2 text-xs leading-5 text-slate-600">{(selectedProfile?.reference_basis || []).map((item) => <li key={item} className="flex gap-2"><Check size={14} className="mt-0.5 shrink-0 text-certiva-leaf" />{item}</li>)}</ul>
            <button type="button" onClick={submitReview} disabled={busy || running} className="mt-5 inline-flex w-full items-center justify-center gap-2 rounded-xl bg-certiva-green px-4 py-3 text-sm font-semibold text-white hover:bg-certiva-mid disabled:cursor-wait disabled:opacity-60">{busy || running ? <Loader2 size={17} className="animate-spin" /> : <FileSearch size={17} />}{busy ? 'Submitting…' : running ? STATE_COPY[status?.state || 'QUEUED'] : 'Run report review'}</button>
          </div>
          {running && <CertivAINotice tone="info">{STATE_COPY[status?.state || 'QUEUED']}</CertivAINotice>}
          {message && <CertivAINotice tone="error">{message}</CertivAINotice>}
        </aside>
      </div>

      <div className="mt-5">
        <CertivAISection
          title="Review result"
          description={status ? `${STATE_COPY[status.state] || status.state} · ${status.standard_code} · ${status.accreditation_body}` : 'Findings and corrective guidance will appear here.'}
          action={summary && hasDocxSource ? <button type="button" onClick={downloadAnnotatedReport} disabled={downloading} className="inline-flex items-center gap-2 rounded-xl border border-certiva-leaf/30 bg-certiva-mist px-3 py-2 text-sm font-semibold text-certiva-green hover:bg-certiva-pale disabled:opacity-60">{downloading ? <Loader2 size={15} className="animate-spin" /> : <Download size={15} />} Annotated DOCX</button> : undefined}
        >
          {summary ? (
            <div className="space-y-5">
              <div className="grid gap-3 sm:grid-cols-5">
                <Metric label="Critical" value={summary.critical_count} tone="text-red-700 bg-red-50 border-red-200" />
                <Metric label="Major" value={summary.major_count} tone="text-orange-700 bg-orange-50 border-orange-200" />
                <Metric label="Minor" value={summary.minor_count} tone="text-amber-700 bg-amber-50 border-amber-200" />
                <Metric label="Warning" value={summary.warning_count} tone="text-sky-700 bg-sky-50 border-sky-200" />
                <Metric label="OK clauses" value={okCount} tone="text-emerald-700 bg-emerald-50 border-emerald-200" />
              </div>
              <div className="rounded-xl border border-slate-200 bg-slate-50 p-4"><p className="text-sm font-semibold text-slate-900">Overall assessment</p><div className="mt-2 whitespace-pre-wrap text-sm leading-6 text-slate-700">{summary.overall_assessment || 'No overall assessment returned.'}</div></div>
              {actionable.length === 0 ? <CertivAINotice tone="success">No actionable findings were returned.</CertivAINotice> : <div className="space-y-3">{actionable.map((finding, index) => <article key={`${finding.clause_id}-${index}`} className={`rounded-xl border p-4 ${SEVERITY_STYLES[finding.severity]}`}><div className="flex flex-wrap items-start justify-between gap-3"><div><p className="text-sm font-semibold">{finding.clause_id} {finding.clause_title}</p><p className="mt-1 text-xs opacity-70">{finding.finding_type.replaceAll('_', ' ')}</p></div><span className="rounded-full bg-white/70 px-2 py-1 text-xs font-bold">{finding.severity}</span></div><p className="mt-3 text-sm leading-6">{finding.description}</p>{finding.quote && <p className="mt-3 border-l-2 border-current/30 pl-3 text-xs italic opacity-80">“{finding.quote}”</p>}<p className="mt-3 text-sm leading-6"><span className="font-semibold">Recommended correction: </span>{finding.suggestion}</p></article>)}</div>}
            </div>
          ) : <div className="rounded-xl border border-dashed border-slate-200 bg-slate-50 p-8 text-center text-sm text-slate-500">No review has been completed in this session.</div>}
        </CertivAISection>
      </div>
    </CertivAIToolShell>
  )
}

function Metric({ label, value, tone }: { label: string; value: number; tone: string }) {
  return <div className={`rounded-xl border px-4 py-3 ${tone}`}><p className="text-2xl font-semibold">{value}</p><p className="mt-1 text-xs font-semibold uppercase opacity-75">{label}</p></div>
}
