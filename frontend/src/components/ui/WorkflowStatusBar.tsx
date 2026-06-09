'use client'

import { useState } from 'react'
import { useMutation } from '@tanstack/react-query'
import api from '@/lib/api'

interface WorkflowStatusBarProps {
  auditSetId: string
  currentStatus: string | null
  currentUserRole: string
  onAdvanced: () => void
}

const STEPS = [
  { key: 'pending_review',    label: 'Pending'    },
  { key: 'in_planning',       label: 'Planning'   },
  { key: 'quotation_sent',    label: 'Quotation'  },
  { key: 'agreement_signed',  label: 'Agreement'  },
  { key: 'audit_scheduled',   label: 'Scheduled'  },
  { key: 'audit_in_progress', label: 'In Progress'},
  { key: 'under_review',      label: 'Review'     },
  { key: 'certified',         label: 'Certified'  },
]

interface ActionPanel {
  heading: string
  body:    string
  cta?:    { label: string; nextStatus: string; allowedRoles?: string[] }
}

const PANELS: Record<string, ActionPanel> = {
  in_planning: {
    heading: 'Ready to send quotation?',
    body: "Download and generate the FR.220 quotation, then release it to the client using the Shared Documents section below. Once you release a document with type 'Quotation', the status advances automatically.",
  },
  quotation_sent: {
    heading: 'Waiting for client signature',
    body: 'The quotation has been sent. The client needs to sign it via their portal. Status will advance automatically when they sign.',
  },
  agreement_signed: {
    heading: 'Agreement confirmed',
    body: 'The client has signed the agreement. Once audit dates are confirmed with the client, mark the audit as scheduled.',
    cta: { label: 'Mark as Audit Scheduled', nextStatus: 'audit_scheduled' },
  },
  audit_scheduled: {
    heading: 'Audit is scheduled',
    body: 'Audit dates are confirmed. When the audit begins, mark it as in progress.',
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

export function WorkflowStatusBar({ auditSetId, currentStatus, currentUserRole, onAdvanced }: WorkflowStatusBarProps) {
  const [errMsg, setErrMsg] = useState<string | null>(null)

  const { mutate: advance, isPending } = useMutation({
    mutationFn: (nextStatus: string) =>
      api.patch(`/audit-sets/${auditSetId}/workflow-status`, {
        workflow_status: nextStatus,
        notes: 'Advanced from workflow status bar',
      }),
    onSuccess: () => { setErrMsg(null); onAdvanced() },
    onError: (e: unknown) => {
      const detail = (e as { response?: { data?: { detail?: string } } })?.response?.data?.detail
      setErrMsg(detail ?? 'Failed to advance status')
    },
  })

  if (!currentStatus || currentStatus === 'pending_review') return null

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
            <button
              type="button"
              disabled={isPending}
              onClick={() => advance(panel.cta!.nextStatus)}
              className="mt-3 rounded-lg px-4 py-2 text-sm font-medium text-white hover:opacity-90 disabled:opacity-60"
              style={{ background: '#1A4731' }}
            >
              {isPending ? 'Saving…' : panel.cta.label}
            </button>
          )}
          {errMsg && <p className="mt-2 text-sm text-red-600">{errMsg}</p>}
        </div>
      )}
    </div>
  )
}
