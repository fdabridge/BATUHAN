'use client'

import { useEffect, useMemo, useState } from 'react'
import Link from 'next/link'
import api from '@/lib/api'
import {
  AlertTriangle,
  ArrowLeft,
  CheckCircle2,
  Download,
  FileSearch,
  Loader2,
  Radar,
  ShieldCheck,
  Upload,
} from 'lucide-react'

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
  profiles: [
    {
      code: 'UAF',
      display_name: 'UAF (United Accreditation Foundation)',
      governing_standard: 'ISO/IEC 17021-1:2015',
      reference_basis: [
        'ISO/IEC 17021-1:2015-based certification audit report controls',
        'UAF accreditation profile and internal certification procedures',
        'Selected management system standard clause map',
      ],
      required_report_elements: ['audit_scope', 'audit_objectives', 'audit_criteria', 'findings_per_clause_with_evidence'],
    },
  ],
  standards: ['QMS', 'EMS', 'OHSMS', 'FSMS', 'MDQMS', 'ISMS', 'ABMS', 'ENMS'],
  stages: ['Stage 1', 'Stage 2', 'Surveillance', 'Recertification'],
  file_types: ['.pdf', '.docx'],
}

const SEVERITY_STYLES: Record<ReviewFinding['severity'], string> = {
  CRITICAL: 'border-red-400/50 bg-red-500/12 text-red-100',
  MAJOR: 'border-orange-300/50 bg-orange-400/12 text-orange-100',
  MINOR: 'border-amber-300/50 bg-amber-300/12 text-amber-100',
  WARNING: 'border-sky-300/45 bg-sky-300/12 text-sky-100',
  OK: 'border-emerald-300/35 bg-emerald-300/10 text-emerald-100',
}

const STATE_COPY: Record<string, string> = {
  QUEUED: 'Queued',
  PREPROCESSING: 'Reading report',
  REVIEWING: 'Accreditation assessment',
  ANNOTATING: 'Preparing annotated DOCX',
  COMPLETE: 'Complete',
  FAILED: 'Failed',
}

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
        const availableStandards = response.data.standards.length > 0 ? response.data.standards : FALLBACK_REFERENCES.standards
        setSelectedStandards((current) => {
          const kept = current.filter((item) => availableStandards.includes(item))
          return kept.length > 0 ? kept : [availableStandards[0]]
        })
        if (response.data.profiles.length > 0) {
          setProfileCode(response.data.profiles.find((profile) => profile.code === 'UAF')?.code || response.data.profiles[0].code)
        }
      })
      .catch(() => setReferences(FALLBACK_REFERENCES))
    return () => {
      alive = false
    }
  }, [])

  useEffect(() => {
    if (!jobId || summary) return

    const poll = async () => {
      try {
        const statusResponse = await api.get<ReviewStatus>(`/review/${jobId}/status`)
        setStatus(statusResponse.data)

        if (statusResponse.data.state === 'COMPLETE') {
          const summaryResponse = await api.get<ReviewSummary>(`/review/${jobId}/download/review-summary`)
          setSummary(summaryResponse.data)
        }

        if (statusResponse.data.state === 'FAILED') {
          setMessage(statusResponse.data.error_message || 'Review failed. Please check the file and try again.')
        }
      } catch (error) {
        setMessage('Could not read review status yet. I will keep trying while the job is open.')
      }
    }

    poll()
    const timer = window.setInterval(poll, 3500)
    return () => window.clearInterval(timer)
  }, [jobId, summary])

  const selectedProfile = useMemo(
    () => references.profiles.find((profile) => profile.code === profileCode) || references.profiles[0],
    [references.profiles, profileCode],
  )

  const activeFindings = useMemo(
    () => (summary?.findings || []).filter((finding) => finding.finding_type !== 'OK'),
    [summary],
  )

  const okCount = useMemo(
    () => (summary?.findings || []).filter((finding) => finding.finding_type === 'OK').length,
    [summary],
  )
  const hasDocxSource = Boolean(report?.name.toLowerCase().endsWith('.docx'))
  const standardLabel = selectedStandards.join(' + ')

  function toggleStandard(item: string) {
    setSelectedStandards((current) => {
      if (current.includes(item)) {
        return current.length === 1 ? current : current.filter((value) => value !== item)
      }
      return [...current, item]
    })
  }

  async function submitReview() {
    if (!report) {
      setMessage('Please choose a completed audit report PDF or DOCX first.')
      return
    }
    if (selectedStandards.length === 0) {
      setMessage('Please select at least one standard for the review.')
      return
    }
    const reportName = report.name.toLowerCase()
    if (!reportName.endsWith('.pdf') && !reportName.endsWith('.docx')) {
      setMessage('Report Review accepts PDF or DOCX reports only.')
      return
    }

    setBusy(true)
    setMessage(null)
    setSummary(null)
    setStatus(null)
    setJobId(null)

    const formData = new FormData()
    formData.append('report', report)
    selectedStandards.forEach((item) => formData.append('standards', item))
    formData.append('stage', stage)
    formData.append('accreditation_body', profileCode)

    try {
      const response = await api.post<{ review_job_id: string; state: string }>('/review/submit', formData, {
        headers: { 'Content-Type': 'multipart/form-data' },
      })
      setJobId(response.data.review_job_id)
      setStatus({
        review_job_id: response.data.review_job_id,
        state: response.data.state,
        standard_code: standardLabel,
        accreditation_body: profileCode,
      })
    } catch (error: any) {
      setMessage(error?.response?.data?.detail || 'Could not submit the report for review.')
    } finally {
      setBusy(false)
    }
  }

  async function downloadAnnotatedReport() {
    if (!jobId) return
    setDownloading(true)
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
    } finally {
      setDownloading(false)
    }
  }

  return (
    <div className="min-h-[calc(100vh-52px)] bg-[#06130D] text-white">
      <div
        className="mx-auto max-w-[1320px] px-6 py-8"
        style={{
          backgroundImage:
            'linear-gradient(rgba(255,255,255,0.05) 1px, transparent 1px), linear-gradient(90deg, rgba(255,255,255,0.05) 1px, transparent 1px)',
          backgroundSize: '34px 34px',
        }}
      >
        <Link href="/certivai" className="mb-6 inline-flex items-center gap-2 text-sm text-emerald-200 hover:text-white">
          <ArrowLeft size={16} />
          Certiv.AI
        </Link>

        <section className="grid gap-5 lg:grid-cols-[0.95fr_1.05fr]">
          <div className="border border-amber-200/25 bg-white/[0.045] p-6" style={{ borderRadius: 8 }}>
            <div className="flex items-center gap-4">
              <span className="flex h-14 w-14 items-center justify-center rounded bg-amber-300/15 text-amber-200">
                <FileSearch size={28} />
              </span>
              <div>
                <h1 className="text-3xl font-semibold">Report Review</h1>
                <p className="mt-2 max-w-2xl text-sm leading-6 text-slate-300">
                  Upload a completed audit report and compare it against the selected accreditation profile, integrated standard clause maps, evidence rules, and stage logic.
                </p>
              </div>
            </div>

            <div className="mt-7 grid gap-4 sm:grid-cols-2">
              <div className="space-y-2 sm:col-span-2">
                <span className="text-xs font-semibold uppercase text-slate-400">Standards</span>
                <div className="grid grid-cols-2 gap-2 sm:grid-cols-4">
                  {references.standards.map((item) => {
                    const active = selectedStandards.includes(item)
                    return (
                      <button
                        key={item}
                        type="button"
                        onClick={() => toggleStandard(item)}
                        className={`border px-3 py-3 text-sm font-semibold transition ${
                          active
                            ? 'border-cyan-300 bg-cyan-300/15 text-cyan-50 shadow-[0_0_18px_rgba(103,232,249,0.18)]'
                            : 'border-white/10 bg-black/35 text-slate-300 hover:border-white/25 hover:text-white'
                        }`}
                        style={{ borderRadius: 8 }}
                      >
                        {item}
                      </button>
                    )
                  })}
                </div>
                <span className="block text-xs text-slate-400">
                  Select every standard included in the report. Integrated reviews check all selected clause maps together.
                </span>
              </div>
              <label className="space-y-2">
                <span className="text-xs font-semibold uppercase text-slate-400">Audit Type</span>
                <select value={stage} onChange={(event) => setStage(event.target.value)} className="w-full border border-white/10 bg-black/40 px-3 py-3 text-sm text-white outline-none" style={{ borderRadius: 8 }}>
                  {references.stages.map((item) => <option key={item}>{item}</option>)}
                </select>
              </label>
              <label className="space-y-2 sm:col-span-2">
                <span className="text-xs font-semibold uppercase text-slate-400">Reference Profile</span>
                <select value={profileCode} onChange={(event) => setProfileCode(event.target.value)} className="w-full border border-white/10 bg-black/40 px-3 py-3 text-sm text-white outline-none" style={{ borderRadius: 8 }}>
                  {references.profiles.map((profile) => (
                    <option key={profile.code} value={profile.code}>{profile.display_name}</option>
                  ))}
                </select>
                <span className="block text-xs text-slate-400">
                  The review will use {standardLabel || 'the selected standards'} with this accreditation profile.
                </span>
              </label>
              <label className="space-y-2 sm:col-span-2">
                <span className="text-xs font-semibold uppercase text-slate-400">Completed Report</span>
                <input
                  type="file"
                  accept=".pdf,.docx"
                  onChange={(event) => setReport(event.target.files?.[0] || null)}
                  className="w-full border border-white/10 bg-black/40 px-3 py-3 text-sm text-slate-200 file:mr-3 file:border-0 file:bg-emerald-500/20 file:px-3 file:py-2 file:text-emerald-100"
                  style={{ borderRadius: 8 }}
                />
                <span className="block text-xs text-slate-400">
                  Accepted: PDF or DOCX. DOCX uploads also produce an annotated Word file.
                </span>
              </label>
            </div>

            {message && (
              <div className="mt-4 flex items-start gap-3 border border-red-300/30 bg-red-500/12 px-4 py-3 text-sm text-red-100" style={{ borderRadius: 8 }}>
                <AlertTriangle size={18} className="mt-0.5 shrink-0" />
                <span>{message}</span>
              </div>
            )}

            <button
              type="button"
              onClick={submitReview}
              disabled={busy}
              className="mt-5 inline-flex w-full items-center justify-center gap-2 bg-amber-300 px-4 py-3 text-sm font-semibold text-black transition hover:bg-amber-200 disabled:cursor-not-allowed disabled:opacity-60"
              style={{ borderRadius: 8 }}
            >
              {busy ? <Loader2 className="animate-spin" size={18} /> : <Upload size={18} />}
              Run Report Review
            </button>
          </div>

          <div className="border border-white/10 bg-white/[0.045] p-6" style={{ borderRadius: 8 }}>
            <div className="mb-5 flex items-center gap-3">
              <Radar size={24} className="text-emerald-200" />
              <div>
                <h2 className="text-xl font-semibold">Reference Set</h2>
                <p className="text-sm text-slate-400">{selectedProfile?.governing_standard || 'Reference profile loading'}</p>
              </div>
            </div>

            <div className="space-y-3">
              {(selectedProfile?.reference_basis || []).map((item) => (
                <div key={item} className="flex gap-3 border border-white/10 bg-black/25 px-3 py-3 text-sm text-slate-200" style={{ borderRadius: 8 }}>
                  <ShieldCheck size={17} className="mt-0.5 shrink-0 text-emerald-200" />
                  <span>{item}</span>
                </div>
              ))}
            </div>

            <div className="mt-5 border border-white/10 bg-black/20 p-4" style={{ borderRadius: 8 }}>
              <p className="text-xs font-semibold uppercase text-slate-400">Report must include</p>
              <div className="mt-3 flex flex-wrap gap-2">
                {(selectedProfile?.required_report_elements || []).slice(0, 12).map((item) => (
                  <span key={item} className="rounded bg-white/10 px-2 py-1 text-xs text-slate-200">
                    {item.replaceAll('_', ' ')}
                  </span>
                ))}
              </div>
            </div>
          </div>
        </section>

        <section className="mt-5 border border-white/10 bg-white/[0.045] p-6" style={{ borderRadius: 8 }}>
          <div className="flex flex-wrap items-center justify-between gap-4">
            <div>
              <h2 className="text-xl font-semibold">Review Result</h2>
              <p className="mt-1 text-sm text-slate-400">
                {status ? `${STATE_COPY[status.state] || status.state} · ${status.standard_code} · ${status.accreditation_body}` : 'No report submitted yet.'}
              </p>
            </div>
            {status && status.state !== 'COMPLETE' && status.state !== 'FAILED' && (
              <div className="inline-flex items-center gap-2 rounded bg-white/10 px-3 py-2 text-sm text-amber-100">
                <Loader2 size={16} className="animate-spin" />
                {STATE_COPY[status.state] || status.state}
              </div>
            )}
            {summary && hasDocxSource && (
              <button
                type="button"
                onClick={downloadAnnotatedReport}
                disabled={downloading}
                className="inline-flex items-center gap-2 border border-emerald-300/35 bg-emerald-300/12 px-3 py-2 text-sm font-semibold text-emerald-100 hover:bg-emerald-300/20 disabled:opacity-60"
                style={{ borderRadius: 8 }}
              >
                {downloading ? <Loader2 size={16} className="animate-spin" /> : <Download size={16} />}
                Annotated DOCX
              </button>
            )}
          </div>

          {summary ? (
            <div className="mt-6 space-y-5">
              {!hasDocxSource && (
                <div className="border border-amber-300/30 bg-amber-300/10 px-4 py-3 text-sm text-amber-100" style={{ borderRadius: 8 }}>
                  PDF review complete. Findings are shown below; annotated Word download is available for DOCX uploads only.
                </div>
              )}
              <div className="grid gap-3 sm:grid-cols-5">
                <Metric label="Critical" value={summary.critical_count} tone="text-red-100 bg-red-500/15 border-red-300/30" />
                <Metric label="Major" value={summary.major_count} tone="text-orange-100 bg-orange-400/15 border-orange-300/30" />
                <Metric label="Minor" value={summary.minor_count} tone="text-amber-100 bg-amber-300/15 border-amber-300/30" />
                <Metric label="Warning" value={summary.warning_count} tone="text-sky-100 bg-sky-300/15 border-sky-300/30" />
                <Metric label="OK clauses" value={okCount} tone="text-emerald-100 bg-emerald-300/15 border-emerald-300/30" />
              </div>

              <div className="border border-white/10 bg-black/25 p-4" style={{ borderRadius: 8 }}>
                <div className="mb-2 flex items-center gap-2 text-emerald-100">
                  <CheckCircle2 size={18} />
                  <span className="font-semibold">Overall Assessment</span>
                </div>
                <div className="whitespace-pre-wrap text-sm leading-6 text-slate-200">
                  {summary.overall_assessment || 'No overall assessment returned.'}
                </div>
              </div>

              <div className="space-y-3">
                {activeFindings.length === 0 ? (
                  <div className="border border-emerald-300/30 bg-emerald-300/10 p-4 text-sm text-emerald-100" style={{ borderRadius: 8 }}>
                    No actionable findings were returned.
                  </div>
                ) : activeFindings.map((finding, index) => (
                  <article key={`${finding.clause_id}-${index}`} className={`border p-4 ${SEVERITY_STYLES[finding.severity]}`} style={{ borderRadius: 8 }}>
                    <div className="flex flex-wrap items-start justify-between gap-3">
                      <div>
                        <p className="text-sm font-semibold">
                          {finding.clause_id} {finding.clause_title}
                        </p>
                        <p className="mt-1 text-xs opacity-80">{finding.finding_type.replaceAll('_', ' ')}</p>
                      </div>
                      <span className="rounded bg-black/25 px-2 py-1 text-xs font-semibold">{finding.severity}</span>
                    </div>
                    <p className="mt-3 text-sm leading-6">{finding.description}</p>
                    {finding.quote && (
                      <p className="mt-3 border-l-2 border-white/35 pl-3 text-xs italic opacity-85">"{finding.quote}"</p>
                    )}
                    <p className="mt-3 text-sm leading-6 opacity-90">
                      <span className="font-semibold">Fix: </span>{finding.suggestion}
                    </p>
                  </article>
                ))}
              </div>
            </div>
          ) : (
            <div className="mt-6 border border-dashed border-white/15 bg-black/20 p-8 text-center text-sm text-slate-400" style={{ borderRadius: 8 }}>
              The completed review will appear here with exact findings, severity, evidence quotes, and fix instructions.
            </div>
          )}
        </section>
      </div>
    </div>
  )
}

function Metric({ label, value, tone }: { label: string; value: number; tone: string }) {
  return (
    <div className={`border px-4 py-3 ${tone}`} style={{ borderRadius: 8 }}>
      <p className="text-2xl font-semibold">{value}</p>
      <p className="mt-1 text-xs font-semibold uppercase opacity-80">{label}</p>
    </div>
  )
}
