'use client'

import { useState, useEffect, useRef, useMemo, useCallback } from 'react'
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
import { FR233Panel } from '@/components/ui/FR233Panel'
// Portal 55 — MeetingAttendeesSection removed from the planner view. FR.225
// signers are now picked from the client's employee roster (ClientOrgEmployee)
// at upload time and embedded in the template; there is no separate OTP invite
// flow to manage from the CB side.
import { AssessmentManagementSection } from '@/components/ui/AssessmentManagementSection'
import { NCFormManagementSection } from '@/components/ui/NCFormManagementSection'
import { DeclarationManagementSection } from '@/components/ui/DeclarationManagementSection'
import { AuditReportSection } from '@/components/ui/AuditReportSection'
import { WorkflowStatusBar } from '@/components/ui/WorkflowStatusBar'
import type { AuditSetResponse, AuditSite, CommitteeTeamMember, StageResponse, ManDayResult, AuditorSummary, AuditorAvailabilityItem, RequiredScope } from '@/types'

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

// ── NC Management types (Portal 103) ─────────────────────────────────────────

interface NCEvidence {
  id:          string
  file_name:   string | null
  upload_type: string
  uploaded_at: string
  round_number: number
}

interface NCReview {
  id:          string
  decision:    string
  notes:       string | null
  reviewed_at: string
  round_number: number
}

interface NCItem {
  id:          string
  nc_index:    number
  category:    string
  description: string
  status:      string
  due_date:    string | null
  evidence:    NCEvidence[]
  reviews:     NCReview[]
}

interface NCDecision {
  id:          string
  audit_set_id: string
  no_nc:       boolean
  notes:       string | null
  decided_at:  string
  items:       NCItem[]
}

interface NCItemDraft {
  category:    string
  description: string
}

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
  observers:         TeamMember[]
  trainees:          TeamMember[]
}

function parseTeamMembers(arr: unknown[] | null | undefined): TeamMember[] {
  if (!arr || !arr.length) return []
  return (arr as { id?: string; name?: string; ea_code?: string }[])
    .filter((a) => a.name)
    .map((a) => ({ id: a.id ?? '', name: a.name!, ea_code: a.ea_code ?? '' }))
}

function buildStageEdit(s: StageResponse): StageEdit {
  return {
    lead_auditor_id:   s.lead_auditor_id   ?? '',  // Portal 50a fix: preserve from API
    lead_auditor_name: s.lead_auditor_name ?? '',
    audit_date_start:  s.audit_date_start  ?? '',
    audit_date_end:    s.audit_date_end    ?? '',
    auditors:          parseTeamMembers(s.auditors as unknown[]),
    technical_experts: parseTeamMembers(s.technical_experts as unknown[]),
    observers:         parseTeamMembers(s.observers as unknown[]),
    trainees:          parseTeamMembers((s as StageResponse & { trainees?: unknown[] }).trainees as unknown[]),
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

/** Given a start date (YYYY-MM-DD) and a number of audit days, return the end date.
 *  All days of the week are counted — audits may run on any day including weekends. */
function suggestEndDate(startISO: string, auditDays: number): string {
  const d = new Date(startISO)
  // day 1 = the start date itself; add the remaining days
  d.setDate(d.getDate() + Math.max(0, Math.round(auditDays) - 1))
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

/** Count all calendar days between two dates (inclusive). Weekends are valid audit days. */
function calendarDaysBetween(start: string, end: string): number {
  const s = new Date(start)
  const e = new Date(end)
  return Math.max(1, Math.round((e.getTime() - s.getTime()) / 86_400_000) + 1)
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
  teNames?: Set<string>,
): CoverageResult[] {
  const teamAuditors = allAuditors.filter(
    (a) => teamMembers.some((m) => (m.id ? m.id === a.id : m.name === a.name))
  )

  const labelName = (name: string | null) =>
    name && teNames?.has(name) ? `${name} (TE)` : name

  return requiredStandards.map((std) => {
    const stdNorm = std.toLowerCase().replace('iso ', '').replace(/\s/g, '')
    const scopeType = standardUsesCodes(std)
    const rsEntry = requiredScope?.[std]

    // ── Per-code check when requiredScope is available ──────────────────────
    if (rsEntry && rsEntry.codes.length > 0) {
      const codeResults = rsEntry.codes.map((code) => {
        const coveringAuditor = teamAuditors.find((a) => {
          // Standard path: auditor covers this code for this specific standard
          const cs = a.covered_scope?.[std]
          if (cs && cs.includes(code)) return true
          // TE path: a Technical Expert's EA code applies to ALL audit standards,
          // not only the standard they hold a formal auditor qualification for.
          if (teNames?.has(a.name ?? '')) {
            return Object.values(a.covered_scope ?? {}).some((codes) => codes.includes(code))
          }
          return false
        })
        const coveredBy = labelName(coveringAuditor?.name ?? null)
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
      // TE short-circuit: if this auditor is a TE and covers the client EA code
      // in any standard, they satisfy this standard's coverage requirement.
      if (teNames?.has(a.name ?? '') && scopeType === 'ea' && clientEACode) {
        const clientNum = clientEACode.replace(/[^0-9]/g, '')
        const coversEA = Object.values(a.covered_scope ?? {}).some((codes) =>
          codes.some((c) => c.replace(/[^0-9]/g, '') === clientNum)
        )
        if (coversEA) return true
      }

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
      coveredBy: labelName(cover?.name ?? null),
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

/** Returns allowed risk/complexity options for an EA-type standard. */
function riskOptions(stdName: string): string[] {
  if (stdName.includes('14001')) return ['High', 'Medium', 'Low', 'Limited']
  if (stdName.includes('9001') || stdName.includes('45001')) return ['High', 'Medium', 'Low']
  return []  // non-EA standards have no risk level
}

/** Badge style for a risk/complexity value. */
function riskBadgeStyle(risk: string): React.CSSProperties {
  if (risk === 'High')    return { background: '#FEE2E2', color: '#991B1B', border: '1px solid #FCA5A5' }
  if (risk === 'Medium')  return { background: '#FEF3C7', color: '#92400E', border: '1px solid #FCD34D' }
  if (risk === 'Low')     return { background: '#DCFCE7', color: '#166534', border: '1px solid #86EFAC' }
  if (risk === 'Limited') return { background: '#EFF6FF', color: '#1E40AF', border: '1px solid #93C5FD' }
  return {}
}

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

function RetroactiveBanner() {
  return (
    <div className="mb-4 flex items-start gap-3 rounded-lg border border-amber-200 bg-amber-50 px-4 py-3">
      <span className="mt-0.5 text-base leading-none text-amber-500">⚠</span>
      <div>
        <p className="text-sm font-semibold text-amber-800">Retroactive Operation Mode</p>
        <p className="mt-0.5 text-xs text-amber-700">
          Historical data entry is active. Use the <strong>Effective date</strong> field
          next to each workflow button to record when transitions actually occurred.
          Stage dates and certificate dates are already freely editable.
        </p>
      </div>
    </div>
  )
}

function PlanOverview({
  data,
  auditSetId,
  onInvalidate,
  userRole = '',
}: {
  data: AuditSetResponse
  auditSetId: string
  onInvalidate: () => void
  userRole?: string
}) {
  const isRealtimeMode = userRole === 'planner_us'
  const [integLevel, setIntegLevel] = useState<string>(data.scope_integration_level ?? 'Medium')
  const [certFee, setCertFee] = useState(data.certification_fee != null ? String(data.certification_fee) : '')
  const [survFee, setSurvFee] = useState(data.surveillance_fee != null ? String(data.surveillance_fee) : '')
  const [currency, setCurrency] = useState(data.currency ?? 'USD')
  const [feeSaved, setFeeSaved] = useState(false)
  const [nacText, setNacText] = useState<string>(data.non_applicable_clauses ?? '')
  const [nacSuggestions, setNacSuggestions] = useState<NACSuggestion[]>([])
  const [nacSaved, setNacSaved] = useState(false)
  const [nacEmptyMsg, setNacEmptyMsg] = useState(false)
  // Keep textarea in sync with server value after PUT round-trips invalidate the query.
  useEffect(() => { setNacText(data.non_applicable_clauses ?? '') }, [data.non_applicable_clauses])

  // Scope editor state
  const [scopeEditing, setScopeEditing] = useState(false)
  const [scopeDraft, setScopeDraft] = useState<RequiredScope>(data.required_scope ?? {})
  const [newCodeInput, setNewCodeInput] = useState<Record<string, string>>({})
  const [scopeSaved, setScopeSaved] = useState(false)
  // Keep draft in sync whenever server data changes (but not while the user is editing)
  useEffect(() => {
    if (!scopeEditing) setScopeDraft(data.required_scope ?? {})
  }, [data.required_scope])  // eslint-disable-line react-hooks/exhaustive-deps

  // Portal 78 — per-site details inline editor
  const [sitesEditing, setSitesEditing] = useState(false)
  const [sitesDraft, setSitesDraft] = useState<AuditSite[]>(data.sites ?? [])
  useEffect(() => { setSitesDraft(data.sites ?? []) }, [data.sites])

  const { mutate: saveSites, isPending: savingSites } = useMutation({
    mutationFn: () =>
      api.put(`/audit-sets/${auditSetId}/planning`, { sites: sitesDraft }),
    onSuccess: () => { onInvalidate(); setSitesEditing(false) },
  })

  // Plan reference number (client_reference)
  const [refNum, setRefNum]           = useState<string>(data.client_reference ?? '')
  const [refNumSaved, setRefNumSaved] = useState(false)
  useEffect(() => {
    setRefNum(data.client_reference ?? '')
  }, [data.client_reference])

  // Application date — retroactive override
  const [appDate, setAppDate] = useState<string>(
    data.application_date ? String(data.application_date) : ''
  )
  const [appDateSaved, setAppDateSaved] = useState(false)
  useEffect(() => {
    setAppDate(data.application_date ? String(data.application_date) : '')
  }, [data.application_date])

  const { mutate: saveRefNum, isPending: savingRefNum } = useMutation({
    mutationFn: () =>
      api.put(`/audit-sets/${auditSetId}/planning`, {
        client_reference: refNum.trim() || null,
      }),
    onSuccess: () => {
      onInvalidate()
      setRefNumSaved(true)
      setTimeout(() => setRefNumSaved(false), 2000)
    },
  })

  const { mutate: saveAppDate, isPending: savingAppDate } = useMutation({
    mutationFn: () =>
      api.put(`/audit-sets/${auditSetId}/planning`, {
        application_date: appDate || null,
      }),
    onSuccess: () => {
      onInvalidate()
      setAppDateSaved(true)
      setTimeout(() => setAppDateSaved(false), 2000)
    },
  })

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
        currency,
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

  /** Merge any still-typed (un-Enter'd) codes into a given scope draft. */
  function flushNewCodes(draft: RequiredScope): RequiredScope {
    const result: RequiredScope = {}
    for (const [std, entry] of Object.entries(draft)) {
      const raw = newCodeInput[std] ?? ''
      const extras = raw
        .split(',')
        .map((t) => t.trim().toUpperCase())
        .filter((t) => t.length > 0 && !entry.codes.includes(t))
      result[std] = extras.length > 0
        ? { ...entry, codes: [...entry.codes, ...extras] }
        : entry
    }
    return result
  }

  const { mutate: saveScope, isPending: savingScope } = useMutation({
    mutationFn: (draft: RequiredScope) =>
      api.put<AuditSetResponse>(`/audit-sets/${auditSetId}/planning`, {
        required_scope: draft,
      }),
    onSuccess: () => {
      onInvalidate()
      setScopeEditing(false)
      setScopeSaved(true)
      setTimeout(() => setScopeSaved(false), 2000)
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

      {/* Plan reference number — planner-assigned */}
      <div className="mb-4 flex flex-wrap items-center gap-3">
        <label className="text-xs font-medium text-gray-600">Plan / Set No.</label>
        <input
          type="text"
          value={refNum}
          onChange={e => { setRefNum(e.target.value); setRefNumSaved(false) }}
          placeholder={`#${data.plan_number}`}
          className="rounded border border-gray-200 px-2 py-1 text-sm focus:border-[#1A4731] focus:outline-none"
        />
        <button
          type="button"
          onClick={() => saveRefNum()}
          disabled={savingRefNum}
          className="rounded-lg bg-[#1A4731] px-3 py-1 text-xs font-medium text-white hover:bg-[#143828] disabled:opacity-50"
        >
          {refNumSaved ? 'Saved ✓' : savingRefNum ? 'Saving…' : 'Save'}
        </button>
        {data.client_reference && (
          <span className="text-xs text-gray-400">Currently: {data.client_reference}</span>
        )}
      </div>

      {/* Application date — retroactive override (hidden in realtime mode) */}
      {!isRealtimeMode && (
        <div className="mb-4 flex flex-wrap items-center gap-3">
          <label className="text-xs font-medium text-gray-600">Application date</label>
          <input
            type="date"
            value={appDate}
            onChange={e => setAppDate(e.target.value)}
            className="rounded border border-gray-200 px-2 py-1 text-sm focus:border-[#1A4731] focus:outline-none"
          />
          <button
            type="button"
            onClick={() => saveAppDate()}
            disabled={savingAppDate}
            className="rounded-lg bg-[#1A4731] px-3 py-1 text-xs font-medium text-white hover:bg-[#143828] disabled:opacity-50"
          >
            {appDateSaved ? 'Saved ✓' : savingAppDate ? 'Saving…' : 'Save'}
          </button>
          {data.application_date && (
            <span className="text-xs text-gray-400">
              Currently: {new Date(data.application_date).toLocaleDateString('en-GB', {
                day: 'numeric', month: 'short', year: 'numeric',
              })}
            </span>
          )}
        </div>
      )}

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

        {/* Portal 78 — Additional sites */}
        {((data.sites && data.sites.length > 0) || sitesEditing) && (
          <div className="col-span-3">
            <div className="flex items-center justify-between mb-2">
              <p className="font-medium uppercase tracking-wide text-gray-400" style={{ fontSize: 11 }}>
                Additional sites ({sitesDraft.length})
              </p>
              {!sitesEditing ? (
                <button
                  type="button"
                  onClick={() => setSitesEditing(true)}
                  className="flex items-center gap-1 text-xs text-certiva-primary hover:underline"
                >
                  <Pencil size={11} /> Edit sites
                </button>
              ) : (
                <div className="flex items-center gap-2">
                  <button
                    type="button"
                    onClick={() => { setSitesDraft(data.sites ?? []); setSitesEditing(false) }}
                    className="text-xs text-gray-400 hover:text-gray-600"
                  >Cancel</button>
                  <button
                    type="button"
                    disabled={savingSites}
                    onClick={() => saveSites()}
                    className="flex items-center gap-1 rounded bg-certiva-primary px-2 py-1 text-xs text-white disabled:opacity-50"
                  >
                    {savingSites ? <Loader2 size={11} className="animate-spin" /> : <Check size={11} />}
                    Save
                  </button>
                </div>
              )}
            </div>
            {!sitesEditing ? (
              <div className="space-y-2">
                {sitesDraft.map((site, i) => (
                  <div key={i} className="rounded-md border border-gray-100 bg-gray-50 px-3 py-2 text-xs text-gray-600">
                    <span className="font-medium">{site.name || `Site ${i + 1}`}</span>
                    {site.address && <span className="text-gray-400"> · {site.address}</span>}
                    {site.employee_count != null && site.employee_count > 0 && (
                      <span className="text-gray-400"> · {site.employee_count} emp.</span>
                    )}
                    {site.process && <span className="text-gray-400"> · {site.process}</span>}
                  </div>
                ))}
                {sitesDraft.length === 0 && (
                  <p className="text-xs text-amber-600 bg-amber-50 border border-amber-200 rounded px-3 py-2">
                    Sites were declared but details are missing — edit to add site names, addresses and headcounts so audit duration can be calculated correctly.
                  </p>
                )}
              </div>
            ) : (
              <div className="space-y-3">
                {sitesDraft.map((site, i) => (
                  <div key={i} className="rounded-lg border border-gray-200 bg-gray-50 p-3 space-y-2">
                    <div className="flex items-center justify-between">
                      <span className="text-xs font-medium text-gray-600">Site {i + 1}</span>
                      <button
                        type="button"
                        onClick={() => setSitesDraft(sitesDraft.filter((_, idx) => idx !== i))}
                        className="text-xs text-red-400 hover:text-red-600"
                      ><Trash2 size={11} /></button>
                    </div>
                    <div className="grid grid-cols-2 gap-2">
                      <div>
                        <label className="block text-[10px] text-gray-400 mb-0.5">Name / label</label>
                        <input
                          className="w-full rounded border border-gray-200 px-2 py-1 text-xs focus:outline-none focus:ring-1 focus:ring-certiva-primary"
                          placeholder="e.g. İstanbul branch"
                          value={site.name ?? ''}
                          onChange={e => setSitesDraft(sitesDraft.map((s, idx) => idx === i ? { ...s, name: e.target.value } : s))}
                        />
                      </div>
                      <div>
                        <label className="block text-[10px] text-gray-400 mb-0.5">Employees</label>
                        <input
                          type="number" min="0"
                          className="w-full rounded border border-gray-200 px-2 py-1 text-xs focus:outline-none focus:ring-1 focus:ring-certiva-primary"
                          placeholder="0"
                          value={site.employee_count ?? ''}
                          onChange={e => setSitesDraft(sitesDraft.map((s, idx) => idx === i ? { ...s, employee_count: parseInt(e.target.value) || 0 } : s))}
                        />
                      </div>
                      <div className="col-span-2">
                        <label className="block text-[10px] text-gray-400 mb-0.5">Address</label>
                        <input
                          className="w-full rounded border border-gray-200 px-2 py-1 text-xs focus:outline-none focus:ring-1 focus:ring-certiva-primary"
                          placeholder="Street, City, Country"
                          value={site.address ?? ''}
                          onChange={e => setSitesDraft(sitesDraft.map((s, idx) => idx === i ? { ...s, address: e.target.value } : s))}
                        />
                      </div>
                      <div className="col-span-2">
                        <label className="block text-[10px] text-gray-400 mb-0.5">Main activities</label>
                        <input
                          className="w-full rounded border border-gray-200 px-2 py-1 text-xs focus:outline-none focus:ring-1 focus:ring-certiva-primary"
                          placeholder="e.g. Warehousing and distribution"
                          value={site.process ?? ''}
                          onChange={e => setSitesDraft(sitesDraft.map((s, idx) => idx === i ? { ...s, process: e.target.value } : s))}
                        />
                      </div>
                    </div>
                  </div>
                ))}
                <button
                  type="button"
                  onClick={() => setSitesDraft([...sitesDraft, { name: '', address: '', employee_count: 0, process: '' }])}
                  className="text-xs text-certiva-primary hover:underline"
                >+ Add site</button>
              </div>
            )}
          </div>
        )}

        {rs && Object.keys(rs).length > 0 && (
          <div className="col-span-3">
            <div className="mb-1 flex items-center justify-between">
              <p className="font-medium uppercase tracking-wide text-gray-400" style={{ fontSize: 11 }}>Required scope (derived)</p>
              {!scopeEditing && (
                <button
                  type="button"
                  onClick={() => { setScopeDraft(data.required_scope ?? {}); setScopeEditing(true) }}
                  className="flex items-center gap-1 text-xs text-certiva-primary hover:underline"
                >
                  <Pencil size={11} /> Edit
                </button>
              )}
            </div>

            {!scopeEditing ? (
              /* ── VIEW MODE — read-only badges ── */
              <div className="space-y-1">
                {Object.entries(rs).map(([std, entry]) => (
                  <div key={std} className="flex flex-wrap items-center gap-1.5">
                    <span className="text-xs font-medium text-gray-600 w-24 shrink-0">{std}</span>
                    {entry.codes.length === 0 ? (
                      <span className="text-xs text-gray-400 italic">
                        {entry.type === 'ea'
                          ? 'EA-based (CB accreditation scope — add manually if needed)'
                          : 'no codes derived'}
                      </span>
                    ) : entry.codes.map((code) => (
                      <span key={code} className="rounded px-2 py-0.5 text-xs font-medium" style={scopeBadgeStyle(entry.type, code)}>
                        {code}
                      </span>
                    ))}
                    {entry.type === 'ea' && entry.risk && (
                      <span
                        className="rounded px-2 py-0.5 text-xs font-medium"
                        style={riskBadgeStyle(entry.risk)}
                        title="Risk/complexity category per IAF MD 5:2023 — click Edit to override"
                      >
                        {entry.risk}
                      </span>
                    )}
                  </div>
                ))}
              </div>
            ) : (
              /* ── EDIT MODE — removable chips + add-code input per standard ── */
              <div className="space-y-2">
                {Object.entries(scopeDraft).map(([std, entry]) => (
                  <div key={std} className="flex flex-wrap items-start gap-1.5">
                    <span className="w-24 shrink-0 pt-1 text-xs font-medium text-gray-600">{std}</span>
                    <div className="flex flex-1 flex-wrap items-center gap-1">
                      {entry.codes.map((code) => (
                        <span
                          key={code}
                          className="flex items-center gap-0.5 rounded px-2 py-0.5 text-xs font-medium"
                          style={scopeBadgeStyle(entry.type, code)}
                        >
                          {code}
                          <button
                            type="button"
                            title={`Remove ${code}`}
                            className="ml-0.5 leading-none opacity-60 hover:opacity-100"
                            onClick={() =>
                              setScopeDraft((prev) => ({
                                ...prev,
                                [std]: { ...entry, codes: entry.codes.filter((c) => c !== code) },
                              }))
                            }
                          >
                            ×
                          </button>
                        </span>
                      ))}
                      <input
                        type="text"
                        placeholder="Add code…"
                        value={newCodeInput[std] ?? ''}
                        onChange={(e) => setNewCodeInput((p) => ({ ...p, [std]: e.target.value }))}
                        onKeyDown={(e) => {
                          if (e.key !== 'Enter') return
                          e.preventDefault()
                          const tokens = (newCodeInput[std] ?? '')
                            .split(',')
                            .map((t) => t.trim().toUpperCase())
                            .filter((t) => t.length > 0 && !entry.codes.includes(t))
                          if (tokens.length > 0) {
                            setScopeDraft((prev) => ({
                              ...prev,
                              [std]: { ...entry, codes: [...entry.codes, ...tokens] },
                            }))
                          }
                          setNewCodeInput((p) => ({ ...p, [std]: '' }))
                        }}
                        className="h-6 w-24 rounded border border-gray-200 px-1.5 text-xs focus:border-certiva-primary focus:outline-none"
                      />
                      {/* Risk/complexity override — EA-type standards only */}
                      {entry.type === 'ea' && riskOptions(std).length > 0 && (
                        <select
                          className="h-6 rounded border border-gray-200 px-1 text-xs focus:border-certiva-primary focus:outline-none"
                          style={entry.risk ? riskBadgeStyle(entry.risk) : {}}
                          value={entry.risk ?? 'Medium'}
                          title="Risk/complexity per IAF MD 5:2023 — override if needed"
                          onChange={(e) =>
                            setScopeDraft((prev) => ({
                              ...prev,
                              [std]: { ...entry, risk: e.target.value },
                            }))
                          }
                        >
                          {riskOptions(std).map((opt) => (
                            <option key={opt} value={opt}>{opt}</option>
                          ))}
                        </select>
                      )}
                    </div>
                  </div>
                ))}
                <div className="mt-2 flex items-center gap-2">
                  <button
                    type="button"
                    disabled={savingScope}
                    onClick={() => {
                      const flushed = flushNewCodes(scopeDraft)
                      setScopeDraft(flushed)
                      setNewCodeInput({})
                      saveScope(flushed)
                    }}
                    className="flex items-center gap-1 rounded-lg bg-certiva-primary px-3 py-1.5 text-xs font-medium text-white hover:opacity-90 disabled:opacity-50"
                  >
                    {savingScope ? <Loader2 size={11} className="animate-spin" /> : <Check size={11} />}
                    Save scope
                  </button>
                  <button
                    type="button"
                    onClick={() => { setScopeEditing(false); setScopeDraft(data.required_scope ?? {}) }}
                    className="rounded-lg border border-gray-200 px-3 py-1.5 text-xs text-gray-500 hover:bg-gray-50"
                  >
                    Cancel
                  </button>
                  {scopeSaved && (
                    <span className="flex items-center gap-1 text-xs text-green-600">
                      <Check size={11} /> Saved
                    </span>
                  )}
                </div>
              </div>
            )}
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
            <div className="w-28">
              <label className={lblCls}>Currency</label>
              {(userRole === 'planner' || userRole === 'planner_us' || userRole === 'admin') ? (
                <select
                  className={inputCls}
                  value={currency}
                  onChange={(e) => setCurrency(e.target.value)}
                >
                  <option value="USD">USD ($)</option>
                  <option value="EUR">EUR (€)</option>
                  <option value="TRY">TRY (₺)</option>
                </select>
              ) : (
                <div className={inputCls + ' bg-gray-50 text-gray-500 cursor-not-allowed'}>
                  {currency}
                </div>
              )}
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


// ── FR.218 Reviewer Picker (Portal 51 — FSMS/ISMS only) ──────────────────────

function needsFr218Reviewer(standards: string[]): boolean {
  // Mirror _needs_reviewer() in documents_router.py:
  // match both short-code format ("FSMS", "ISMS") and ISO-number format ("22000", "27001")
  const joined = standards.join(' ').toUpperCase()
  return ['FSMS', 'ISMS', '22000', '27001'].some(kw => joined.includes(kw))
}

function FR218ReviewerPicker({
  auditSetId, currentReviewerId, currentReviewerName, onSaved,
}: {
  auditSetId: string
  currentReviewerId: string | null | undefined
  currentReviewerName: string | null | undefined
  onSaved: (id: string | null, name: string | null) => void
}) {
  const [auditors,    setAuditors]    = useState<{ id: string; name: string }[]>([])
  const [selected,    setSelected]    = useState(currentReviewerId ?? '')
  const [saving,      setSaving]      = useState(false)
  const [msg,         setMsg]         = useState('')
  const [fetchError,  setFetchError]  = useState('')

  useEffect(() => {
    setFetchError('')
    api.get<{ id: string; name: string }[]>(`/audit-sets/${auditSetId}/fr218/eligible-reviewers`)
      .then(r => setAuditors(r.data))
      .catch(() => setFetchError('Could not load eligible reviewers. Check your connection or contact support.'))
  }, [auditSetId])

  useEffect(() => {
    setSelected(currentReviewerId ?? '')
  }, [currentReviewerId])

  async function save() {
    setSaving(true)
    setMsg('')
    try {
      const aud = auditors.find(a => a.id === selected) ?? null
      await api.patch(`/audit-sets/${auditSetId}/fr218-reviewer`, {
        fr218_reviewer_id:   aud?.id ?? null,
        fr218_reviewer_name: aud?.name ?? null,
      })
      onSaved(aud?.id ?? null, aud?.name ?? null)
      setMsg('Saved ✓')
    } catch {
      setMsg('Error saving')
    } finally {
      setSaving(false)
    }
  }

  return (
    <div className="flex flex-wrap items-center gap-3">
      {fetchError && (
        <p className="mb-2 text-xs text-red-500">{fetchError}</p>
      )}
      <select
        value={selected}
        onChange={e => setSelected(e.target.value)}
        className="rounded-lg border px-3 py-1.5 text-sm focus:outline-none focus:ring-2 focus:ring-[#1A4731]/30"
      >
        <option value="">— Select reviewer —</option>
        {auditors.map(a => (
          <option key={a.id} value={a.id}>{a.name}</option>
        ))}
      </select>
      <button
        type="button"
        onClick={save}
        disabled={saving}
        className="rounded-lg bg-[#1A4731] px-3 py-1.5 text-xs font-medium text-white disabled:opacity-40"
      >
        {saving ? 'Saving…' : 'Assign'}
      </button>
      {currentReviewerName && (
        <span className="text-xs text-gray-500">Current: <strong>{currentReviewerName}</strong></span>
      )}
      {msg && <span className={`text-xs ${msg.startsWith('Error') ? 'text-red-600' : 'text-green-600'}`}>{msg}</span>}
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


// ── Committee Planning Card (Portal 66) ──────────────────────────────────────
// Reuses the same chip + dropdown + coverage-breakdown pattern as StageCard.
// Pool data comes from GET /planning/committee/available-auditors (Portal 64)
// which returns covered_scope: {iso_std: [codes]} — identical to /auditors/available.

interface AvailableCommitteeAuditor {
  id: string
  full_name: string
  email: string
  ea_codes: string[]
  standards: string[]        // ISO names — all standards the auditor is qualified for
  covers_audit: boolean
  covered_scope: Record<string, string[]>   // {iso_std: [matched_codes]}
}

// Short-code → ISO name map (mirrors backend _STD_CODE_TO_ISO)
const _COMMITTEE_STD_TO_ISO: Record<string, string> = {
  "QMS": "ISO 9001", "EMS": "ISO 14001", "OHSMS": "ISO 45001",
  "FSMS": "ISO 22000", "FSSC 22000": "FSSC 22000", "MDQMS": "ISO 13485",
  "MDMS": "ISO 13485", "ISMS": "ISO 27001", "ENMS": "ISO 50001",
  "EnMS": "ISO 50001", "ABMS": "ISO 37001", "CMS": "ISO 37301",
}

function CommitteePlanningCard({
  auditSetId,
  stages,
  standards,
  eaCode,
  initialCommittee,
  onSuccess,
}: {
  auditSetId: string
  stages: StageResponse[]
  standards: string[]
  eaCode: string | null
  initialCommittee: CommitteeTeamMember[] | null | undefined
  onSuccess: () => void
}) {
  // Ordered list: index 0 = Chairperson, rest = Members
  // Plain initializer — initialCommittee arrives asynchronously, so the lazy
  // initializer would always see undefined on first render. Restoration is
  // handled by the hasInitializedRef useEffect below.
  const [selected, setSelected] = useState<AvailableCommitteeAuditor[]>([])
  // Available pool — all eligible auditors NOT already selected
  const [pool, setPool]             = useState<AvailableCommitteeAuditor[]>([])
  const [loadingPool, setLoadingPool] = useState(false)
  const [saving, setSaving]         = useState(false)
  const [saved, setSaved]           = useState(false)
  const [error, setError]           = useState<string | null>(null)

  // Ref lets the pool-fetch effect read current selected without a stale closure.
  const selectedRef = useRef<AvailableCommitteeAuditor[]>(selected)
  selectedRef.current = selected

  // Ref guard: restores saved committee from initialCommittee exactly once,
  // even though the prop arrives asynchronously after first render.
  const hasInitializedRef = useRef(false)

  useEffect(() => {
    if (hasInitializedRef.current) return          // already initialized — don't overwrite user edits
    if (!initialCommittee || initialCommittee.length === 0) return   // nothing saved yet

    hasInitializedRef.current = true

    const restored: AvailableCommitteeAuditor[] = initialCommittee.map((m) => ({
      id:           m.id,
      full_name:    m.name ?? '',       // backend stores "name"; UI expects "full_name"
      email:        m.email ?? '',
      ea_codes:     m.ea_codes ?? [],
      standards:    m.standards ?? [],
      covers_audit: true,
      covered_scope: {},                // enriched by pool-fetch useEffect when pool arrives
    }))

    setSelected(restored)

    // If the pool has already loaded (race: pool resolved before data),
    // also remove the restored members from the dropdown pool.
    const restoredIds = new Set(restored.map((r) => r.id))
    setPool((prev) => prev.filter((a) => !restoredIds.has(a.id)))
  }, [initialCommittee])

  // Stable string key from all stage team IDs — effect re-fires when assignments change.
  // Includes ik_experts and evaluators so they are excluded from the committee pool.
  const stageAuditorIdsKey = useMemo(() => {
    const ids: string[] = []
    for (const s of stages) {
      if (s.lead_auditor_id) ids.push(s.lead_auditor_id)
      for (const group of [s.auditors, s.technical_experts, s.observers, s.ik_experts, s.evaluators] as ({ id?: string } | null)[][]) {
        for (const a of group ?? []) { if (a?.id) ids.push(a.id) }
      }
    }
    return ids.sort().join(',')
  }, [stages])

  useEffect(() => {
    setLoadingPool(true)
    // Never exclude already-selected committee members from the backend query —
    // we need their covered_scope in the response to enrich their data.
    // The pool dropdown still hides them via setPool's selectedIds filter below.
    const committeeIds = new Set(selectedRef.current.map((m) => m.id))
    const excludeParam = stageAuditorIdsKey
      ? stageAuditorIdsKey.split(',').filter(id => !committeeIds.has(id)).join(',')
      : ''
    const qs = excludeParam ? `?exclude_auditor_ids=${encodeURIComponent(excludeParam)}` : ''
    api.get<AvailableCommitteeAuditor[]>(`/audit-sets/${auditSetId}/planning/committee/available-auditors${qs}`)
      .then((r) => {
        const all = r.data
        const byId = new Map(all.map((a) => [a.id, a]))
        const currentSelected = selectedRef.current
        const selectedIds = new Set(currentSelected.map((m) => m.id))
        // Enrich pre-selected members with covered_scope from the fresh pool
        setSelected(currentSelected.map((m) => {
          const enriched = byId.get(m.id)
          return enriched ? { ...m, covered_scope: enriched.covered_scope, covers_audit: enriched.covers_audit } : m
        }))
        setPool(all.filter((a) => !selectedIds.has(a.id)))
      })
      .catch(() => setError('Failed to load available auditors'))
      .finally(() => setLoadingPool(false))
  }, [auditSetId, stageAuditorIdsKey])

  function addMember(id: string) {
    const auditor = pool.find((a) => a.id === id)
    if (!auditor) return
    setSelected((prev) => [...prev, auditor])
    setPool((prev) => prev.filter((a) => a.id !== id))
    setError(null)
  }

  function removeMember(id: string) {
    const removed = selected.find((m) => m.id === id)
    if (!removed) return
    setSelected((prev) => prev.filter((m) => m.id !== id))
    setPool((prev) => [...prev, removed].sort((a, b) => (a.full_name ?? '').localeCompare(b.full_name ?? '')))
  }

  // Clear stale backend error whenever selection changes (e.g. a 422 from a prior
  // save attempt should vanish as soon as the user adjusts the committee).
  useEffect(() => { setError(null) }, [selected])

  // ── Coverage summary — per-code check (same as computeCoverage in StageCard) ──
  const auditStandardsISO = (standards ?? []).map((s) => _COMMITTEE_STD_TO_ISO[s] ?? s)

  // Step 1: derive required codes per standard from the union of pool covered_scope.
  // The backend puts only audit-relevant codes in covered_scope, so this union
  // represents exactly the codes that must be collectively covered.
  const requiredScopeMap: Record<string, string[]> = {}
  for (const a of pool) {
    for (const [std, codes] of Object.entries(a.covered_scope ?? {})) {
      requiredScopeMap[std] = [...new Set([...(requiredScopeMap[std] ?? []), ...codes])]
    }
  }
  // Also include codes from already-selected members so the map is complete
  // even when a member has been moved out of the pool.
  for (const m of selected) {
    for (const [std, codes] of Object.entries(m.covered_scope ?? {})) {
      requiredScopeMap[std] = [...new Set([...(requiredScopeMap[std] ?? []), ...codes])]
    }
  }

  // Step 2: for every required standard, check every required code individually.
  const coverageSummary = auditStandardsISO.map((std) => {
    const requiredCodes = requiredScopeMap[std] ?? []
    if (requiredCodes.length === 0) {
      // No EA code breakdown — simple qualification check
      const covered = selected.some((m) => m.standards.includes(std))
      return { standard: std, covered, coveredCodes: [] as { code: string; by: string }[], missingCodes: [] as string[] }
    }
    const codeResults = requiredCodes.map((code) => {
      const coveringMember = selected.find((m) => {
        // Direct coverage: member explicitly covers this standard + code
        if ((m.covered_scope?.[std] ?? []).includes(code)) return true
        // Cross-standard: sector expertise (EA code) spans all audit standards —
        // if the member covers this EA code for ANY standard, they cover it here too.
        return Object.values(m.covered_scope ?? {}).some((codes) => codes.includes(code))
      })
      return { code, coveredBy: coveringMember?.full_name ?? null }
    })
    return {
      standard: std,
      covered: codeResults.every((r) => r.coveredBy !== null),
      coveredCodes: codeResults.filter((r) => r.coveredBy !== null).map((r) => ({ code: r.code, by: r.coveredBy! })),
      missingCodes: codeResults.filter((r) => !r.coveredBy).map((r) => r.code),
    }
  })
  const coverageComplete = coverageSummary.length === 0 || coverageSummary.every((r) => r.covered)

  // Filter pool to only auditors with at least one covered code — same as StageCard's
  // dropdownList filter (coveredTotal > 0). Hides zero-match auditors entirely.
  const eligiblePool = pool.filter(
    (a) => Object.values(a.covered_scope ?? {}).flat().length > 0
  )

  async function handleSave() {
    if (selected.length === 0) { setError('Select at least one member (Chairperson)'); return }
    setSaving(true); setError(null)
    try {
      await api.put(`/audit-sets/${auditSetId}/planning`, {
        committee_members: selected.map((m, i) => ({
          id:        m.id,
          full_name: m.full_name,
          ea_codes:  m.ea_codes,
          standards: m.standards,
          role:      i === 0 ? 'chairperson' : 'member',
        })),
      })
      onSuccess(); setSaved(true); setTimeout(() => setSaved(false), 2500)
    } catch (e: unknown) {
      const detail = (e as { response?: { data?: { detail?: string } } })?.response?.data?.detail
      setError(detail ?? 'Save failed')
    } finally { setSaving(false) }
  }

  return (
    <div className="mt-4 rounded-xl border border-gray-100 bg-white p-5">
      <p className="mb-1 text-sm font-medium text-gray-700">Certification Committee</p>
      <p className="mb-3 text-xs text-gray-400">
        First added = Chairperson. Must collectively cover all standards and EA codes.
        Cannot include any Stage 1 or Stage 2 team member.
      </p>

      {/* Committee member chips — same visual style as stage auditor chips */}
      <div>
        <label className={lblCls}>Committee members</label>
        <div className="flex flex-wrap gap-1 mb-2 min-h-[24px]">
          {selected.map((m, i) => {
            const role = i === 0 ? 'chairperson' : 'member'
            // "EA 3 (ISO 9001) | CI CIV (ISO 22000)" — same format as stage coverLabel
            const scopeLabel = m.covered_scope && Object.keys(m.covered_scope).length > 0
              ? Object.entries(m.covered_scope)
                  .filter(([, codes]) => codes.length > 0)
                  .map(([std, codes]) => `${codes.join(' ')} (${std})`)
                  .join(' | ')
              : ''
            return (
              <span key={m.id}
                className="flex items-center gap-1 rounded-full px-2 py-0.5 text-xs"
                style={{ background: '#F0FAF4', color: '#1A4731', border: '1px solid #BBF7D0' }}>
                {m.full_name}
                <span className="opacity-60">— {role}</span>
                {scopeLabel && <span className="opacity-60">— {scopeLabel}</span>}
                <button type="button"
                  className="ml-1 text-gray-400 hover:text-red-500"
                  onClick={() => removeMember(m.id)}>
                  ×
                </button>
              </span>
            )
          })}
        </div>

        {/* Dropdown to add — identical pattern to "Add auditor…" in StageCard.
            Only auditors with coveredTotal > 0 are shown (same as StageCard dropdownList filter). */}
        {loadingPool && <p className="mb-1 text-xs text-gray-400">Loading available auditors…</p>}
        <select
          className={inputCls}
          value=""
          disabled={loadingPool}
          onChange={(e) => { if (e.target.value) addMember(e.target.value) }}
        >
          <option value="">
            {loadingPool ? 'Loading…' : `+ Add committee member… (${eligiblePool.length} qualifying)`}
          </option>
          {eligiblePool.map((a) => {
            // Show covered codes in option text — same format as stage auditor dropdown
            const coverLabel = ' — ' + Object.entries(a.covered_scope)
              .filter(([, codes]) => codes.length > 0)
              .map(([std, codes]) => `${codes.join(' ')} (${std})`)
              .join(' | ')
            return (
              <option key={a.id} value={a.id}>
                {a.full_name}{coverLabel}
              </option>
            )
          })}
        </select>
      </div>

      {/* Coverage summary — identical style to stage picker coverage block */}
      {coverageSummary.length > 0 && (
        <div
          className={`mt-3 rounded-md p-3 text-sm ${coverageComplete ? 'border border-green-200' : 'border border-amber-200'}`}
          style={{ background: coverageComplete ? '#F0FAF4' : '#FFFBEB' }}
        >
          <p className="font-medium mb-1" style={{ color: coverageComplete ? '#1A4731' : '#92400E' }}>
            {coverageComplete ? '✓ Committee covers all required standards' : '⚠ Coverage incomplete'}
          </p>
          {coverageSummary.map((r) => (
            <div key={r.standard} className="mt-0.5">
              <span className="text-xs" style={{ color: r.covered ? '#1A4731' : '#92400E' }}>
                {r.covered ? '✓' : '✗'} {r.standard}
              </span>
              {/* Per-code breakdown — same as stage picker codeResults display */}
              {r.coveredCodes.length > 0 || r.missingCodes.length > 0 ? (
                <div className="ml-4 mt-0.5 flex flex-wrap gap-x-3 gap-y-0.5">
                  {r.coveredCodes.map(({ code, by }) => (
                    <span key={code} className="text-xs" style={{ color: '#1A4731' }}>
                      ✓ {code} — {by.split(' ')[0]}
                    </span>
                  ))}
                  {r.missingCodes.map((code) => (
                    <span key={code} className="text-xs" style={{ color: '#92400E' }}>
                      ✗ {code} — not covered
                    </span>
                  ))}
                </div>
              ) : !r.covered ? (
                <span className="ml-1 text-xs" style={{ color: '#92400E' }}>
                  — not covered by any committee member
                </span>
              ) : null}
            </div>
          ))}
        </div>
      )}

      {error && <p className="mt-2 text-xs text-red-600">{error}</p>}

      <div className="mt-4 flex items-center gap-3">
        <button
          type="button"
          onClick={handleSave}
          disabled={saving || selected.length === 0 || !coverageComplete}
          className="flex items-center gap-1.5 rounded-lg px-4 py-1.5 text-sm font-medium text-white disabled:opacity-60 hover:opacity-90"
          style={{ background: '#1A4731' }}
        >
          {saving && <Loader2 size={13} className="animate-spin" />}
          Save committee
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
      d.setDate(d.getDate() + 14)   // 2-week lead time (any day of week)
      suggestedStart = d.toISOString().slice(0, 10)
    } else if (stage.stage_type === 'stage_2') {
      const stage1 = allStages.find((s) => s.stage_type === 'stage_1')
      if (!stage1?.audit_date_end) return   // need stage 1 end first
      const d = new Date(stage1.audit_date_end)
      d.setDate(d.getDate() + 7)   // 1-week gap after stage 1 (any day of week)
      suggestedStart = d.toISOString().slice(0, 10)
    }

    if (suggestedStart) {
      patch({
        audit_date_start: suggestedStart,
        audit_date_end: suggestEndDate(suggestedStart, recommended),
      })
    }
  }, [])   // eslint-disable-line react-hooks/exhaustive-deps — intentionally on mount only

  const calendarDays = datesReady ? calendarDaysBetween(edit.audit_date_start, edit.audit_date_end) : null
  // Team size for man-day math: lead + additional auditors ONLY (technical experts observe, not audit — per IAF MD 5 / spec Part 5)
  const teamCount = (edit.lead_auditor_name ? 1 : 0) + edit.auditors.length

  // Reactive: when team size changes and a start date exists, recompute end date
  // so that: calendar days = ceil(recommended / teamCount).
  // Always divides the IAF man-day figure — never stage.audit_days (stale calendar-day artifact).
  useEffect(() => {
    if (!edit.audit_date_start) return           // no start date yet — nothing to do
    if (!recommended) return                     // no IAF recommendation — nothing to base on
    if (teamCount === 0) return                  // no auditors yet — keep existing date
    const calendarDaysNeeded = Math.ceil(recommended / teamCount)
    const newEnd = suggestEndDate(edit.audit_date_start, calendarDaysNeeded)
    if (newEnd !== edit.audit_date_end) {
      patch({ audit_date_end: newEnd })
    }
  }, [teamCount])   // eslint-disable-line react-hooks/exhaustive-deps — intentionally watches teamCount only

  // Man-days covered = calendar days in range × number of assigned team members (all days of week valid)
  const manDaysCovered = calendarDays != null && teamCount > 0 ? calendarDays * teamCount : null
  // Shortfall: covered < stage.audit_days (recommended for this stage from calculation)
  const manDayShortfall = stage.audit_days != null && manDaysCovered != null && manDaysCovered < stage.audit_days
  const dateMismatch = recommended != null && calendarDays != null && teamCount === 0 && Math.abs(calendarDays - recommended) > 0.5
  const stageOrderErr = validateStageOrder(stage, allStages, edit.audit_date_start, edit.audit_date_end)

  const [coverageError, setCoverageError] = useState<string | null>(null)

  const resolvedStandards = resolvedStds

  // Coverage: full team (lead + auditors + TEs) collectively covers all required codes (IAF MD 11)
  const teamMembers: TeamMember[] = [
    ...(edit.lead_auditor_name ? [{ id: edit.lead_auditor_id, name: edit.lead_auditor_name }] : []),
    ...edit.auditors,
    ...edit.technical_experts,
  ]
  const teNameSet = new Set(edit.technical_experts.map((te) => te.name))
  const coverageResults = (resolvedStandards.length > 0 && (availableAuditors ?? []).length > 0)
    ? computeCoverage(resolvedStandards, eaCode, teamMembers, availableAuditors ?? [], requiredScope, teNameSet)
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
          lead_auditor_id:   isThis ? (edit.lead_auditor_id   || null) : (s.lead_auditor_id ?? null),
          audit_date_start:  isThis ? (edit.audit_date_start  || null) : s.audit_date_start,
          audit_date_end:    isThis ? (edit.audit_date_end    || null) : s.audit_date_end,
          auditors:          isThis ? edit.auditors          : ((s.auditors as TeamMember[]) ?? []),
          technical_experts: isThis ? edit.technical_experts : ((s.technical_experts as TeamMember[]) ?? []),
          observers:         isThis ? edit.observers.map((x) => ({ id: x.id, name: x.name })) : ((s.observers as TeamMember[]) ?? []),
          trainees:          isThis ? edit.trainees.map((x) => ({ id: x.id, name: x.name })) : ((s as StageResponse & { trainees?: TeamMember[] }).trainees ?? []),
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
      {manDayShortfall && calendarDays != null && (
        <div className="mb-3 rounded-md px-3 py-2 text-sm" style={{ background: '#FEF3C7', color: '#92400E' }}>
          ⚠ Your date range covers {calendarDays} calendar day(s) × {teamCount} auditor(s) = {manDaysCovered} man-day(s).
          IAF recommends {stage.audit_days} audit-day(s) for this stage.
          Consider expanding the date range or adding more auditors.
        </div>
      )}
      {/* Fallback: no team assigned yet — show plain date-vs-recommendation mismatch */}
      {dateMismatch && calendarDays != null && (
        <div className="mb-3 rounded-md px-3 py-2 text-sm" style={{ background: '#FEF3C7', color: '#92400E' }}>
          ⚠ Date range covers {calendarDays} calendar day(s), but IAF MD 5 recommends {recommended} for a single auditor.
          {calendarDays > recommended!
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
          {recommended != null && edit.audit_date_start && (() => {
            const calendarDaysNeeded = Math.ceil(recommended / Math.max(1, teamCount))
            return (
              <button
                type="button"
                onClick={() => patch({ audit_date_end: suggestEndDate(edit.audit_date_start, calendarDaysNeeded) })}
                className="text-xs text-certiva-primary underline hover:opacity-70"
              >
                Suggest end date ({calendarDaysNeeded} audit days from start)
                {teamCount > 1 && (
                  <span className="ml-1 opacity-70">
                    ({recommended} person-days ÷ {teamCount} auditors)
                  </span>
                )}
              </button>
            )
          })()}
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
              .map((a) => {
                const avail = availableAuditors?.find((x) => x.name === a.name)
                const isUnavailable = avail && !avail.available
                const coverLabel = avail?.covered_scope && Object.keys(avail.covered_scope).length > 0
                  ? ' — ' + Object.entries(avail.covered_scope)
                      .filter(([, codes]) => (codes as string[]).length > 0)
                      .map(([std, codes]) => `${(codes as string[]).join(' ')} (${std})`)
                      .join(' | ')
                  : ''
                return (
                  <option key={a.id ?? a.name} value={a.id ?? a.name} disabled={!!isUnavailable}>
                    {a.name}{'role' in a && a.role ? ` — ${a.role}` : ''}{coverLabel}
                    {isUnavailable ? ' (unavailable)' : ''}
                  </option>
                )
              })}
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
              .map((a) => {
                const avail = availableAuditors?.find((x) => x.name === a.name)
                const isUnavailable = avail && !avail.available
                const coverLabel = avail?.covered_scope && Object.keys(avail.covered_scope).length > 0
                  ? ' — ' + Object.entries(avail.covered_scope)
                      .filter(([, codes]) => (codes as string[]).length > 0)
                      .map(([std, codes]) => `${(codes as string[]).join(' ')} (${std})`)
                      .join(' | ')
                  : ''
                return (
                  <option key={a.id ?? a.name} value={a.id ?? a.name} disabled={!!isUnavailable}>
                    {a.name}{'role' in a && a.role ? ` — ${a.role}` : ''}{coverLabel}
                    {isUnavailable ? ' (unavailable)' : ''}
                  </option>
                )
              })}
          </select>
        </div>
      </div>

      {/* Observers and Trainees row */}
      <div className="mt-3 grid grid-cols-2 gap-4">

        {/* Observers */}
        <div>
          <label className={lblCls}>Observers</label>
          <div className="flex flex-wrap gap-1 mb-1 min-h-[24px]">
            {edit.observers.map((a) => (
              <span key={a.id || a.name}
                className="flex items-center gap-1 rounded-full px-2 py-0.5 text-xs"
                style={{ background: '#F5F5F5', color: '#555', border: '1px solid #DDD' }}>
                {a.name}
                <button type="button"
                  className="ml-1 text-gray-400 hover:text-red-500"
                  onClick={() => patch({ observers: edit.observers.filter((x) => (x.id || x.name) !== (a.id || a.name)) })}>
                  ×
                </button>
              </span>
            ))}
          </div>
          <select className={inputCls} value=""
            onChange={(e) => {
              const found = dropdownList.find((a) => (a.id ?? a.name) === e.target.value)
              if (found && !edit.observers.find((x) => (x.id || x.name) === (found.id || found.name))) {
                patch({ observers: [...edit.observers, { id: found.id ?? '', name: found.name }] })
              }
            }}>
            <option value="">+ Add observer…</option>
            {auditors
              .filter((a) => !edit.observers.find((x) => (x.id || x.name) === (a.id || a.name)))
              .filter((a) => a.name !== edit.lead_auditor_name)
              .map((a) => (
                <option key={a.id ?? a.name} value={a.id ?? a.name}>
                  {a.name}
                </option>
              ))}
          </select>
          <p className="text-[11px] text-gray-400 mt-0.5">Observers — no audit days, not assessed</p>
        </div>

        {/* Trainee Auditors */}
        <div>
          <label className={lblCls}>Trainee Auditors</label>
          <div className="flex flex-wrap gap-1 mb-1 min-h-[24px]">
            {edit.trainees.map((a) => (
              <span key={a.id || a.name}
                className="flex items-center gap-1 rounded-full px-2 py-0.5 text-xs"
                style={{ background: '#FFF7ED', color: '#92400E', border: '1px solid #FDE68A' }}>
                {a.name}
                <button type="button"
                  className="ml-1 text-gray-400 hover:text-red-500"
                  onClick={() => patch({ trainees: edit.trainees.filter((x) => (x.id || x.name) !== (a.id || a.name)) })}>
                  ×
                </button>
              </span>
            ))}
          </div>
          <select className={inputCls} value=""
            onChange={(e) => {
              const found = dropdownList.find((a) => (a.id ?? a.name) === e.target.value)
              if (found && !edit.trainees.find((x) => (x.id || x.name) === (found.id || found.name))) {
                patch({ trainees: [...edit.trainees, { id: found.id ?? '', name: found.name }] })
              }
            }}>
            <option value="">+ Add trainee…</option>
            {auditors
              .filter((a) => !edit.trainees.find((x) => (x.id || x.name) === (a.id || a.name)))
              .filter((a) => a.name !== edit.lead_auditor_name)
              .map((a) => (
                <option key={a.id ?? a.name} value={a.id ?? a.name}>
                  {a.name}
                </option>
              ))}
          </select>
          <p className="text-[11px] text-gray-400 mt-0.5">Trainees — no audit days, not counted in team coverage</p>
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
                      {cr.coveredBy ? '✓' : '✗'} {cr.code}{cr.coveredBy ? ` — ${cr.coveredBy}` : ' — not covered'}
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

const CAN_DELETE_ROLES = new Set(['admin', 'planner', 'planner_us'])

export default function ClientDetailPage({ params }: { params: { id: string } }) {
  const { id } = params
  const router = useRouter()
  const queryClient = useQueryClient()
  const { user: currentUser } = useAuth()
  const isRealtimeMode = currentUser?.role === 'planner_us'
  const canDelete = !!currentUser && CAN_DELETE_ROLES.has(currentUser.role)
  const [downloading, setDownloading] = useState(false)
  const [deleteError, setDeleteError] = useState<string | null>(null)

  // NC Management state (Portal 103)
  const [ncDecision, setNcDecision] = useState<NCDecision | null | undefined>(undefined)
  const [ncLoading, setNcLoading]   = useState(false)
  const [ncSubmitting, setNcSubmitting] = useState(false)
  const [ncError, setNcError]       = useState<string | null>(null)
  const [ncItems, setNcItems]       = useState<NCItemDraft[]>([{ category: 'minor', description: '' }])
  const [ncNoNC, setNcNoNC]         = useState(false)
  const [ncNotes, setNcNotes]       = useState('')
  const [reviewingId, setReviewingId]   = useState<string | null>(null)
  const [reviewNotes, setReviewNotes]   = useState('')

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

  // NC Management — load decision (Portal 103)
  const loadNCDecision = useCallback(() => {
    if (!id) return
    setNcLoading(true)
    api.get<NCDecision | null>(`/audit-sets/${id}/nc-decision`)
      .then((r) => setNcDecision(r.data))
      .catch(() => setNcDecision(null))
      .finally(() => setNcLoading(false))
  }, [id])

  useEffect(() => {
    if (data?.id) loadNCDecision()
  }, [data?.id, loadNCDecision])

  const handleSubmitNCDecision = async () => {
    if (!id) return
    setNcSubmitting(true)
    setNcError(null)
    try {
      const payload = ncNoNC
        ? { no_nc: true, notes: ncNotes, items: [] }
        : { no_nc: false, notes: ncNotes, items: ncItems.filter((i) => i.description.trim()) }
      const r = await api.post<NCDecision>(`/audit-sets/${id}/nc-decision`, payload)
      setNcDecision(r.data)
    } catch (e: unknown) {
      const err = e as { response?: { data?: { detail?: string } } }
      setNcError(err.response?.data?.detail || 'Submission failed')
    } finally {
      setNcSubmitting(false)
    }
  }

  const handleReviewNC = async (ncId: string, decision: 'approved' | 'rejected') => {
    if (!id) return
    try {
      await api.post(`/audit-sets/${id}/nc-items/${ncId}/review`, {
        decision,
        notes: reviewNotes,
      })
      setReviewingId(null)
      setReviewNotes('')
      loadNCDecision()
    } catch (e: unknown) {
      const err = e as { response?: { data?: { detail?: string } } }
      alert(err.response?.data?.detail || 'Review failed')
    }
  }

  async function handleDownload() {
    if (!data) return
    setDownloading(true)
    try {
      const res = await api.get(`/audit-sets/${id}/download`, { responseType: 'blob' })
      const url = window.URL.createObjectURL(res.data as Blob)
      const a   = document.createElement('a')
      a.href     = url
      a.download = `Set_${data.plan_number}_${data.company_name}.zip`
      document.body.appendChild(a)
      a.click()
      a.remove()
      window.URL.revokeObjectURL(url)
    } catch (e: unknown) {
      // Error responses arrive as a Blob because responseType is 'blob'.
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

      {/* Retroactive mode — always shown, no off switch (hidden for planner_us) */}
      {!isRealtimeMode && <RetroactiveBanner />}

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

      <PlanOverview data={data} auditSetId={id} onInvalidate={invalidate} userRole={currentUser?.role ?? ''} />
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
          {/* Portal 64 — Certification Committee picker (planning phase) */}
          <CommitteePlanningCard
            auditSetId={id}
            stages={data.stages}
            standards={(data.standards ?? []) as string[]}
            eaCode={data.ea_code ?? null}
            initialCommittee={data.committee_members}
            onSuccess={invalidate}
          />
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
      <SharedDocumentsSection auditSetId={id} stages={data.stages ?? []} auditType={data.audit_type ?? null} />

      {/* Internal CB Approvals — Prompt 13 (FR.218 / FR.222) */}
      <InternalApprovalsSection
        auditSetId={id}
        workflowStatus={data.workflow_status ?? null}
        auditType={data.audit_type ?? null}
      />

      {/* FR.218 Application Reviewer — Portal 51 (FSMS/ISMS only) */}
      {needsFr218Reviewer((data.standards ?? []) as string[]) &&
       !(data.audit_type ?? '').startsWith('surveillance') && (
        <div className="mt-4 rounded-xl border bg-white p-4">
          <h3 className="mb-1 text-sm font-semibold text-gray-700">
            Application Reviewer (FR.218) — Required for FSMS / ISMS
          </h3>
          <p className="mb-3 text-xs text-gray-500">
            Appoint the auditor or technical expert who will review the application
            and sign FR.218. They will see the document in their auditor portal.
          </p>
          <FR218ReviewerPicker
            auditSetId={id}
            currentReviewerId={data.fr218_reviewer_id}
            currentReviewerName={data.fr218_reviewer_name}
            onSaved={invalidate}
          />
        </div>
      )}

      {/* Portal 64 — Certification Committee moved to planning phase (see CommitteePlanningCard inside Audit stages block) */}

      {/* FR.233 Review & Decision — Portal 49a Part 3 */}
      <FR233Panel
        auditSetId={id}
        workflowStatus={data.workflow_status ?? null}
      />

      {/* Portal 55 — Meeting Attendees section removed (replaced by FR.225
          employee-roster flow). FR.225 attendees are now managed by the client
          via their /client/employees roster and signed in the viewer. */}

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
        userRole={currentUser?.role}
      />

      {/* ── NC Management (Portal 103) ──────────────────────────────────────── */}
      {ncDecision === undefined ? (
        ncLoading ? (
          <div className="rounded-lg border bg-white p-6 text-sm text-gray-400">Loading NC data…</div>
        ) : null
      ) : ncDecision === null ? (
        /* No decision yet — show submission form for auditor/admin/planner */
        currentUser && ['admin', 'planner', 'planner_us', 'auditor'].includes(currentUser.role) ? (
          <div className="rounded-lg border bg-white p-6 space-y-4">
            <h2 className="text-base font-semibold text-gray-900">Nonconformities (NC)</h2>
            <p className="text-sm text-gray-500">
              After Stage 2 is complete, the lead auditor submits the NC decision. IFC Global
              timelines: Critical = 14 days, Major = 90 days, Minor = 30 days.
            </p>

            <label className="flex items-center gap-2 cursor-pointer">
              <input
                type="checkbox"
                checked={ncNoNC}
                onChange={(e) => setNcNoNC(e.target.checked)}
                className="h-4 w-4 rounded border-gray-300 text-green-700"
              />
              <span className="text-sm font-medium text-gray-700">No nonconformities were identified</span>
            </label>

            <div>
              <label className="block text-xs font-medium text-gray-500 mb-1">Notes (optional)</label>
              <textarea
                value={ncNotes}
                onChange={(e) => setNcNotes(e.target.value)}
                rows={2}
                className="w-full rounded border border-gray-300 px-3 py-2 text-sm focus:outline-none focus:ring-1 focus:ring-green-700"
                placeholder="Any additional context for this NC decision..."
              />
            </div>

            {!ncNoNC && (
              <div className="space-y-3">
                <p className="text-xs font-medium text-gray-500">Nonconformities</p>
                {ncItems.map((item, idx) => (
                  <div key={idx} className="rounded border border-gray-200 p-3 space-y-2 bg-gray-50">
                    <div className="flex items-center gap-2">
                      <span className="text-xs font-semibold text-gray-500">NC-{idx + 1}</span>
                      <select
                        value={item.category}
                        onChange={(e) => {
                          const updated = [...ncItems]
                          updated[idx] = { ...updated[idx], category: e.target.value }
                          setNcItems(updated)
                        }}
                        className="rounded border border-gray-300 px-2 py-1 text-xs"
                      >
                        <option value="minor">Minor</option>
                        <option value="major">Major</option>
                        <option value="critical">Critical</option>
                      </select>
                      {ncItems.length > 1 && (
                        <button
                          type="button"
                          onClick={() => setNcItems(ncItems.filter((_, i) => i !== idx))}
                          className="ml-auto text-xs text-red-500 hover:text-red-700"
                        >
                          Remove
                        </button>
                      )}
                    </div>
                    <textarea
                      value={item.description}
                      onChange={(e) => {
                        const updated = [...ncItems]
                        updated[idx] = { ...updated[idx], description: e.target.value }
                        setNcItems(updated)
                      }}
                      rows={3}
                      className="w-full rounded border border-gray-300 px-3 py-2 text-sm focus:outline-none focus:ring-1 focus:ring-green-700"
                      placeholder="Describe the nonconformity in detail (reference clause number, evidence, observation)..."
                    />
                  </div>
                ))}
                <button
                  type="button"
                  onClick={() => setNcItems([...ncItems, { category: 'minor', description: '' }])}
                  className="text-xs text-green-700 hover:underline"
                >
                  + Add another NC
                </button>
              </div>
            )}

            {ncError && <p className="text-sm text-red-500">{ncError}</p>}

            <button
              type="button"
              onClick={handleSubmitNCDecision}
              disabled={ncSubmitting}
              className="rounded-lg px-4 py-2 text-sm font-medium text-white disabled:opacity-50"
              style={{ background: '#1A4731' }}
            >
              {ncSubmitting ? 'Submitting…' : ncNoNC ? 'Confirm — No NC' : 'Submit NC Decision'}
            </button>
          </div>
        ) : null
      ) : (
        /* Existing decision — show items list with review controls */
        <div className="rounded-lg border bg-white p-6 space-y-4">
          <div className="flex items-center justify-between">
            <h2 className="text-base font-semibold text-gray-900">Nonconformities</h2>
            <span className="text-xs text-gray-400">
              Decided {ncDecision.decided_at ? new Date(ncDecision.decided_at).toLocaleDateString() : '—'}
            </span>
          </div>

          {ncDecision.no_nc ? (
            <div className="flex items-center gap-2 rounded-lg bg-green-50 border border-green-200 p-3">
              <span className="text-green-700 font-medium text-sm">✓ No nonconformities were identified</span>
              {ncDecision.notes && <span className="text-xs text-gray-500 ml-2">{ncDecision.notes}</span>}
            </div>
          ) : (
            <div className="space-y-4">
              {ncDecision.items.map((item) => {
                const isOverdue = item.due_date && new Date(item.due_date) < new Date() && item.status !== 'closed'
                return (
                  <div key={item.id} className="rounded-lg border border-gray-200 p-4 space-y-3">
                    <div className="flex items-start justify-between gap-2">
                      <div className="space-y-1">
                        <div className="flex items-center gap-2">
                          <span className="text-sm font-semibold text-gray-700">NC-{item.nc_index}</span>
                          <span className={`inline-flex items-center rounded-full px-2 py-0.5 text-[11px] font-semibold uppercase ${
                            item.category === 'critical' ? 'bg-red-50 text-red-700' :
                            item.category === 'major' ? 'bg-orange-50 text-orange-700' :
                            'bg-blue-50 text-blue-700'
                          }`}>
                            {item.category}
                          </span>
                          <span className={`inline-flex items-center rounded-full px-2 py-0.5 text-[11px] font-medium ${
                            item.status === 'closed' ? 'bg-green-50 text-green-700' :
                            item.status === 'rejected' ? 'bg-red-50 text-red-600' :
                            item.status === 'client_responded' ? 'bg-blue-50 text-blue-700' :
                            'bg-gray-100 text-gray-600'
                          }`}>
                            {item.status.replace(/_/g, ' ')}
                          </span>
                        </div>
                        <p className="text-sm text-gray-700">{item.description}</p>
                      </div>
                      {item.due_date && (
                        <span className={`shrink-0 text-xs ${isOverdue ? 'text-red-600 font-semibold' : 'text-gray-400'}`}>
                          Due {new Date(item.due_date).toLocaleDateString()}{isOverdue ? ' ⚠' : ''}
                        </span>
                      )}
                    </div>

                    {item.evidence.length > 0 && (
                      <div className="space-y-1">
                        <p className="text-xs font-medium text-gray-500">Evidence uploaded by client</p>
                        {item.evidence.map((ev) => (
                          <div key={ev.id} className="flex items-center gap-2">
                            <a
                              href={`${process.env.NEXT_PUBLIC_API_URL}/audit-sets/${id}/nc-items/${item.id}/evidence/${ev.id}/download`}
                              target="_blank"
                              rel="noreferrer"
                              className="text-xs text-green-700 hover:underline"
                            >
                              {ev.file_name || 'File'} ({ev.upload_type.replace(/_/g, ' ')}, round {ev.round_number})
                            </a>
                          </div>
                        ))}
                      </div>
                    )}

                    {item.reviews.length > 0 && (
                      <div className="space-y-1">
                        <p className="text-xs font-medium text-gray-500">Review history</p>
                        {item.reviews.map((rev) => (
                          <div key={rev.id} className="text-xs text-gray-500 flex items-center gap-2">
                            <span className={rev.decision === 'approved' ? 'text-green-600' : 'text-red-500'}>
                              {rev.decision === 'approved' ? '✓ Approved' : '✗ Rejected'}
                            </span>
                            {rev.notes && <span>— {rev.notes}</span>}
                            <span className="text-gray-400">{new Date(rev.reviewed_at).toLocaleDateString()}</span>
                          </div>
                        ))}
                      </div>
                    )}

                    {item.status === 'client_responded' && (
                      <div className="border-t pt-3 space-y-2">
                        {reviewingId === item.id ? (
                          <div className="space-y-2">
                            <textarea
                              value={reviewNotes}
                              onChange={(e) => setReviewNotes(e.target.value)}
                              rows={2}
                              placeholder="Review notes (required for rejection, optional for approval)"
                              className="w-full rounded border border-gray-300 px-3 py-2 text-xs focus:outline-none focus:ring-1 focus:ring-green-700"
                            />
                            <div className="flex gap-2">
                              <button
                                type="button"
                                onClick={() => handleReviewNC(item.id, 'approved')}
                                className="rounded px-3 py-1.5 text-xs font-medium text-white bg-green-700 hover:bg-green-800"
                              >
                                Approve & Close NC
                              </button>
                              <button
                                type="button"
                                onClick={() => handleReviewNC(item.id, 'rejected')}
                                className="rounded px-3 py-1.5 text-xs font-medium text-white bg-red-600 hover:bg-red-700"
                              >
                                Reject — Request Resubmission
                              </button>
                              <button
                                type="button"
                                onClick={() => { setReviewingId(null); setReviewNotes('') }}
                                className="rounded px-3 py-1.5 text-xs text-gray-500 hover:text-gray-700"
                              >
                                Cancel
                              </button>
                            </div>
                          </div>
                        ) : (
                          <button
                            type="button"
                            onClick={() => setReviewingId(item.id)}
                            className="text-xs text-green-700 hover:underline"
                          >
                            Review client evidence →
                          </button>
                        )}
                      </div>
                    )}
                  </div>
                )
              })}
            </div>
          )}
        </div>
      )}
    </div>
  )
}
