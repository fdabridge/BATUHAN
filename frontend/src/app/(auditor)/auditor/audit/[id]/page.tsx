'use client'

import { useEffect, useRef, useState } from 'react'
import { useParams } from 'next/navigation'
import api from '@/lib/api'
import { MessageThread } from '@/components/ui/MessageThread'
import { useManualActionDates } from '@/lib/useManualActionDates'

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

interface Stage {
  stage_type:        string
  stage_order:       number
  audit_date_start:  string | null
  audit_date_end:    string | null
  lead_auditor_id:   string | null
  lead_auditor_name: string | null
  audit_days:        number | null
  status:            string
}

interface AssignmentDetail {
  id:                     string
  plan_number:            number
  client_reference:       string | null
  company_name:           string
  company_address:        string
  email:                  string
  phone:                  string
  representative:         string
  standards:              string[]
  audit_type:             string
  scope_en:               string | null
  non_applicable_clauses: string | null
  ea_code:                string | null
  ea_category:            string | null
  accreditation_body:     string | null
  workflow_status:        string | null
  // Portal 51 — FR.218 Application Reviewer (FSMS/ISMS only)
  fr218_reviewer_id:      string | null
  stages:                 Stage[]
}

interface NCEvidence {
  id: string
  file_name: string | null
  upload_type: string
  round_number: number
}

interface NCReview {
  id: string
  decision: string
  notes: string | null
  reviewed_at: string
  round_number: number
}

interface NCItem {
  id: string
  nc_index: number
  category: string
  description: string
  status: string
  due_date: string | null
  evidence: NCEvidence[]
  reviews: NCReview[]
}

interface NCDecision {
  id: string
  stage_type: string | null
  no_nc: boolean
  notes: string | null
  decided_at: string
  items: NCItem[]
}

interface NCDraft {
  noNC: boolean
  notes: string
  items: { category: string; description: string }[]
}

// Portal 55 — 'attendees' tab removed; FR.225 attendees come from the client's
// employee roster via docxtpl loop, not the legacy OTP invite flow.
type Tab = 'overview' | 'documents' | 'messages' | 'upload' | 'nc_forms' | 'declarations' | 'reports'
type UploadStageType = 'stage_1' | 'stage_2' | 'surveillance'

function isSurveillanceAudit(auditType: string | null | undefined) {
  return (auditType ?? '').toLowerCase().startsWith('surveillance')
}

function uploadStageLabel(stageType: UploadStageType) {
  if (stageType === 'stage_1') return 'Stage 1'
  if (stageType === 'stage_2') return 'Stage 2'
  return 'Surveillance'
}

// Portal 55 — AuditorAttendeesView removed. FR.225 attendees are now sourced
// from the client's employee roster (ClientOrgEmployee), embedded in the FR.225
// template via docxtpl loop, and signed via [SIG:ORG_OPENING_ORG_EMP_<uuid>] /
// [SIG:ORG_CLOSING_ORG_EMP_<uuid>] keys in the viewer.

function AuditorNCFormsView({ auditSetId }: { auditSetId: string }) {
  const [forms, setForms]   = useState<{
    id: string; stage_type: string; label: string; file_name: string | null; status: string;
    la_signed_at: string | null;
  }[]>([])
  const [loading, setLoading] = useState(true)

  const STAGE_LABELS: Record<string, string> = {
    stage_1: 'Stage 1', stage_2: 'Stage 2', surveillance: 'Surveillance',
    recertification: 'Recertification',
  }

  useEffect(() => {
    api.get(`/audit-sets/${auditSetId}/nc-forms`)
      .then(r => setForms(r.data as typeof forms))
      .finally(() => setLoading(false))
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [auditSetId])

  if (loading) return <p className="text-sm text-gray-400">Loading…</p>

  const pending   = forms.filter(f => f.status === 'pending_la')
  const completed = forms.filter(f => f.status !== 'pending_la')

  return (
    <div className="space-y-4">
      {forms.length === 0 && (
        <p className="py-8 text-center text-sm text-gray-400">No NC forms for your stages.</p>
      )}

      {pending.length > 0 && (
        <div>
          <p className="mb-2 text-xs font-semibold uppercase tracking-wide text-amber-600">
            Awaiting Your Signature
          </p>
          <div className="space-y-3">
            {pending.map(f => (
              <div key={f.id} className="rounded-xl border border-amber-200 bg-amber-50 p-4 flex items-center justify-between">
                <div>
                  <p className="font-medium text-gray-800">{f.label}</p>
                  <p className="text-xs text-gray-400">{STAGE_LABELS[f.stage_type] ?? f.stage_type}</p>
                </div>
                <a
                  href={`/auditor/viewer/nc_form/${f.id}`}
                  className="inline-flex items-center rounded-lg bg-[#1A4731] px-3 py-1.5
                    text-xs font-medium text-white hover:bg-[#143828] transition-colors"
                >
                  Open to Sign
                </a>
              </div>
            ))}
          </div>
        </div>
      )}

      {completed.length > 0 && (
        <div>
          <p className="mb-2 text-xs font-semibold uppercase tracking-wide text-gray-400">
            Signed
          </p>
          <div className="rounded-xl border bg-white divide-y divide-gray-50">
            {completed.map(f => (
              <div key={f.id} className="flex items-center justify-between px-4 py-3">
                <div>
                  <p className="text-sm font-medium text-gray-800">{f.label}</p>
                  <p className="text-xs text-gray-400">
                    {STAGE_LABELS[f.stage_type] ?? f.stage_type} ·{' '}
                    {f.status === 'complete' ? 'Both parties signed' : 'Awaiting client'}
                  </p>
                </div>
                <a
                  href={`/auditor/viewer/nc_form/${f.id}`}
                  className="inline-flex items-center rounded-lg border border-[#1A4731] px-2.5 py-1
                    text-xs font-medium text-[#1A4731] hover:bg-[#1A4731]/5 transition-colors"
                >
                  Open
                </a>
              </div>
            ))}
          </div>
        </div>
      )}
    </div>
  )
}

function AuditorNCManagementView({
  auditSetId,
  stages,
  currentAuditorId,
}: {
  auditSetId: string
  stages: Stage[]
  currentAuditorId: string | null
}) {
  const ncStages = stages.filter(s => ['stage_1', 'stage_2', 'surveillance'].includes(s.stage_type))
  const [decisions, setDecisions] = useState<Record<string, NCDecision | null | undefined>>({})
  const [drafts, setDrafts] = useState<Record<string, NCDraft>>({})
  const [errors, setErrors] = useState<Record<string, string>>({})
  const [loading, setLoading] = useState(false)
  const [busyStage, setBusyStage] = useState<string | null>(null)
  const [reviewingId, setReviewingId] = useState<string | null>(null)
  const [reviewNotes, setReviewNotes] = useState('')

  const STAGE_LABELS: Record<string, string> = {
    stage_1: 'Stage 1',
    stage_2: 'Stage 2',
    surveillance: 'Surveillance',
  }

  function isLead(stage: Stage) {
    return !!currentAuditorId && stage.lead_auditor_id === currentAuditorId
  }

  function draftFor(stageType: string): NCDraft {
    return drafts[stageType] ?? {
      noNC: true,
      notes: '',
      items: [{ category: 'minor', description: '' }],
    }
  }

  function updateDraft(stageType: string, updater: (draft: NCDraft) => NCDraft) {
    setDrafts(prev => ({ ...prev, [stageType]: updater(draftFor(stageType)) }))
  }

  async function load() {
    if (!auditSetId || ncStages.length === 0) return
    setLoading(true)
    const entries = await Promise.all(ncStages.map(async stage => {
      if (!isLead(stage)) return [stage.stage_type, undefined] as const
      try {
        const r = await api.get<NCDecision | null>(`/audit-sets/${auditSetId}/nc-decision`, {
          params: { stage_type: stage.stage_type },
        })
        return [stage.stage_type, r.data] as const
      } catch {
        return [stage.stage_type, null] as const
      }
    }))
    setDecisions(Object.fromEntries(entries))
    setLoading(false)
  }

  useEffect(() => { load() }, [auditSetId, currentAuditorId]) // eslint-disable-line react-hooks/exhaustive-deps

  async function submitDecision(stageType: string) {
    const draft = draftFor(stageType)
    setBusyStage(stageType)
    setErrors(prev => ({ ...prev, [stageType]: '' }))
    try {
      const payload = draft.noNC
        ? { stage_type: stageType, no_nc: true, notes: draft.notes, items: [] }
        : {
            stage_type: stageType,
            no_nc: false,
            notes: draft.notes,
            items: draft.items.filter(i => i.description.trim()),
          }
      const r = await api.post<NCDecision>(`/audit-sets/${auditSetId}/nc-decision`, payload)
      setDecisions(prev => ({ ...prev, [stageType]: r.data }))
    } catch (err: unknown) {
      const detail = (err as { response?: { data?: { detail?: string } } })?.response?.data?.detail
      setErrors(prev => ({ ...prev, [stageType]: detail || 'NC decision could not be saved.' }))
    } finally {
      setBusyStage(null)
    }
  }

  async function reviewNC(ncId: string, decision: 'approved' | 'rejected') {
    try {
      await api.post(`/audit-sets/${auditSetId}/nc-items/${ncId}/review`, {
        decision,
        notes: reviewNotes,
      })
      setReviewingId(null)
      setReviewNotes('')
      load()
    } catch (err: unknown) {
      const detail = (err as { response?: { data?: { detail?: string } } })?.response?.data?.detail
      alert(detail || 'NC review failed.')
    }
  }

  if (loading) return <p className="text-sm text-gray-400">Loading NC workflow...</p>

  return (
    <div className="space-y-4">
      {ncStages.length === 0 && (
        <p className="py-8 text-center text-sm text-gray-400">No NC-managed audit stages found.</p>
      )}

      {ncStages.map(stage => {
        const stageType = stage.stage_type
        const stageLabel = STAGE_LABELS[stageType] ?? stageType
        const decision = decisions[stageType]
        const draft = draftFor(stageType)
        const lead = isLead(stage)

        return (
          <div key={stageType} className="rounded-xl border bg-white p-5">
            <div className="mb-4 flex items-start justify-between gap-3">
              <div>
                <p className="text-sm font-semibold text-gray-900">{stageLabel} NC Decision</p>
                <p className="mt-0.5 text-xs text-gray-400">
                  Lead auditor: {stage.lead_auditor_name || 'Not assigned'}
                </p>
              </div>
              {decision?.no_nc ? (
                <span className="rounded-full bg-green-100 px-2.5 py-0.5 text-xs font-semibold text-green-700">
                  No NC
                </span>
              ) : decision ? (
                <span className="rounded-full bg-blue-100 px-2.5 py-0.5 text-xs font-semibold text-blue-700">
                  {decision.items.filter(i => i.status !== 'closed').length} open
                </span>
              ) : (
                <span className="rounded-full bg-amber-100 px-2.5 py-0.5 text-xs font-semibold text-amber-700">
                  Required
                </span>
              )}
            </div>

            {!lead ? (
              <div className="rounded-lg border border-gray-200 bg-gray-50 p-3 text-xs text-gray-600">
                Only the assigned lead auditor can submit or review the NC decision for this stage.
              </div>
            ) : decision === null || decision === undefined ? (
              <div className="space-y-4">
                <label className="flex cursor-pointer items-center gap-2">
                  <input
                    type="checkbox"
                    checked={draft.noNC}
                    onChange={e => updateDraft(stageType, current => ({ ...current, noNC: e.target.checked }))}
                    className="h-4 w-4 rounded border-gray-300 accent-[#1A4731]"
                  />
                  <span className="text-sm font-medium text-gray-700">No nonconformities were identified</span>
                </label>

                <textarea
                  value={draft.notes}
                  onChange={e => updateDraft(stageType, current => ({ ...current, notes: e.target.value }))}
                  rows={2}
                  className="w-full rounded-lg border px-3 py-2 text-sm"
                  placeholder="Optional notes for this stage..."
                />

                {!draft.noNC && (
                  <div className="space-y-3">
                    {draft.items.map((item, idx) => (
                      <div key={idx} className="rounded-lg border border-gray-200 bg-gray-50 p-3">
                        <div className="mb-2 flex items-center gap-2">
                          <span className="text-xs font-semibold text-gray-500">NC-{idx + 1}</span>
                          <select
                            value={item.category}
                            onChange={e => updateDraft(stageType, current => {
                              const items = [...current.items]
                              items[idx] = { ...items[idx], category: e.target.value }
                              return { ...current, items }
                            })}
                            className="rounded border px-2 py-1 text-xs"
                          >
                            <option value="minor">Minor</option>
                            <option value="major">Major</option>
                            <option value="critical">Critical</option>
                          </select>
                          {draft.items.length > 1 && (
                            <button
                              type="button"
                              onClick={() => updateDraft(stageType, current => ({
                                ...current,
                                items: current.items.filter((_, i) => i !== idx),
                              }))}
                              className="ml-auto text-xs text-red-600"
                            >
                              Remove
                            </button>
                          )}
                        </div>
                        <textarea
                          value={item.description}
                          onChange={e => updateDraft(stageType, current => {
                            const items = [...current.items]
                            items[idx] = { ...items[idx], description: e.target.value }
                            return { ...current, items }
                          })}
                          rows={3}
                          className="w-full rounded border px-3 py-2 text-sm"
                          placeholder="Describe clause, evidence, and finding..."
                        />
                      </div>
                    ))}
                    <button
                      type="button"
                      onClick={() => updateDraft(stageType, current => ({
                        ...current,
                        items: [...current.items, { category: 'minor', description: '' }],
                      }))}
                      className="text-xs font-medium text-[#1A4731] hover:underline"
                    >
                      + Add another NC
                    </button>
                  </div>
                )}

                {errors[stageType] && <p className="text-sm text-red-600">{errors[stageType]}</p>}
                <button
                  type="button"
                  onClick={() => submitDecision(stageType)}
                  disabled={busyStage === stageType}
                  className="rounded-lg bg-[#1A4731] px-4 py-2 text-sm font-medium text-white disabled:opacity-40"
                >
                  {busyStage === stageType ? 'Saving...' : draft.noNC ? 'Confirm No NC' : 'Submit NC Decision'}
                </button>
              </div>
            ) : decision.no_nc ? (
              <div className="rounded-lg border border-green-200 bg-green-50 p-3 text-sm text-green-800">
                No nonconformities were identified for {stageLabel}.
                {decision.notes && <span className="ml-2 text-xs text-green-700">{decision.notes}</span>}
              </div>
            ) : (
              <div className="space-y-3">
                {decision.items.map(item => (
                  <div key={item.id} className="rounded-lg border border-gray-200 p-3">
                    <div className="flex items-start justify-between gap-3">
                      <div>
                        <div className="mb-1 flex items-center gap-2">
                          <span className="text-sm font-semibold text-gray-800">NC-{item.nc_index}</span>
                          <span className="rounded-full bg-gray-100 px-2 py-0.5 text-[11px] uppercase text-gray-600">
                            {item.category}
                          </span>
                          <span className={`rounded-full px-2 py-0.5 text-[11px] ${
                            item.status === 'closed' ? 'bg-green-100 text-green-700' :
                            item.status === 'client_responded' ? 'bg-blue-100 text-blue-700' :
                            item.status === 'rejected' ? 'bg-red-100 text-red-700' :
                            'bg-amber-100 text-amber-700'
                          }`}>
                            {item.status.replace(/_/g, ' ')}
                          </span>
                        </div>
                        <p className="text-sm text-gray-700">{item.description}</p>
                      </div>
                      {item.due_date && (
                        <span className="shrink-0 text-xs text-gray-400">
                          Due {new Date(item.due_date).toLocaleDateString('en-GB')}
                        </span>
                      )}
                    </div>

                    {item.evidence.length > 0 && (
                      <div className="mt-3 space-y-1">
                        <p className="text-xs font-medium text-gray-500">Client evidence</p>
                        {item.evidence.map(ev => (
                          <a
                            key={ev.id}
                            href={`${process.env.NEXT_PUBLIC_API_URL}/audit-sets/${auditSetId}/nc-items/${item.id}/evidence/${ev.id}/download`}
                            target="_blank"
                            rel="noreferrer"
                            className="block text-xs text-[#1A4731] hover:underline"
                          >
                            {ev.file_name || 'Evidence'} ({ev.upload_type.replace(/_/g, ' ')}, round {ev.round_number})
                          </a>
                        ))}
                      </div>
                    )}

                    {item.reviews.length > 0 && (
                      <div className="mt-3 space-y-1">
                        <p className="text-xs font-medium text-gray-500">Review history</p>
                        {item.reviews.map(review => (
                          <p key={review.id} className="text-xs text-gray-500">
                            {review.decision === 'approved' ? 'Approved' : 'Rejected'}
                            {review.notes ? ` - ${review.notes}` : ''}
                          </p>
                        ))}
                      </div>
                    )}

                    {item.status === 'client_responded' && (
                      <div className="mt-3 border-t pt-3">
                        {reviewingId === item.id ? (
                          <div className="space-y-2">
                            <textarea
                              value={reviewNotes}
                              onChange={e => setReviewNotes(e.target.value)}
                              rows={2}
                              className="w-full rounded border px-3 py-2 text-sm"
                              placeholder="Review notes..."
                            />
                            <div className="flex gap-2">
                              <button
                                type="button"
                                onClick={() => reviewNC(item.id, 'approved')}
                                className="rounded bg-green-700 px-3 py-1.5 text-xs text-white"
                              >
                                Approve and close
                              </button>
                              <button
                                type="button"
                                onClick={() => reviewNC(item.id, 'rejected')}
                                className="rounded bg-red-600 px-3 py-1.5 text-xs text-white"
                              >
                                Reject
                              </button>
                              <button
                                type="button"
                                onClick={() => { setReviewingId(null); setReviewNotes('') }}
                                className="rounded border px-3 py-1.5 text-xs"
                              >
                                Cancel
                              </button>
                            </div>
                          </div>
                        ) : (
                          <button
                            type="button"
                            onClick={() => setReviewingId(item.id)}
                            className="rounded-lg border border-[#1A4731] px-3 py-1.5 text-xs font-medium text-[#1A4731]"
                          >
                            Review client evidence
                          </button>
                        )}
                      </div>
                    )}
                  </div>
                ))}
              </div>
            )}
          </div>
        )
      })}
    </div>
  )
}


const DECLARATION_TEXT = [
  "I have no conflict of interest with the client organization and its representatives.",
  "I have had no commercial or other relevant relations with the client organization during the past two years.",
  "I will not have such relations for the next two years.",
  "I am not acting as a consultant to this organization in any management system area.",
  "I understand my obligation to maintain the confidentiality of all information obtained during and after the audit.",
]

function AuditorDeclarationsView({
  auditSetId,
  currentAuditorId,
}: {
  auditSetId: string
  currentAuditorId: string | null
}) {
  const { manualActionDatesEnabled } = useManualActionDates()
  const [declarations, setDeclarations] = useState<{
    id: string; stage_type: string; member_name: string; member_role: string
    auditor_ref_id: string | null; is_signed: boolean; signed_at: string | null
    file_path: string | null; file_name: string | null
  }[]>([])
  const [loading, setLoading]   = useState(true)
  const [signing, setSigning]   = useState<Record<string, boolean>>({})
  const [signErrs, setSignErrs] = useState<Record<string, string>>({})
  const [confirmed, setConfirmed] = useState<Record<string, boolean>>({})
  const [signDates, setSignDates] = useState<Record<string, string>>({})

  const STAGE_LABELS: Record<string, string> = {
    stage_1: 'Stage 1', stage_2: 'Stage 2',
    surveillance: 'Surveillance', recertification: 'Recertification',
  }
  const ROLE_COLOR: Record<string, string> = {
    'Lead Auditor':     'bg-purple-100 text-purple-700',
    'Team Auditor':     'bg-blue-100 text-blue-700',
    'Technical Expert': 'bg-teal-100 text-teal-700',
    'Observer':         'bg-gray-100 text-gray-500',
  }

  useEffect(() => {
    api.get(`/audit-sets/${auditSetId}/declarations`)
      .then(r => setDeclarations(r.data as typeof declarations))
      .finally(() => setLoading(false))
  }, [auditSetId])

  const myPending = declarations.filter(
    d => !d.is_signed && (
      currentAuditorId ? d.auditor_ref_id === currentAuditorId : true
    )
  )
  const otherDeclarations = declarations.filter(
    d => !myPending.some(mp => mp.id === d.id)
  )

  async function handleSign(id: string) {
    setSigning(s => ({ ...s, [id]: true }))
    setSignErrs(e => ({ ...e, [id]: '' }))
    try {
      const signed_date = manualActionDatesEnabled
        ? (signDates[id] || new Date().toISOString().slice(0, 10))
        : undefined
      await api.post(`/audit-sets/${auditSetId}/declarations/${id}/sign/direct`, { signed_date })
      // Re-fetch to get file_path/file_name from server after PDF generation
      const refreshed = await api.get(`/audit-sets/${auditSetId}/declarations`)
      setDeclarations(refreshed.data as typeof declarations)
    } catch (err: unknown) {
      const detail = (err as { response?: { data?: { detail?: string } } })?.response?.data?.detail
      setSignErrs(e => ({ ...e, [id]: detail || 'Signing failed' }))
    } finally {
      setSigning(s => ({ ...s, [id]: false }))
    }
  }

  if (loading) return <p className="text-sm text-gray-400">Loading…</p>

  return (
    <div className="space-y-5">
      {declarations.length === 0 && (
        <p className="py-8 text-center text-sm text-gray-400">
          No declaration forms yet. The CB will create them before the audit.
        </p>
      )}

      {myPending.map(d => (
        <div key={d.id} className="rounded-xl border border-amber-200 bg-white p-5">
          <div className="mb-4 flex items-center justify-between">
            <div>
              <p className="font-semibold text-gray-800">Impartiality Declaration</p>
              <p className="mt-0.5 text-xs text-gray-400">
                {STAGE_LABELS[d.stage_type] ?? d.stage_type} ·{' '}
                <span className={`rounded-full px-1.5 py-0.5 text-xs ${ROLE_COLOR[d.member_role] ?? ''}`}>
                  {d.member_role}
                </span>
              </p>
            </div>
            <span className="rounded-full bg-amber-100 px-2.5 py-0.5 text-xs font-semibold text-amber-700">
              Signature Required
            </span>
          </div>

          <div className="mb-4 rounded-lg bg-gray-50 p-4">
            <p className="mb-2 text-xs font-semibold uppercase tracking-wide text-gray-500">
              I, {d.member_name}, hereby declare that:
            </p>
            <ul className="space-y-1.5">
              {DECLARATION_TEXT.map((line, i) => (
                <li key={i} className="flex gap-2 text-sm text-gray-700">
                  <span className="mt-0.5 shrink-0 text-[#1A4731]">✓</span>
                  <span>{line}</span>
                </li>
              ))}
            </ul>
          </div>

          <div className="mb-3">
            <label className="flex cursor-pointer items-start gap-2 text-sm text-gray-700">
              <input
                type="checkbox"
                checked={confirmed[d.id] || false}
                onChange={e => setConfirmed(c => ({ ...c, [d.id]: e.target.checked }))}
                className="mt-0.5 accent-[#1A4731]"
              />
              I confirm the above declaration is true and accurate.
            </label>
          </div>

          <div className="flex items-end gap-3">
            {manualActionDatesEnabled && <div>
              <label className="block text-xs text-gray-500 mb-1">Signing date</label>
              <input
                type="date"
                value={signDates[d.id] || new Date().toISOString().slice(0, 10)}
                onChange={e => setSignDates(prev => ({ ...prev, [d.id]: e.target.value }))}
                className="rounded-lg border px-2 py-1 text-sm"
              />
            </div>}
            <button
              type="button"
              onClick={() => handleSign(d.id)}
              disabled={!confirmed[d.id] || signing[d.id]}
              className="rounded-lg bg-[#1A4731] px-5 py-2.5 text-sm font-medium text-white disabled:opacity-40 hover:bg-[#143828]"
            >
              {signing[d.id] ? 'Signing…' : 'Sign Declaration'}
            </button>
          </div>
          {signErrs[d.id] && (
            <p className="mt-1 text-xs text-red-500">{signErrs[d.id]}</p>
          )}
        </div>
      ))}

      {otherDeclarations.length > 0 && (
        <div>
          <p className="mb-2 text-xs font-semibold uppercase tracking-wide text-gray-400">
            Team Status
          </p>
          <div className="rounded-xl border bg-white divide-y divide-gray-50">
            {otherDeclarations.map(d => (
              <div key={d.id} className="flex items-center justify-between px-4 py-3">
                <div className="flex items-center gap-2">
                  <p className="text-sm font-medium text-gray-800">{d.member_name}</p>
                  <span className={`rounded-full px-1.5 py-0.5 text-xs ${ROLE_COLOR[d.member_role] ?? 'bg-gray-100 text-gray-500'}`}>
                    {d.member_role}
                  </span>
                </div>
                {d.is_signed ? (
                  <div className="flex items-center gap-2">
                    <span className="rounded-full bg-green-100 px-2.5 py-0.5 text-xs font-semibold text-green-700">
                      ✓ Signed
                    </span>
                    {d.file_path && (
                      <a
                        href={`/api/audit-sets/${auditSetId}/declarations/${d.id}/download-certificate`}
                        target="_blank"
                        rel="noopener noreferrer"
                        className="rounded-md border border-[#1A4731] px-2 py-0.5 text-xs font-medium text-[#1A4731] hover:bg-[#1A4731] hover:text-white transition-colors"
                      >
                        Download Certificate
                      </a>
                    )}
                  </div>
                ) : (
                  <span className="rounded-full bg-amber-100 px-2 py-0.5 text-xs text-amber-700">
                    Pending
                  </span>
                )}
              </div>
            ))}
          </div>
        </div>
      )}
    </div>
  )
}


const STAGE_OPTS_REPORTS = [
  { value: 'stage_1',         label: 'Stage 1' },
  { value: 'stage_2',         label: 'Stage 2' },
  { value: 'surveillance',    label: 'Surveillance' },
  { value: 'recertification', label: 'Recertification' },
]

const FORM_OPTS: {
  value: string
  label: string
  stageTypes: string[]
  requiredStandard?: string
}[] = [
  {
    value: 'FR.231',
    label: 'FR.231 — Stage 1 Audit Report',
    stageTypes: ['stage_1'],
  },
  {
    value: 'FR.231-1',
    label: 'FR.231-1 — MDQMS Report',
    stageTypes: ['stage_1'],
    requiredStandard: 'MDQMS',
  },
  {
    value: 'FR.232',
    label: 'FR.232 — Stage 2 / Surveillance / Recertification Report',
    stageTypes: ['stage_2', 'surveillance', 'recertification'],
  },
  {
    value: 'FR.232-1',
    label: 'FR.232-1 — MDQMS Stage 2 / Surveillance / Recertification Report',
    stageTypes: ['stage_2', 'surveillance', 'recertification'],
    requiredStandard: 'MDQMS',
  },
  {
    value: 'FR.229',
    label: 'FR.229 — ISMS/PIMS Audit Report (ISO 27001)',
    stageTypes: ['stage_1', 'stage_2', 'surveillance', 'recertification'],
  },
]

function reportFormOptionsForStage(stageType: string, standards: string[]) {
  return FORM_OPTS.filter(option => (
    option.stageTypes.includes(stageType)
    && (!option.requiredStandard || standards.includes(option.requiredStandard))
  ))
}

function AuditorReportsView({
  auditSetId,
  auditType,
  standards,
}: {
  auditSetId: string
  auditType: string | null
  standards: string[]
}) {
  const { manualActionDatesEnabled } = useManualActionDates()
  const [reports, setReports] = useState<{
    id: string; stage_type: string; report_form: string; label: string
    file_name: string | null; status: string
    la_signed_at: string | null; reviewer_signed_at: string | null
    can_review: boolean
    reviewer_auditor_id: string | null; reviewer_auditor_name: string | null
  }[]>([])
  const [loading, setLoading]   = useState(true)
  const [showUpload, setShowUpload] = useState(false)
  const [form, setForm]   = useState({ stage_type: 'stage_1', report_form: 'FR.231', label: '' })
  const [file, setFile]   = useState<File | null>(null)
  const [uploading, setUploading] = useState(false)
  const [uploadMsg, setUploadMsg] = useState('')
  const [reportDate, setReportDate] = useState(() => new Date().toISOString().slice(0, 10))
  const fileRef = useRef<HTMLInputElement>(null)

  // Reviewer direct-sign state (Portal 77)
  const [reviewSignDate, setReviewSignDate] = useState<Record<string, string>>({})
  const [reviewSigning,  setReviewSigning]  = useState<Record<string, boolean>>({})
  const [reviewErr,      setReviewErr]      = useState<Record<string, string>>({})
  const isSurveillance = isSurveillanceAudit(auditType)
  const stageOptions = isSurveillance
    ? [{ value: 'surveillance', label: 'Surveillance' }]
    : STAGE_OPTS_REPORTS
  const reportFormOptions = reportFormOptionsForStage(form.stage_type, standards)

  const STAGE_LABELS: Record<string, string> = {
    stage_1: 'Stage 1', stage_2: 'Stage 2',
    surveillance: 'Surveillance', recertification: 'Recertification',
  }
  const STATUS_CONFIG: Record<string, { label: string; chip: string }> = {
    pending_la:     { label: 'Signature Required',  chip: 'bg-amber-100 text-amber-700' },
    pending_review: { label: 'Awaiting CB Review',   chip: 'bg-blue-100 text-blue-700' },
    approved:       { label: 'Approved ✓',           chip: 'bg-green-100 text-green-700' },
  }

  async function load() {
    try {
      const r = await api.get(`/audit-sets/${auditSetId}/audit-reports`)
      setReports(r.data as typeof reports)
    } finally {
      setLoading(false)
    }
  }
  useEffect(() => { load() }, [auditSetId])
  useEffect(() => {
    if (isSurveillance) {
      setForm(f => ({
        ...f,
        stage_type: 'surveillance',
        report_form: ['FR.232', 'FR.232-1', 'FR.229'].includes(f.report_form)
          ? f.report_form
          : 'FR.232',
      }))
    }
  }, [isSurveillance])

  async function download(id: string, fileName: string | null) {
    const r = await api.get(`/audit-sets/${auditSetId}/audit-reports/${id}/download`, {
      responseType: 'blob',
    })
    const url = window.URL.createObjectURL(new Blob([r.data]))
    const a   = document.createElement('a')
    const contentType = String(r.headers?.['content-type'] ?? '')
    const ext = contentType.includes('pdf') ? '.pdf' : '.docx'
    const base = (fileName || 'report').replace(/\.(pdf|docx)$/i, '')
    a.href = url; a.download = `${base}${ext}`
    document.body.appendChild(a); a.click(); a.remove()
    window.URL.revokeObjectURL(url)
  }

  async function handleUpload(e: React.FormEvent) {
    e.preventDefault()
    if (!file || !form.label.trim()) return
    setUploading(true)
    setUploadMsg('')
    try {
      const stageType = isSurveillance ? 'surveillance' : form.stage_type
      const validOptions = reportFormOptionsForStage(stageType, standards)
      const reportForm = validOptions.some(option => option.value === form.report_form)
        ? form.report_form
        : validOptions[0].value
      const fd = new FormData()
      fd.append('stage_type', stageType)
      fd.append('report_form', reportForm)
      fd.append('label', form.label.trim())
      if (manualActionDatesEnabled) fd.append('report_date', reportDate)
      fd.append('file', file)
      const r = await api.post(`/audit-sets/${auditSetId}/audit-reports/upload`, fd, {
        headers: { 'Content-Type': 'multipart/form-data' },
      })
      setReports(prev => [...prev, r.data as typeof reports[0]])
      setForm({
        stage_type: isSurveillance ? 'surveillance' : 'stage_1',
        report_form: isSurveillance ? 'FR.232' : 'FR.231',
        label: '',
      })
      setFile(null)
      if (fileRef.current) fileRef.current.value = ''
      setShowUpload(false)
      setUploadMsg('')
    } catch (err: unknown) {
      const detail = (err as { response?: { data?: { detail?: string } } })?.response?.data?.detail
      setUploadMsg(detail || 'Upload failed')
    } finally {
      setUploading(false)
    }
  }

  async function handleReviewSign(id: string) {
    setReviewSigning(s => ({ ...s, [id]: true }))
    setReviewErr(e => ({ ...e, [id]: '' }))
    try {
      const signed_date = manualActionDatesEnabled
        ? (reviewSignDate[id] || new Date().toISOString().slice(0, 10))
        : undefined
      const r = await api.post(
        `/audit-sets/${auditSetId}/audit-reports/${id}/sign/review/direct`,
        { signed_date }
      )
      setReports(prev =>
        prev.map(rpt =>
          rpt.id === id ? { ...rpt, ...(r.data as object), can_review: false } : rpt
        )
      )
    } catch (err: unknown) {
      const detail = (err as { response?: { data?: { detail?: string } } })?.response?.data?.detail
      setReviewErr(e => ({ ...e, [id]: detail || 'Signing failed' }))
    } finally {
      setReviewSigning(s => ({ ...s, [id]: false }))
    }
  }

  if (loading) return <p className="text-sm text-gray-400">Loading…</p>

  const pending  = reports.filter(r => r.status === 'pending_la')
  const uploaded = reports.filter(r => r.status !== 'pending_la')

  return (
    <div className="space-y-5">
      <div className="flex justify-end">
        <button
          type="button"
          onClick={() => { setShowUpload(!showUpload); setUploadMsg('') }}
          className="rounded-lg border border-[#1A4731] px-3 py-1.5 text-xs font-medium text-[#1A4731] hover:bg-green-50"
        >
          {showUpload ? 'Cancel' : '+ Upload Report'}
        </button>
      </div>

      {showUpload && (
        <form
          onSubmit={handleUpload}
          className="space-y-3 rounded-xl border border-amber-200 bg-amber-50 p-4"
        >
          <div className="grid grid-cols-2 gap-3">
            <div>
              <label className="mb-1 block text-xs font-medium text-gray-600">Stage</label>
              <select
                value={form.stage_type}
                onChange={e => {
                  const stageType = e.target.value
                  const validOptions = reportFormOptionsForStage(stageType, standards)
                  setForm(f => {
                    const reportForm = validOptions.some(option => option.value === f.report_form)
                      ? f.report_form
                      : validOptions[0].value
                    return { ...f, stage_type: stageType, report_form: reportForm }
                  })
                }}
                className="w-full rounded-lg border bg-white px-3 py-2 text-sm"
              >
                {stageOptions.map(s => (
                  <option key={s.value} value={s.value}>{s.label}</option>
                ))}
              </select>
            </div>
            <div>
              <label className="mb-1 block text-xs font-medium text-gray-600">Report Form</label>
              <select
                value={form.report_form}
                onChange={e => setForm(f => ({ ...f, report_form: e.target.value }))}
                className="w-full rounded-lg border bg-white px-3 py-2 text-sm"
              >
                {reportFormOptions.map(o => (
                  <option key={o.value} value={o.value}>{o.label}</option>
                ))}
              </select>
            </div>
          </div>
          <div>
            <label className="mb-1 block text-xs font-medium text-gray-600">Label</label>
            <input
              required
              value={form.label}
              onChange={e => setForm(f => ({ ...f, label: e.target.value }))}
              placeholder={
                isSurveillance
                  ? 'e.g. Surveillance Audit Report — ACME Manufacturing'
                  : 'e.g. Stage 2 Audit Report — ACME Manufacturing'
              }
              className="w-full rounded-lg border bg-white px-3 py-2 text-sm"
            />
          </div>
          <div className="grid grid-cols-2 gap-3">
            <div>
              <label className="mb-1 block text-xs font-medium text-gray-600">File</label>
              <input
                ref={fileRef}
                required type="file"
                onChange={e => setFile(e.target.files?.[0] || null)}
                className="text-sm"
              />
            </div>
            {manualActionDatesEnabled && <div>
              <label className="mb-1 block text-xs font-medium text-gray-600">Report date</label>
              <input
                type="date"
                value={reportDate}
                onChange={(e) => setReportDate(e.target.value)}
                className="w-full rounded-lg border px-3 py-2 text-sm"
              />
            </div>}
          </div>
          <button
            type="submit"
            disabled={uploading || !file || !form.label.trim()}
            className="rounded-lg bg-[#1A4731] px-4 py-2 text-sm text-white disabled:opacity-40"
          >
            {uploading ? 'Uploading…' : 'Upload Report'}
          </button>
          {uploadMsg && <p className="text-xs text-red-600">{uploadMsg}</p>}
        </form>
      )}

      {pending.length > 0 && (
        <div>
          <p className="mb-2 text-xs font-semibold uppercase tracking-wide text-amber-600">
            Awaiting Your Signature
          </p>
          {pending.map(r => {
            const cfg = STATUS_CONFIG[r.status] ?? { label: r.status, chip: '' }
            return (
              <div key={r.id} className="rounded-xl border border-amber-200 bg-amber-50 p-4">
                <div className="flex items-center justify-between">
                  <div>
                    <p className="font-medium text-gray-800">{r.label}</p>
                    <p className="text-xs text-gray-400">
                      {STAGE_LABELS[r.stage_type] ?? r.stage_type} · {r.report_form}
                    </p>
                  </div>
                  <a
                    href={`/auditor/viewer/audit_report/${r.id}`}
                    className="inline-flex items-center rounded-lg bg-[#1A4731] px-3 py-1.5
                      text-xs font-medium text-white hover:bg-[#143828] transition-colors"
                  >
                    Open to Sign
                  </a>
                </div>
              </div>
            )
          })}
        </div>
      )}

      {uploaded.length > 0 && (
        <div>
          <p className="mb-2 text-xs font-semibold uppercase tracking-wide text-gray-400">
            Submitted
          </p>
          <div className="rounded-xl border bg-white divide-y divide-gray-50">
            {uploaded.map(r => {
              const cfg = STATUS_CONFIG[r.status] ?? { label: r.status, chip: 'bg-gray-100 text-gray-500' }
              return (
                <div key={r.id} className="px-4 py-3">
                  <div className="flex items-center justify-between">
                    <div>
                      <p className="text-sm font-medium text-gray-800">{r.label}</p>
                      <p className="text-xs text-gray-400">
                        {STAGE_LABELS[r.stage_type] ?? r.stage_type} · {r.report_form}
                      </p>
                    </div>
                    <div className="flex items-center gap-2">
                      <span className={`rounded-full px-2.5 py-0.5 text-xs font-semibold ${cfg.chip}`}>
                        {cfg.label}
                      </span>
                      <a
                        href={`/auditor/viewer/audit_report/${r.id}`}
                        className="inline-flex items-center rounded-lg border border-[#1A4731] px-2.5 py-1
                          text-xs font-medium text-[#1A4731] hover:bg-[#1A4731]/5 transition-colors"
                      >
                        Open
                      </a>
                      <button
                        type="button"
                        onClick={() => download(r.id, r.file_name)}
                        className="rounded-lg border border-[#1A4731] px-3 py-1.5 text-xs font-medium text-[#1A4731] hover:bg-green-50"
                      >
                        Download
                      </button>
                    </div>
                  </div>

                  {/* Portal 77 — Reviewer direct-sign panel */}
                  {r.can_review && r.status === 'pending_review' && (
                    <div className="mt-3 rounded-lg border border-blue-200 bg-blue-50 p-3">
                      <p className="mb-2 text-xs font-medium text-blue-800">
                        You are assigned as the reviewer for this report.
                      </p>
                      <div className="flex flex-wrap items-center gap-2">
                        {manualActionDatesEnabled && <input
                          type="date"
                          value={reviewSignDate[r.id] || new Date().toISOString().slice(0, 10)}
                          onChange={e => setReviewSignDate(d => ({ ...d, [r.id]: e.target.value }))}
                          className="rounded-lg border bg-white px-2 py-1.5 text-sm"
                        />}
                        <button
                          type="button"
                          disabled={reviewSigning[r.id]}
                          onClick={() => handleReviewSign(r.id)}
                          className="flex items-center gap-1.5 rounded-lg bg-[#1A4731] px-3 py-1.5 text-xs text-white disabled:opacity-40 hover:bg-[#143828]"
                        >
                          {reviewSigning[r.id] && <span className="animate-spin">⟳</span>}
                          {reviewSigning[r.id] ? 'Signing…' : 'Sign as Reviewer'}
                        </button>
                      </div>
                      {reviewErr[r.id] && (
                        <p className="mt-1 text-xs text-red-500">{reviewErr[r.id]}</p>
                      )}
                    </div>
                  )}
                </div>
              )
            })}
          </div>
        </div>
      )}

      {reports.length === 0 && !showUpload && (
        <p className="py-8 text-center text-sm text-gray-400">
          No reports uploaded yet. Click "+ Upload Report" to begin.
        </p>
      )}
    </div>
  )
}


// ── FR.218 Reviewer document view — Portal 51 ────────────────────────────────

function FR218ReviewerDocumentView({ auditSetId }: { auditSetId: string }) {
  const [doc, setDoc]     = useState<{ id: string; label: string; status: string } | null>(null)
  const [loading, setLoading] = useState(true)

  useEffect(() => {
    api.get(`/audit-sets/${auditSetId}/documents`)
      .then(r => {
        const fr218 = (r.data as { id: string; label: string; document_type: string; status: string }[])
          .find(d => d.document_type === 'fr218_review')
        setDoc(fr218 ?? null)
      })
      .finally(() => setLoading(false))
  }, [auditSetId])

  if (loading) return <p className="text-xs text-gray-400">Loading…</p>
  if (!doc)    return <p className="text-xs text-gray-400">FR.218 not yet uploaded by the CB.</p>

  return (
    <a
      href={`/auditor/viewer/shared_doc/${doc.id}`}
      className="inline-block rounded-lg bg-blue-700 px-3 py-1.5 text-xs font-medium text-white hover:bg-blue-800"
    >
      Open FR.218 to Review &amp; Sign
    </a>
  )
}


// ── Documents tab — Portal 49b ────────────────────────────────────────────────
// Shared documents visible to this auditor (backend filters by role; team_info
// FR.224 is own-only). Own pending FR.224 surfaces at the top with a sign prompt.

const SHARED_DOC_TYPE_LABELS: Record<string, string> = {
  team_info:     'FR.224 Team Info',
  audit_plan:    'FR.223 Audit Plan',
  meeting_form:  'FR.225 Meeting Form',
  nc_form:       'FR.230 NC Form',
  stage1_report: 'FR.231 Stage 1 Report',
  stage2_report: 'Stage 2 Audit Report',
  certificate:   'Certificate',
  audit_upload:  'Audit Upload',
}

function AuditorSharedDocsView({
  auditSetId,
  currentAuditorId,
}: {
  auditSetId: string
  currentAuditorId: string | null
}) {
  const [docs, setDocs] = useState<{
    id: string; label: string; document_type: string; status: string
    stage_type: string | null; assigned_auditor_id: string | null
    released_at: string | null; signed_at: string | null
  }[]>([])
  const [loading, setLoading] = useState(true)

  useEffect(() => {
    api.get(`/audit-sets/${auditSetId}/documents`)
      .then(r => setDocs(r.data as typeof docs))
      .finally(() => setLoading(false))
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [auditSetId])

  async function download(docId: string, label: string) {
    const r = await api.get(`/audit-sets/${auditSetId}/documents/${docId}/download`, {
      responseType: 'blob',
    })
    const url = window.URL.createObjectURL(new Blob([r.data as Blob]))
    const a   = document.createElement('a')
    const contentType = String(r.headers?.['content-type'] ?? '')
    const ext = contentType.includes('pdf') ? '.pdf' : '.docx'
    const base = (label || 'document').replace(/\.(pdf|docx)$/i, '')
    a.href = url; a.download = `${base}${ext}`
    document.body.appendChild(a); a.click(); a.remove()
    window.URL.revokeObjectURL(url)
  }

  if (loading) return <p className="py-8 text-center text-sm text-gray-400">Loading documents…</p>

  const myPendingFr224 = docs.filter(
    d => d.document_type === 'team_info'
      && d.status !== 'signed'
      && (!currentAuditorId || d.assigned_auditor_id === currentAuditorId),
  )
  const others = docs.filter(d => !myPendingFr224.some(p => p.id === d.id))

  return (
    <div className="space-y-5">
      {docs.length === 0 && (
        <p className="py-8 text-center text-sm text-gray-400">
          No documents shared with you yet.
        </p>
      )}

      {myPendingFr224.map(d => (
        <div key={d.id} className="rounded-xl border border-amber-200 bg-white p-5">
          <div className="flex items-center justify-between">
            <div>
              <p className="font-semibold text-gray-800">{d.label}</p>
              <p className="mt-0.5 text-xs text-gray-400">
                Your audit team information form
                {d.stage_type ? ` · ${d.stage_type.replace('_', ' ')}` : ''} — please review and sign.
              </p>
            </div>
            <a
              href={`/auditor/viewer/shared_doc/${d.id}`}
              className="rounded-lg bg-[#1A4731] px-4 py-2 text-sm font-medium text-white hover:bg-[#143828]"
            >
              Open to Sign
            </a>
          </div>
        </div>
      ))}

      {others.length > 0 && (
        <div className="rounded-xl border bg-white divide-y divide-gray-50">
          {others.map(d => (
            <div key={d.id} className="flex items-center justify-between px-4 py-3">
              <div>
                <p className="text-sm font-medium text-gray-800">{d.label}</p>
                <p className="mt-0.5 text-xs text-gray-400">
                  {SHARED_DOC_TYPE_LABELS[d.document_type] ?? d.document_type}
                  {d.stage_type ? ` · ${d.stage_type.replace('_', ' ')}` : ''}
                </p>
              </div>
              <div className="flex items-center gap-2">
                <span
                  className={`rounded-full px-2 py-0.5 text-xs font-semibold ${
                    d.status === 'signed'   ? 'bg-green-100 text-green-700'
                    : d.status === 'uploaded' ? 'bg-blue-100 text-blue-700'
                    : 'bg-amber-100 text-amber-700'
                  }`}
                >
                  {d.status === 'signed' ? '✓ Signed' : d.status === 'uploaded' ? 'Uploaded' : 'Pending'}
                </span>
                <a
                  href={`/auditor/viewer/shared_doc/${d.id}`}
                  className="rounded-lg border border-[#1A4731] px-2.5 py-1 text-xs font-medium text-[#1A4731] hover:bg-[#F0FAF4]"
                >
                  Open
                </a>
                <button
                  type="button"
                  onClick={() => download(d.id, d.label)}
                  className="rounded-lg border border-gray-300 px-2.5 py-1 text-xs text-gray-700 hover:bg-gray-50"
                >
                  Download
                </button>
              </div>
            </div>
          ))}
        </div>
      )}
    </div>
  )
}


export default function AuditorAuditDetail() {
  const { id } = useParams<{ id: string }>()
  const { manualActionDatesEnabled } = useManualActionDates()
  const [data, setData]   = useState<AssignmentDetail | null>(null)
  const [myAuditorId, setMyAuditorId] = useState<string | null>(null)
  const [tab, setTab]     = useState<Tab>('overview')
  const [downloading, setDownloading] = useState(false)
  const [uploading, setUploading]     = useState(false)
  const [uploadLabel, setUploadLabel] = useState('')
  const [uploadFile, setUploadFile]   = useState<File | null>(null)
  const [uploadMsg, setUploadMsg]     = useState('')
  const [uploadDate, setUploadDate]   = useState(() => new Date().toISOString().slice(0, 10))

  // Portal 55 — typed upload state for FR.223 (Audit Plan) and FR.225 (Meeting Form).
  const [auditPlanStage, setAuditPlanStage] = useState<UploadStageType>('stage_1')
  const [auditPlanFile, setAuditPlanFile]   = useState<File | null>(null)
  const [uploadingPlan, setUploadingPlan]   = useState(false)
  const [planMsg, setPlanMsg]               = useState('')

  const [meetingStage, setMeetingStage] = useState<UploadStageType>('stage_1')
  const [meetingFile, setMeetingFile]   = useState<File | null>(null)
  const [uploadingMeeting, setUploadingMeeting] = useState(false)
  const [meetingMsg, setMeetingMsg]     = useState('')

  useEffect(() => {
    api.get<AssignmentDetail>(`/auditor/my-assignments/${id}`)
      .then((r) => setData(r.data))
    api.get<{ auditor_id: string | null }>('/auth/me')
      .then(r => setMyAuditorId(r.data.auditor_id ?? null))
      .catch(() => {})
  }, [id])

  const isSurveillance = isSurveillanceAudit(data?.audit_type)
  const effectiveAuditPlanStage: UploadStageType = isSurveillance ? 'surveillance' : auditPlanStage
  const effectiveMeetingStage: UploadStageType = isSurveillance ? 'surveillance' : meetingStage

  useEffect(() => {
    if (isSurveillance) {
      setAuditPlanStage('surveillance')
      setMeetingStage('surveillance')
    } else {
      setAuditPlanStage(prev => prev === 'surveillance' ? 'stage_1' : prev)
      setMeetingStage(prev => prev === 'surveillance' ? 'stage_1' : prev)
    }
  }, [isSurveillance])

  async function handleDownload() {
    if (!data) return
    setDownloading(true)
    try {
      const res = await api.get(`/audit-sets/${id}/download`, { responseType: 'blob' })
      const blob = new Blob([res.data])
      const url  = window.URL.createObjectURL(blob)
      const a    = document.createElement('a')
      a.href     = url
      a.download = `${data.plan_number || 'audit-set'}.zip`
      document.body.appendChild(a)
      a.click()
      a.remove()
      window.URL.revokeObjectURL(url)
    } catch (e: unknown) {
      // eslint-disable-next-line @typescript-eslint/no-explicit-any
      const anyErr = e as any
      let detail = 'Download failed.'
      const body = anyErr?.response?.data
      if (body instanceof Blob) {
        try {
          const txt    = await body.text()
          const parsed = JSON.parse(txt)
          if (parsed?.detail) detail = String(parsed.detail)
        } catch { /* keep default */ }
      } else if (anyErr?.response?.data?.detail) {
        detail = String(anyErr.response.data.detail)
      } else if (anyErr?.message) {
        detail = String(anyErr.message)
      }
      alert(detail)
    } finally {
      setDownloading(false)
    }
  }

  async function handleUpload() {
    if (!uploadFile || !uploadLabel.trim()) return
    setUploading(true)
    setUploadMsg('')
    try {
      const form = new FormData()
      form.append('file', uploadFile)
      await api.post(
        `/audit-sets/${id}/documents/upload?label=${encodeURIComponent(uploadLabel)}`
          + (manualActionDatesEnabled ? `&upload_date=${uploadDate}` : ''),
        form,
        { headers: { 'Content-Type': 'multipart/form-data' } },
      )
      setUploadMsg('Document uploaded successfully.')
      setUploadFile(null)
      setUploadLabel('')
      setUploadDate(new Date().toISOString().slice(0, 10))
    } catch (e: unknown) {
      const detail = (e as { response?: { data?: { detail?: string } } })
        ?.response?.data?.detail
      setUploadMsg(detail || 'Upload failed')
    } finally {
      setUploading(false)
    }
  }

  // Portal 55 — typed FR.223 (Audit Plan) upload.
  async function handleAuditPlanUpload() {
    if (!auditPlanFile) return
    setUploadingPlan(true)
    setPlanMsg('')
    try {
      const form = new FormData()
      form.append('file', auditPlanFile)
      const stageType = effectiveAuditPlanStage
      const label = `FR.223 Audit Plan — ${uploadStageLabel(stageType)}`
      const qs = new URLSearchParams({
        label,
        document_type: 'audit_plan',
        stage_type: stageType,
        ...(manualActionDatesEnabled ? { upload_date: uploadDate } : {}),
      })
      await api.post(
        `/audit-sets/${id}/documents/upload?${qs.toString()}`,
        form,
        { headers: { 'Content-Type': 'multipart/form-data' } },
      )
      setPlanMsg('Audit Plan uploaded successfully.')
      setAuditPlanFile(null)
    } catch (e: unknown) {
      const detail = (e as { response?: { data?: { detail?: string } } })
        ?.response?.data?.detail
      setPlanMsg(detail || 'Upload failed')
    } finally {
      setUploadingPlan(false)
    }
  }

  // Portal 55 — typed FR.225 (Opening/Closing Meeting Form) upload.
  async function handleMeetingUpload() {
    if (!meetingFile) return
    setUploadingMeeting(true)
    setMeetingMsg('')
    try {
      const form = new FormData()
      form.append('file', meetingFile)
      const stageType = effectiveMeetingStage
      const label = `FR.225 Opening/Closing Meeting — ${uploadStageLabel(stageType)}`
      const qs = new URLSearchParams({
        label,
        document_type: 'meeting_form',
        stage_type: stageType,
        ...(manualActionDatesEnabled ? { upload_date: uploadDate } : {}),
      })
      await api.post(
        `/audit-sets/${id}/documents/upload?${qs.toString()}`,
        form,
        { headers: { 'Content-Type': 'multipart/form-data' } },
      )
      setMeetingMsg('Meeting Form uploaded successfully.')
      setMeetingFile(null)
    } catch (e: unknown) {
      const detail = (e as { response?: { data?: { detail?: string } } })
        ?.response?.data?.detail
      setMeetingMsg(detail || 'Upload failed')
    } finally {
      setUploadingMeeting(false)
    }
  }

  // Portal 60 — refresh the most recent FR.225 with the current employee
  // roster (run after the client registers/updates employees, before signing).
  async function handleMeetingRegenerate() {
    setUploadingMeeting(true)
    setMeetingMsg('')
    try {
      const qs = new URLSearchParams({ stage_type: effectiveMeetingStage })
      await api.post(`/audit-sets/${id}/meeting-form/regenerate?${qs.toString()}`)
      setMeetingMsg('Meeting Form regenerated with the current organisation roster.')
    } catch (e: unknown) {
      const detail = (e as { response?: { data?: { detail?: string } } })
        ?.response?.data?.detail
      setMeetingMsg(detail || 'Regeneration failed')
    } finally {
      setUploadingMeeting(false)
    }
  }

  if (!data) {
    return <div className="p-8 text-sm text-gray-400">Loading…</div>
  }

  return (
    <div className="mx-auto max-w-3xl p-6">
      {/* Header */}
      <div className="mb-6">
        <h1 className="text-xl font-bold text-gray-900">{data.company_name}</h1>
        <p className="mt-0.5 text-sm text-gray-400">{data.company_address}</p>
        <div className="mt-2 flex flex-wrap gap-2">
          {(data.standards || []).map((s) => (
            <span key={s} className="rounded bg-blue-50 px-2 py-0.5 text-xs text-blue-700">
              {STANDARD_NAMES[s] || s}
            </span>
          ))}
        </div>
      </div>

      {/* Tabs */}
      <div className="mb-6 flex w-fit gap-1 rounded-lg bg-gray-100 p-1">
        {(['overview', 'documents', 'messages', 'upload', 'nc_forms', 'declarations', 'reports'] as const).map((t) => (
          <button
            key={t}
            type="button"
            onClick={() => setTab(t)}
            className={`rounded-md px-4 py-1.5 text-sm font-medium capitalize transition-colors ${
              tab === t
                ? 'bg-white text-gray-900 shadow-sm'
                : 'text-gray-500 hover:text-gray-700'
            }`}
          >
            {t === 'documents' ? 'Documents'
              : t === 'upload' ? 'Upload Documents'
              : t === 'nc_forms' ? 'NC Management'
              : t === 'declarations' ? 'Declarations'
              : t === 'reports' ? 'Reports'
              : t}
          </button>
        ))}
      </div>

      {/* Overview tab */}
      {tab === 'overview' && (
        <div className="space-y-4">
          <div className="grid grid-cols-2 gap-4 rounded-xl border bg-white p-5 text-sm">
            <div>
              <p className="mb-1 text-xs uppercase tracking-wide text-gray-400">Contact</p>
              <p className="font-medium">{data.representative || '—'}</p>
              <p className="text-gray-500">{data.email}</p>
              <p className="text-gray-500">{data.phone}</p>
            </div>
            <div>
              <p className="mb-1 text-xs uppercase tracking-wide text-gray-400">Accreditation</p>
              <p className="font-medium">{data.accreditation_body || '—'}</p>
              <p className="text-gray-500">{data.audit_type?.replace('_', ' ')}</p>
            </div>
          </div>

          {data.scope_en && (
            <div className="rounded-xl border bg-white p-5">
              <p className="mb-2 text-xs uppercase tracking-wide text-gray-400">Scope</p>
              <p className="text-sm text-gray-700">{data.scope_en}</p>
            </div>
          )}

          {data.non_applicable_clauses && (
            <div className="rounded-xl border bg-white p-5">
              <p className="mb-2 text-xs uppercase tracking-wide text-gray-400">
                Non-Applicable Clauses
              </p>
              <p className="text-sm text-gray-700">{data.non_applicable_clauses}</p>
            </div>
          )}

          <div className="rounded-xl border bg-white p-5">
            <p className="mb-3 text-xs uppercase tracking-wide text-gray-400">Audit Stages</p>
            <div className="space-y-2">
              {(data.stages || []).map((s, i) => (
                <div key={i} className="flex items-center justify-between text-sm">
                  <span className="capitalize text-gray-700">
                    {s.stage_type?.replace('_', ' ')}
                  </span>
                  <span className="text-gray-500">
                    {s.audit_date_start
                      ? new Date(s.audit_date_start).toLocaleDateString('en-GB', {
                          day: 'numeric', month: 'short', year: 'numeric',
                        })
                      : 'TBD'}
                    {s.audit_date_end && s.audit_date_end !== s.audit_date_start
                      ? ` – ${new Date(s.audit_date_end).toLocaleDateString('en-GB', {
                          day: 'numeric', month: 'short',
                        })}`
                      : ''}
                  </span>
                </div>
              ))}
            </div>
          </div>

          <button
            type="button"
            onClick={handleDownload}
            disabled={downloading}
            className="block w-full rounded-xl bg-[#1A4731] py-3 text-center font-medium text-white transition-colors hover:bg-[#143828] disabled:opacity-40"
          >
            {downloading ? 'Preparing package…' : 'Download Audit Package'}
          </button>
        </div>
      )}

      {/* Documents tab — Portal 49b (shared docs incl. own FR.224) */}
      {tab === 'documents' && (
        <div className="space-y-4">
          {/* Portal 51 — FR.218 Application Review sign prompt (appointed reviewer only) */}
          {data.fr218_reviewer_id && myAuditorId && data.fr218_reviewer_id === myAuditorId && (
            <div className="rounded-xl border border-blue-200 bg-blue-50 p-4">
              <h3 className="mb-1 text-sm font-semibold text-blue-800">
                Application Review (FR.218) — Your Signature Required
              </h3>
              <p className="mb-3 text-xs text-blue-600">
                You are appointed as the Application Reviewer for this FSMS / ISMS audit.
                Please review and sign FR.218 after the Planning Officer has signed.
              </p>
              <FR218ReviewerDocumentView auditSetId={id} />
            </div>
          )}
          <AuditorSharedDocsView auditSetId={id} currentAuditorId={myAuditorId} />
        </div>
      )}

      {/* Messages tab */}
      {tab === 'messages' && (
        <div className="overflow-hidden rounded-xl border bg-white" style={{ height: 500 }}>
          <MessageThread
            fetchUrl={`/auditor/my-assignments/${id}/messages`}
            postUrl={`/auditor/my-assignments/${id}/messages`}
          />
        </div>
      )}

      {/* Upload tab — Portal 55: typed FR.223 / FR.225 sections + generic */}
      {tab === 'upload' && (
        <div className="space-y-4">
          {/* FR.223 — Audit Plan (per stage) */}
          <div className="rounded-xl border border-amber-200 bg-amber-50 p-5">
            <p className="mb-1 text-sm font-semibold text-amber-900">Audit Plan (FR.223)</p>
            <p className="mb-3 text-xs text-amber-800/80">
              {isSurveillance
                ? 'The Lead Auditor uploads the Surveillance Audit Plan. The organisation representative signs it via their portal once it is uploaded.'
                : 'The Lead Auditor uploads the Audit Plan for each stage. The organisation representative signs it via their portal once it is uploaded.'}
            </p>
            <div className="grid grid-cols-1 gap-2 sm:grid-cols-[140px_1fr_auto_auto] sm:items-center">
              {isSurveillance ? (
                <div className="rounded-lg border bg-white px-2 py-1.5 text-sm text-gray-700">
                  Surveillance
                </div>
              ) : (
                <select
                  value={auditPlanStage}
                  onChange={(e) => setAuditPlanStage(e.target.value as UploadStageType)}
                  className="rounded-lg border bg-white px-2 py-1.5 text-sm"
                >
                  <option value="stage_1">Stage 1</option>
                  <option value="stage_2">Stage 2</option>
                </select>
              )}
              <input
                type="file"
                accept=".pdf,.docx"
                onChange={(e) => setAuditPlanFile(e.target.files?.[0] ?? null)}
                className="text-sm"
              />
              {manualActionDatesEnabled && <input
                type="date"
                value={uploadDate}
                onChange={(e) => setUploadDate(e.target.value)}
                className="rounded-lg border px-2 py-1.5 text-sm"
                title="Document date (leave as today if correct)"
              />}
              <button
                type="button"
                onClick={handleAuditPlanUpload}
                disabled={!auditPlanFile || uploadingPlan}
                className="rounded-lg bg-[#1A4731] px-3 py-1.5 text-xs font-medium text-white disabled:opacity-40"
              >
                {uploadingPlan ? 'Uploading…' : 'Upload Audit Plan'}
              </button>
            </div>
            {planMsg && <p className="mt-2 text-xs text-amber-900">{planMsg}</p>}
          </div>

          {/* FR.225 — Opening / Closing Meeting Form (per stage) */}
          <div className="rounded-xl border border-amber-200 bg-amber-50 p-5">
            <p className="mb-1 text-sm font-semibold text-amber-900">
              Opening / Closing Meeting Form (FR.225)
            </p>
            <p className="mb-3 text-xs text-amber-800/80">
              Generated from the client's employee roster. The organisation
              representatives sign their respective slots once it is uploaded.
            </p>
            <div className="grid grid-cols-1 gap-2 sm:grid-cols-[140px_1fr_auto_auto] sm:items-center">
              {isSurveillance ? (
                <div className="rounded-lg border bg-white px-2 py-1.5 text-sm text-gray-700">
                  Surveillance
                </div>
              ) : (
                <select
                  value={meetingStage}
                  onChange={(e) => setMeetingStage(e.target.value as UploadStageType)}
                  className="rounded-lg border bg-white px-2 py-1.5 text-sm"
                >
                  <option value="stage_1">Stage 1</option>
                  <option value="stage_2">Stage 2</option>
                </select>
              )}
              <input
                type="file"
                accept=".pdf,.docx"
                onChange={(e) => setMeetingFile(e.target.files?.[0] ?? null)}
                className="text-sm"
              />
              {manualActionDatesEnabled && <input
                type="date"
                value={uploadDate}
                onChange={(e) => setUploadDate(e.target.value)}
                className="rounded-lg border px-2 py-1.5 text-sm"
                title="Document date (leave as today if correct)"
              />}
              <button
                type="button"
                onClick={handleMeetingUpload}
                disabled={!meetingFile || uploadingMeeting}
                className="rounded-lg bg-[#1A4731] px-3 py-1.5 text-xs font-medium text-white disabled:opacity-40"
              >
                {uploadingMeeting ? 'Uploading…' : 'Upload Meeting Form'}
              </button>
            </div>
            <div className="mt-2 flex items-center justify-between gap-3">
              <p className="text-[11px] text-amber-800/70">
                Already uploaded? Refresh the stored FR.225 with the current
                organisation roster (clears any prior signatures).
              </p>
              <button
                type="button"
                onClick={handleMeetingRegenerate}
                disabled={uploadingMeeting}
                className="rounded-lg border border-amber-300 bg-white px-3 py-1.5 text-xs font-medium text-amber-900 disabled:opacity-40"
              >
                ↻ Refresh attendees
              </button>
            </div>
            {meetingMsg && <p className="mt-2 text-xs text-amber-900">{meetingMsg}</p>}
          </div>

          {/* Generic upload — anything else (audit_upload bucket) */}
          <div className="space-y-4 rounded-xl border bg-white p-6">
            <p className="text-sm text-gray-600">
              Other documents — uploads here are filed as generic audit evidence.
              Use the FR.223 / FR.225 / NC Forms / Reports sections for typed deliverables.
            </p>
            <div>
              <label className="mb-1 block text-sm font-medium text-gray-700">
                Document Label
              </label>
              <input
                className="w-full rounded-lg border px-3 py-2 text-sm"
                placeholder={isSurveillance ? 'e.g. Surveillance evidence pack' : 'e.g. Stage 2 evidence pack'}
                value={uploadLabel}
                onChange={(e) => setUploadLabel(e.target.value)}
              />
            </div>
            {manualActionDatesEnabled && <div>
              <label className="mb-1 block text-sm font-medium text-gray-700">Upload date</label>
              <input
                type="date"
                value={uploadDate}
                onChange={(e) => setUploadDate(e.target.value)}
                className="w-full rounded-lg border px-3 py-2 text-sm"
              />
            </div>}
            <div>
              <label className="mb-1 block text-sm font-medium text-gray-700">File</label>
              <input
                type="file"
                onChange={(e) => setUploadFile(e.target.files?.[0] || null)}
                className="text-sm"
              />
            </div>
            <button
              type="button"
              onClick={handleUpload}
              disabled={!uploadFile || !uploadLabel.trim() || uploading}
              className="rounded-lg bg-[#1A4731] px-6 py-2.5 text-sm text-white disabled:opacity-40"
            >
              {uploading ? 'Uploading…' : 'Upload Document'}
            </button>
            {uploadMsg && <p className="text-sm text-gray-600">{uploadMsg}</p>}
          </div>
        </div>
      )}

      {/* NC Management tab — typed NC workflow + legacy FR.230 forms */}
      {tab === 'nc_forms' && (
        <div className="space-y-6">
          <AuditorNCManagementView
            auditSetId={id}
            stages={data.stages || []}
            currentAuditorId={myAuditorId}
          />
          <div className="rounded-xl border bg-white p-5">
            <p className="mb-3 text-xs font-semibold uppercase tracking-wide text-gray-400">
              Legacy FR.230 Files
            </p>
            <AuditorNCFormsView auditSetId={id} />
          </div>
        </div>
      )}

      {/* Declarations tab — Prompt 18 (FR.224 impartiality, each team member self-signs) */}
      {tab === 'declarations' && (
        <AuditorDeclarationsView auditSetId={id} currentAuditorId={myAuditorId} />
      )}

      {/* Reports tab — FR.231/FR.231-1/FR.229/FR.232/FR.232-1 two-party signing */}
      {tab === 'reports' && (
        <AuditorReportsView
          auditSetId={id}
          auditType={data.audit_type ?? null}
          standards={data.standards ?? []}
        />
      )}
    </div>
  )
}
