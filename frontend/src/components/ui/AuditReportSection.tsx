'use client'

import { useEffect, useState } from 'react'
import { ExternalLink } from 'lucide-react'
import api from '@/lib/api'

interface AuditReport {
  id:                    string
  stage_type:            string
  report_form:           string
  label:                 string
  file_name:             string | null
  status:                string
  la_signed_at:          string | null
  reviewer_signed_at:    string | null
  can_review:            boolean
  created_at:            string
  reviewer_auditor_id:   string | null
  reviewer_auditor_name: string | null
}

interface ReviewerCandidate {
  id:           string
  name:         string
  email:        string
  standards:    string[]
  covers_audit: boolean
}

const STAGE_LABELS: Record<string, string> = {
  stage_1: 'Stage 1', stage_2: 'Stage 2',
  surveillance: 'Surveillance', recertification: 'Recertification',
}

const STATUS_CONFIG: Record<string, { label: string; chip: string }> = {
  pending_la:     { label: 'Awaiting Lead Auditor', chip: 'bg-amber-100 text-amber-700' },
  pending_review: { label: 'Awaiting Reviewer',     chip: 'bg-blue-100 text-blue-700' },
  approved:       { label: 'Approved',              chip: 'bg-green-100 text-green-700' },
}

function fmtDate(iso: string | null) {
  if (!iso) return ''
  return new Date(iso).toLocaleDateString('en-GB', {
    day: 'numeric', month: 'short', year: 'numeric',
  })
}

export function AuditReportSection({
  auditSetId,
  workflowStatus,
  userRole,
}: {
  auditSetId: string
  workflowStatus: string | null
  userRole?: string
}) {
  const [reports, setReports]     = useState<AuditReport[]>([])
  const [loading, setLoading]     = useState(true)
  const [approving, setApproving] = useState<Record<string, boolean>>({})
  const [errors,    setErrors]    = useState<Record<string, string>>({})
  const [approveDates, setApproveDates] = useState<Record<string, string>>({})

  const canAssignReviewer = ['admin', 'planner', 'certification_manager', 'executive'].includes(userRole ?? '')

  // Reviewer assignment state
  const [assigningFor, setAssigningFor] = useState<string | null>(null)
  const [candidates,   setCandidates]   = useState<ReviewerCandidate[]>([])
  const [loadingCands, setLoadingCands] = useState(false)
  const [selectedCand, setSelectedCand] = useState('')
  const [assigning,    setAssigning]    = useState(false)
  const [assignErr,    setAssignErr]    = useState('')

  const relevantStatuses = new Set([
    'stage1_in_progress', 'stage1_complete',
    'stage2_scheduled', 'stage2_in_progress',
    'audit_in_progress', 'under_review', 'certified',
  ])

  useEffect(() => {
    if (!workflowStatus || !relevantStatuses.has(workflowStatus)) {
      setLoading(false)
      return
    }
    api.get<AuditReport[]>(`/audit-sets/${auditSetId}/audit-reports`)
      .then(r => setReports(r.data))
      .finally(() => setLoading(false))
  }, [auditSetId, workflowStatus])

  if (!workflowStatus || !relevantStatuses.has(workflowStatus)) return null

  async function download(id: string, fileName: string | null) {
    const r = await api.get(`/audit-sets/${auditSetId}/audit-reports/${id}/download`, {
      responseType: 'blob',
    })
    const url = window.URL.createObjectURL(new Blob([r.data]))
    const a   = document.createElement('a')
    a.href = url; a.download = fileName || 'report.docx'
    document.body.appendChild(a); a.click(); a.remove()
    window.URL.revokeObjectURL(url)
  }

  async function handleApprove(id: string) {
    setApproving(a => ({ ...a, [id]: true }))
    setErrors(e => ({ ...e, [id]: '' }))
    try {
      const signed_date = approveDates[id] || new Date().toISOString().slice(0, 10)
      const r = await api.post<AuditReport>(
        `/audit-sets/${auditSetId}/audit-reports/${id}/sign/review/direct`,
        { signed_date }
      )
      setReports(prev =>
        prev.map(rpt => (rpt.id === id ? { ...rpt, ...r.data, can_review: false } : rpt))
      )
    } catch (err: unknown) {
      const detail = (err as { response?: { data?: { detail?: string } } })?.response?.data?.detail
      setErrors(e => ({ ...e, [id]: detail || 'Approval failed' }))
    } finally {
      setApproving(a => ({ ...a, [id]: false }))
    }
  }

  async function openAssignPanel(reportId: string) {
    if (assigningFor === reportId) { setAssigningFor(null); return }
    setAssigningFor(reportId)
    setSelectedCand('')
    setAssignErr('')
    setLoadingCands(true)
    try {
      const r = await api.get<ReviewerCandidate[]>(
        `/audit-sets/${auditSetId}/audit-reports/reviewer-candidates`
      )
      setCandidates(r.data)
    } catch {
      setCandidates([])
    } finally {
      setLoadingCands(false)
    }
  }

  async function handleAssign(reportId: string) {
    if (!selectedCand) return
    setAssigning(true)
    setAssignErr('')
    try {
      const r = await api.put<AuditReport>(
        `/audit-sets/${auditSetId}/audit-reports/${reportId}/reviewer`,
        { auditor_id: selectedCand }
      )
      setReports(prev => prev.map(rpt => rpt.id === reportId ? { ...rpt, ...r.data } : rpt))
      setAssigningFor(null)
    } catch (err: unknown) {
      const detail = (err as { response?: { data?: { detail?: string } } })?.response?.data?.detail
      setAssignErr(detail || 'Assignment failed')
    } finally {
      setAssigning(false)
    }
  }

  return (
    <div className="mt-6">
      <h2 className="mb-3 text-sm font-semibold uppercase tracking-wide text-gray-700">
        Audit Reports (FR.231 / FR.229 / FR.232)
      </h2>

      {loading ? (
        <p className="text-xs text-gray-400">Loading…</p>
      ) : reports.length === 0 ? (
        <div className="rounded-xl border bg-white px-4 py-6 text-center text-xs text-gray-400">
          No reports uploaded yet. Lead Auditors upload from the Reports tab in their portal.
        </div>
      ) : (
        <div className="space-y-2">
          {reports.map(r => {
            const cfg = STATUS_CONFIG[r.status] ?? { label: r.status, chip: 'bg-gray-100 text-gray-500' }
            const isPanelOpen = assigningFor === r.id

            return (
              <div
                key={r.id}
                className={`rounded-xl border bg-white p-4 ${r.can_review && r.status === 'pending_review' ? 'border-blue-200' : ''}`}
              >
                {/* Header row */}
                <div className="mb-2 flex items-start justify-between gap-3">
                  <div className="min-w-0">
                    <p className="font-medium text-gray-800 truncate">{r.label}</p>
                    <p className="mt-0.5 text-xs text-gray-400">
                      {STAGE_LABELS[r.stage_type] ?? r.stage_type} · {r.report_form}
                      {r.la_signed_at && ` · LA signed ${fmtDate(r.la_signed_at)}`}
                      {r.reviewer_signed_at && ` · Reviewer approved ${fmtDate(r.reviewer_signed_at)}`}
                    </p>
                    {/* Reviewer assignment badge */}
                    <p className="mt-0.5 text-xs text-gray-500">
                      {r.reviewer_auditor_name
                        ? <>Reviewer: <span className="font-medium text-gray-700">{r.reviewer_auditor_name}</span></>
                        : <span className="text-amber-600">No reviewer assigned</span>
                      }
                    </p>
                  </div>
                  <div className="flex shrink-0 flex-wrap items-center gap-2">
                    <span className={`rounded-full px-2.5 py-0.5 text-xs font-semibold ${cfg.chip}`}>
                      {cfg.label}
                    </span>
                    <a
                      href={`/viewer/audit_report/${r.id}`}
                      className="flex items-center gap-1 text-xs text-[#1A4731] underline"
                    >
                      <ExternalLink size={11} />
                      View
                    </a>
                    <button type="button" onClick={() => download(r.id, r.file_name)}
                      className="text-xs text-[#1A4731] underline">
                      Download
                    </button>
                    {/* Assign Reviewer button — planner/admin only, before approval */}
                    {canAssignReviewer && r.status !== 'approved' && (
                      <button
                        type="button"
                        onClick={() => openAssignPanel(r.id)}
                        className={`rounded-lg border px-2.5 py-1 text-xs font-medium transition-colors ${
                          isPanelOpen
                            ? 'border-gray-400 bg-gray-100 text-gray-700'
                            : 'border-[#1A4731] text-[#1A4731] hover:bg-green-50'
                        }`}
                      >
                        {r.reviewer_auditor_name ? 'Change Reviewer' : 'Assign Reviewer'}
                      </button>
                    )}
                  </div>
                </div>

                {/* Assign reviewer panel */}
                {isPanelOpen && (
                  <div className="mt-3 rounded-lg border border-dashed border-gray-300 bg-gray-50 p-3">
                    <p className="mb-2 text-xs font-medium text-gray-600">
                      Select reviewer from eligible auditors:
                    </p>
                    {loadingCands ? (
                      <p className="text-xs text-gray-400">Loading candidates…</p>
                    ) : candidates.length === 0 ? (
                      <p className="text-xs text-red-500">
                        No eligible auditors found for this audit&apos;s standards.
                      </p>
                    ) : (
                      <div className="flex items-center gap-2">
                        <select
                          value={selectedCand}
                          onChange={e => setSelectedCand(e.target.value)}
                          className="flex-1 rounded-lg border bg-white px-2 py-1.5 text-sm"
                        >
                          <option value="">— choose auditor —</option>
                          {candidates.map(c => (
                            <option key={c.id} value={c.id}>{c.name}</option>
                          ))}
                        </select>
                        <button
                          type="button"
                          disabled={!selectedCand || assigning}
                          onClick={() => handleAssign(r.id)}
                          className="rounded-lg bg-[#1A4731] px-3 py-1.5 text-xs text-white disabled:opacity-40 hover:bg-[#143828]"
                        >
                          {assigning ? 'Saving…' : 'Assign'}
                        </button>
                        <button
                          type="button"
                          onClick={() => setAssigningFor(null)}
                          className="text-xs text-gray-400 hover:text-gray-600"
                        >
                          Cancel
                        </button>
                      </div>
                    )}
                    {assignErr && <p className="mt-1 text-xs text-red-500">{assignErr}</p>}
                  </div>
                )}

                {/* CM/reviewer direct-approve (only for CB staff with can_review) */}
                {r.can_review && r.status === 'pending_review' && (
                  <div className="mt-2 flex items-end gap-3">
                    <div>
                      <label className="block text-xs text-gray-500 mb-1">Approval date</label>
                      <input
                        type="date"
                        value={approveDates[r.id] || new Date().toISOString().slice(0, 10)}
                        onChange={e => setApproveDates(prev => ({ ...prev, [r.id]: e.target.value }))}
                        className="rounded-lg border px-2 py-1 text-sm"
                      />
                    </div>
                    <div>
                      <button
                        type="button"
                        onClick={() => handleApprove(r.id)}
                        disabled={approving[r.id]}
                        className="flex items-center gap-1.5 rounded-lg bg-[#1A4731] px-4 py-2 text-sm text-white disabled:opacity-40 hover:bg-[#143828]"
                      >
                        {approving[r.id] && <span className="animate-spin text-sm">⟳</span>}
                        {approving[r.id] ? 'Approving…' : 'Approve Report'}
                      </button>
                      {errors[r.id] && (
                        <p className="mt-1 text-xs text-red-500">{errors[r.id]}</p>
                      )}
                    </div>
                  </div>
                )}
                {r.status === 'approved' && (
                  <p className="mt-1 text-sm font-medium text-green-600">Report approved ✓</p>
                )}
              </div>
            )
          })}
        </div>
      )}
    </div>
  )
}
