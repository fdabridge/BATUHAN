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
  { key: 'fr218_in_progress',  label: 'FR.218'     },
  { key: 'fr218_complete',     label: 'FR.218 ✓'   },
  { key: 'stage1_in_progress', label: 'S1 Audit'   },
  { key: 'stage1_complete',    label: 'S1 Done'    },
  { key: 'stage2_in_progress', label: 'S2 Audit'   },
  { key: 'stage2_complete',    label: 'S2 Done'    },
  { key: 'committee_review',   label: 'Committee'  },
  { key: 'certified',          label: 'Certified'  },
]

// Legacy / alternate statuses mapped onto the step strip (Portal 49b removed
// the scheduling steps; old sets may still carry these statuses).
const INITIAL_STEP_ALIAS: Record<string, string> = {
  stage1_scheduled: 'stage1_in_progress',
  stage2_scheduled: 'stage2_in_progress',
  under_review:     'committee_review',
}

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

const SURVEILLANCE_STEPS = [
  { key: 'pending_review',    label: 'Pending'    },
  { key: 'in_planning',       label: 'Planning'   },
  { key: 'notification_sent', label: 'Notified'   },
  { key: 'audit_scheduled',   label: 'Scheduled'  },
  { key: 'audit_in_progress', label: 'In Progress'},
  { key: 'under_review',      label: 'Review'     },
  { key: 'certified',         label: 'Continued'  },
]

function isSurveillanceAudit(auditType: string | null): boolean {
  return auditType != null && auditType.startsWith('surveillance')
}

function getSteps(auditType: string | null) {
  if (auditType === 'initial') return INITIAL_STEPS
  if (isSurveillanceAudit(auditType)) return SURVEILLANCE_STEPS
  return STANDARD_STEPS
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
    heading: 'Agreement confirmed — application review pending',
    body: 'The client has signed the agreement. FR.218 application review will open automatically; if you do not see it, refresh the page.',
  },
  fr218_in_progress: {
    heading: 'FR.218 application review in progress',
    body: 'The Planning Officer, optional independent reviewer (FSMS/ISMS only), and Certification Manager must sign FR.218 before Stage 1 can be scheduled. Track signatures in the Internal Approvals section below.',
  },
  fr218_complete: {
    heading: 'FR.218 complete — ready for Stage 1',
    body: 'Application review is signed off. Upload FR.222 (Audit Programme), the per-auditor FR.224 forms, and the Stage 1 FR.223 (Audit Plan). Stage 1 can begin once FR.222 is signed by Planner + Cert Manager, every Stage 1 FR.224 is signed by its auditor, and FR.223 is signed by the organisation representative.',
    cta: { label: 'Begin Stage 1', nextStatus: 'stage1_in_progress', allowedRoles: ['admin', 'planner', 'planner_us'] },
  },
  stage1_scheduled: {
    heading: 'Stage 1 scheduled (legacy)',
    body: 'Stage 1 dates are confirmed. Mark as in progress when the Stage 1 audit begins.',
    cta: { label: 'Mark Stage 1 In Progress', nextStatus: 'stage1_in_progress' },
  },
  stage1_in_progress: {
    heading: 'Stage 1 audit in progress',
    body: 'Stage 1 is underway. The status advances automatically when FR.231 (Stage 1 report) is fully signed, or you can mark it complete manually.',
    cta: { label: 'Mark Stage 1 Complete', nextStatus: 'stage1_complete' },
  },
  stage1_complete: {
    heading: 'Stage 1 complete — Certification Manager review',
    body: 'The Certification Manager reviews all Stage 1 work (FR.218, FR.222, FR.224s, FR.223, FR.225, FR.230, FR.231). When satisfied, click "Stage 1 appropriate" to begin Stage 2.',
    cta: { label: 'Stage 1 appropriate — Begin Stage 2', nextStatus: 'stage2_in_progress', allowedRoles: ['admin', 'executive', 'certification_manager'] },
  },
  stage2_scheduled: {
    heading: 'Stage 2 scheduled (legacy)',
    body: 'Stage 2 dates are confirmed. Mark as in progress when the on-site audit begins.',
    cta: { label: 'Mark Stage 2 In Progress', nextStatus: 'stage2_in_progress' },
  },
  stage2_in_progress: {
    heading: 'Stage 2 audit in progress',
    body: 'Stage 2 is underway. The status advances automatically when FR.232/FR.229 (Stage 2 report) is fully signed, or you can mark it complete manually.',
    cta: { label: 'Mark Stage 2 Complete', nextStatus: 'stage2_complete' },
  },
  stage2_complete: {
    heading: 'Stage 2 complete — committee review next',
    body: 'Stage 2 is done. Certification is NOT automatic: release FR.233 from Shared Documents to open the committee review.',
    cta: { label: 'Open Committee Review', nextStatus: 'committee_review', allowedRoles: ['admin', 'planner', 'planner_us', 'certification_manager'] },
  },
  committee_review: {
    heading: 'Committee review in progress',
    body: 'Committee members sign FR.233 one by one. When all have signed, the Certification Manager signs to issue the certification.',
  },
  under_review: {
    heading: 'Under review (legacy)',
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

const SURVEILLANCE_PANELS: Record<string, ActionPanel> = {
  in_planning: {
    heading: 'Prepare surveillance notification',
    body: 'Download and generate FR.234 (Surveillance Notification Form), fill in audit dates and team, then release it to the client using the Shared Documents section below. Status advances automatically when you release it.',
  },
  notification_sent: {
    heading: 'Client notified — confirm audit dates',
    body: 'FR.234 has been released to the client. Upload FR.224 (Team Information) and FR.223 (Audit Plan) for the surveillance stage. Once dates are confirmed, mark the audit as scheduled.',
    cta: { label: 'Mark as Audit Scheduled', nextStatus: 'audit_scheduled', allowedRoles: ['admin', 'planner', 'planner_us'] },
  },
  audit_scheduled: {
    heading: 'Surveillance audit is scheduled',
    body: 'Audit dates are confirmed. Mark as in progress when the surveillance audit begins.',
    cta: { label: 'Mark as In Progress', nextStatus: 'audit_in_progress' },
  },
  audit_in_progress: {
    heading: 'Surveillance audit in progress',
    body: 'The audit is underway. The auditor uploads FR.232 (Audit Report), FR.225, and FR.230 via their portal. Status advances to Under Review automatically when documents are uploaded.',
  },
  under_review: {
    heading: 'Under review — committee decision',
    body: 'Audit documents are complete. Release FR.233 (Review & Decision Form) from Shared Documents so the committee can sign. Once the decision is issued, mark certification as continued.',
    cta: { label: 'Issue Continuation Certificate', nextStatus: 'certified', allowedRoles: ['admin', 'executive'] },
  },
  certified: {
    heading: 'Surveillance completed ✓',
    body: 'Surveillance audit is closed. The continuation certificate has been issued.',
  },
}

function getPanels(auditType: string | null) {
  if (auditType === 'initial') return INITIAL_PANELS
  if (isSurveillanceAudit(auditType)) return SURVEILLANCE_PANELS
  return STANDARD_PANELS
}

export function WorkflowStatusBar({ auditSetId, currentStatus, currentUserRole, auditType, onAdvanced }: WorkflowStatusBarProps) {
  const isRealtimeMode = currentUserRole === 'planner_us'
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
    if (currentUserRole !== 'admin' && currentUserRole !== 'planner' && currentUserRole !== 'planner_us') return null

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
              <option value="notification_sent">Notification Sent</option>
              <option value="quotation_sent">Quotation Sent</option>
              <option value="agreement_signed">Agreement Signed</option>
              <option value="fr218_in_progress">FR.218 In Progress</option>
              <option value="fr218_complete">FR.218 Complete</option>
              <option value="stage1_scheduled">Stage 1 Scheduled</option>
              <option value="stage1_in_progress">Stage 1 In Progress</option>
              <option value="stage1_complete">Stage 1 Complete</option>
              <option value="stage2_scheduled">Stage 2 Scheduled</option>
              <option value="stage2_in_progress">Stage 2 In Progress</option>
              <option value="stage2_complete">Stage 2 Complete</option>
              <option value="committee_review">Committee Review</option>
              <option value="audit_scheduled">Audit Scheduled</option>
              <option value="audit_in_progress">Audit In Progress</option>
              <option value="under_review">Under Review</option>
              <option value="certified">Certified ✓</option>
            </select>
          </div>

          {/* Date picker — hidden in realtime mode */}
          {!isRealtimeMode && (
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
          )}

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

  const stepKey    = (auditType === 'initial' && currentStatus && INITIAL_STEP_ALIAS[currentStatus]) || currentStatus
  const currentIdx = STEPS.findIndex((s) => s.key === stepKey)
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
              {/* Retroactive date picker — hidden in realtime mode */}
              {!isRealtimeMode && (
                <div className="mt-2 flex items-center gap-2">
                  <label className="text-xs text-gray-500">Effective date:</label>
                  <input
                    type="date"
                    value={effectiveDate}
                    onChange={e => setEffectiveDate(e.target.value)}
                    className="rounded border border-gray-200 px-2 py-0.5 text-xs text-gray-700 focus:border-[#1A4731] focus:outline-none"
                  />
                </div>
              )}
            </div>
          )}
          {errMsg && <p className="mt-2 text-sm text-red-600">{errMsg}</p>}
        </div>
      )}
    </div>
  )
}
