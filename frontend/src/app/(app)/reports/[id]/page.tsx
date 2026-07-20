'use client'

import { useEffect, useRef, useState } from 'react'
import Link from 'next/link'
import { useSearchParams } from 'next/navigation'
import { ArrowLeft, Check, CheckCircle2, Download, Loader2, X } from 'lucide-react'
import { useQuery } from '@tanstack/react-query'
import api from '@/lib/api'
import type { JobStatus, JobStateValue } from '@/types'

// ── Pipeline definition ───────────────────────────────────────────────────────

type PipelineState = Exclude<JobStateValue, 'QUEUED' | 'FAILED'>

const PIPELINE: { state: PipelineState; label: string }[] = [
  { state: 'PREPROCESSING', label: 'Preprocessing' },
  { state: 'STEP_0',        label: 'Step 0' },
  { state: 'STEP_A',        label: 'Step A' },
  { state: 'STEP_B',        label: 'Step B' },
  { state: 'STEP_C',        label: 'Step C' },
  { state: 'ASSEMBLING',    label: 'Assembly' },
  { state: 'COMPLETE',      label: 'Done' },
]

const STATUS_TEXT: Record<JobStateValue, string> = {
  QUEUED:        'Queued — waiting to start…',
  PREPROCESSING: 'Preprocessing documents…',
  STEP_0:        'Running Step 0 — Initial analysis…',
  STEP_A:        'Running Step A — Evidence extraction…',
  STEP_B:        'Running Step B — Findings synthesis…',
  STEP_C:        'Running Step C — Conclusion drafting…',
  ASSEMBLING:    'Assembling final report…',
  COMPLETE:      'Report ready',
  FAILED:        'Report generation failed',
}

function isTerminal(s: JobStateValue): boolean {
  return s === 'COMPLETE' || s === 'FAILED'
}

function pipelineIndex(s: JobStateValue): number {
  if (s === 'QUEUED') return -1
  if (s === 'FAILED') return -1
  return PIPELINE.findIndex((p) => p.state === s)
}

function formatDateTime(iso: string | null | undefined): string {
  if (!iso) return '—'
  const d = new Date(iso)
  if (Number.isNaN(d.getTime())) return '—'
  return d.toLocaleString('en-GB', { day: '2-digit', month: 'short', year: 'numeric', hour: '2-digit', minute: '2-digit' })
}

function durationStr(start?: string | null, end?: string | null): string {
  if (!start || !end) return '—'
  const ms = new Date(end).getTime() - new Date(start).getTime()
  if (Number.isNaN(ms) || ms < 0) return '—'
  const s = Math.floor(ms / 1000)
  const m = Math.floor(s / 60)
  return m > 0 ? `${m}m ${s % 60}s` : `${s}s`
}

// ── Pipeline display ──────────────────────────────────────────────────────────

function PipelineTrack({ state, failedAt }: { state: JobStateValue; failedAt: number }) {
  const currentIdx = pipelineIndex(state)
  const isDone     = state === 'COMPLETE'
  const isFailed   = state === 'FAILED'

  return (
    <div className="flex items-center justify-between">
      {PIPELINE.map((stage, i) => {
        let circleCls = 'flex h-8 w-8 items-center justify-center rounded-full border-2 '
        let icon: React.ReactNode = null
        let labelCls = 'mt-2 text-xs '

        if (isFailed && i === failedAt) {
          circleCls += 'border-red-500 bg-red-500 text-white'
          icon = <X size={14} />
          labelCls += 'text-red-600 font-medium'
        } else if (isFailed && i > failedAt) {
          circleCls += 'border-gray-200 bg-white text-gray-300'
          labelCls += 'text-gray-300'
        } else if (i < currentIdx || isDone) {
          circleCls += 'border-certiva-primary bg-certiva-primary text-white'
          icon = <Check size={14} />
          labelCls += 'text-gray-700'
        } else if (i === currentIdx) {
          circleCls += 'border-certiva-accent bg-certiva-accent text-white animate-pulse'
          icon = <Loader2 size={14} className="animate-spin" />
          labelCls += 'text-certiva-accent font-medium'
        } else {
          circleCls += 'border-gray-200 bg-white text-gray-300'
          labelCls += 'text-gray-400'
        }

        return (
          <div key={stage.state} className="flex flex-1 flex-col items-center">
            <div className="flex w-full items-center">
              {i > 0 && (
                <div className="h-px flex-1" style={{
                  background: (isFailed && i > failedAt) || i > currentIdx ? '#E5E7EB' : '#1A4731',
                }} />
              )}
              <div className={circleCls} style={{ background: undefined }}>{icon}</div>
              {i < PIPELINE.length - 1 && (
                <div className="h-px flex-1" style={{
                  background: (isFailed && i >= failedAt) || i >= currentIdx ? '#E5E7EB' : '#1A4731',
                }} />
              )}
            </div>
            <span className={labelCls}>{stage.label}</span>
          </div>
        )
      })}
    </div>
  )
}

// ── Metadata card ─────────────────────────────────────────────────────────────

function MetaCard({ status, meta }: {
  status: JobStatus
  meta: { standards: string; stage: string; body: string; company: string }
}) {
  return (
    <div className="grid grid-cols-3 gap-x-6 gap-y-4 rounded-lg border border-gray-100 bg-white p-5">
      <Field label="Standards" value={meta.standards || '—'} />
      <Field label="Report context" value={meta.stage || '—'} />
      <Field label="Accreditation body" value={meta.body || '—'} />
      <Field label="Company" value={meta.company || '—'} />
      <Field label="Submitted at" value={formatDateTime(status.started_at)} />
      <Field label="Duration" value={status.state === 'COMPLETE' ? durationStr(status.started_at, status.completed_at) : '—'} />
    </div>
  )
}

function Field({ label, value }: { label: string; value: string }) {
  return (
    <div>
      <p className="mb-0.5 font-medium uppercase tracking-wide text-gray-400" style={{ fontSize: 11 }}>{label}</p>
      <p className="text-sm text-gray-800">{value}</p>
    </div>
  )
}


// ── Main page ─────────────────────────────────────────────────────────────────

export default function ReportStatusPage({ params }: { params: { id: string } }) {
  const { id } = params
  const sp = useSearchParams()
  const standardsFromQuery = sp.get('standards')
  const meta = {
    standards: standardsFromQuery ? standardsFromQuery.split(',').filter(Boolean).join(' + ') : (sp.get('standard') ?? ''),
    stage:    sp.get('stage')    ?? '',
    body:     sp.get('accreditation_body') ?? '',
    company:  sp.get('company')  ?? '',
  }
  const clientId = sp.get('client_id')

  const [downloading, setDownloading] = useState(false)
  const [downloadError, setDownloadError] = useState<string | null>(null)

  const { data, isLoading, isError, refetch } = useQuery<JobStatus>({
    queryKey: ['job', id],
    queryFn: () => api.get<JobStatus>(`/jobs/${id}/status`).then((r) => r.data),
  })

  // Polling — every 3s while not in a terminal state
  const failedAtRef = useRef<number>(0)
  useEffect(() => {
    if (!data) return
    if (isTerminal(data.state)) return
    const t = setInterval(() => { refetch() }, 3000)
    return () => clearInterval(t)
  }, [data, refetch])

  // Track which step failed (snapshot at the moment of failure)
  useEffect(() => {
    if (data?.state !== 'FAILED') return
    const cs = (data.current_step ?? '').toUpperCase()
    const idx = PIPELINE.findIndex((p) => p.state === cs)
    failedAtRef.current = idx >= 0 ? idx : 0
  }, [data])

  async function handleDownload() {
    setDownloadError(null)
    setDownloading(true)
    try {
      const res = await api.get(`/jobs/${id}/download/report`, { responseType: 'blob' })
      const url = URL.createObjectURL(res.data as Blob)
      const a   = document.createElement('a')
      const date = new Date().toISOString().slice(0, 10)
      a.href     = url
      a.download = `${meta.standards || 'report'}_${meta.stage || 'context'}_${meta.company || 'company'}_${date}.docx`
      a.click()
      URL.revokeObjectURL(url)
    } catch (err: unknown) {
      const detail = (err as { response?: { data?: { detail?: string } } })?.response?.data?.detail
      setDownloadError(detail ?? 'Download failed.')
    } finally {
      setDownloading(false)
    }
  }

  if (isLoading) return (
    <div className="flex items-center justify-center py-24">
      <Loader2 size={24} className="animate-spin text-certiva-primary" />
    </div>
  )
  if (isError || !data) return (
    <div className="py-12 text-center text-sm text-red-500">Job not found.</div>
  )

  const tryAgainHref = clientId ? `/reports/new?client_id=${clientId}` : '/reports/new'

  return (
    <div className="mx-auto max-w-[900px] space-y-5 py-4">
      <Link href="/reports" className="flex items-center gap-1 text-certiva-primary hover:opacity-70" style={{ fontSize: 13 }}>
        <ArrowLeft size={13} /> Reports
      </Link>

      <div className="flex items-start justify-between">
        <div>
          <h1 className="text-gray-800" style={{ fontSize: 22, fontWeight: 500 }}>AI report</h1>
          <p className="mt-1 font-mono text-xs text-gray-500">{data.job_id}</p>
        </div>
      </div>

      {/* Pipeline */}
      <div className="rounded-lg border border-gray-100 bg-white p-6">
        <PipelineTrack state={data.state} failedAt={failedAtRef.current} />
        <p className="mt-5 text-center text-gray-600" style={{ fontSize: 14 }}>
          {STATUS_TEXT[data.state]}
        </p>
      </div>

      {/* Metadata */}
      <MetaCard status={data} meta={meta} />

      {/* Done state */}
      {data.state === 'COMPLETE' && (
        <div className="flex flex-col items-center gap-3 rounded-lg border border-gray-100 bg-white p-8">
          <CheckCircle2 size={48} className="text-certiva-accent" />
          <p className="text-gray-800" style={{ fontSize: 18, fontWeight: 500 }}>Report ready</p>
          <p className="text-sm text-gray-500">Your AI-generated audit report is ready to download.</p>
          <button
            type="button" disabled={downloading} onClick={handleDownload}
            className="mt-2 flex items-center gap-1.5 rounded-lg px-4 py-2 text-sm font-medium text-white disabled:opacity-60 hover:opacity-90"
            style={{ background: '#1A4731' }}
          >
            {downloading ? <Loader2 size={14} className="animate-spin" /> : <Download size={14} />}
            Download report (.docx)
          </button>
          {downloadError && <p className="text-xs text-red-500">{downloadError}</p>}
        </div>
      )}

      {/* Failed state */}
      {data.state === 'FAILED' && (
        <div className="rounded-lg border border-red-200 bg-red-50 p-5">
          <p className="mb-1 text-sm font-medium text-red-700">Report generation failed</p>
          {data.error_message && (
            <p className="mb-3 text-sm text-red-600">{data.error_message}</p>
          )}
          <Link
            href={tryAgainHref}
            className="inline-flex items-center rounded-lg px-3 py-1.5 text-sm font-medium text-white hover:opacity-90"
            style={{ background: '#B91C1C' }}
          >
            Try again
          </Link>
        </div>
      )}
    </div>
  )
}
