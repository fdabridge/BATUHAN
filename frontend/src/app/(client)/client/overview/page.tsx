'use client'

import { useEffect, useState } from 'react'
import Link from 'next/link'
import api from '@/lib/api'

const WORKFLOW_STEPS = [
  { key: 'pending_review',    label: 'Application Received', desc: 'Your application is being reviewed by our team.' },
  { key: 'in_planning',       label: 'Planning',             desc: 'We are preparing your audit plan and assigning your auditor.' },
  { key: 'quotation_sent',    label: 'Quotation',            desc: 'Your quotation is ready. Please review and sign.' },
  { key: 'agreement_signed',  label: 'Agreement Confirmed',  desc: 'Your agreement has been signed.' },
  { key: 'audit_scheduled',   label: 'Audit Scheduled',      desc: 'Your audit dates have been confirmed.' },
  { key: 'audit_in_progress', label: 'Audit In Progress',    desc: 'Your audit is currently underway.' },
  { key: 'under_review',      label: 'Under Review',         desc: 'The certification committee is reviewing your audit.' },
  { key: 'certified',         label: 'Certified \u2713',          desc: 'Congratulations! Your certification has been issued.' },
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

interface OrgEmployee { id: string; has_signature: boolean }
interface SharedDoc    { id: string; status: string; signatures?: { signer_role_label: string; order_index: number; required: boolean; signed_at: string | null }[] }

function waitingOnCb(doc: SharedDoc): boolean {
  const sigs = doc.signatures ?? []
  const clientSlot = sigs.find((s) => s.signer_role_label === 'client' || s.signer_role_label === 'org_rep')
  if (!clientSlot) return false
  return sigs.some((s) => s.order_index < clientSlot.order_index && s.required && !s.signed_at)
}

function fmtLongDate(iso: string): string {
  return new Date(iso).toLocaleDateString('en-GB', { day: 'numeric', month: 'long', year: 'numeric' })
}
function fmtShortDate(iso: string): string {
  return new Date(iso).toLocaleDateString('en-GB', { day: 'numeric', month: 'short', year: 'numeric' })
}

// ── Next-action computation ───────────────────────────────────────────────────

interface ActionCard {
  urgency:  'high' | 'medium' | 'info' | 'success'
  title:    string
  body:     string
  href?:    string
  cta?:     string
}

function computeNextAction(
  status:          string | null,
  hasSig:          boolean,
  employees:       OrgEmployee[],
  unsignedDocCount: number,
  pendingForClient: number,
): ActionCard {
  // Highest priority — documents needing the CLIENT's signature
  if (pendingForClient > 0) {
    return {
      urgency: 'high',
      title:   `You have ${pendingForClient} document${pendingForClient > 1 ? 's' : ''} to sign`,
      body:    'Open the Documents section to review and sign.',
      href:    '/client/documents',
      cta:     'Go to Documents \u2192',
    }
  }

  // Certified — just celebrate
  if (status === 'certified') {
    return {
      urgency: 'success',
      title:   'Your certification is complete!',
      body:    'Your certificate is available in the Documents section.',
      href:    '/client/documents',
      cta:     'View Certificate \u2192',
    }
  }

  // Under review — nothing to do
  if (status === 'under_review') {
    return {
      urgency: 'info',
      title:   'Your audit is under committee review',
      body:    'No action needed right now. We\'ll notify you when the decision is made.',
    }
  }

  // No signature set up
  if (!hasSig) {
    return {
      urgency: 'high',
      title:   'Set up your signature',
      body:    'Your signature is required on audit forms and documents. Set it up now before your audit begins.',
      href:    '/client/signature',
      cta:     'Set Up Signature \u2192',
    }
  }

  // No employees
  if (employees.length === 0 && (status === 'audit_scheduled' || status === 'audit_in_progress' || status === 'in_planning' || status === 'agreement_signed')) {
    return {
      urgency: 'medium',
      title:   'Add your organisation personnel',
      body:    'Your employees\' names and signatures appear on audit meeting forms. Add them before your audit.',
      href:    '/client/employees',
      cta:     'Add Employees \u2192',
    }
  }

  // Employees missing signatures
  const missingSigs = employees.filter((e) => !e.has_signature).length
  if (missingSigs > 0 && (status === 'audit_scheduled' || status === 'audit_in_progress')) {
    return {
      urgency: 'medium',
      title:   `${missingSigs} employee${missingSigs > 1 ? 's' : ''} missing a signature`,
      body:    'Upload their signature images so they can be included on audit meeting forms.',
      href:    '/client/employees',
      cta:     'Go to Employees \u2192',
    }
  }

  // Documents released but waiting on CB (no client action yet)
  if (unsignedDocCount > 0) {
    return {
      urgency: 'info',
      title:   'Documents are awaiting the CB\'s signature first',
      body:    'You\'ll be notified when they\'re ready for you to sign.',
    }
  }

  // Status-specific fallbacks
  const statusMap: Record<string, ActionCard> = {
    pending_review:   { urgency: 'info',   title: 'Application received', body: 'Our team is reviewing your application. No action needed right now.' },
    in_planning:      { urgency: 'info',   title: 'Audit planning in progress', body: 'We\'re preparing your audit plan and assigning your auditor.' },
    agreement_signed: { urgency: 'info',   title: 'Agreement confirmed', body: 'We\'ll notify you when your audit dates are confirmed.' },
    audit_scheduled:  { urgency: 'medium', title: 'Your audit is scheduled', body: 'Prepare your documentation and ensure your employees are listed.' },
    audit_in_progress:{ urgency: 'info',   title: 'Audit in progress', body: 'Your audit is underway. Sign any meeting forms you receive.' },
  }
  return statusMap[status ?? ''] ?? { urgency: 'info', title: 'All caught up', body: 'No pending actions right now.' }
}

// ── Component ─────────────────────────────────────────────────────────────────

export default function ClientOverviewPage() {
  const [data,       setData]       = useState<ClientAuditSet | null>(null)
  const [history,    setHistory]    = useState<StatusEvent[]>([])
  const [hasSig,     setHasSig]     = useState(false)
  const [employees,  setEmployees]  = useState<OrgEmployee[]>([])
  const [docs,       setDocs]       = useState<SharedDoc[]>([])
  const [loading,    setLoading]    = useState(true)

  useEffect(() => {
    Promise.all([
      api.get<ClientAuditSet>('/client/my-audit-set'),
      api.get<StatusEvent[]>('/client/my-audit-set/status-history'),
      api.get('/me/signature').catch(() => null),
      api.get<OrgEmployee[]>('/org/employees').catch(() => ({ data: [] })),
      api.get<SharedDoc[]>('/client/my-audit-set/documents').catch(() => ({ data: [] })),
    ]).then(([r1, r2, r3, r4, r5]) => {
      setData(r1.data)
      setHistory(r2.data)
      setHasSig(!!(r3?.data?.has_signature))
      setEmployees((r4 as { data: OrgEmployee[] }).data ?? [])
      setDocs((r5 as { data: SharedDoc[] }).data ?? [])
    }).finally(() => setLoading(false))
  }, [])

  if (loading) return <div className="p-8 text-gray-400">Loading\u2026</div>
  if (!data)   return <div className="p-8 text-red-500">Could not load your data.</div>

  const currentIdx = WORKFLOW_STEPS.findIndex((s) => s.key === data.workflow_status)
  const stage1 = data.stages?.find((s) => s.stage_type === 'stage_1')
  const stage2 = data.stages?.find((s) => s.stage_type === 'stage_2')
  const auditorName = stage2?.lead_auditor_name ?? stage1?.lead_auditor_name

  // Classify docs
  const unsignedDocs     = docs.filter((d) => d.status !== 'signed')
  const pendingForClient = unsignedDocs.filter((d) => !waitingOnCb(d)).length
  const waitingOnCbCount = unsignedDocs.filter((d) => waitingOnCb(d)).length

  const action = computeNextAction(
    data.workflow_status,
    hasSig,
    employees,
    waitingOnCbCount,
    pendingForClient,
  )

  // Checklist
  const empWithSig   = employees.filter((e) => e.has_signature).length
  const empTotal     = employees.length
  const docsAllDone  = docs.length > 0 && pendingForClient === 0 && waitingOnCbCount === 0

  const urgencyStyle: Record<string, { bg: string; border: string; title: string; body: string }> = {
    high:    { bg: '#FFF7ED', border: '#FED7AA', title: '#9A3412', body: '#C2410C' },
    medium:  { bg: '#FEFCE8', border: '#FDE68A', title: '#713F12', body: '#92400E' },
    info:    { bg: '#EFF6FF', border: '#BFDBFE', title: '#1E3A8A', body: '#1D4ED8' },
    success: { bg: '#F0FDF4', border: '#BBF7D0', title: '#14532D', body: '#15803D' },
  }
  const us = urgencyStyle[action.urgency]

  return (
    <div className="mx-auto max-w-3xl space-y-5 p-6">

      {/* Header */}
      <div>
        <h1 className="text-xl font-bold text-gray-900">{data.company_name}</h1>
        <p className="mt-0.5 text-sm text-gray-400">
          {(data.standards ?? []).map((s) => STANDARD_NAMES[s] ?? s).join(' \u00B7 ') || '\u2014'}
          {data.accreditation_body && ` \u00B7 ${data.accreditation_body}`}
        </p>
      </div>

      {/* Next Action Hero */}
      <div
        className="rounded-xl border p-5"
        style={{ background: us.bg, borderColor: us.border }}
      >
        <p className="text-xs font-semibold uppercase tracking-wide mb-1" style={{ color: us.body }}>
          {action.urgency === 'high' ? '\u26A0 Action required' :
           action.urgency === 'success' ? '\u2713 Complete' : 'Status'}
        </p>
        <p className="text-base font-semibold" style={{ color: us.title }}>{action.title}</p>
        <p className="mt-1 text-sm" style={{ color: us.body }}>{action.body}</p>
        {action.href && action.cta && (
          <Link
            href={action.href}
            className="mt-3 inline-flex items-center rounded-lg px-4 py-2 text-sm font-medium text-white hover:opacity-90"
            style={{ background: '#1A4731' }}
          >
            {action.cta}
          </Link>
        )}
      </div>

      {/* Setup Checklist */}
      <div className="rounded-xl border bg-white p-5">
        <p className="mb-3 text-xs font-semibold uppercase tracking-wide text-gray-400">Setup checklist</p>
        <div className="space-y-2.5">
          {/* Signature */}
          <div className="flex items-center gap-3">
            <div className={`flex h-6 w-6 shrink-0 items-center justify-center rounded-full text-xs font-bold
              ${hasSig ? 'bg-[#1A4731] text-white' : 'bg-amber-100 text-amber-700'}`}>
              {hasSig ? '\u2713' : '!'}
            </div>
            <div className="flex-1 min-w-0">
              <p className="text-sm font-medium text-gray-700">Personal signature</p>
              <p className="text-xs text-gray-400">{hasSig ? 'On file' : 'Not set up yet'}</p>
            </div>
            {!hasSig && (
              <Link href="/client/signature" className="text-xs font-medium text-[#1A4731] hover:underline">
                Set up \u2192
              </Link>
            )}
          </div>

          {/* Employees */}
          <div className="flex items-center gap-3">
            <div className={`flex h-6 w-6 shrink-0 items-center justify-center rounded-full text-xs font-bold
              ${empTotal > 0 && empWithSig === empTotal ? 'bg-[#1A4731] text-white'
                : empTotal > 0 ? 'bg-amber-100 text-amber-700'
                : 'bg-gray-100 text-gray-400'}`}>
              {empTotal > 0 && empWithSig === empTotal ? '\u2713' : empTotal > 0 ? '!' : '\u2014'}
            </div>
            <div className="flex-1 min-w-0">
              <p className="text-sm font-medium text-gray-700">Organisation employees</p>
              <p className="text-xs text-gray-400">
                {empTotal === 0
                  ? 'No employees added yet'
                  : empWithSig < empTotal
                  ? `${empTotal} added \u00B7 ${empTotal - empWithSig} missing signature`
                  : `${empTotal} added, all signatures on file`}
              </p>
            </div>
            <Link href="/client/employees" className="text-xs font-medium text-[#1A4731] hover:underline">
              {empTotal === 0 ? 'Add \u2192' : 'Manage \u2192'}
            </Link>
          </div>

          {/* Documents */}
          <div className="flex items-center gap-3">
            <div className={`flex h-6 w-6 shrink-0 items-center justify-center rounded-full text-xs font-bold
              ${docs.length === 0 ? 'bg-gray-100 text-gray-400'
                : pendingForClient > 0 ? 'bg-red-100 text-red-700'
                : docsAllDone ? 'bg-[#1A4731] text-white'
                : 'bg-gray-100 text-gray-400'}`}>
              {docs.length === 0 ? '\u2014'
                : pendingForClient > 0 ? '!'
                : docsAllDone ? '\u2713'
                : '~'}
            </div>
            <div className="flex-1 min-w-0">
              <p className="text-sm font-medium text-gray-700">Documents</p>
              <p className="text-xs text-gray-400">
                {docs.length === 0
                  ? 'No documents yet'
                  : pendingForClient > 0
                  ? `${pendingForClient} document${pendingForClient > 1 ? 's' : ''} need${pendingForClient === 1 ? 's' : ''} your signature`
                  : waitingOnCbCount > 0
                  ? `${waitingOnCbCount} awaiting CB signature`
                  : 'All signed'}
              </p>
            </div>
            {docs.length > 0 && (
              <Link href="/client/documents" className="text-xs font-medium text-[#1A4731] hover:underline">
                View \u2192
              </Link>
            )}
          </div>
        </div>
      </div>

      {/* Status Timeline */}
      <div className="rounded-xl border bg-white p-5">
        <h2 className="mb-4 text-xs font-semibold uppercase tracking-wide text-gray-400">Certification Progress</h2>
        <div className="space-y-0">
          {WORKFLOW_STEPS.map((step, idx) => {
            const isDone    = currentIdx >= 0 && idx <  currentIdx
            const isCurrent = currentIdx >= 0 && idx === currentIdx
            const isFuture  = currentIdx <  0 || idx >  currentIdx
            const histEvent = history.find((h) => h.to_status === step.key)

            return (
              <div key={step.key} className="flex gap-3">
                <div className="flex flex-col items-center">
                  <div className={[
                    'flex h-6 w-6 shrink-0 items-center justify-center rounded-full text-[10px] font-bold transition-all',
                    isDone    ? 'bg-[#1A4731] text-white' : '',
                    isCurrent ? 'bg-[#1A4731] text-white ring-4 ring-[#1A4731]/20' : '',
                    isFuture  ? 'bg-gray-100 text-gray-400' : '',
                  ].join(' ')}>
                    {isDone ? '\u2713' : idx + 1}
                  </div>
                  {idx < WORKFLOW_STEPS.length - 1 && (
                    <div className={`mt-0.5 h-6 w-0.5 ${isDone ? 'bg-[#1A4731]' : 'bg-gray-200'}`} />
                  )}
                </div>
                <div className="min-w-0 flex-1 pb-4">
                  <p className={`text-sm font-medium ${isFuture ? 'text-gray-400' : 'text-gray-800'}`}>
                    {step.label}
                  </p>
                  {isCurrent && <p className="text-xs text-gray-500">{step.desc}</p>}
                  {histEvent && (
                    <p className="text-xs text-gray-400">
                      {fmtShortDate(histEvent.triggered_at)}
                      {histEvent.notes && ` \u2014 ${histEvent.notes}`}
                    </p>
                  )}
                </div>
              </div>
            )
          })}
        </div>
      </div>

      {/* Key Info Cards */}
      {(auditorName || stage1?.audit_date_start || stage2?.audit_date_start || data.cert_expiry_date) && (
        <div className="grid grid-cols-2 gap-3">
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
      )}

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
