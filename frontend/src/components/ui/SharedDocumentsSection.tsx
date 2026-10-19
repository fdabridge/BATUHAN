'use client'

import { useEffect, useRef, useState } from 'react'
import api from '@/lib/api'
import { useAuth } from '@/lib/auth'
import type { StageResponse } from '@/types'
import { useManualActionDates } from '@/lib/useManualActionDates'
import { isSurveillanceWorkflowAudit } from '@/lib/auditTypes'
import { activePlannerDocumentTypes } from '@/lib/workflowWorkspace'

interface SharedDoc {
  id: string
  label: string
  document_type: string
  direction: 'cb_to_client' | 'auditor_to_cb' | 'client_to_cb'
  status: 'pending_cb_signature' | 'released' | 'signed' | 'uploaded'
  stage_type: string | null
  assigned_auditor_id: string | null
  released_at: string | null
  signed_at: string | null
  signed_by: string | null
  cb_sig_status: 'pending' | 'signed' | null
  cb_sig_id: string | null
}

const FR218_FIRST_STATUS_ORDER = [
  'pending_review', 'in_planning', 'fr218_in_progress', 'fr218_complete',
  'quotation_sent', 'agreement_signed', 'audit_scheduled', 'audit_in_progress',
  'stage1_scheduled', 'stage1_in_progress', 'stage1_complete',
  'stage2_scheduled', 'stage2_in_progress', 'stage2_complete',
  'under_review', 'committee_review', 'certified',
]

function statusAtLeast(current: string | null, threshold: string): boolean {
  const currentIndex = FR218_FIRST_STATUS_ORDER.indexOf(current ?? '')
  const thresholdIndex = FR218_FIRST_STATUS_ORDER.indexOf(threshold)
  return currentIndex >= 0 && thresholdIndex >= 0 && currentIndex >= thresholdIndex
}

// DOC_TYPES is computed inside the component based on auditType — see below.

// Document types tagged to a specific stage when released.
const STAGE_SCOPED_TYPES = new Set(['team_info'])

const STAGE_LABELS: Record<string, string> = {
  stage_1:      'Stage 1',
  stage_2:      'Stage 2',
  surveillance: 'Surveillance',
}

interface TeamMember { id: string; name: string }

// Collect {id, name} of every assigned team member on a stage (lead + auditors + TEs).
function stageTeam(stage: StageResponse | undefined): TeamMember[] {
  if (!stage) return []
  const out: TeamMember[] = []
  const seen = new Set<string>()
  const push = (id?: unknown, name?: unknown) => {
    if (typeof id !== 'string' || !id || seen.has(id)) return
    seen.add(id)
    out.push({ id, name: typeof name === 'string' && name ? name : id })
  }
  push(stage.lead_auditor_id ?? undefined, stage.lead_auditor_name ?? undefined)
  for (const list of [stage.auditors, stage.technical_experts]) {
    for (const m of (list ?? [])) {
      if (m && typeof m === 'object') {
        const o = m as { id?: unknown; name?: unknown }
        push(o.id, o.name)
      }
    }
  }
  return out
}

function fmtDate(iso: string | null): string {
  if (!iso) return '—'
  return new Date(iso).toLocaleDateString('en-GB', {
    day: 'numeric', month: 'short', year: 'numeric',
  })
}

export function SharedDocumentsSection({
  auditSetId,
  stages = [],
  auditType = null,
  standards = [],
  workflowStatus = null,
  workflowVersion = 1,
  isTransfer = false,
  mode = 'combined',
  onDocumentReleased,
}: {
  auditSetId: string
  stages?: StageResponse[]
  auditType?: string | null
  standards?: string[]
  workflowStatus?: string | null
  workflowVersion?: number
  isTransfer?: boolean
  mode?: 'workspace' | 'records' | 'combined'
  onDocumentReleased?: () => void
}) {
  const isSurveillance = isSurveillanceWorkflowAudit(auditType)
  const transferSurveillance = isSurveillance && isTransfer
  const fr218First = workflowVersion >= 2 && (!isSurveillance || transferSurveillance)
  const commercialLocked = fr218First && !statusAtLeast(workflowStatus, 'fr218_complete')
  const agreementLocked = fr218First && !statusAtLeast(workflowStatus, 'quotation_sent')
  const [docs, setDocs] = useState<SharedDoc[]>([])
  const [loading, setLoading] = useState(true)

  // Complete catalogue. The active workspace applies a second, strict filter
  // so future-phase uploads are not presented before their workflow step.
  const ALL_DOC_TYPES = (() => {
    const transferTypes = isTransfer
      ? [{ value: 'transfer_review', label: 'Transfer Application Control (FR.250)' }]
      : []
    if (isSurveillance && !transferSurveillance) {
      return [
        ...transferTypes,
        { value: 'surveillance_notification', label: 'Surveillance Notification (FR.234)' },
        { value: 'team_info',                 label: 'Audit Team Info (FR.224)' },
        { value: 'review_decision',           label: 'Review & Decision (FR.233)' },
        { value: 'certificate',               label: 'Certificate' },
      ]
    }
    // Certification / recertification / transfer-surveillance flow.
    // A transfer surveillance deliberately uses FR.217 + the commercial
    // documents instead of the ordinary FR.234 notification path.
    if (fr218First) {
      return [
        ...transferTypes,
        { value: 'fr218_review',    label: 'Application Review (FR.218)' },
        { value: 'quotation',       label: commercialLocked ? 'Quotation (FR.220) — complete FR.218 first' : 'Quotation (FR.220)', disabled: commercialLocked },
        { value: 'agreement',       label: agreementLocked ? 'Contract (FR.221) — complete quotation first' : 'Contract (FR.221)', disabled: agreementLocked },
        { value: 'audit_programme', label: 'Audit Programme (FR.222)' },
        { value: 'team_info',       label: 'Audit Team Info (FR.224)' },
        { value: 'review_decision', label: 'Review & Decision (FR.233)' },
        { value: 'certificate',     label: 'Certificate' },
      ]
    }
    return [
      ...transferTypes,
      { value: 'quotation',       label: 'Quotation (FR.220)' },
      { value: 'agreement',       label: 'Agreement (FR.221)' },
      { value: 'fr218_review',    label: 'Application Review (FR.218)' },
      { value: 'audit_programme', label: 'Audit Programme (FR.222)' },
      // Portal 55 — FR.223 is uploaded by the Lead Auditor from their portal,
      // not released by the Planner. The Planner can still view it once uploaded.
      { value: 'team_info',       label: 'Audit Team Info (FR.224)' },
      { value: 'review_decision', label: 'Review & Decision (FR.233)' },
      { value: 'certificate',     label: 'Certificate' },
    ]
  })()

  const baseActiveTypeValues = activePlannerDocumentTypes({
    workflowStatus,
    auditType,
    workflowVersion,
    isTransfer,
  })
  const quotationSigned = docs.some((doc) => doc.document_type === 'quotation' && doc.status === 'signed')
  const activeTypeValues = baseActiveTypeValues.filter((value) => (
    workflowStatus !== 'quotation_sent' || value !== 'agreement' || quotationSigned
  ))
  const DOC_TYPES = ALL_DOC_TYPES.filter((type) => activeTypeValues.includes(type.value))

  const currentRecordTypes = (() => {
    if (workflowStatus === 'fr218_in_progress') return ['fr218_review']
    if (workflowStatus === 'fr218_complete') return ['fr218_review', ...activeTypeValues]
    if (workflowStatus === 'quotation_sent') return ['quotation', ...activeTypeValues]
    if (workflowStatus === 'agreement_signed') return ['agreement', ...activeTypeValues]
    if (workflowStatus === 'notification_sent') return ['surveillance_notification', ...activeTypeValues]
    if (workflowStatus === 'committee_review') return ['fr233', 'review_decision']
    if (workflowStatus === 'certified') return ['certificate']
    return activeTypeValues
  })()
  const displayedDocs = mode === 'workspace'
    ? docs.filter((doc) => currentRecordTypes.includes(doc.document_type))
    : docs

  function defaultDocumentType(): string {
    return DOC_TYPES[0]?.value ?? ''
  }

  function defaultDocumentLabel(type: string): string {
    return ALL_DOC_TYPES.find((item) => item.value === type)?.label.replace(/ — .+$/, '') ?? ''
  }

  const [showForm, setShowForm] = useState(mode === 'workspace' && DOC_TYPES.length > 0)
  const [showCertificateForm, setShowCertificateForm] = useState(false)
  const [label, setLabel]     = useState('')
  const [docType, setDocType] = useState(() => defaultDocumentType())
  const [stageType, setStageType] = useState('')
  const [auditorId, setAuditorId] = useState('')
  const [file, setFile]       = useState<File | null>(null)
  const [submitting, setSubmitting] = useState(false)
  const [error, setError]     = useState('')
  const [certificateError, setCertificateError] = useState('')
  const [certificateSubmitting, setCertificateSubmitting] = useState(false)
  const [releaseDate, setReleaseDate] = useState(() => new Date().toISOString().slice(0, 10))
  const [certificateIssueDate, setCertificateIssueDate] = useState(() => new Date().toISOString().slice(0, 10))
  const [certificateInitialDate, setCertificateInitialDate] = useState(() => new Date().toISOString().slice(0, 10))
  const [certificateRevision, setCertificateRevision] = useState('0')
  const [statementOfApplicability, setStatementOfApplicability] = useState('')
  const { manualActionDatesEnabled } = useManualActionDates()
  const fileRef = useRef<HTMLInputElement>(null)

  const { user }                           = useAuth()
  const [deletingId, setDeletingId]        = useState<string | null>(null)  // doc id pending confirm
  const [deleteError, setDeleteError]      = useState<string>('')
  const [deleteLoading, setDeleteLoading]  = useState(false)

  const canDelete = (
    user?.role === 'admin'
    || user?.role === 'planner'
    || user?.role === 'planner_us'
  )
  const hasCertificate = docs.some((doc) => doc.document_type === 'certificate')
  const certificateReady = docs.some((doc) =>
    ['fr233', 'review_decision'].includes(doc.document_type) && doc.status === 'signed'
  )

  async function deleteDoc(docId: string) {
    setDeleteError('')
    setDeleteLoading(true)
    try {
      const deletedDoc = docs.find((doc) => doc.id === docId)
      await api.delete(`/audit-sets/${auditSetId}/documents/${docId}`)
      setDeletingId(null)
      await load()
      if (deletedDoc?.document_type === 'fr233') {
        window.dispatchEvent(new CustomEvent('certiva:fr233-updated', {
          detail: { auditSetId },
        }))
      }
    } catch (err: unknown) {
      const detail = (err as { response?: { data?: { detail?: string } } })
        ?.response?.data?.detail
      setDeleteError(detail || 'Failed to delete document.')
    } finally {
      setDeleteLoading(false)
    }
  }

  const stageScoped   = STAGE_SCOPED_TYPES.has(docType)
  const selectedStage = stages.find((s) => s.stage_type === stageType)
  const teamOptions   = docType === 'team_info' ? stageTeam(selectedStage) : []

  async function load() {
    try {
      const r = await api.get<SharedDoc[]>(`/audit-sets/${auditSetId}/documents`)
      setDocs(r.data)
      if (r.data.some((doc) => doc.document_type === 'certificate')) {
        onDocumentReleased?.()
      }
    } catch {
      // A GET failure after a successful release must not surface as
      // "Failed to release document." — keep errors isolated.
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => { load() }, [auditSetId])

  useEffect(() => {
    const nextType = defaultDocumentType()
    setDocType(nextType)
    setLabel(defaultDocumentLabel(nextType))
    setStageType('')
    setAuditorId('')
    setShowForm(mode === 'workspace' && Boolean(nextType))
    setShowCertificateForm(false)
  // The primitive dependencies intentionally describe the current workflow phase.
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [workflowStatus, auditType, isTransfer, workflowVersion, mode, quotationSigned])

  async function release() {
    setError('')
    if (!label.trim()) { setError('Label is required.'); return }
    if (!file)         { setError('Please select a file to upload.'); return }
    if (stageScoped && !stageType) { setError('Please select a stage.'); return }
    if (docType === 'team_info' && !auditorId) {
      setError('FR.224 is per-auditor — please select the assigned auditor.'); return
    }
    const selectedType = DOC_TYPES.find((type) => type.value === docType)
    if (selectedType && 'disabled' in selectedType && selectedType.disabled) {
      setError('This document is locked until the preceding workflow stage is complete.'); return
    }
    setSubmitting(true)
    try {
      const fd = new FormData()
      fd.append('label', label.trim())
      fd.append('document_type', docType)
      if (manualActionDatesEnabled) fd.append('release_date', releaseDate)
      if (stageScoped && stageType) fd.append('stage_type', stageType)
      if (docType === 'team_info' && auditorId) fd.append('assigned_auditor_id', auditorId)
      fd.append('file', file)
      await api.post(`/audit-sets/${auditSetId}/documents/release`, fd, {
        headers: { 'Content-Type': 'multipart/form-data' },
      })
      const releasedFR233 = docType === 'review_decision'
      const nextType = defaultDocumentType()
      setLabel(defaultDocumentLabel(nextType)); setFile(null)
      setDocType(nextType)
      setStageType(''); setAuditorId('')
      setReleaseDate(new Date().toISOString().slice(0, 10))
      if (fileRef.current) fileRef.current.value = ''
      setShowForm(false)
      await load()
      onDocumentReleased?.()
      if (releasedFR233) {
        window.dispatchEvent(new CustomEvent('certiva:fr233-updated', {
          detail: { auditSetId },
        }))
      }
    } catch (err: unknown) {
      const detail = (err as { response?: { data?: { detail?: string } } })
        ?.response?.data?.detail
      setError(detail || 'Failed to release document.')
    } finally {
      setSubmitting(false)
    }
  }

  async function generateCertificate() {
    setCertificateError('')
    if (!certificateInitialDate) {
      setCertificateError('Initial certification date is required.'); return
    }
    if (manualActionDatesEnabled && !certificateIssueDate) {
      setCertificateError('Issue date is required.'); return
    }
    const includesIsms = standards.some((standard) => {
      const value = standard.toUpperCase()
      return value === 'ISMS' || value.includes('27001')
    })
    if (includesIsms && !statementOfApplicability.trim()) {
      setCertificateError('Statement of Applicability reference is required for ISO 27001.'); return
    }
    if (!window.confirm(
      'This will register one active certificate per standard in IAF CertSearch, place each official verification QR on the English certificate, and issue the final PDF. Continue?',
    )) return

    setCertificateSubmitting(true)
    try {
      await api.post(`/audit-sets/${auditSetId}/certificates/generate`, {
        issue_date: manualActionDatesEnabled ? certificateIssueDate : null,
        initial_date: certificateInitialDate,
        revision: certificateRevision.trim() || '0',
        statement_of_applicability: statementOfApplicability.trim() || null,
      })
      setShowCertificateForm(false)
      await load()
      onDocumentReleased?.()
    } catch (err: unknown) {
      const detail = (err as { response?: { data?: { detail?: string } } })
        ?.response?.data?.detail
      setCertificateError(detail || 'Failed to generate the certificate PDF.')
    } finally {
      setCertificateSubmitting(false)
    }
  }

  async function downloadDoc(docId: string, docLabel: string) {
    try {
      const r = await api.get(
        `/audit-sets/${auditSetId}/documents/${docId}/download`,
        { responseType: 'blob' },
      )
      const url = window.URL.createObjectURL(r.data as Blob)
      const a = document.createElement('a')
      a.href = url
      const contentType = String(r.headers?.['content-type'] ?? '')
      const ext = contentType.includes('pdf') ? '.pdf' : '.docx'
      const base = docLabel.replace(/\.(pdf|docx)$/i, '')
      a.download = `${base}${ext}`
      document.body.appendChild(a)
      a.click()
      a.remove()
      window.URL.revokeObjectURL(url)
    } catch {
      alert('Could not download document.')
    }
  }

  return (
    <div id="shared-documents" className="mt-8 scroll-mt-6">
      <div className="mb-3 flex items-center justify-between gap-3">
        <div>
          <h2 className="text-sm font-semibold text-certiva-ink">
            {mode === 'records' ? 'Document records' : 'Current document action'}
          </h2>
          <p className="mt-0.5 text-xs text-slate-500">
            {mode === 'records'
              ? 'Every released, uploaded, and signed file remains available here throughout the case.'
              : workflowStatus === 'quotation_sent' && !quotationSigned
                ? 'The quotation is awaiting signatures. The contract upload will appear automatically after it is fully signed.'
                : workflowStatus === 'fr218_in_progress'
                  ? 'FR.218 is awaiting its required signatures. No later document is available yet.'
                  : 'Only documents required by the current workflow phase can be uploaded here.'}
          </p>
        </div>
        {mode !== 'records' && <div className="flex items-center gap-2">
          {['under_review', 'committee_review', 'certified'].includes(workflowStatus ?? '') && (certificateReady || hasCertificate) && (
            <button
              type="button"
              disabled={hasCertificate}
              onClick={() => {
                setShowCertificateForm((value) => !value)
                setShowForm(false)
                setCertificateError('')
              }}
              className="rounded-full border border-certiva-green px-3 py-1.5 text-xs font-semibold text-certiva-green hover:bg-certiva-mist disabled:cursor-not-allowed disabled:border-gray-300 disabled:text-gray-400 disabled:hover:bg-transparent"
            >
              {hasCertificate
                ? 'Certificate issued'
                : showCertificateForm ? 'Cancel' : 'Issue certificate'}
            </button>
          )}
          {DOC_TYPES.length > 0 && <button
            type="button"
            onClick={() => { setShowForm((s) => !s); setShowCertificateForm(false) }}
            className="rounded-full border border-slate-300 bg-white px-3 py-1.5 text-xs font-semibold text-slate-600 hover:border-certiva-green/40 hover:text-certiva-green"
          >
            {showForm ? 'Close upload' : `Upload ${DOC_TYPES.length === 1 ? DOC_TYPES[0].label : 'required document'}`}
          </button>}
        </div>}
      </div>

      {mode !== 'records' && showCertificateForm && (
        <div className="mb-4 rounded-xl border border-emerald-200 bg-emerald-50/40 p-4">
          <p className="text-sm font-medium text-gray-800">Generate final certificate</p>
          <p className="mt-1 text-xs text-gray-500">
            Each selected standard will be registered in IAF CertSearch first. One English certificate page with its official IAF verification QR will then be generated and combined into the final PDF.
          </p>
          <p className="mt-2 text-xs font-medium text-emerald-800">
            Standards: {standards.length > 0 ? standards.join(', ') : 'None selected'}
          </p>
          <div className="mt-3 grid grid-cols-1 gap-3 md:grid-cols-2">
            <div>
              <label className="block text-xs font-medium text-gray-500">Initial certification date</label>
              <input
                type="date"
                value={certificateInitialDate}
                onChange={(e) => setCertificateInitialDate(e.target.value)}
                className="mt-1 w-full rounded-lg border bg-white px-3 py-1.5 text-sm focus:outline-none focus:ring-2 focus:ring-[#1A4731]/30"
              />
            </div>
            {manualActionDatesEnabled ? (
              <div>
                <label className="block text-xs font-medium text-gray-500">Issue date</label>
                <input
                  type="date"
                  value={certificateIssueDate}
                  onChange={(e) => setCertificateIssueDate(e.target.value)}
                  className="mt-1 w-full rounded-lg border bg-white px-3 py-1.5 text-sm focus:outline-none focus:ring-2 focus:ring-[#1A4731]/30"
                />
              </div>
            ) : (
              <div className="rounded-lg border border-gray-200 bg-white px-3 py-2 text-xs text-gray-500">
                Issue date will use the current server date under the active date policy.
              </div>
            )}
            <div>
              <label className="block text-xs font-medium text-gray-500">Revision</label>
              <input
                value={certificateRevision}
                onChange={(e) => setCertificateRevision(e.target.value)}
                maxLength={30}
                className="mt-1 w-full rounded-lg border bg-white px-3 py-1.5 text-sm focus:outline-none focus:ring-2 focus:ring-[#1A4731]/30"
              />
            </div>
            {standards.some((standard) => standard.toUpperCase() === 'ISMS' || standard.includes('27001')) && (
              <div>
                <label className="block text-xs font-medium text-gray-500">Statement of Applicability / SoA</label>
                <input
                  value={statementOfApplicability}
                  onChange={(e) => setStatementOfApplicability(e.target.value)}
                  placeholder="e.g. 01.01.2026 / Rev.0"
                  className="mt-1 w-full rounded-lg border bg-white px-3 py-1.5 text-sm focus:outline-none focus:ring-2 focus:ring-[#1A4731]/30"
                />
              </div>
            )}
          </div>
          {certificateError && <p className="mt-2 text-xs text-red-600">{certificateError}</p>}
          <button
            type="button"
            onClick={generateCertificate}
            disabled={certificateSubmitting || standards.length === 0}
            className="mt-3 rounded-lg bg-[#1A4731] px-4 py-1.5 text-sm font-medium text-white disabled:opacity-40"
          >
            {certificateSubmitting ? 'Registering with IAF and generating…' : 'Register with IAF and issue PDF'}
          </button>
        </div>
      )}

      {mode !== 'records' && showForm && DOC_TYPES.length > 0 && (
        <div className="mb-4 rounded-xl border bg-white p-4">
          <div className="mb-3 rounded-lg border border-slate-200 bg-slate-50 px-3 py-2 text-xs leading-5 text-slate-600">
            This upload is limited to the document required by the current workflow phase. Backend gates remain active as a final safety check.
          </div>
          <div className="grid grid-cols-1 gap-3 md:grid-cols-2">
            <div>
              <label className="block text-xs font-medium text-gray-500">Label</label>
              <input
                value={label}
                onChange={(e) => setLabel(e.target.value)}
                placeholder="Quotation (FR.220)"
                className="mt-1 w-full rounded-lg border px-3 py-1.5 text-sm focus:outline-none focus:ring-2 focus:ring-[#1A4731]/30"
              />
            </div>
            {DOC_TYPES.length > 1 && <div>
              <label className="block text-xs font-medium text-gray-500">Type</label>
              <select
                value={docType}
                onChange={(e) => {
                  setDocType(e.target.value)
                  setLabel(defaultDocumentLabel(e.target.value))
                  setStageType('')
                  setAuditorId('')
                }}
                className="mt-1 w-full rounded-lg border px-3 py-1.5 text-sm focus:outline-none focus:ring-2 focus:ring-[#1A4731]/30"
              >
                {DOC_TYPES.map((t) => (
                  <option
                    key={t.value}
                    value={t.value}
                    disabled={'disabled' in t && Boolean(t.disabled)}
                  >
                    {t.label}
                  </option>
                ))}
              </select>
            </div>}
            {stageScoped && (
              <div>
                <label className="block text-xs font-medium text-gray-500">Stage</label>
                <select
                  value={stageType}
                  onChange={(e) => { setStageType(e.target.value); setAuditorId('') }}
                  className="mt-1 w-full rounded-lg border px-3 py-1.5 text-sm focus:outline-none focus:ring-2 focus:ring-[#1A4731]/30"
                >
                  <option value="">— Select stage —</option>
                  {(stages.length > 0
                    ? stages.map((s) => s.stage_type)
                    : ['stage_1', 'stage_2']
                  ).map((st) => (
                    <option key={st} value={st}>{STAGE_LABELS[st] ?? st}</option>
                  ))}
                </select>
              </div>
            )}
            {docType === 'team_info' && (
              <div>
                <label className="block text-xs font-medium text-gray-500">Assigned auditor</label>
                <select
                  value={auditorId}
                  onChange={(e) => setAuditorId(e.target.value)}
                  className="mt-1 w-full rounded-lg border px-3 py-1.5 text-sm focus:outline-none focus:ring-2 focus:ring-[#1A4731]/30"
                >
                  <option value="">— Select auditor —</option>
                  {teamOptions.map((m) => (
                    <option key={m.id} value={m.id}>{m.name}</option>
                  ))}
                </select>
                {stageType && teamOptions.length === 0 && (
                  <p className="mt-1 text-[11px] text-amber-600">
                    No auditors assigned to this stage yet — assign the audit team first.
                  </p>
                )}
              </div>
            )}
            {manualActionDatesEnabled && <div>
              <label className="block text-xs font-medium text-gray-500">Release date</label>
              <input
                type="date"
                value={releaseDate}
                onChange={(e) => setReleaseDate(e.target.value)}
                className="mt-1 w-full rounded-lg border px-3 py-1.5 text-sm focus:outline-none focus:ring-2 focus:ring-[#1A4731]/30"
              />
            </div>}
            <div>
              <label className="block text-xs font-medium text-gray-500">File</label>
              <input
                ref={fileRef}
                type="file"
                accept=".docx,.pdf"
                onChange={(e) => setFile(e.target.files?.[0] ?? null)}
                className="mt-1 w-full rounded-lg border px-3 py-1.5 text-sm text-gray-700 file:mr-2 file:rounded file:border-0 file:bg-gray-100 file:px-2 file:py-0.5 file:text-xs focus:outline-none"
              />
            </div>
          </div>
          {error && <p className="mt-2 text-xs text-red-500">{error}</p>}
          <button
            type="button"
            onClick={release}
            disabled={submitting}
            className="mt-3 rounded-lg bg-[#1A4731] px-4 py-1.5 text-sm font-medium text-white disabled:opacity-40"
          >
            {submitting ? 'Uploading…' : 'Release to Client'}
          </button>
        </div>
      )}

      {(mode !== 'workspace' || displayedDocs.length > 0 || loading) && <div className="rounded-xl border bg-white">
        {loading ? (
          <p className="p-6 text-sm text-gray-400">Loading…</p>
        ) : displayedDocs.length === 0 ? (
          <p className="p-6 text-sm text-gray-400">No documents released yet.</p>
        ) : (
          <>
          <ul className="divide-y">
            {displayedDocs.map((d) => (
              <li key={d.id} className="flex items-center justify-between px-4 py-3">
                <div>
                  <p className="text-sm font-medium text-gray-800">{d.label}</p>
                  <p className="mt-0.5 text-xs text-gray-400">
                    {d.direction === 'auditor_to_cb' ? 'Auditor upload'
                      : d.direction === 'client_to_cb' ? 'Client upload'
                      : 'Released'}
                    {' · '}{fmtDate(d.released_at)}
                    {d.stage_type && ` · ${STAGE_LABELS[d.stage_type] ?? d.stage_type}`}
                    {d.signed_at && ` · Signed ${fmtDate(d.signed_at)}`}
                  </p>
                </div>
                <div className="flex items-center gap-2">
                  {d.cb_sig_status && (
                    <span className={`rounded-full px-2 py-0.5 text-xs font-semibold ${
                      d.cb_sig_status === 'signed'
                        ? 'bg-blue-100 text-blue-700'
                        : 'bg-amber-100 text-amber-800'
                    }`}>
                      {d.cb_sig_status === 'signed' ? 'CB ✓' : 'CB Signing…'}
                    </span>
                  )}
                  <span
                    className={`rounded-full px-2 py-0.5 text-xs font-semibold ${
                      d.status === 'signed'                 ? 'bg-green-100 text-green-700'
                      : d.status === 'uploaded'             ? 'bg-blue-100 text-blue-700'
                      : d.status === 'pending_cb_signature' ? 'bg-gray-100 text-gray-500'
                      : 'bg-amber-100 text-amber-700'
                    }`}
                  >
                    {d.document_type === 'certificate'
                      ? 'Issued'
                      : d.status === 'signed'
                      ? '✓ Signed'
                      : d.status === 'uploaded'
                      ? 'Uploaded'
                      : d.status === 'pending_cb_signature'
                      ? 'Pending release'
                      : 'Awaiting Signature'}
                  </span>
                  {d.document_type !== 'certificate' && (
                    <a
                      href={`/viewer/shared_doc/${d.id}`}
                      className="rounded-lg border border-[#1A4731] px-2.5 py-1 text-xs
                        font-medium text-[#1A4731] hover:bg-[#F0FAF4]"
                    >
                      Open
                    </a>
                  )}
                  <button
                    type="button"
                    onClick={() => downloadDoc(d.id, d.label)}
                    className="rounded-lg border border-gray-300 px-2.5 py-1 text-xs text-gray-700 hover:bg-gray-50"
                  >
                    Download
                  </button>
                  {canDelete && (
                    deletingId === d.id ? (
                      <span className="flex items-center gap-1">
                        <span className="text-xs text-gray-500">Delete?</span>
                        <button
                          type="button"
                          disabled={deleteLoading}
                          onClick={() => deleteDoc(d.id)}
                          className="rounded px-2 py-0.5 text-xs font-medium text-white disabled:opacity-50"
                          style={{ background: '#DC2626' }}
                        >
                          {deleteLoading ? '…' : 'Yes'}
                        </button>
                        <button
                          type="button"
                          onClick={() => { setDeletingId(null); setDeleteError('') }}
                          className="rounded border border-gray-300 px-2 py-0.5 text-xs text-gray-600 hover:bg-gray-50"
                        >
                          No
                        </button>
                      </span>
                    ) : (
                      <button
                        type="button"
                        onClick={() => { setDeletingId(d.id); setDeleteError('') }}
                        className="rounded-lg border border-red-200 px-2.5 py-1 text-xs text-red-600 hover:bg-red-50"
                      >
                        Delete
                      </button>
                    )
                  )}
                </div>
              </li>
            ))}
          </ul>
            {deleteError && (
              <p className="px-4 py-2 text-xs text-red-600 border-t border-red-100 bg-red-50">
                {deleteError}
              </p>
            )}
          </>
        )}
      </div>}
    </div>
  )
}
