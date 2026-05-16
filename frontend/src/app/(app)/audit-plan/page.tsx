'use client'

import { useState } from 'react'
import { Loader2, Plus, Sparkles, X } from 'lucide-react'
import { useQuery } from '@tanstack/react-query'
import api from '@/lib/api'
import type {
  AuditPlanAssignment, AuditPlanClauseRef, AuditPlanInput,
  AuditorSummary, ClauseAssignmentEntry, ClauseAssignmentResponse,
} from '@/types'

// ── Constants ─────────────────────────────────────────────────────────────────

const STANDARDS = ['QMS', 'EMS', 'OHSMS', 'FSMS', 'ISMS', 'MDQMS', 'ABMS', 'ENMS'] as const
const STAGES    = ['Stage 1', 'Stage 2'] as const
const BODIES    = ['UAF', 'TURKAK'] as const
const ROLES     = ['Lead Auditor', 'Auditor', 'Technical Expert'] as const

type Role = typeof ROLES[number]

interface ClauseGroup {
  key:     string
  label:   string
  clauses: AuditPlanClauseRef[]
}

const CLAUSE_GROUPS: ClauseGroup[] = [
  { key: 'planning',   label: 'Context & planning (4., 5., 6.)', clauses: [
    { clause_id: '4', title: 'Context of the organization' },
    { clause_id: '5', title: 'Leadership' },
    { clause_id: '6', title: 'Planning' },
  ]},
  { key: 'support',    label: 'Support (7.)', clauses: [
    { clause_id: '7', title: 'Support' },
  ]},
  { key: 'operation',  label: 'Operation (8.)', clauses: [
    { clause_id: '8', title: 'Operation' },
  ]},
  { key: 'evaluation', label: 'Evaluation & improvement (9., 10.)', clauses: [
    { clause_id: '9',  title: 'Performance evaluation' },
    { clause_id: '10', title: 'Improvement' },
  ]},
]

const inputCls = 'w-full rounded-lg border border-gray-200 px-3 py-2 text-sm text-gray-800 outline-none focus:border-certiva-primary focus:ring-2 focus:ring-certiva-primary/20'
const lblCls   = 'mb-1 block text-xs font-medium text-gray-500'

// ── Form state ────────────────────────────────────────────────────────────────

interface AuditorRow { auditor_id: string; role: Role }

interface FormState {
  company_name:       string
  audit_date:         string
  company_address:    string   // "Audit location" in spec
  standard_code:      string
  stage:              string   // "Stage 1" | "Stage 2"
  accreditation_body: string
  start_time:         string
  auditors:           AuditorRow[]
  clauses:            Record<string, boolean>
}

const INITIAL_FORM: FormState = {
  company_name:       '',
  audit_date:         '',
  company_address:    '',
  standard_code:      '',
  stage:              '',
  accreditation_body: 'UAF',
  start_time:         '09:00',
  auditors:           [{ auditor_id: '', role: 'Lead Auditor' }],
  clauses:            Object.fromEntries(CLAUSE_GROUPS.map((g) => [g.key, true])),
}

// ── Helpers ───────────────────────────────────────────────────────────────────

function lookupName(pool: AuditorSummary[], id: string): string {
  return pool.find((a) => a.id === id)?.name.trim() ?? ''
}

function buildAssignmentsRoundRobin(
  pool: AuditorSummary[], auditors: AuditorRow[], selectedKeys: string[],
): AuditPlanAssignment[] {
  const flat: AuditPlanClauseRef[] = []
  for (const g of CLAUSE_GROUPS) {
    if (selectedKeys.includes(g.key)) flat.push(...g.clauses)
  }

  const valid = auditors
    .map((a) => ({ ...a, name: lookupName(pool, a.auditor_id) }))
    .filter((a) => a.name.length > 0)

  if (valid.length === 0 || flat.length === 0) {
    return valid.map((a) => ({ auditor_name: a.name, role: a.role, assigned_clauses: [] }))
  }

  const ordered = [...valid].sort((a, b) => (a.role === 'Lead Auditor' ? -1 : b.role === 'Lead Auditor' ? 1 : 0))
  const buckets: AuditPlanClauseRef[][] = ordered.map(() => [])
  flat.forEach((c, i) => buckets[i % ordered.length].push(c))

  return ordered.map((a, i) => ({
    auditor_name:     a.name,
    role:             a.role,
    assigned_clauses: buckets[i],
  }))
}

function buildAssignmentsFromSuggestion(
  pool: AuditorSummary[], auditors: AuditorRow[], suggestion: ClauseAssignmentEntry[],
): AuditPlanAssignment[] {
  // Map auditor_id → role from form so the planner's role choice wins.
  const roleById = new Map(auditors.map((a) => [a.auditor_id, a.role]))
  return suggestion.map((s) => ({
    auditor_name:     s.auditor_name || lookupName(pool, s.auditor_id),
    role:             roleById.get(s.auditor_id) ?? (s.role || 'Auditor'),
    assigned_clauses: s.assigned_clauses.map((c) => ({ clause_id: c.clause_id, title: c.title })),
  }))
}

function pickLeadName(pool: AuditorSummary[], auditors: AuditorRow[]): string {
  const lead = auditors.find((a) => a.role === 'Lead Auditor' && a.auditor_id)
  if (lead) return lookupName(pool, lead.auditor_id)
  const first = auditors.find((a) => a.auditor_id)
  return first ? lookupName(pool, first.auditor_id) : ''
}

function stageToInt(s: string): number {
  return s === 'Stage 2' ? 2 : 1
}

function downloadBlob(blob: Blob, filename: string) {
  const url = URL.createObjectURL(blob)
  const a   = document.createElement('a')
  a.href     = url
  a.download = filename
  a.click()
  URL.revokeObjectURL(url)
}


// ── Main page ────────────────────────────────────────────────────────────────

export default function AuditPlanPage() {
  const [form,       setForm]       = useState<FormState>(INITIAL_FORM)
  const [errors,     setErrors]     = useState<Partial<Record<keyof FormState, string>>>({})
  const [loading,    setLoading]    = useState(false)
  const [apiErr,     setApiErr]     = useState<string | null>(null)
  const [suggestion, setSuggestion] = useState<ClauseAssignmentEntry[] | null>(null)
  const [suggestLoading, setSuggestLoading] = useState(false)
  const [suggestErr, setSuggestErr] = useState<string | null>(null)

  const { data: auditorPool = [], isLoading: poolLoading } = useQuery<AuditorSummary[]>({
    queryKey: ['auditors-active'],
    queryFn:  () => api.get<AuditorSummary[]>('/auditors/?active_only=true').then((r) => r.data),
  })

  function update<K extends keyof FormState>(k: K, v: FormState[K]) {
    setForm((f) => ({ ...f, [k]: v }))
    if (errors[k]) setErrors((e) => ({ ...e, [k]: undefined }))
    // Clearing suggestion if the standard or team composition changes.
    if (k === 'standard_code') setSuggestion(null)
  }

  function updateAuditor(i: number, patch: Partial<AuditorRow>) {
    setForm((f) => {
      const next = f.auditors.map((row, idx) => (idx === i ? { ...row, ...patch } : row))
      return { ...f, auditors: next }
    })
    setSuggestion(null)
  }

  function addAuditor() {
    setForm((f) => ({ ...f, auditors: [...f.auditors, { auditor_id: '', role: 'Auditor' }] }))
    setSuggestion(null)
  }

  function removeAuditor(i: number) {
    setForm((f) => (f.auditors.length <= 1 ? f : { ...f, auditors: f.auditors.filter((_, idx) => idx !== i) }))
    setSuggestion(null)
  }

  function toggleClause(key: string) {
    setForm((f) => ({ ...f, clauses: { ...f.clauses, [key]: !f.clauses[key] } }))
  }

  function validate(): boolean {
    const e: Partial<Record<keyof FormState, string>> = {}
    if (!form.company_name.trim())       e.company_name       = 'Required'
    if (!form.audit_date)                e.audit_date         = 'Required'
    if (!form.company_address.trim())    e.company_address    = 'Required'
    if (!form.standard_code)             e.standard_code      = 'Required'
    if (!form.stage)                     e.stage              = 'Required'
    if (!form.accreditation_body)        e.accreditation_body = 'Required'
    if (!form.auditors.some((a) => a.auditor_id)) e.auditors = 'Select at least one auditor'
    setErrors(e)
    return Object.keys(e).length === 0
  }

  async function handleSuggest() {
    setSuggestErr(null)
    const ids = form.auditors.map((a) => a.auditor_id).filter(Boolean)
    if (ids.length === 0) { setSuggestErr('Select at least one auditor.'); return }
    if (!form.standard_code) { setSuggestErr('Choose a standard first.'); return }

    setSuggestLoading(true)
    try {
      const res = await api.post<ClauseAssignmentResponse>('/auditors/assign-clauses', {
        auditor_ids:   ids,
        standard_code: form.standard_code,
      })
      setSuggestion(res.data.assignments)
    } catch (err) {
      // eslint-disable-next-line @typescript-eslint/no-explicit-any
      const anyErr = err as any
      setSuggestErr(String(anyErr?.response?.data?.detail ?? anyErr?.message ?? 'Failed to suggest assignment.'))
    } finally {
      setSuggestLoading(false)
    }
  }

  async function handleSubmit(ev: React.FormEvent) {
    ev.preventDefault()
    setApiErr(null)
    if (!validate()) return

    const selectedClauseKeys = Object.entries(form.clauses).filter(([, v]) => v).map(([k]) => k)
    const assignments = suggestion
      ? buildAssignmentsFromSuggestion(auditorPool, form.auditors, suggestion)
      : buildAssignmentsRoundRobin(auditorPool, form.auditors, selectedClauseKeys)

    const payload: AuditPlanInput = {
      company_name:       form.company_name.trim(),
      company_address:    form.company_address.trim(),
      standard_code:      form.standard_code,
      accreditation_body: form.accreditation_body,
      stage:              stageToInt(form.stage),
      audit_date:         form.audit_date,
      lead_auditor_name:  pickLeadName(auditorPool, form.auditors),
      assignments,
      opening_time:       form.start_time || '09:00',
    }

    setLoading(true)
    try {
      const res = await api.post('/auditors/generate-audit-plan', payload, { responseType: 'blob' })
      const safeCompany = form.company_name.trim().replace(/[^A-Za-z0-9_-]+/g, '_')
      downloadBlob(res.data as Blob, `AuditPlan_${safeCompany}_${form.audit_date}.docx`)
    } catch (err) {
      // Blob error responses: parse text from the blob body when present
      let detail = 'Failed to generate audit plan.'
      // eslint-disable-next-line @typescript-eslint/no-explicit-any
      const anyErr = err as any
      const blob   = anyErr?.response?.data
      if (blob instanceof Blob) {
        try {
          const txt    = await blob.text()
          const parsed = JSON.parse(txt)
          if (parsed?.detail) detail = String(parsed.detail)
        } catch { /* keep default */ }
      } else if (anyErr?.response?.data?.detail) {
        detail = String(anyErr.response.data.detail)
      } else if (anyErr?.message) {
        detail = String(anyErr.message)
      }
      setApiErr(detail)
    } finally {
      setLoading(false)
    }
  }

  return (
    <div className="mx-auto max-w-[680px] py-4">
      <h1 className="text-gray-800" style={{ fontSize: 22, fontWeight: 500 }}>Audit plan generator</h1>
      <p className="mt-1 mb-5 text-sm text-gray-500">
        Generate a formatted audit plan document (FR.223) for a specific audit.
      </p>

      <form onSubmit={handleSubmit} className="rounded-lg border border-gray-100 bg-white p-6">
        <div className="grid grid-cols-2 gap-4">
          <div className="col-span-2">
            <label className={lblCls}>Company name *</label>
            <input
              type="text" value={form.company_name}
              onChange={(e) => update('company_name', e.target.value)} className={inputCls}
            />
            {errors.company_name && <p className="mt-1 text-xs text-red-500">{errors.company_name}</p>}
          </div>

          <div>
            <label className={lblCls}>Audit date *</label>
            <input
              type="date" value={form.audit_date}
              onChange={(e) => update('audit_date', e.target.value)} className={inputCls}
            />
            {errors.audit_date && <p className="mt-1 text-xs text-red-500">{errors.audit_date}</p>}
          </div>

          <div>
            <label className={lblCls}>Start time</label>
            <input
              type="time" value={form.start_time}
              onChange={(e) => update('start_time', e.target.value)} className={inputCls}
            />
          </div>

          <div className="col-span-2">
            <label className={lblCls}>Audit location *</label>
            <input
              type="text" value={form.company_address}
              onChange={(e) => update('company_address', e.target.value)} className={inputCls}
            />
            {errors.company_address && <p className="mt-1 text-xs text-red-500">{errors.company_address}</p>}
          </div>

          <div>
            <label className={lblCls}>Standard *</label>
            <select
              value={form.standard_code} onChange={(e) => update('standard_code', e.target.value)}
              className={inputCls}
            >
              <option value="">Select…</option>
              {STANDARDS.map((s) => <option key={s} value={s}>{s}</option>)}
            </select>
            {errors.standard_code && <p className="mt-1 text-xs text-red-500">{errors.standard_code}</p>}
          </div>

          <div>
            <label className={lblCls}>Audit stage *</label>
            <select
              value={form.stage} onChange={(e) => update('stage', e.target.value)}
              className={inputCls}
            >
              <option value="">Select…</option>
              {STAGES.map((s) => <option key={s} value={s}>{s}</option>)}
            </select>
            {errors.stage && <p className="mt-1 text-xs text-red-500">{errors.stage}</p>}
          </div>

          <div className="col-span-2">
            <label className={lblCls}>Accreditation body *</label>
            <select
              value={form.accreditation_body} onChange={(e) => update('accreditation_body', e.target.value)}
              className={inputCls}
            >
              {BODIES.map((b) => <option key={b} value={b}>{b}</option>)}
            </select>
          </div>
        </div>

        {/* Audit team */}
        <div className="mt-6">
          <label className="mb-2 block text-sm font-medium text-gray-700">Audit team</label>
          <div className="space-y-2">
            {form.auditors.map((a, i) => {
              const selectedElsewhere = new Set(
                form.auditors.filter((_, idx) => idx !== i).map((x) => x.auditor_id).filter(Boolean),
              )
              return (
                <div key={i} className="flex items-center gap-2">
                  <select
                    value={a.auditor_id}
                    onChange={(e) => updateAuditor(i, { auditor_id: e.target.value })}
                    disabled={poolLoading}
                    className={`${inputCls} flex-1`}
                  >
                    <option value="">{poolLoading ? 'Loading…' : 'Select auditor…'}</option>
                    {auditorPool.map((p) => (
                      <option key={p.id} value={p.id} disabled={selectedElsewhere.has(p.id)}>
                        {p.name}{p.role ? ` — ${p.role}` : ''}
                      </option>
                    ))}
                  </select>
                  <select
                    value={a.role}
                    onChange={(e) => updateAuditor(i, { role: e.target.value as Role })}
                    className={`${inputCls} w-44`}
                  >
                    {ROLES.map((r) => <option key={r} value={r}>{r}</option>)}
                  </select>
                  <button
                    type="button"
                    onClick={() => removeAuditor(i)}
                    disabled={form.auditors.length <= 1}
                    className="rounded p-2 text-gray-400 hover:bg-gray-50 hover:text-red-500 disabled:opacity-30 disabled:hover:bg-transparent disabled:hover:text-gray-400"
                    aria-label="Remove auditor"
                  >
                    <X size={14} />
                  </button>
                </div>
              )
            })}
          </div>
          {errors.auditors && <p className="mt-1 text-xs text-red-500">{errors.auditors}</p>}
          {auditorPool.length === 0 && !poolLoading && (
            <p className="mt-2 text-xs text-gray-400">
              No registered auditors yet. Add one from the Auditors page.
            </p>
          )}
          <button
            type="button" onClick={addAuditor}
            className="mt-2 inline-flex items-center gap-1 text-xs font-medium text-certiva-primary hover:opacity-70"
          >
            <Plus size={13} /> Add auditor
          </button>
        </div>

        {/* Suggest clause assignment */}
        <div className="mt-5 rounded-lg border border-gray-100 p-4" style={{ background: '#F0FAF4' }}>
          <div className="flex items-center justify-between">
            <div>
              <p className="text-sm font-medium text-gray-700">Smart clause assignment</p>
              <p className="text-xs text-gray-500">
                Suggest a split based on each auditor&apos;s technical depth and experience.
              </p>
            </div>
            <button
              type="button"
              onClick={handleSuggest}
              disabled={suggestLoading || !form.standard_code || !form.auditors.some((a) => a.auditor_id)}
              className="flex items-center gap-1.5 rounded-lg border border-certiva-primary px-3 py-1.5 text-sm font-medium text-certiva-primary hover:bg-white disabled:opacity-50"
            >
              {suggestLoading ? <Loader2 size={14} className="animate-spin" /> : <Sparkles size={14} />}
              {suggestion ? 'Re-suggest' : 'Suggest assignment'}
            </button>
          </div>

          {suggestErr && (
            <p className="mt-2 text-xs text-red-600">{suggestErr}</p>
          )}

          {suggestion && (
            <div className="mt-3 overflow-hidden rounded-md border border-gray-100 bg-white">
              <table className="w-full text-sm">
                <thead>
                  <tr className="border-b border-gray-100 bg-gray-50 text-left text-xs font-medium uppercase tracking-wide text-gray-400">
                    <th className="px-3 py-2">Auditor</th>
                    <th className="px-3 py-2">Assigned clauses</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-gray-50">
                  {suggestion.map((s) => (
                    <tr key={s.auditor_id}>
                      <td className="px-3 py-2 align-top">
                        <div className="font-medium text-gray-800">{s.auditor_name}</div>
                        {s.role && <div className="text-xs text-gray-400">{s.role}</div>}
                      </td>
                      <td className="px-3 py-2 text-gray-600">
                        {s.assigned_clauses.length === 0
                          ? <span className="text-gray-400">—</span>
                          : (
                            <div className="flex flex-wrap gap-1">
                              {s.assigned_clauses.map((c) => (
                                <span key={c.clause_id} className="rounded px-1.5 py-0.5 text-xs" style={{ background: '#F0FAF4', color: '#1A4731' }}>
                                  {c.clause_id} {c.title}
                                </span>
                              ))}
                            </div>
                          )}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </div>

        {/* Clauses */}
        <div className="mt-6">
          <label className="mb-2 block text-sm font-medium text-gray-700">Clauses to audit</label>
          <div className="space-y-1.5">
            {CLAUSE_GROUPS.map((g) => (
              <label key={g.key} className="flex cursor-pointer items-center gap-2 text-sm text-gray-700">
                <input
                  type="checkbox" checked={!!form.clauses[g.key]}
                  onChange={() => toggleClause(g.key)}
                  className="h-3.5 w-3.5 accent-certiva-primary"
                />
                {g.label}
              </label>
            ))}
          </div>
        </div>

        {apiErr && (
          <div className="mt-5 rounded-lg border border-red-200 bg-red-50 p-3 text-sm text-red-700">
            {apiErr}
          </div>
        )}

        <button
          type="submit" disabled={loading}
          className="mt-6 flex w-full items-center justify-center gap-2 rounded-lg bg-certiva-primary px-4 py-2.5 text-sm font-medium text-white hover:opacity-90 disabled:opacity-60"
        >
          {loading && <Loader2 size={14} className="animate-spin" />}
          {loading ? 'Generating…' : 'Generate plan'}
        </button>
      </form>
    </div>
  )
}
