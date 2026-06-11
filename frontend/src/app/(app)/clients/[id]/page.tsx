'use client'

import { useState, useEffect, useRef } from 'react'
import Link from 'next/link'
import { useRouter } from 'next/navigation'
import { ArrowLeft, ChevronDown, ChevronRight, Download, Loader2, Pencil, Check, Sparkles, Trash2 } from 'lucide-react'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import api from '@/lib/api'
import { useAuth } from '@/lib/auth'
import { CertBadge } from '@/components/ui/CertBadge'
import { MessageThread } from '@/components/ui/MessageThread'
import { SharedDocumentsSection } from '@/components/ui/SharedDocumentsSection'
import { InternalApprovalsSection } from '@/components/ui/InternalApprovalsSection'
import { CommitteeSection } from '@/components/ui/CommitteeSection'
import { MeetingAttendeesSection } from '@/components/ui/MeetingAttendeesSection'
import { AssessmentManagementSection } from '@/components/ui/AssessmentManagementSection'
import { NCFormManagementSection } from '@/components/ui/NCFormManagementSection'
import { DeclarationManagementSection } from '@/components/ui/DeclarationManagementSection'
import { AuditReportSection } from '@/components/ui/AuditReportSection'
import { WorkflowStatusBar } from '@/components/ui/WorkflowStatusBar'
import type { AuditSetResponse, StageResponse, ManDayResult, AuditorSummary, AuditorAvailabilityItem, RequiredScope } from '@/types'

// ── Helpers ───────────────────────────────────────────────────────────────────

function formatDate(iso: string | null | undefined): string {
  if (!iso) return '—'
  const [y, m, d] = iso.split('-')
  return `${d}/${m}/${y}`
}

function auditTypeLabel(t: string): string {
  if (t === 'initial')         return 'Initial certification'
  if (t === 'surveillance')    return 'Surveillance'
  if (t === 'recertification') return 'Recertification'
  return t
}

// ── Standard code resolver ────────────────────────────────────────────────────

const ISO_LABEL_MAP: Record<string, string> = {
  'QMS':        'ISO 9001',
  'EMS':        'ISO 14001',
  'OHSMS':      'ISO 45001',
  'FSMS':       'ISO 22000',
  'FSSC 22000': 'FSSC 22000',
  'ISMS':       'ISO 27001',
  'EnMS':       'ISO 50001',
  'ABMS':       'ISO 37001',
  'MDMS':       'ISO 13485',
  'CMS':        'ISO 37301',
}

function resolveStandards(raw: string[]): string[] {
  return raw.map((s) => ISO_LABEL_MAP[s] ?? s)
}

// ── Local stage-edit state ────────────────────────────────────────────────────

interface TeamMember { id: string; name: string; ea_code?: string }

interface NACSuggestion {
  clause: string
  standard: string
  title: string
  justification: string
  confidence?: 'high' | 'medium' | 'low' | string
}

interface NACGenerationResponse {
  non_applicable_clauses: string
  suggestions: NACSuggestion[]
}

interface StageEdit {
  lead_auditor_id:   string
  lead_auditor_name: string
  audit_date_start:  string
  audit_date_end:    string
  auditors:          TeamMember[]
  technical_experts: TeamMember[]
}

function parseTeamMembers(arr: unknown[] | null | undefined): TeamMember[] {
  if (!arr || !arr.length) return []
  return (arr as { id?: string; name?: string; ea_code?: string }[])
    .filter((a) => a.name)
    .map((a) => ({ id: a.id ?? '', name: a.name!, ea_code: a.ea_code ?? '' }))
}

function buildStageEdit(s: StageResponse): StageEdit {
  return {
    lead_auditor_id:   '',
    lead_auditor_name: s.lead_auditor_name ?? '',
    audit_date_start:  s.audit_date_start  ?? '',
    audit_date_end:    s.audit_date_end    ?? '',
    auditors:          parseTeamMembers(s.auditors as unknown[]),
    technical_experts: parseTeamMembers(s.technical_experts as unknown[]),
  }
}

// ── Shared styles ─────────────────────────────────────────────────────────────

const inputCls = 'w-full rounded-lg border border-gray-200 px-3 py-2 text-sm text-gray-800 placeholder-gray-400 outline-none focus:border-certiva-primary focus:ring-2 focus:ring-certiva-primary/20'
const lblCls   = 'mb-1 block text-xs font-medium text-gray-500'

// ── Man-day helpers ───────────────────────────────────────────────────────────

function recommendedDays(
  stageType: string,
  manDayResult: ManDayResult | null,
  auditType: string | null,
): number | null {
  if (!manDayResult) return null
  const t = (auditType ?? '').toLowerCase()
  if (t === 'initial') {
    if (stageType === 'stage_1') return manDayResult.final_ph1 ?? null
    if (stageType === 'stage_2') return manDayResult.final_ph2 ?? null
  }
  if (t === 'surveillance' || t === 'surveillance_1' || t === 'surveillance_2') {
    return manDayResult.final_surv1 ?? null
  }
  if (t === 'recertification') {
    if (stageType === 'stage_1') return manDayResult.final_recert_ph1 ?? null
    if (stageType === 'stage_2') return manDayResult.final_recert_ph2 ?? null
    return manDayResult.final_recert ?? null
  }
  return null
}

/** Given a start date (YYYY-MM-DD) and a number of working days, return the end date. */
function suggestEndDate(startISO: string, workDays: number): string {
  const d = new Date(startISO)
  let remaining = Math.max(1, Math.round(workDays))
  // day 1 is the start date itself if it's a weekday
  if (d.getDay() !== 0 && d.getDay() !== 6) remaining--
  while (remaining > 0) {
    d.setDate(d.getDate() + 1)
    if (d.getDay() !== 0 && d.getDay() !== 6) remaining--
  }
  return d.toISOString().slice(0, 10)
}

/**
 * Returns an error message if stage ordering is violated.
 * Stage 2 start must be after Stage 1 end (if both are set).
 */
function validateStageOrder(
  currentStage: StageResponse,
  allStages: StageResponse[],
  startDate: string,
  endDate: string,
): string | null {
  if (currentStage.stage_type === 'stage_2' && startDate) {
    const stage1 = allStages.find((s) => s.stage_type === 'stage_1')
    if (stage1?.audit_date_end && startDate <= stage1.audit_date_end) {
      return `Stage 2 must start after Stage 1 ends (${formatDate(stage1.audit_date_end)}).`
    }
  }
  if (currentStage.stage_type === 'stage_1' && endDate) {
    const stage2 = allStages.find((s) => s.stage_type === 'stage_2')
    if (stage2?.audit_date_start && endDate >= stage2.audit_date_start) {
      return `Stage 1 must end before Stage 2 starts (${formatDate(stage2.audit_date_start)}).`
    }
  }
  return null
}

function workingDaysBetween(start: string, end: string): number {
  const s = new Date(start)
  const e = new Date(end)
  let count = 0
  const d = new Date(s)
  while (d <= e) {
    const day = d.getDay()
    if (day !== 0 && day !== 6) count++
    d.setDate(d.getDate() + 1)
  }
  return count
}

// ── Coverage check helpers ────────────────────────────────────────────────────

const EA_CODE_STANDARDS = ['9001', '14001', '45001', '27001']
const CATEGORY_STANDARDS = ['22000', 'fssc', '13485', '50001', '37001', '37301']

function standardUsesCodes(std: string): 'ea' | 'category' | 'unknown' {
  const n = std.toLowerCase().replace('iso ', '').replace(/\s/g, '')
  if (EA_CODE_STANDARDS.some((s) => n.includes(s))) return 'ea'
  if (CATEGORY_STANDARDS.some((s) => n.includes(s))) return 'category'
  return 'unknown'
}

interface CoverageResult {
  standard: string
  covered: boolean
  coveredBy: string | null
  reason: string | null
  // Per-code detail (populated when requiredScope is available)
  codeResults?: { code: string; coveredBy: string | null }[]
}

function computeCoverage(
  requiredStandards: string[],
  clientEACode: string | null,
  teamMembers: TeamMember[],
  allAuditors: AuditorAvailabilityItem[],
  requiredScope?: RequiredScope | null,
): CoverageResult[] {
  const teamAuditors = allAuditors.filter(
    (a) => teamMembers.some((m) => (m.id ? m.id === a.id : m.name === a.name))
  )

  return requiredStandards.map((std) => {
    const stdNorm = std.toLowerCase().replace('iso ', '').replace(/\s/g, '')
    const scopeType = standardUsesCodes(std)
    const rsEntry = requiredScope?.[std]

    // ── Per-code check when requiredScope is available ──────────────────────
    if (rsEntry && rsEntry.codes.length > 0) {
      const codeResults = rsEntry.codes.map((code) => {
        const coveredBy = teamAuditors.find((a) => {
          const cs = a.covered_scope?.[std]
          return cs && cs.includes(code)
        })?.name ?? null
        return { code, coveredBy }
      })
      const allCodesCovered = codeResults.every((r) => r.coveredBy !== null)
      const firstCover = codeResults.find((r) => r.coveredBy)
      return {
        standard: std,
        covered: allCodesCovered,
        coveredBy: firstCover?.coveredBy ?? null,
        reason: allCodesCovered ? null : `missing codes: ${codeResults.filter((r) => !r.coveredBy).map((r) => r.code).join(', ')}`,
        codeResults,
      }
    }

    // ── Fallback: per-standard check ────────────────────────────────────────
    const cover = teamAuditors.find((a) => {
      const qual = a.standard_qualifications.find((q) => {
        const qNorm = q.standard_code.toLowerCase().replace('iso ', '').replace(/\s/g, '')
        return qNorm === stdNorm || qNorm.startsWith(stdNorm) || stdNorm.startsWith(qNorm)
      })
      if (!qual) return false
      if (scopeType === 'ea') {
        if (!clientEACode) return true
        const qualEA = qual.ea_codes
        if (!qualEA || qualEA.length === 0) return true
        const clientNum = clientEACode.replace(/[^0-9]/g, '')
        return qualEA.some((c) => c.replace(/[^0-9]/g, '') === clientNum)
      }
      return true
    })

    let reason: string | null = null
    if (!cover) {
      reason = scopeType === 'ea' && clientEACode
        ? `needs qualification + ${clientEACode}`
        : 'no qualified team member'
    }

    return {
      standard: std,
      covered: !!cover,
      coveredBy: cover?.name ?? null,
      reason,
    }
  })
}

function LabeledField({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div>
      <p className="mb-0.5 font-medium uppercase tracking-wide text-gray-400" style={{ fontSize: 11 }}>{label}</p>
      <div className="text-sm text-gray-800">{children}</div>
    </div>
  )
}

// ── Scope type badge colors ───────────────────────────────────────────────────

function scopeBadgeStyle(type: string, code: string): React.CSSProperties {
  if (type === 'food')    return { background: '#FEF3C7', color: '#92400E' }
  if (type === 'medical') return { background: '#EDE9FE', color: '#5B21B6' }
  if (type === 'sector')  return { background: '#EFF6FF', color: '#1E40AF' }
  if (type === 'energy') {
    if (code === 'High')   return { background: '#FEE2E2', color: '#991B1B' }
    if (code === 'Medium') return { background: '#FEF3C7', color: '#92400E' }
    return { background: '#F0FDF4', color: '#166534' }
  }
  return { background: '#F0FAF4', color: '#1A4731' }
}

// ── Plan overview ─────────────────────────────────────────────────────────────

const MD11_LEVELS = ['Low', 'Medium', 'High'] as const
const MD11_RATES: Record<string, number> = { Low: 5, Medium: 10, High: 20 }
const MD11_COLORS: Record<string, { bg: string; text: string; border: string }> = {
  Low:    { bg: '#F0FDF4', text: '#166534', border: '#BBF7D0' },
  Medium: { bg: '#FEF3C7', text: '#92400E', border: '#FDE68A' },
  High:   { bg: '#FEF2F2', text: '#991B1B', border: '#FECACA' },
}

function PlanOverview({
  data,
  auditSetId,
  onInvalidate,
}: {
  data: AuditSetResponse
  auditSetId: string
  onInvalidate: () => void
}) {
  const [integLevel, setIntegLevel] = useState<string>(data.scope_integration_level ?? 'Medium')
  const [certFee, setCertFee] = useState(data.certification_fee != null ? String(data.certification_fee) : '')
  const [survFee, setSurvFee] = useState(data.surveillance_fee != null ? String(data.surveillance_fee) : '')
  const [feeSaved, setFeeSaved] = useState(false)
  const [nacText, setNacText] = useState<string>(data.non_applicable_clauses ?? '')
  const [nacSuggestions, setNacSuggestions] = useState<NACSuggestion[]>([])
  const [nacSaved, setNacSaved] = useState(false)
  const [nacEmptyMsg, setNacEmptyMsg] = useState(false)
  // Keep textarea in sync with server value after PUT round-trips invalidate the query.
  useEffect(() => { setNacText(data.non_applicable_clauses ?? '') }, [data.non_applicable_clauses])

  const p = data.personnel
  const personnelStr = p
    ? `${p.full_time} FT · ${p.part_time} PT · ${p.subcontractors} contractor`
    : data.effective_employees != null
    ? `${data.effective_employees} effective employees`
    : '—'

  const { mutate: applyIntegLevel, isPending: applyingLevel } = useMutation({
    mutationFn: (level: string) =>
      api.post<AuditSetResponse>(`/audit-sets/${auditSetId}/quick-calculate`, {
        scope_integration_level: level,
      }),
    onSuccess: () => onInvalidate(),
  })

  const { mutate: saveFees, isPending: savingFees } = useMutation({
    mutationFn: () =>
      api.put<AuditSetResponse>(`/audit-sets/${auditSetId}/planning`, {
        certification_fee: certFee.trim() === '' ? null : parseFloat(certFee),
        surveillance_fee:  survFee.trim() === '' ? null : parseFloat(survFee),
      }),
    onSuccess: () => {
      onInvalidate()
      setFeeSaved(true)
      setTimeout(() => setFeeSaved(false), 2000)
    },
  })

  const { mutate: generateNac, isPending: generatingNac } = useMutation({
    mutationFn: () =>
      api.post<NACGenerationResponse>(`/audit-sets/${auditSetId}/generate-nac`, {}).then((r) => r.data),
    onSuccess: (res) => {
      setNacText(res.non_applicable_clauses ?? '')
      setNacSuggestions(res.suggestions ?? [])
      setNacEmptyMsg((res.suggestions ?? []).length === 0 && !(res.non_applicable_clauses ?? '').trim())
    },
  })

  const { mutate: saveNac, isPending: savingNac } = useMutation({
    mutationFn: () =>
      api.put<AuditSetResponse>(`/audit-sets/${auditSetId}/planning`, {
        non_applicable_clauses: nacText,
      }),
    onSuccess: () => {
      onInvalidate()
      setNacSaved(true)
      setTimeout(() => setNacSaved(false), 2000)
    },
  })

  const rs = data.required_scope
  const hasCalcResult = !!data.man_day_result

  return (
    <div className="rounded-lg border border-gray-100 bg-white p-5">
      <div className="mb-4 flex items-center justify-between">
        <p className="text-sm font-medium text-gray-700">Plan overview</p>
        <div className="flex items-center gap-3">
          {/* IAF MD 11 integration level selector — only when a calculation exists */}
          {hasCalcResult && (
            <div className="flex items-center gap-1.5">
              <span className="text-xs text-gray-400">MD 11:</span>
              {MD11_LEVELS.map((lvl) => {
                const active = integLevel === lvl
                const colors = MD11_COLORS[lvl]
                return (
                  <button
                    key={lvl}
                    type="button"
                    disabled={applyingLevel}
                    onClick={() => {
                      setIntegLevel(lvl)
                      applyIntegLevel(lvl)
                    }}
                    className="rounded px-2 py-0.5 text-xs font-medium transition-opacity disabled:opacity-50"
                    style={active
                      ? { background: colors.bg, color: colors.text, border: `1px solid ${colors.border}` }
                      : { background: '#F9FAFB', color: '#6B7280', border: '1px solid #E5E7EB' }
                    }
                  >
                    {applyingLevel && active ? '…' : lvl}
                  </button>
                )
              })}
              <span className="text-xs text-gray-400">({MD11_RATES[integLevel]}% reduction)</span>
            </div>
          )}
        </div>
      </div>
      <div className="grid grid-cols-3 gap-x-6 gap-y-5">
        <LabeledField label="Standards">
          <div className="mt-0.5 flex flex-wrap gap-1.5">
            {(data.standards ?? []).map((s) => (
              <span key={s} className="rounded px-2 py-0.5 text-xs font-medium" style={{ background: '#F0FAF4', color: '#1A4731' }}>
                {s}
              </span>
            ))}
          </div>
        </LabeledField>
        <LabeledField label="Audit type">{auditTypeLabel(data.audit_type)}</LabeledField>
        <LabeledField label="Accreditation body">{data.accreditation_body ?? '—'}</LabeledField>
        <LabeledField label="Scope (TR)">
          <span className="text-gray-500">{data.scope_tr || '—'}</span>
        </LabeledField>
        <LabeledField label="Scope (EN)">
          <span className="text-gray-500">{data.scope_en || '—'}</span>
        </LabeledField>
        <LabeledField label="Personnel">{personnelStr}</LabeledField>

        {rs && Object.keys(rs).length > 0 && (
          <div className="col-span-3">
            <p className="mb-0.5 font-medium uppercase tracking-wide text-gray-400" style={{ fontSize: 11 }}>Required scope (derived)</p>
            <div className="mt-1 space-y-1">
              {Object.entries(rs).map(([std, entry]) => (
                <div key={std} className="flex flex-wrap items-center gap-1.5">
                  <span className="text-xs font-medium text-gray-600 w-24 shrink-0">{std}</span>
                  {entry.codes.length === 0 ? (
                    <span className="text-xs text-gray-400 italic">no codes derived</span>
                  ) : entry.codes.map((code) => (
                    <span key={code} className="rounded px-2 py-0.5 text-xs font-medium" style={scopeBadgeStyle(entry.type, code)}>
                      {code}
                    </span>
                  ))}
                </div>
              ))}
            </div>
          </div>
        )}

        <div className="col-span-3 border-t border-gray-100 pt-4">
          <p className="mb-2 font-medium uppercase tracking-wide text-gray-400" style={{ fontSize: 11 }}>Fees</p>
          <div className="flex flex-wrap items-end gap-4">
            <div className="w-44">
              <label className={lblCls}>Initial Certification Fee</label>
              <input type="number" step="0.01" min="0" className={inputCls} value={certFee} onChange={(e) => setCertFee(e.target.value)} placeholder="0.00" />
            </div>
            <div className="w-44">
              <label className={lblCls}>Surveillance Fee</label>
              <input type="number" step="0.01" min="0" className={inputCls} value={survFee} onChange={(e) => setSurvFee(e.target.value)} placeholder="0.00" />
            </div>
            <button
              type="button"
              disabled={savingFees}
              onClick={() => saveFees()}
              className="flex items-center gap-1 rounded-lg bg-certiva-primary px-4 py-2 text-sm font-medium text-white transition-opacity hover:opacity-90 disabled:opacity-50"
            >
              {savingFees ? <Loader2 size={14} className="animate-spin" /> : feeSaved ? <Check size={14} /> : null}
              {feeSaved ? 'Saved' : 'Save fees'}
            </button>
          </div>
        </div>

        <div className="col-span-3 border-t border-gray-100 pt-4">
          <div className="mb-2 flex items-center justify-between">
            <p className="font-medium uppercase tracking-wide text-gray-400" style={{ fontSize: 11 }}>Not Applicable Clauses</p>
            <button
              type="button"
              disabled={generatingNac}
              onClick={() => generateNac()}
              className="flex items-center gap-1.5 rounded-md border border-certiva-primary px-2.5 py-1 text-xs font-medium text-certiva-primary hover:bg-green-50 disabled:opacity-50"
            >
              {generatingNac ? <Loader2 size={12} className="animate-spin" /> : <Sparkles size={12} />}
              {generatingNac ? 'Generating…' : 'Generate Suggestions'}
            </button>
          </div>
          <textarea
            className={`${inputCls} min-h-[72px] font-mono`}
            value={nacText}
            onChange={(e) => { setNacText(e.target.value); setNacEmptyMsg(false) }}
            placeholder="e.g. 8.3 (ISO 9001:2015): Organization manufactures to external specifications — no design/development activities."
          />
          {nacEmptyMsg && (
            <p className="mt-1 text-xs italic text-gray-500">
              No clearly non-applicable clauses were identified for this scope. You can manually enter any N/A clauses in the field above.
            </p>
          )}
          {nacSuggestions.length > 0 && (
            <div className="mt-2 overflow-x-auto rounded-md border border-gray-100">
              <table className="w-full text-xs">
                <thead>
                  <tr className="border-b border-gray-100 bg-gray-50 text-left text-gray-500">
                    <th className="px-2 py-1.5 font-medium">Clause</th>
                    <th className="px-2 py-1.5 font-medium">Standard</th>
                    <th className="px-2 py-1.5 font-medium">Title</th>
                    <th className="px-2 py-1.5 font-medium">Justification</th>
                    <th className="px-2 py-1.5 font-medium">Confidence</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-gray-50">
                  {nacSuggestions.map((s, i) => (
                    <tr key={`${s.clause}-${i}`} className="text-gray-700">
                      <td className="px-2 py-1.5 font-mono">{s.clause}</td>
                      <td className="px-2 py-1.5">{s.standard}</td>
                      <td className="px-2 py-1.5">{s.title}</td>
                      <td className="px-2 py-1.5 text-gray-600">{s.justification}</td>
                      <td className="px-2 py-1.5">
                        <span
                          className="rounded px-1.5 py-0.5 text-[10px] font-medium uppercase"
                          style={
                            s.confidence === 'high'   ? { background: '#DCFCE7', color: '#166534' } :
                            s.confidence === 'medium' ? { background: '#FEF3C7', color: '#92400E' } :
                                                        { background: '#FEE2E2', color: '#991B1B' }
                          }
                        >
                          {s.confidence ?? 'low'}
                        </span>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
          <div className="mt-2 flex items-center gap-2">
            <button
              type="button"
              disabled={savingNac}
              onClick={() => saveNac()}
              className="flex items-center gap-1 rounded-lg bg-certiva-primary px-3 py-1.5 text-xs font-medium text-white transition-opacity hover:opacity-90 disabled:opacity-50"
            >
              {savingNac ? <Loader2 size={12} className="animate-spin" /> : nacSaved ? <Check size={12} /> : null}
              {nacSaved ? 'Saved' : 'Save N/A clauses'}
            </button>
          </div>
        </div>
      </div>
    </div>
  )
}


// ── Certification status section ──────────────────────────────────────────────

function CertSection({
  data, id, onInvalidate,
}: {
  data: AuditSetResponse
  id: string
  onInvalidate: () => void
}) {
  const [editing, setEditing]       = useState(false)
  const [issuedDate, setIssuedDate] = useState(data.cert_issued_date ?? '')
  const [expiryDate, setExpiryDate] = useState(data.cert_expiry_date ?? '')

  const { mutate, isPending } = useMutation({
    mutationFn: () =>
      api.patch(`/dashboard/clients/${id}/cert-dates`, {
        cert_issued_date: issuedDate || null,
        cert_expiry_date: expiryDate || null,
      }),
    onSuccess: () => {
      onInvalidate()
      setEditing(false)
    },
  })

  return (
    <div className="rounded-lg border border-gray-100 bg-white p-5">
      <div className="mb-4 flex items-center justify-between">
        <p className="text-sm font-medium text-gray-700">Certification status</p>
        <button
          type="button"
          onClick={() => setEditing((v) => !v)}
          className="flex items-center gap-1 text-certiva-primary hover:opacity-70"
          style={{ fontSize: 13 }}
        >
          <Pencil size={13} /> Edit dates
        </button>
      </div>

      <div className="grid grid-cols-4 gap-6">
        <LabeledField label="Cert status">
          <div className="mt-0.5"><CertBadge status={data.cert_status ?? null} /></div>
        </LabeledField>
        <LabeledField label="Issued date">{formatDate(data.cert_issued_date)}</LabeledField>
        <LabeledField label="Expiry date">{formatDate(data.cert_expiry_date)}</LabeledField>
        <div />
      </div>

      {editing && (
        <div className="mt-5 border-t border-gray-100 pt-4">
          <div className="grid grid-cols-2 gap-4">
            <div>
              <label className={lblCls}>Issued date</label>
              <input type="date" className={inputCls} value={issuedDate} onChange={(e) => setIssuedDate(e.target.value)} />
            </div>
            <div>
              <label className={lblCls}>Expiry date</label>
              <input type="date" className={inputCls} value={expiryDate} onChange={(e) => setExpiryDate(e.target.value)} />
            </div>
          </div>
          <div className="mt-3 flex gap-2">
            <button
              type="button" disabled={isPending}
              onClick={() => mutate()}
              className="flex items-center gap-1.5 rounded-lg px-4 py-1.5 text-sm font-medium text-white disabled:opacity-60 hover:opacity-90"
              style={{ background: '#1A4731' }}
            >
              {isPending && <Loader2 size={14} className="animate-spin" />}
              Save
            </button>
            <button type="button" onClick={() => setEditing(false)} className="rounded-lg border border-gray-200 px-4 py-1.5 text-sm text-gray-500 hover:bg-gray-50">
              Cancel
            </button>
          </div>
        </div>
      )}
    </div>
  )
}


// ── Stage card ────────────────────────────────────────────────────────────────

function StageCard({
  stage, label, allStages, auditSetId, onSuccess,
  auditors, auditorsLoading,
  manDayResult, auditType, eaCode, standards, requiredScope,
}: {
  stage: StageResponse
  label: string
  allStages: StageResponse[]
  auditSetId: string
  onSuccess: () => void
  auditors: AuditorSummary[]
  auditorsLoading: boolean
  manDayResult: ManDayResult | null
  auditType: string | null
  eaCode: string | null
  standards: string[]
  requiredScope: RequiredScope | null
}) {
  const [edit, setEdit] = useState<StageEdit>(() => buildStageEdit(stage))
  const [saved, setSaved] = useState(false)

  const recommended = recommendedDays(stage.stage_type, manDayResult, auditType)
  const resolvedStds = resolveStandards(standards ?? [])
  const primaryStandard = resolvedStds[0] ?? null

  // Availability query — fires only when both dates are filled
  const datesReady = !!edit.audit_date_start && !!edit.audit_date_end
  const reqCatStr = requiredScope ? JSON.stringify(requiredScope) : undefined
  const { data: availableAuditors, isFetching: loadingAvailability } = useQuery<AuditorAvailabilityItem[]>({
    queryKey: ['auditor-availability', edit.audit_date_start, edit.audit_date_end, primaryStandard, eaCode, reqCatStr],
    queryFn: () => {
      const params = new URLSearchParams({
        date_start: edit.audit_date_start,
        date_end:   edit.audit_date_end,
      })
      if (primaryStandard) params.set('standard_code', primaryStandard)
      if (eaCode)          params.set('ea_code', eaCode)
      if (reqCatStr)       params.set('required_categories', reqCatStr)
      return api.get<AuditorAvailabilityItem[]>(`/auditors/available?${params}`).then((r) => r.data)
    },
    enabled: datesReady,
    staleTime: 30_000,
  })

  // Auto-fill suggested dates on mount when the stage has no dates yet
  useEffect(() => {
    if (edit.audit_date_start || edit.audit_date_end) return   // don't override existing dates
    if (!recommended) return                                    // need man-day recommendation first

    let suggestedStart: string | null = null

    if (stage.stage_type === 'stage_1') {
      const d = new Date()
      d.setDate(d.getDate() + 14)   // 2-week lead time
      while (d.getDay() === 0 || d.getDay() === 6) d.setDate(d.getDate() + 1)
      suggestedStart = d.toISOString().slice(0, 10)
    } else if (stage.stage_type === 'stage_2') {
      const stage1 = allStages.find((s) => s.stage_type === 'stage_1')
      if (!stage1?.audit_date_end) return   // need stage 1 end first
      const d = new Date(stage1.audit_date_end)
      d.setDate(d.getDate() + 7)   // 1-week gap after stage 1
      while (d.getDay() === 0 || d.getDay() === 6) d.setDate(d.getDate() + 1)
      suggestedStart = d.toISOString().slice(0, 10)
    }

    if (suggestedStart) {
      patch({
        audit_date_start: suggestedStart,
        audit_date_end: suggestEndDate(suggestedStart, recommended),
      })
    }
  }, [])   // eslint-disable-line react-hooks/exhaustive-deps — intentionally on mount only

  const workingDays = datesReady ? workingDaysBetween(edit.audit_date_start, edit.audit_date_end) : null
  // Team size for man-day math: lead + additional auditors ONLY (technical experts observe, not audit — per IAF MD 5 / spec Part 5)
  const teamCount = (edit.lead_auditor_name ? 1 : 0) + edit.auditors.length

  // Reactive: when team size changes and a start date exists, recompute end date
  // so that: calendar days = ceil(audit_days / teamCount)
  useEffect(() => {
    if (!edit.audit_date_start) return           // no start date yet — nothing to do
    if (!stage.audit_days) return                // no IAF recommendation — nothing to base on
    if (teamCount === 0) return                  // no auditors yet — keep existing date
    const calendarDaysNeeded = Math.ceil(stage.audit_days / teamCount)
    const newEnd = suggestEndDate(edit.audit_date_start, calendarDaysNeeded)
    if (newEnd !== edit.audit_date_end) {
      patch({ audit_date_end: newEnd })
    }
  }, [teamCount])   // eslint-disable-line react-hooks/exhaustive-deps — intentionally watches teamCount only

  // Man-days covered = working days in range × number of assigned team members
  const manDaysCovered = workingDays != null && teamCount > 0 ? workingDays * teamCount : null
  // Shortfall: covered < stage.audit_days (recommended for this stage from calculation)
  const manDayShortfall = stage.audit_days != null && manDaysCovered != null && manDaysCovered < stage.audit_days
  const dateMismatch = recommended != null && workingDays != null && teamCount === 0 && Math.abs(workingDays - recommended) > 0.5
  const stageOrderErr = validateStageOrder(stage, allStages, edit.audit_date_start, edit.audit_date_end)

  const [coverageError, setCoverageError] = useState<string | null>(null)

  const resolvedStandards = resolvedStds

  // Coverage computation — lead + additional auditors only, NOT technical experts (per spec Part 5)
  const teamMembers: TeamMember[] = [
    ...(edit.lead_auditor_name ? [{ id: edit.lead_auditor_id, name: edit.lead_auditor_name }] : []),
    ...edit.auditors,
  ]
  const coverageResults = (resolvedStandards.length > 0 && (availableAuditors ?? []).length > 0)
    ? computeCoverage(resolvedStandards, eaCode, teamMembers, availableAuditors ?? [], requiredScope)
    : []
  const allCovered = coverageResults.length === 0 || coverageResults.every((r) => r.covered)

  const isStage2 = stage.stage_type === 'stage_2'
  const coverageIncomplete = coverageResults.length > 0 && !allCovered

  const { mutate, isPending } = useMutation({
    mutationFn: () => {
      // Stage 2: hard block — every required code must be covered
      if (isStage2 && coverageIncomplete) {
        const missingCodes = coverageResults
          .flatMap((r) => r.codeResults?.filter((cr) => !cr.coveredBy).map((cr) => cr.code) ?? (r.covered ? [] : [r.standard]))
          .join(', ')
        throw new Error(`Stage 2 save blocked — uncovered codes: ${missingCodes}. Assign team members who cover these codes first.`)
      }
      // Stage ordering: Stage 1 end must be strictly before Stage 2 start
      const s1 = allStages.find((s) => s.stage_type === 'stage_1')
      const s2 = allStages.find((s) => s.stage_type === 'stage_2')
      const s1End   = stage.id === s1?.id ? edit.audit_date_end   : s1?.audit_date_end
      const s2Start = stage.id === s2?.id ? edit.audit_date_start : s2?.audit_date_start
      if (s1 && s2 && s1End && s2Start && s1End >= s2Start) {
        throw new Error(`Stage 1 end (${s1End}) must be strictly before Stage 2 start (${s2Start}).`)
      }

      // Stage 1: allow save even with incomplete coverage (warning shown separately)
      const stages = allStages.map((s) => {
        const isThis = s.id === stage.id
        return {
          stage_type:        s.stage_type,
          stage_order:       s.stage_order,
          status:            s.status,
          lead_auditor_name: isThis ? (edit.lead_auditor_name || null) : s.lead_auditor_name,
          audit_date_start:  isThis ? (edit.audit_date_start  || null) : s.audit_date_start,
          audit_date_end:    isThis ? (edit.audit_date_end    || null) : s.audit_date_end,
          auditors:          isThis ? edit.auditors          : ((s.auditors as TeamMember[]) ?? []),
          technical_experts: isThis ? edit.technical_experts : ((s.technical_experts as TeamMember[]) ?? []),
          observers:         (s.observers as { name: string }[]) ?? [],
          ik_experts:        [],
          evaluators:        [],
        }
      })
      return api.put<AuditSetResponse>(`/audit-sets/${auditSetId}/planning`, { stages })
    },
    onSuccess: (res) => {
      const updated = res.data.stages.find((s) => s.id === stage.id)
      if (updated) setEdit(buildStageEdit(updated))
      setCoverageError(null)
      onSuccess()
      setSaved(true)
      setTimeout(() => setSaved(false), 2000)
    },
    onError: (err: unknown) => {
      // Surface backend HTTPException detail (e.g. 400 stage-ordering violation)
      const e = err as { response?: { data?: { detail?: string } }; message?: string }
      const msg = e?.response?.data?.detail ?? e?.message ?? 'Failed to save.'
      setCoverageError(msg)
    },
  })

  function patch(p: Partial<StageEdit>) { setEdit((prev) => ({ ...prev, ...p })) }

  // Determine the auditor list to render in dropdowns
  // When required_scope is derived and availability data is loaded, exclude auditors
  // who cover zero required codes — they add no value to this audit.
  const allDropdown: (AuditorSummary | AuditorAvailabilityItem)[] = availableAuditors ?? auditors
  const dropdownList: (AuditorSummary | AuditorAvailabilityItem)[] =
    (availableAuditors && requiredScope && Object.keys(requiredScope).length > 0)
      ? availableAuditors.filter((a) => {
          const coveredTotal = Object.values(a.covered_scope ?? {}).flat().length
          return coveredTotal > 0
        })
      : allDropdown

  return (
    <div className="rounded-lg border border-gray-100 p-4">
      {/* Header */}
      <div className="mb-4 flex items-center justify-between">
        <span className="text-sm font-medium text-gray-700">{label}</span>
        <div className="flex items-center gap-2">
          {stage.audit_days != null && (
            <span className="rounded px-2 py-0.5 text-xs font-medium" style={{ background: '#F0FAF4', color: '#1A4731' }}>
              {stage.audit_days} days audited
              {recommended != null && stage.audit_days !== recommended && (
                <span className="ml-1" style={{ color: '#92400E' }}>(recommended: {recommended})</span>
              )}
            </span>
          )}
          {stage.audit_days == null && recommended != null && (
            <span className="rounded px-2 py-0.5 text-xs font-medium" style={{ background: '#FEF3C7', color: '#92400E' }}>
              {recommended} days recommended — not yet scheduled
            </span>
          )}
        </div>
      </div>

      {/* IAF MD 5 banner — shows live calendar days based on team size */}
      {stage.audit_days != null && (
        <div className="mb-3 rounded-md px-3 py-2 text-sm" style={{ background: '#F0FAF4', color: '#1A4731' }}>
          <span className="font-medium">IAF MD 5:</span>{' '}
          {stage.audit_days} audit-day{stage.audit_days !== 1 ? 's' : ''} required.
          {teamCount > 0 ? (
            <span className="ml-2 font-medium">
              ÷ {teamCount} auditor{teamCount > 1 ? 's' : ''}{' = '}
              <span>
                {Math.ceil(stage.audit_days / teamCount)} calendar day{Math.ceil(stage.audit_days / teamCount) > 1 ? 's' : ''}
              </span>
            </span>
          ) : (
            <span className="ml-1 text-xs" style={{ color: '#92400E' }}>— assign auditors to see required calendar days</span>
          )}
        </div>
      )}

      {/* Man-day coverage warning — team × dates vs required audit days */}
      {manDayShortfall && workingDays != null && (
        <div className="mb-3 rounded-md px-3 py-2 text-sm" style={{ background: '#FEF3C7', color: '#92400E' }}>
          ⚠ Your date range covers {workingDays} working day(s) × {teamCount} auditor(s) = {manDaysCovered} man-day(s).
          IAF recommends {stage.audit_days} audit-day(s) for this stage.
          Consider expanding the date range or adding more auditors.
        </div>
      )}
      {/* Fallback: no team assigned yet — show plain date-vs-recommendation mismatch */}
      {dateMismatch && workingDays != null && (
        <div className="mb-3 rounded-md px-3 py-2 text-sm" style={{ background: '#FEF3C7', color: '#92400E' }}>
          ⚠ Date range covers {workingDays} working day(s), but IAF MD 5 recommends {recommended} for a single auditor.
          {workingDays > recommended!
            ? ' This exceeds the recommended duration.'
            : ' Assign auditors or expand the date range.'}
        </div>
      )}

      {/* 2-col grid of fields */}
      <div className="grid grid-cols-2 gap-4">
        {/* Lead auditor with availability */}
        <div>
          <label className={lblCls}>Lead auditor</label>
          {loadingAvailability && (
            <p className="mb-1 text-xs text-gray-400">Checking availability…</p>
          )}
          {availableAuditors && (
            <p className="mb-1 text-xs text-gray-500">
              {availableAuditors.filter((a) => a.available).length} of {availableAuditors.length} auditors
              qualified &amp; available for {primaryStandard ?? 'this standard'} on selected dates.
            </p>
          )}
          <select
            className={inputCls}
            value={edit.lead_auditor_name}
            onChange={(e) => {
              const found = dropdownList.find((a) => a.name === e.target.value)
              patch({ lead_auditor_name: e.target.value, lead_auditor_id: found?.id ?? '' })
            }}
            disabled={!availableAuditors && auditorsLoading}
          >
            <option value="">{!availableAuditors && auditorsLoading ? 'Loading…' : '— Select —'}</option>
            {edit.lead_auditor_name && !dropdownList.some((a) => a.name === edit.lead_auditor_name) && (
              <option value={edit.lead_auditor_name}>{edit.lead_auditor_name}</option>
            )}
            {dropdownList.map((a) => {
              const avail = availableAuditors?.find((x) => x.name === a.name)
              const isUnavailable = avail && !avail.available
              // Group covered codes by standard: "EA 3 (ISO 9001) | CIV CIII (ISO 22000)"
              const coverLabel = avail?.covered_scope && Object.keys(avail.covered_scope).length > 0
                ? ' — ' + Object.entries(avail.covered_scope)
                    .filter(([, codes]) => (codes as string[]).length > 0)
                    .map(([std, codes]) => `${(codes as string[]).join(' ')} (${std})`)
                    .join(' | ')
                : ''
              return (
                <option key={a.id ?? a.name} value={a.name} disabled={!!isUnavailable}>
                  {a.name}{'role' in a && a.role ? ` — ${a.role}` : ''}
                  {coverLabel}{isUnavailable ? ' (unavailable on selected dates)' : ''}
                </option>
              )
            })}
          </select>
          {availableAuditors && (() => {
            const selected = availableAuditors.find((a) => a.name === edit.lead_auditor_name)
            if (selected?.conflict_detail) {
              return <p className="mt-1 text-xs text-red-500">{selected.conflict_detail}</p>
            }
            return null
          })()}
        </div>

        {/* Date range */}
        <div className="space-y-1">
          <div className="grid grid-cols-2 gap-2">
            <div>
              <label className={lblCls}>Start date</label>
              <input type="date" className={inputCls} value={edit.audit_date_start} onChange={(e) => patch({ audit_date_start: e.target.value })} />
            </div>
            <div>
              <label className={lblCls}>End date</label>
              <input type="date" className={inputCls} value={edit.audit_date_end} onChange={(e) => patch({ audit_date_end: e.target.value })} />
            </div>
          </div>
          {recommended != null && edit.audit_date_start && (
            <button
              type="button"
              onClick={() => patch({ audit_date_end: suggestEndDate(edit.audit_date_start, recommended) })}
              className="text-xs text-certiva-primary underline hover:opacity-70"
            >
              Suggest end date ({recommended} working days from start)
            </button>
          )}
        </div>

        {/* Auditors multi-select */}
        <div>
          <label className={lblCls}>Auditors</label>
          <div className="flex flex-wrap gap-1 mb-1 min-h-[24px]">
            {edit.auditors.map((a) => (
              <span key={a.id || a.name}
                className="flex items-center gap-1 rounded-full px-2 py-0.5 text-xs"
                style={{ background: '#F0FAF4', color: '#1A4731', border: '1px solid #BBF7D0' }}>
                {a.name}
                <input
                  type="text"
                  placeholder="EA"
                  className="w-14 rounded border border-green-200 bg-white/70 px-1 py-0 text-[11px] leading-tight text-gray-700 outline-none focus:border-certiva-primary"
                  value={a.ea_code ?? ''}
                  title="EA/IAF Code for this assignment (e.g. EA 3) — used in FR.223/FR.224 when the auditor's profile has no scope match"
                  onChange={(e) => patch({
                    auditors: edit.auditors.map((x) =>
                      (x.id || x.name) === (a.id || a.name) ? { ...x, ea_code: e.target.value } : x
                    ),
                  })}
                />
                <button type="button"
                  className="ml-1 text-gray-400 hover:text-red-500"
                  onClick={() => patch({ auditors: edit.auditors.filter((x) => (x.id || x.name) !== (a.id || a.name)) })}>
                  ×
                </button>
              </span>
            ))}
          </div>
          <select className={inputCls} value=""
            onChange={(e) => {
              const found = dropdownList.find((a) => (a.id ?? a.name) === e.target.value)
              if (found && !edit.auditors.find((x) => (x.id || x.name) === (found.id || found.name))) {
                patch({ auditors: [...edit.auditors, { id: found.id ?? '', name: found.name }] })
              }
            }}>
            <option value="">+ Add auditor…</option>
            {dropdownList
              .filter((a) => !edit.auditors.find((x) => (x.id || x.name) === (a.id || a.name)))
              .filter((a) => a.name !== edit.lead_auditor_name)
              .map((a) => (
                <option key={a.id ?? a.name} value={a.id ?? a.name}>{a.name}</option>
              ))}
          </select>
        </div>

        {/* Technical experts multi-select */}
        <div>
          <label className={lblCls}>Technical experts</label>
          <div className="flex flex-wrap gap-1 mb-1 min-h-[24px]">
            {edit.technical_experts.map((a) => (
              <span key={a.id || a.name}
                className="flex items-center gap-1 rounded-full px-2 py-0.5 text-xs"
                style={{ background: '#F0FAF4', color: '#1A4731', border: '1px solid #BBF7D0' }}>
                {a.name}
                <input
                  type="text"
                  placeholder="EA"
                  className="w-14 rounded border border-green-200 bg-white/70 px-1 py-0 text-[11px] leading-tight text-gray-700 outline-none focus:border-certiva-primary"
                  value={a.ea_code ?? ''}
                  title="EA/IAF Code for this assignment (e.g. EA 3) — used in FR.223/FR.224 when the auditor's profile has no scope match"
                  onChange={(e) => patch({
                    technical_experts: edit.technical_experts.map((x) =>
                      (x.id || x.name) === (a.id || a.name) ? { ...x, ea_code: e.target.value } : x
                    ),
                  })}
                />
                <button type="button"
                  className="ml-1 text-gray-400 hover:text-red-500"
                  onClick={() => patch({ technical_experts: edit.technical_experts.filter((x) => (x.id || x.name) !== (a.id || a.name)) })}>
                  ×
                </button>
              </span>
            ))}
          </div>
          <select className={inputCls} value=""
            onChange={(e) => {
              const found = dropdownList.find((a) => (a.id ?? a.name) === e.target.value)
              if (found && !edit.technical_experts.find((x) => (x.id || x.name) === (found.id || found.name))) {
                patch({ technical_experts: [...edit.technical_experts, { id: found.id ?? '', name: found.name }] })
              }
            }}>
            <option value="">+ Add technical expert…</option>
            {dropdownList
              .filter((a) => !edit.technical_experts.find((x) => (x.id || x.name) === (a.id || a.name)))
              .filter((a) => a.name !== edit.lead_auditor_name)
              .map((a) => (
                <option key={a.id ?? a.name} value={a.id ?? a.name}>{a.name}</option>
              ))}
          </select>
        </div>
      </div>

      {/* Coverage summary */}
      {coverageResults.length > 0 && (
        <div className={`mt-3 rounded-md p-3 text-sm ${allCovered ? 'border border-green-200' : isStage2 ? 'border border-red-200' : 'border border-amber-200'}`}
          style={{ background: allCovered ? '#F0FAF4' : isStage2 ? '#FEF2F2' : '#FFFBEB' }}>
          <p className="font-medium mb-1" style={{ color: allCovered ? '#1A4731' : isStage2 ? '#991B1B' : '#92400E' }}>
            {allCovered
              ? '✓ All required codes covered'
              : isStage2
              ? '✗ Coverage incomplete — Stage 2 save blocked'
              : '⚠ Coverage incomplete — Stage 1 can still be saved (warning)'}
          </p>
          {coverageResults.map((r) => (
            <div key={r.standard} className="mt-0.5">
              <span className="text-xs" style={{ color: r.covered ? '#1A4731' : '#991B1B' }}>
                {r.covered ? '✓' : '✗'} {r.standard}
                {!r.codeResults && (r.coveredBy ? ` — ${r.coveredBy}` : r.reason ? ` — ${r.reason}` : ' — no qualified team member')}
              </span>
              {r.codeResults && (
                <div className="ml-4 mt-0.5 flex flex-wrap gap-x-3 gap-y-0.5">
                  {r.codeResults.map((cr) => (
                    <span key={cr.code} className="text-xs" style={{ color: cr.coveredBy ? '#1A4731' : '#991B1B' }}>
                      {cr.coveredBy ? '✓' : '✗'} {cr.code}{cr.coveredBy ? ` (${cr.coveredBy})` : ''}
                    </span>
                  ))}
                </div>
              )}
            </div>
          ))}
        </div>
      )}

      {/* Stage order / coverage errors */}
      {stageOrderErr && (
        <div className="mt-3 rounded-md border border-red-200 bg-red-50 px-3 py-2 text-xs text-red-700">
          ⛔ {stageOrderErr}
        </div>
      )}
      {coverageError && !stageOrderErr && (
        <div className="mt-3 rounded-md border border-red-200 bg-red-50 px-3 py-2 text-xs text-red-700">
          {coverageError}
        </div>
      )}

      {/* Save row */}
      <div className="mt-4 flex items-center gap-2">
        <button
          type="button"
          disabled={isPending || !!stageOrderErr || (isStage2 && coverageIncomplete)}
          onClick={() => mutate()}
          className="flex items-center gap-1.5 rounded-lg px-4 py-1.5 text-sm font-medium text-white disabled:opacity-60 hover:opacity-90"
          style={{ background: '#1A4731' }}
        >
          {isPending && <Loader2 size={13} className="animate-spin" />}
          Save stage
        </button>
        {saved && (
          <span className="flex items-center gap-1 text-xs text-green-600">
            <Check size={13} /> Saved
          </span>
        )}
      </div>
    </div>
  )
}


// ── Man-day section (collapsible, correct CalculationResult shape) ────────────

function ManDaySection({ result }: { result: ManDayResult | null }) {
  const [open, setOpen] = useState(true)

  function phaseRow(label: string, days: number | undefined) {
    if (!days) return null
    return (
      <div className="flex items-center justify-between py-1">
        <span className="text-gray-500">{label}</span>
        <span className="font-medium text-certiva-primary">{days} days</span>
      </div>
    )
  }

  return (
    <div className="rounded-lg border border-gray-100 bg-white">
      <button
        type="button"
        className="flex w-full items-center justify-between px-5 py-4 text-left"
        onClick={() => setOpen((v) => !v)}
      >
        <span className="text-sm font-medium text-gray-700">
          IAF MD 5 man-day calculation
          {result && (
            <span className="ml-2 text-xs font-normal text-gray-400">
              {result.total_employees} employees · EPS {result.eps}
            </span>
          )}
        </span>
        {open
          ? <ChevronDown size={16} className="text-gray-400" />
          : <ChevronRight size={16} className="text-gray-400" />}
      </button>

      {open && (
        <div className="border-t border-gray-100 px-5 pb-5 pt-4 space-y-4">
          {!result ? (
            <p className="text-sm text-gray-400">Calculation pending — recomputing automatically from stored personnel.</p>
          ) : (
            <>
              {result.warning && (
                <div className="rounded-md border border-amber-200 bg-amber-50 px-3 py-2 text-xs text-amber-800">
                  {result.warning}
                </div>
              )}

              {/* Per-standard breakdown */}
              {result.standard_results?.length > 0 && (
                <div>
                  <p className="mb-2 text-xs font-medium uppercase tracking-wide text-gray-400">Per-standard breakdown</p>
                  <table className="w-full text-sm">
                    <thead>
                      <tr className="text-left text-xs font-medium uppercase tracking-wide text-gray-400">
                        <th className="pb-2 pr-4">Standard</th>
                        <th className="pb-2 pr-4">Category</th>
                        <th className="pb-2 pr-4">Base (init)</th>
                        <th className="pb-2 pr-4">Base (surv)</th>
                        <th className="pb-2">Base (recert)</th>
                      </tr>
                    </thead>
                    <tbody className="divide-y divide-gray-50">
                      {result.standard_results.map((r) => (
                        <tr key={r.standard}>
                          <td className="py-2 pr-4 font-medium">{r.standard}</td>
                          <td className="py-2 pr-4 text-gray-500">{r.category}</td>
                          <td className="py-2 pr-4 text-gray-600">{r.base_init}</td>
                          <td className="py-2 pr-4 text-gray-600">{r.base_surv}</td>
                          <td className="py-2 text-gray-600">{r.base_recert}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              )}

              {/* Final phase totals */}
              <div>
                <p className="mb-2 text-xs font-medium uppercase tracking-wide text-gray-400">Recommended audit days</p>
                <div className="divide-y divide-gray-50 text-sm">
                  {phaseRow('Initial — Stage 1', result.final_ph1)}
                  {phaseRow('Initial — Stage 2', result.final_ph2)}
                  {phaseRow('Surveillance (each)', result.final_surv1)}
                  {phaseRow('Recertification — Stage 1', result.final_recert_ph1)}
                  {phaseRow('Recertification — Stage 2', result.final_recert_ph2)}
                </div>
              </div>

              {/* Deductions summary */}
              <div className="rounded-md bg-gray-50 px-3 py-2 text-xs text-gray-500 space-y-1">
                <div className="flex justify-between">
                  <span>Combined base (incl. sites)</span><span>{result.combined_base} days</span>
                </div>
                {result.integration_reduction > 0 && (() => {
                  const lvl = result.scope_integration_level ?? 'Medium'
                  const pct = MD11_RATES[lvl] ?? 10
                  return (
                    <div className="flex justify-between">
                      <span>Integration reduction (IAF MD 11 — {lvl} {pct}%)</span>
                      <span>−{result.integration_reduction}</span>
                    </div>
                  )
                })()}
                {result.md11_floor_applied && result.md11_floor_value != null && (
                  <div className="flex justify-between rounded px-1 py-0.5" style={{ background: '#FEF3C7', color: '#92400E' }}>
                    <span>⚠ Floor applied per IAF MD 11 — minimum 50% of individual totals ({result.md11_floor_value} days)</span>
                    <span />
                  </div>
                )}
                <div className="flex justify-between">
                  <span>Reporting reduction (20%)</span><span>−{result.reporting_reduction}</span>
                </div>
                <div className="flex justify-between font-medium text-gray-700 border-t border-gray-200 pt-1 mt-1">
                  <span>Final total (on-site)</span><span>{result.final_total} days</span>
                </div>
                {result.fssc_reporting_surcharge != null && result.fssc_reporting_surcharge > 0 && (
                  <div className="flex justify-between rounded px-1 py-0.5" style={{ background: '#FEF3C7', color: '#92400E' }}>
                    <span>+ FSSC 22000 reporting/preparation surcharge (off-site)</span>
                    <span>+{result.fssc_reporting_surcharge} days</span>
                  </div>
                )}
              </div>
            </>
          )}
        </div>
      )}
    </div>
  )
}

// ── Main page ─────────────────────────────────────────────────────────────────

const CAN_DELETE_ROLES = new Set(['admin', 'planner'])

export default function ClientDetailPage({ params }: { params: { id: string } }) {
  const { id } = params
  const router = useRouter()
  const queryClient = useQueryClient()
  const { user: currentUser } = useAuth()
  const canDelete = !!currentUser && CAN_DELETE_ROLES.has(currentUser.role)
  const [downloading, setDownloading] = useState(false)
  const [deleteError, setDeleteError] = useState<string | null>(null)

  const { data, isLoading, isError } = useQuery<AuditSetResponse>({
    queryKey: ['client', id],
    queryFn: () => api.get<AuditSetResponse>(`/audit-sets/${id}`).then((r) => r.data),
  })

  const { data: auditors = [], isLoading: auditorsLoading } = useQuery<AuditorSummary[]>({
    queryKey: ['auditors-active'],
    queryFn:  () => api.get<AuditorSummary[]>('/auditors/?active_only=true').then((r) => r.data),
  })

  // Auto-calculate man-days on page load if result is missing but personnel is stored
  const autoCalcFired = useRef(false)
  useEffect(() => {
    if (!data || data.man_day_result || autoCalcFired.current) return
    const p = data.personnel
    const totalPersonnel = (p?.full_time || 0) + (p?.part_time || 0) + (p?.subcontractors || 0) + (p?.seasonal || 0) + (p?.unskilled || 0)
    if (totalPersonnel <= 0) return  // legacy record with no personnel — nothing to recompute
    autoCalcFired.current = true
    api.post(`/audit-sets/${id}/quick-calculate`, {
      personnel: {
        full_time:      p?.full_time      || 0,
        part_time:      p?.part_time      || 0,
        subcontractors: p?.subcontractors || 0,
        seasonal:       p?.seasonal       || 0,
        unskilled:      p?.unskilled      || 0,
      },
      scope_integration_level: data.scope_integration_level ?? 'Medium',
    }).then(() => queryClient.invalidateQueries({ queryKey: ['client', id] })).catch(() => {})
  }, [data?.id, data?.man_day_result])   // eslint-disable-line react-hooks/exhaustive-deps

  async function handleDownload() {
    if (!data) return
    setDownloading(true)
    try {
      const res = await api.get(`/audit-sets/${id}/download`, { responseType: 'blob' })
      const url = URL.createObjectURL(res.data as Blob)
      const a   = document.createElement('a')
      a.href     = url
      a.download = `Set_${data.plan_number}_${data.company_name}.zip`
      a.click()
      URL.revokeObjectURL(url)
    } finally {
      setDownloading(false)
    }
  }

  function invalidate() {
    queryClient.invalidateQueries({ queryKey: ['client', id] })
  }

  // Approve a client portal application: transitions workflow_status
  // from 'pending_review' → 'in_planning' via the workflow router.
  const { mutate: approveApplication, isPending: approving } = useMutation({
    mutationFn: () =>
      api.patch(`/audit-sets/${id}/workflow-status`, {
        workflow_status: 'in_planning',
        notes: 'Application reviewed and approved by CB coordinator',
      }),
    onSuccess: () => invalidate(),
  })

  const { mutate: deletePlan, isPending: deleting } = useMutation({
    mutationFn: () => api.delete(`/audit-sets/${id}`),
    onSuccess:  () => {
      queryClient.invalidateQueries({ queryKey: ['clients'] })
      router.push('/clients')
    },
    onError:    (e: unknown) => {
      const detail = (e as { response?: { data?: { detail?: string } } })?.response?.data?.detail
      setDeleteError(detail ?? 'Failed to delete plan')
    },
  })

  function handleDelete() {
    if (!data) return
    const ref = data.client_reference || `#${data.plan_number}`
    if (window.confirm(`Delete plan ${ref}? This will also remove the client's portal account. This cannot be undone.`)) {
      setDeleteError(null)
      deletePlan()
    }
  }

  if (isLoading) return (
    <div className="flex items-center justify-center py-24">
      <Loader2 size={24} className="animate-spin text-certiva-primary" />
    </div>
  )
  if (isError || !data) return (
    <div className="py-12 text-center text-sm text-red-500">Client not found.</div>
  )

  // Compute surveillance sequence number for labels
  let survCount = 0

  return (
    <div className="mx-auto max-w-[900px] space-y-5 py-4">
      {/* Back link */}
      <Link href="/clients" className="flex items-center gap-1 text-certiva-primary hover:opacity-70" style={{ fontSize: 13 }}>
        <ArrowLeft size={13} /> Clients
      </Link>

      {/* Header */}
      <div className="flex items-start justify-between">
        <div className="flex items-center gap-3">
          <h1 className="text-gray-800" style={{ fontSize: 22, fontWeight: 500 }}>{data.company_name}</h1>
          <span className="rounded px-2 py-0.5 font-mono text-xs" style={{ background: '#F0FAF4', color: '#1A4731' }}>
            #{data.plan_number}
          </span>
        </div>
        <div className="flex gap-2">
          <button
            type="button" disabled={downloading}
            onClick={handleDownload}
            className="flex items-center gap-1.5 rounded-lg border border-gray-200 px-3 py-1.5 text-sm text-gray-700 hover:bg-gray-50 disabled:opacity-60"
          >
            {downloading ? <Loader2 size={14} className="animate-spin" /> : <Download size={14} />}
            Download audit package
          </button>
          <Link
            href={`/reports/new?client_id=${id}`}
            className="flex items-center rounded-lg px-3 py-1.5 text-sm font-medium text-white hover:opacity-90"
            style={{ background: '#1A4731' }}
          >
            Generate AI report
          </Link>
          {canDelete && (
            <button
              type="button"
              disabled={deleting}
              onClick={handleDelete}
              className="flex items-center gap-1.5 rounded-lg border border-red-200 px-3 py-1.5 text-sm text-red-600 hover:bg-red-50 disabled:opacity-60"
            >
              {deleting ? <Loader2 size={14} className="animate-spin" /> : <Trash2 size={14} />}
              Delete Plan
            </button>
          )}
        </div>
      </div>

      {deleteError && (
        <div className="flex items-center justify-between rounded-lg border border-red-200 bg-red-50 px-4 py-2 text-sm text-red-700">
          <span>{deleteError}</span>
          <button onClick={() => setDeleteError(null)} className="text-xs text-red-600 hover:opacity-70">Dismiss</button>
        </div>
      )}

      {/* Client portal application — show approval banner when pending */}
      {data.workflow_status === 'pending_review' && (
        <div
          className="flex items-center justify-between rounded-xl border border-amber-200 bg-amber-50 p-4"
        >
          <div>
            <p className="text-sm font-semibold text-amber-800">Client Portal Application</p>
            <p className="mt-0.5 text-xs text-amber-700">
              Complete the form below (fees, auditor, etc.) then approve to move to planning.
            </p>
          </div>
          <button
            type="button"
            disabled={approving}
            onClick={() => approveApplication()}
            className="flex items-center gap-1.5 rounded-lg px-4 py-2 text-sm text-white hover:opacity-90 disabled:opacity-60"
            style={{ background: '#1A4731' }}
          >
            {approving && <Loader2 size={13} className="animate-spin" />}
            Approve Application
          </button>
        </div>
      )}

      {/* Workflow status tracker + status-specific action panel */}
      {data.workflow_status && data.workflow_status !== 'pending_review' && (
        <WorkflowStatusBar
          auditSetId={id}
          currentStatus={data.workflow_status}
          currentUserRole={currentUser?.role ?? ''}
          auditType={data.audit_type ?? null}
          onAdvanced={invalidate}
        />
      )}

      <PlanOverview data={data} auditSetId={id} onInvalidate={invalidate} />
      <CertSection data={data} id={id} onInvalidate={invalidate} />

      {/* Audit stages */}
      {data.stages.length > 0 && (
        <div className="rounded-lg border border-gray-100 bg-white p-5">
          <p className="mb-4 text-sm font-medium text-gray-700">Audit stages</p>
          <div className="space-y-3">
            {data.stages.map((stage) => {
              let stageLabel: string
              if (stage.stage_type === 'stage_1')      stageLabel = 'Stage 1 — Documentation review'
              else if (stage.stage_type === 'stage_2') stageLabel = 'Stage 2 — On-site audit'
              else { survCount += 1; stageLabel = `Surveillance ${survCount}` }
              return (
                <StageCard
                  key={stage.id}
                  stage={stage}
                  label={stageLabel}
                  allStages={data.stages}
                  auditSetId={id}
                  onSuccess={invalidate}
                  auditors={auditors}
                  auditorsLoading={auditorsLoading}
                  manDayResult={data.man_day_result}
                  auditType={data.audit_type ?? null}
                  eaCode={data.ea_code ?? null}
                  standards={(data.standards ?? []) as string[]}
                  requiredScope={data.required_scope ?? null}
                />
              )
            })}
          </div>
        </div>
      )}

      <ManDaySection result={data.man_day_result} />

      {/* Client Messages — Prompt 06 (additive, bottom of page) */}
      <div className="mt-8">
        <h2 className="mb-3 text-sm font-semibold uppercase tracking-wide text-gray-700">
          Client Messages
        </h2>
        <div className="overflow-hidden rounded-xl border bg-white" style={{ height: 400 }}>
          <MessageThread
            fetchUrl={`/audit-sets/${id}/messages`}
            postUrl={`/audit-sets/${id}/messages`}
          />
        </div>
      </div>

      {/* Certification complete callout — Prompt 20 */}
      {data.workflow_status === 'certified' && (
        <div className="flex items-start gap-4 rounded-xl border border-emerald-300 bg-emerald-50 p-5">
          <span className="mt-0.5 text-2xl leading-none select-none">🎉</span>
          <div>
            <p className="font-semibold text-emerald-900 text-sm">
              Certification Issued
            </p>
            <p className="mt-1 text-sm text-emerald-800">
              The committee has approved the audit report and the workflow has advanced to{' '}
              <strong>Certified</strong>. Upload the signed certificate document using the{' '}
              <strong>Shared Documents</strong> section below — select{' '}
              <em>Certificate</em> as the document type. It will be released to the client
              portal automatically.
            </p>
            {data.cert_issued_date && (
              <p className="mt-2 text-xs text-emerald-700">
                Certificate issued: {formatDate(data.cert_issued_date)}
              </p>
            )}
          </div>
        </div>
      )}

      {/* Shared Documents — Prompt 07 (additive, bottom of page) */}
      <SharedDocumentsSection auditSetId={id} />

      {/* Internal CB Approvals — Prompt 13 (FR.218 / FR.222) */}
      <InternalApprovalsSection
        auditSetId={id}
        workflowStatus={data.workflow_status ?? null}
      />

      {/* Certification Committee — Prompt 14 (reviewer / decision maker appointments) */}
      <CommitteeSection
        auditSetId={id}
        workflowStatus={data.workflow_status ?? null}
      />

      {/* Meeting Attendees — Prompt 15 (FR.225 opening / closing meeting signatures) */}
      <MeetingAttendeesSection
        auditSetId={id}
        workflowStatus={data.workflow_status ?? null}
      />

      {/* Auditor Assessments — Prompt 16 (FR.211 client rates auditors post-audit) */}
      <AssessmentManagementSection
        auditSetId={id}
        workflowStatus={data.workflow_status ?? null}
      />

      {/* NC Forms — Prompt 17 (FR.230 two-party signing: Lead Auditor → client) */}
      <NCFormManagementSection
        auditSetId={id}
        workflowStatus={data.workflow_status ?? null}
      />

      {/* Impartiality Declarations — Prompt 18 (FR.224 each audit team member self-signs) */}
      <DeclarationManagementSection
        auditSetId={id}
        workflowStatus={data.workflow_status ?? null}
      />

      {/* Audit Reports — Prompt 19 (FR.231/FR.229/FR.232 two-party signing) */}
      <AuditReportSection
        auditSetId={id}
        workflowStatus={data.workflow_status ?? null}
      />
    </div>
  )
}
