'use client'

import { useEffect, useState } from 'react'
import api from '@/lib/api'

const WORKFLOW_STEPS = [
  { key: 'pending_review',    label: 'Application Received', desc: 'Your application is being reviewed by our team.' },
  { key: 'in_planning',       label: 'Planning',             desc: 'We are preparing your audit plan and assigning your auditor.' },
  { key: 'quotation_sent',    label: 'Quotation',            desc: 'Your quotation is ready. Please review and sign.' },
  { key: 'agreement_signed',  label: 'Agreement Confirmed',  desc: 'Your agreement has been signed.' },
  { key: 'audit_scheduled',   label: 'Audit Scheduled',      desc: 'Your audit dates have been confirmed.' },
  { key: 'audit_in_progress', label: 'Audit In Progress',    desc: 'Your audit is currently underway.' },
  { key: 'under_review',      label: 'Under Review',         desc: 'The certification committee is reviewing your audit.' },
  { key: 'certified',         label: 'Certified ✓',          desc: 'Congratulations! Your certification has been issued.' },
]

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

interface ClientStage {
  stage_type: string
  stage_order: number
  audit_date_start: string | null
  audit_date_end:   string | null
  lead_auditor_name: string | null
  status: string
}

interface ClientAuditSet {
  id: string
  plan_number: number
  company_name: string
  company_address: string | null
  standards: string[] | null
  audit_type: string | null
  accreditation_body: string | null
  scope_en: string | null
  workflow_status: string | null
  cert_issued_date: string | null
  cert_expiry_date: string | null
  cert_status: string | null
  stages: ClientStage[]
  created_at: string | null
}

interface StatusEvent {
  to_status:    string
  triggered_at: string
  notes:        string | null
}

function fmtLongDate(iso: string): string {
  return new Date(iso).toLocaleDateString('en-GB', { day: 'numeric', month: 'long', year: 'numeric' })
}

function fmtShortDate(iso: string): string {
  return new Date(iso).toLocaleDateString('en-GB', { day: 'numeric', month: 'short', year: 'numeric' })
}

export default function ClientOverviewPage() {
  const [data, setData]       = useState<ClientAuditSet | null>(null)
  const [history, setHistory] = useState<StatusEvent[]>([])
  const [loading, setLoading] = useState(true)

  useEffect(() => {
    Promise.all([
      api.get<ClientAuditSet>('/client/my-audit-set'),
      api.get<StatusEvent[]>('/client/my-audit-set/status-history'),
    ])
      .then(([r1, r2]) => { setData(r1.data); setHistory(r2.data) })
      .finally(() => setLoading(false))
  }, [])

  if (loading) return <div className="p-8 text-gray-400">Loading…</div>
  if (!data)   return <div className="p-8 text-red-500">Could not load your data.</div>

  const currentIdx = WORKFLOW_STEPS.findIndex((s) => s.key === data.workflow_status)
  const stage1 = data.stages?.find((s) => s.stage_type === 'stage_1')
  const stage2 = data.stages?.find((s) => s.stage_type === 'stage_2')
  const auditorName = stage2?.lead_auditor_name ?? stage1?.lead_auditor_name

  return (
    <div className="mx-auto max-w-3xl space-y-6 p-6">
      {/* Header */}
      <div>
        <h1 className="text-xl font-bold text-gray-900">{data.company_name}</h1>
        <p className="mt-0.5 text-sm text-gray-400">
          {(data.standards ?? []).map((s) => STANDARD_NAMES[s] ?? s).join(' · ') || '—'}
        </p>
      </div>

      {/* Status Timeline */}
      <div className="rounded-xl border bg-white p-6">
        <h2 className="mb-5 text-sm font-semibold text-gray-700">Certification Progress</h2>
        <div className="space-y-0">
          {WORKFLOW_STEPS.map((step, idx) => {
            const isDone    = currentIdx >= 0 && idx <  currentIdx
            const isCurrent = currentIdx >= 0 && idx === currentIdx
            const isFuture  = currentIdx <  0 || idx >  currentIdx
            const histEvent = history.find((h) => h.to_status === step.key)

            const indicatorClass = [
              'flex h-7 w-7 shrink-0 items-center justify-center rounded-full text-xs font-bold transition-all',
              isDone    ? 'bg-[#1A4731] text-white' : '',
              isCurrent ? 'bg-[#1A4731] text-white ring-4 ring-[#1A4731]/20' : '',
              isFuture  ? 'bg-gray-100 text-gray-400' : '',
            ].join(' ')

            return (
              <div key={step.key} className="flex gap-4">
                <div className="flex flex-col items-center">
                  <div className={indicatorClass}>{isDone ? '✓' : idx + 1}</div>
                  {idx < WORKFLOW_STEPS.length - 1 && (
                    <div className={`mt-1 h-8 w-0.5 ${isDone ? 'bg-[#1A4731]' : 'bg-gray-200'}`} />
                  )}
                </div>
                <div className="min-w-0 flex-1 pb-6">
                  <p className={`text-sm font-semibold ${isFuture ? 'text-gray-400' : 'text-gray-800'}`}>
                    {step.label}
                  </p>
                  {isCurrent && <p className="mt-0.5 text-xs text-gray-500">{step.desc}</p>}
                  {histEvent && (
                    <p className="mt-0.5 text-xs text-gray-400">
                      {fmtShortDate(histEvent.triggered_at)}
                      {histEvent.notes && ` — ${histEvent.notes}`}
                    </p>
                  )}
                </div>
              </div>
            )
          })}
        </div>
      </div>

      {/* Key Info Cards */}
      <div className="grid grid-cols-2 gap-4">
        {auditorName && (
          <div className="rounded-xl border bg-white p-4">
            <p className="text-xs uppercase tracking-wide text-gray-400">Your Auditor</p>
            <p className="mt-1 font-semibold text-gray-800">{auditorName}</p>
          </div>
        )}
        {stage1?.audit_date_start && (
          <div className="rounded-xl border bg-white p-4">
            <p className="text-xs uppercase tracking-wide text-gray-400">Stage 1 Audit</p>
            <p className="mt-1 font-semibold text-gray-800">{fmtLongDate(stage1.audit_date_start)}</p>
          </div>
        )}
        {stage2?.audit_date_start && (
          <div className="rounded-xl border bg-white p-4">
            <p className="text-xs uppercase tracking-wide text-gray-400">Stage 2 Audit</p>
            <p className="mt-1 font-semibold text-gray-800">{fmtLongDate(stage2.audit_date_start)}</p>
          </div>
        )}
        {data.cert_expiry_date && (
          <div className="rounded-xl border bg-white p-4">
            <p className="text-xs uppercase tracking-wide text-gray-400">Certificate Expires</p>
            <p className="mt-1 font-semibold text-gray-800">{fmtLongDate(data.cert_expiry_date)}</p>
          </div>
        )}
      </div>

      {/* Scope */}
      {data.scope_en && (
        <div className="rounded-xl border bg-white p-4">
          <p className="mb-1 text-xs uppercase tracking-wide text-gray-400">Certification Scope</p>
          <p className="text-sm text-gray-700">{data.scope_en}</p>
        </div>
      )}
    </div>
  )
}
