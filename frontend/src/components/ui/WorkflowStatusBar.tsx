'use client'

import { useState } from 'react'
import { useMutation } from '@tanstack/react-query'
import api from '@/lib/api'

interface WorkflowStatusBarProps {
  auditSetId:      string
  currentStatus:   string | null
  currentUserRole: string
  auditType:       string | null   // "initial" | "surveillance" | "recertification" | null
  onAdvanced:      () => void
}

const INITIAL_STEPS = [
  { key: 'pending_review',     label: 'Pending'    },
  { key: 'in_planning',        label: 'Planning'   },
  { key: 'quotation_sent',     label: 'Quotation'  },
  { key: 'agreement_signed',   label: 'Agreement'  },
  { key: 'stage1_scheduled',   label: 'Stage 1'    },
  { key: 'stage1_in_progress', label: 'S1 Audit'   },
  { key: 'stage1_complete',    label: 'S1 Done'    },
  { key: 'stage2_scheduled',   label: 'Stage 2'    },
  { key: 'stage2_in_progress', label: 'S2 Audit'   },
  { key: 'under_review',       label: 'Review'     },
  { key: 'certified',          label: 'Certified'  },
]

const STANDARD_STEPS = [
  { key: 'pending_review',    label: 'Pending'    },
  { key: 'in_planning',       label: 'Planning'   },
  { key: 'quotation_sent',    label: 'Quotation'  },
  { key: 'agreement_signed',  label: 'Agreement'  },
  { key: 'audit_scheduled',   label: 'Scheduled'  },
  { key: 'audit_in_progress', label: 'In Progress'},
  { key: 'under_review',      label: 'Review'     },
  { key: 'certified',         label: 'Certified'  },
]

function getSteps(auditType: string | null) {
  return auditType === 'initial' ? INITIAL_STEPS : STANDARD_STEPS
}

interface ActionPanel {
  heading: string
  body:    string
  cta?:    { label: string; nextStatus: string; allowedRoles?: string[] }
}

const INITIAL_PANELS: Record<string, ActionPanel> = {
  in_planning: {
    heading: 'Ready to send quotation?',
    body: "Download and generate the FR.220 quotation, then release it to the client using the Shared Documents section below. Once you release a Quotation document, the status advances automatically.",
  },
  quotation_sent: {
    heading: 'Waiting for client signature',
    body: 'The quotation has been sent. The client needs to sign it via their portal. Status will advance automatically when they sign.',
  },
  agreement_signed: {
    heading: 'Agreement confirmed — ready for Stage 1',
    body: 'The client has signed the agreement. Schedule the Stage 1 (document review) audit dates to proceed.',
    cta: { label: 'Schedule Stage 1', nextStatus: 'stage1_scheduled' },
  },
  stage1_scheduled: {
    heading: 'Stage 1 scheduled',
    body: 'Stage 1 dates are confirmed. Mark as in progress when the Stage 1 audit begins.',
    cta: { label: 'Mark Stage 1 In Progress', nextStatus: 'stage1_in_progress' },
  },
  stage1_in_progress: {
    heading: 'Stage 1 audit in progress',
    body: 'Stage 1 is underway. Once the Stage 1 readiness assessment is complete and the client is cleared for Stage 2, mark it as done.',
    cta: { label: 'Mark Stage 1 Complete', nextStatus: 'stage1_complete' },
  },
  stage1_complete: {
    heading: 'Stage 1 complete ✓',
    body: 'Stage 1 is done. Schedule the Stage 2 (on-site) audit when dates are agreed.',
    cta: { label: 'Schedule Stage 2', nextStatus: 'stage2_scheduled' },
  },
  stage2_scheduled: {
    heading: 'Stage 2 scheduled',
    body: 'Stage 2 dates are confirmed. Mark as in progress when the on-site audit begins.',
    cta: { label: 'Mark Stage 2 In Progress', nextStatus: 'stage2_in_progress' },
  },
  stage2_in_progress: {
    heading: 'Stage 2 audit in progress',
    body: 'Stage 2 is underway. Status will advance to Under Review when the auditor uploads their completed documents.',
  },
  under_review: {
    heading: 'Under review',
    body: 'Audit documents are uploaded. The certification committee can now review and issue the certificate.',
    cta: { label: 'Issue Certificate', nextStatus: 'certified', allowedRoles: ['admin', 'executive'] },
  },
  certified: {
    heading: 'Certified ✓',
    body: 'The certification has been issued.',
  },
}

const STANDARD_PANELS: Record<string, ActionPanel> = {
  in_planning: {
    heading: 'Ready to send quotation?',
    body: "Download and generate the FR.220 quotation, then release it to the client using the Shared Documents section below. Once you release a Quotation document, the status advances automatically.",
  },
  quotation_sent: {
    heading: 'Waiting for client signature',
    body: 'The quotation has been sent. The client needs to sign it via their portal. Status will advance automatically when they sign.',
  },
  agreement_signed: {
    heading: 'Agreement confirmed',
    body: 'The client has signed the agreement. Once audit dates are confirmed, mark the audit as scheduled.',
    cta: { label: 'Mark as Audit Scheduled', nextStatus: 'audit_scheduled' },
  },
  audit_scheduled: {
    heading: 'Audit is scheduled',
    body: 'Audit dates are confirmed. Mark as in progress when the audit begins.',
    cta: { label: 'Mark as In Progress', nextStatus: 'audit_in_progress' },
  },
  audit_in_progress: {
    heading: 'Audit in progress',
    body: 'The audit is underway. Status will advance automatically when the auditor uploads their completed documents.',
  },
  under_review: {
    heading: 'Under review',
    body: 'Audit documents are uploaded. The certification committee can now review and issue the certificate.',
    cta: { label: 'Issue Certificate', nextStatus: 'certified', allowedRoles: ['admin', 'executive'] },
  },
  certified: {
    heading: 'Certified ✓',
    body: 'The certification has been issued.',
  },
}

function getPanels(auditType: string | null) {
  return auditType === 'initial' ? INITIAL_PANELS : STANDARD_PANELS
}

export function WorkflowStatusBar({ auditSetId, currentStatus, currentUserRole, auditType, onAdvanced }: WorkflowStatusBarProps) {
  const [errMsg, setErrMsg] = useState<string | null>(null)
  // Retroactive mode — date picker for recording when transitions actually happened.
  const [effectiveDate, setEffectiveDate] = useState<string>(
    () => new Date().toISOString().slice(0, 10)   // YYYY-MM-DD, defaults to today
  )

  const { mutate: advance, isPending } = useMutation({
    mutationFn: ({ nextStatus, date }: { nextStatus: string; date: string }) =>
      api.patch(`/audit-sets/${auditSetId}/workflow-status`, {
        workflow_status: nextStatus,
        notes: 'Advanced from workflow status bar',
        effective_date: date,
      }),
    onSuccess: () => { setErrMsg(null); onAdvanced() },
    onError: (e: unknown) => {
      const detail = (e as { response?: { data?: { detail?: string } } })?.response?.data?.detail
      setErrMsg(detail ?? 'Failed to advance status')
    },
  })

  // Jump panel — used when workflow_status is null (internal audit sets)
  const [jumpStatus,  setJumpStatus]  = useState('certified')
  const [jumpDate,    setJumpDate]    = useState(() => new Date().toISOString().slice(0, 10))
  const [jumpPending, setJumpPending] = useState(false)
  const [jumpErr,     setJumpErr]     = useState<string | null>(null)

  async function handleJump() {
    setJumpPending(true)
    setJumpErr(null)
    try {
      await api.post(`/audit-sets/${auditSetId}/workflow-status/jump`, {
        target_status: jumpStatus,
        effective_date: jumpDate,
      })
      onAdvanced()
    } catch (err: unknown) {
      const detail = (err as { response?: { data?: { detail?: string } } })?.response?.data?.detail
      setJumpErr(detail || 'Failed to set status')
    } finally {
      setJumpPending(false)
    }
  }

  const STEPS  = getSteps(auditType)
  const PANELS = getPanels(auditType)

  if (currentStatus === 'pending_review') return null

  if (!currentStatus) {
    // Workflow not started yet. Show jump panel for admin/planner only.
    if (currentUserRole !== 'admin' && currentUserRole !== 'planner') return null

    return (
      <div className="rounded-xl border border-gray-200 bg-white p-5 mb-2">
        <p className="text-sm font-semibold text-gray-800">Portal workflow not started</p>
        <p className="mt-1 text-xs text-gray-500">
          This audit set was created internally. Set its current workflow status to activate
          the portal view — use a historical date for retroactive clients.
        </p>

        <div className="mt-4 flex flex-wrap items-end gap-3">
          {/* Status selector */}
          <div>
            <label className="mb-1 block text-xs font-medium text-gray-600">
              Current status
            </label>
            <select
              value={jumpStatus}
              onChange={e => setJumpStatus(e.target.value)}
              className="rounded-lg border border-gray-200 bg-white px-3 py-1.5 text-sm text-gray-800 focus:border-[#1A4731] focus:outline-none"
            >
              <option value="in_planning">In Planning</option>
              <option value="quotation_sent">Quotation Sent</option>
              <option value="agreement_signed">Agreement Signed</option>
              <option value="stage1_scheduled">Stage 1 Scheduled</option>
              <option value="stage1_in_progress">Stage 1 In Progress</option>
              <option value="stage1_complete">Stage 1 Complete</option>
              <option value="stage2_scheduled">Stage 2 Scheduled</option>
              <option value="stage2_in_progress">Stage 2 In Progress</option>
              <option value="audit_scheduled">Audit Scheduled</option>
              <option value="audit_in_progress">Audit In Progress</option>
              <option value="under_review">Under Review</option>
              <option value="certified">Certified ✓</option>
            </select>
          </div>

          {/* Date picker */}
          <div>
            <label className="mb-1 block text-xs font-medium text-gray-600">
              Effective date
            </label>
            <input
              type="date"
              value={jumpDate}
              onChange={e => setJumpDate(e.target.value)}
              className="rounded-lg border border-gray-200 px-3 py-1.5 text-sm text-gray-700 focus:border-[#1A4731] focus:outline-none"
            />
          </div>

          {/* Apply button */}
          <button
            type="button"
            onClick={handleJump}
            disabled={jumpPending}
            className="rounded-lg px-4 py-2 text-sm font-medium text-white hover:opacity-90 disabled:opacity-60"
            style={{ background: '#1A4731' }}
          >
            {jumpPending ? 'Applying…' : 'Activate Workflow'}
          </button>
        </div>

        {jumpErr && (
          <p className="mt-2 text-xs text-red-500">{jumpErr}</p>
        )}
      </div>
    )
  }

  const currentIdx = STEPS.findIndex((s) => s.key === currentStatus)
  const panel      = PANELS[currentStatus]
  const ctaAllowed = !panel?.cta?.allowedRoles || panel.cta.allowedRoles.includes(currentUserRole)

  return (
    <div className="space-y-3">
      {/* Step strip */}
      <div className="rounded-xl border bg-white p-4">
        <div className="flex items-center">
          {STEPS.map((step, idx) => {
            const isDone    = currentIdx >= 0 && idx <  currentIdx
            const isCurrent = currentIdx >= 0 && idx === currentIdx
            const circleClass = [
              'flex h-7 w-7 shrink-0 items-center justify-center rounded-full text-[11px] font-bold',
              isDone    ? 'bg-[#1A4731] text-white' : '',
              isCurrent ? 'bg-[#1A4731] text-white ring-4 ring-[#1A4731]/20' : '',
              !isDone && !isCurrent ? 'border border-gray-300 bg-white text-gray-400' : '',
            ].join(' ')
            return (
              <div key={step.key} className="flex flex-1 items-center last:flex-none">
                <div className="flex flex-col items-center">
                  <div className={circleClass}>{isDone ? '✓' : idx + 1}</div>
                  <span className={`mt-1 text-[10px] ${isCurrent ? 'font-semibold text-[#1A4731]' : 'text-gray-400'}`}>
                    {step.label}
                  </span>
                </div>
                {idx < STEPS.length - 1 && (
                  <div className={`mx-2 h-0.5 flex-1 ${idx < currentIdx ? 'bg-[#1A4731]' : 'bg-gray-200'}`} />
                )}
              </div>
            )
          })}
        </div>
      </div>

      {/* Action panel */}
      {panel && (
        <div className="rounded-xl border bg-white p-5">
          <h3 className="text-sm font-semibold text-gray-900">{panel.heading}</h3>
          <p className="mt-1 text-sm text-gray-600">{panel.body}</p>
          {panel.cta && ctaAllowed && (
            <div>
              <button
                type="button"
                disabled={isPending}
                onClick={() => advance({ nextStatus: panel.cta!.nextStatus, date: effectiveDate })}
                className="mt-3 rounded-lg px-4 py-2 text-sm font-medium text-white hover:opacity-90 disabled:opacity-60"
                style={{ background: '#1A4731' }}
              >
                {isPending ? 'Saving…' : panel.cta.label}
              </button>
              {/* Retroactive date picker — always visible, no off switch */}
              <div className="mt-2 flex items-center gap-2">
                <label className="text-xs text-gray-500">Effective date:</label>
                <input
                  type="date"
                  value={effectiveDate}
                  onChange={e => setEffectiveDate(e.target.value)}
                  className="rounded border border-gray-200 px-2 py-0.5 text-xs text-gray-700 focus:border-[#1A4731] focus:outline-none"
                />
              </div>
            </div>
          )}
          {errMsg && <p className="mt-2 text-sm text-red-600">{errMsg}</p>}
        </div>
      )}
    </div>
  )
}
