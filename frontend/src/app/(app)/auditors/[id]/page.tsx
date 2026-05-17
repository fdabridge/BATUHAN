'use client'

import { useState } from 'react'
import Link from 'next/link'
import { ArrowLeft, AlertTriangle, CheckCircle2, Loader2, Plus, Trash2, XCircle } from 'lucide-react'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import api from '@/lib/api'
import type {
  AuditorResponse, EligibilityCheckRequest, EligibilityResult, EligibilityRoleValue,
  WitnessRecord, WitnessStatus,
} from '@/types'

// ── Constants ─────────────────────────────────────────────────────────────────

const STANDARDS_FULL: Record<string, string> = {
  QMS:   'ISO 9001',  EMS:   'ISO 14001', OHSMS: 'ISO 45001', FSMS:  'ISO 22000',
  ISMS:  'ISO 27001', MDQMS: 'ISO 13485', ABMS:  'ISO 37001', ENMS:  'ISO 50001',
}
const STANDARDS = Object.keys(STANDARDS_FULL)
const BODIES    = ['UAF', 'TURKAK'] as const

const ROLE_OPTIONS: { value: EligibilityRoleValue; label: string }[] = [
  { value: 'lead_auditor',     label: 'Lead Auditor' },
  { value: 'team_auditor',     label: 'Auditor' },
  { value: 'technical_expert', label: 'Technical Expert' },
]

// ── Shared styles ─────────────────────────────────────────────────────────────

const inputCls = 'w-full rounded-lg border border-gray-200 px-3 py-2 text-sm text-gray-800 placeholder-gray-400 outline-none focus:border-certiva-primary focus:ring-2 focus:ring-certiva-primary/20'
const lblCls   = 'mb-1 block text-xs font-medium text-gray-500'

// ── Helpers ───────────────────────────────────────────────────────────────────

function formatDate(iso: string | null | undefined): string {
  if (!iso) return '—'
  const [y, m, d] = iso.split('-')
  if (!y || !m || !d) return iso
  return `${d}/${m}/${y}`
}

function maxYears(qs: AuditorResponse['standard_qualifications']): number | null {
  const yrs = qs.map((q) => q.experience_years ?? 0).filter((y) => y > 0)
  return yrs.length ? Math.max(...yrs) : null
}

function mostRecent(dates: (string | null | undefined)[]): string | null {
  const valid = dates.filter((d): d is string => !!d).sort()
  return valid.length ? valid[valid.length - 1] : null
}

function plusYears(iso: string | null, years: number): string | null {
  if (!iso) return null
  const d = new Date(iso)
  if (Number.isNaN(d.getTime())) return null
  d.setFullYear(d.getFullYear() + years)
  return d.toISOString().slice(0, 10)
}

function trainingExpiryWarning(date: string | null): boolean {
  if (!date) return false
  const d = new Date(date)
  if (Number.isNaN(d.getTime())) return false
  const ageMs = Date.now() - d.getTime()
  return ageMs > 3 * 365 * 24 * 60 * 60 * 1000
}

function verificationWarning(date: string | null): boolean {
  if (!date) return false
  const d = new Date(date)
  if (Number.isNaN(d.getTime())) return false
  const ageMs = Date.now() - d.getTime()
  return ageMs > 365 * 24 * 60 * 60 * 1000
}

// ── Field ─────────────────────────────────────────────────────────────────────

function Field({ label, value }: { label: string; value: React.ReactNode }) {
  return (
    <div>
      <p className="mb-0.5 font-medium uppercase tracking-wide text-gray-400" style={{ fontSize: 11 }}>{label}</p>
      <div className="text-sm text-gray-800">{value}</div>
    </div>
  )
}

// ── Inline alert ──────────────────────────────────────────────────────────────

function InlineWarning({ text }: { text: string }) {
  return (
    <div className="mt-2 flex items-start gap-1.5 rounded border border-amber-200 bg-amber-50 px-2.5 py-1.5" style={{ fontSize: 13, color: '#92400E' }}>
      <AlertTriangle size={13} className="mt-0.5 shrink-0" /> {text}
    </div>
  )
}

// ── Profile overview ──────────────────────────────────────────────────────────

function ProfileOverview({ a }: { a: AuditorResponse }) {
  const lastTraining = mostRecent(a.standard_qualifications.map((q) => q.last_training_date))
  const trainingExp  = plusYears(lastTraining, 3)
  const lastVerified = mostRecent(a.standard_qualifications.map((q) => q.last_verified_date))
  const trainWarn    = trainingExpiryWarning(lastTraining)
  const verifyWarn   = verificationWarning(lastVerified)
  const eaCodes      = (a.ea_codes ?? []).join(', ') || '—'
  const bodies       = (a.accreditation_bodies ?? []).join(', ') || '—'
  const years        = maxYears(a.standard_qualifications)

  return (
    <div className="rounded-lg border border-gray-100 bg-white p-5">
      <p className="mb-4 text-sm font-medium text-gray-700">Profile</p>
      <div className="grid grid-cols-2 gap-x-6 gap-y-5">
        <Field label="Email" value={a.email || '—'} />
        <Field label="Phone" value={a.phone || a.mobile || '—'} />
        <Field label="Years of experience" value={years != null ? `${years} years` : '—'} />
        <Field label="EA / NACE codes" value={eaCodes} />
        <Field label="Accreditation bodies" value={bodies} />
        <Field label="Field of expertise" value={a.field_of_expertise || '—'} />
        <div>
          <Field label="Last training" value={`${formatDate(lastTraining)} · expires ${formatDate(trainingExp)}`} />
          {trainWarn && <InlineWarning text="Training certificate is more than 3 years old — renewal required." />}
        </div>
        <div>
          <Field label="Last verification" value={formatDate(lastVerified)} />
          {verifyWarn && <InlineWarning text="Last TÜRKAK verification was more than 1 year ago." />}
        </div>
      </div>
    </div>
  )
}


// ── Qualified standards (with inline edit mode) ───────────────────────────────

const TECH_DEPTH_OPTIONS = ['Lead Auditor', 'Team Auditor', 'Technical Expert'] as const

interface QualEditRow {
  standard_code:      string
  accreditation_body: string
  scope_category:     string   // EA codes specific to this standard, e.g. "EA 3, EA 18"
  technical_depth:    string
  experience_years:   string   // kept as string for the input; parsed on save
}

function rowsFromAuditor(a: AuditorResponse): QualEditRow[] {
  return a.standard_qualifications
    .filter((q) => q.is_qualified !== false)
    .map((q) => ({
      standard_code:      q.standard_code ?? '',
      accreditation_body: q.accreditation_body ?? '',
      scope_category:     q.scope_category ?? '',
      technical_depth:    q.technical_depth ?? '',
      experience_years:   q.experience_years != null ? String(q.experience_years) : '',
    }))
}

function QualifiedStandards({ a, id }: { a: AuditorResponse; id: string }) {
  const queryClient = useQueryClient()
  const [editing, setEditing]             = useState(false)
  const [eaText, setEaText]               = useState('')
  const [rows, setRows]                   = useState<QualEditRow[]>([])
  const [validationErr, setValidationErr] = useState<string | null>(null)
  const [saveErr, setSaveErr]             = useState<string | null>(null)

  const qs = a.standard_qualifications.filter((q) => q.is_qualified !== false && q.standard_code)

  function startEdit() {
    setEaText((a.ea_codes ?? []).join(', '))
    setRows(rowsFromAuditor(a))
    setValidationErr(null)
    setSaveErr(null)
    setEditing(true)
  }

  function cancelEdit() {
    setEditing(false)
    setValidationErr(null)
    setSaveErr(null)
  }

  function patchRow(i: number, p: Partial<QualEditRow>) {
    setRows((cur) => cur.map((r, idx) => (idx === i ? { ...r, ...p } : r)))
  }
  function addRow()           { setRows((cur) => [...cur, { standard_code: '', accreditation_body: '', scope_category: '', technical_depth: '', experience_years: '' }]) }
  function removeRow(i: number) { setRows((cur) => cur.filter((_, idx) => idx !== i)) }

  const save = useMutation({
    mutationFn: async () => {
      const eaCodes = eaText.split(',').map((s) => s.trim()).filter(Boolean)
      const payload = {
        ...a,
        ea_codes: eaCodes.length ? eaCodes : null,
        standard_qualifications: rows.map((r) => {
          const yrs = parseInt(r.experience_years, 10)
          return {
            standard_code:      r.standard_code.trim(),
            accreditation_body: r.accreditation_body.trim() || null,
            scope_category:     r.scope_category.trim() || null,
            technical_depth:    r.technical_depth || null,
            experience_years:   Number.isFinite(yrs) ? yrs : null,
            is_qualified:       true,
          }
        }),
      }
      await api.put(`/auditors/${id}`, payload)
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['auditor', id] })
      queryClient.invalidateQueries({ queryKey: ['auditors-dashboard'] })
      setEditing(false)
    },
    onError: (err: unknown) => {
      const detail = (err as { response?: { data?: { detail?: string } } })?.response?.data?.detail
      setSaveErr(detail ?? 'Failed to save.')
    },
  })

  function attemptSave() {
    if (rows.some((r) => !r.standard_code.trim())) {
      setValidationErr('Standard code is required for each row.')
      return
    }
    setValidationErr(null)
    setSaveErr(null)
    save.mutate()
  }

  return (
    <div className="rounded-lg border border-gray-100 bg-white p-5">
      <div className="mb-4 flex items-center justify-between">
        <p className="text-sm font-medium text-gray-700">Qualified standards</p>
        {editing ? (
          <div className="flex gap-2">
            <button
              type="button" onClick={cancelEdit} disabled={save.isPending}
              className="rounded-lg border border-gray-200 px-3 py-1 text-xs text-gray-700 hover:bg-gray-50 disabled:opacity-60"
            >
              Cancel
            </button>
            <button
              type="button" onClick={attemptSave} disabled={save.isPending}
              className="inline-flex items-center gap-1 rounded-lg px-3 py-1 text-xs font-medium text-white hover:opacity-90 disabled:opacity-60"
              style={{ background: '#1A4731' }}
            >
              {save.isPending && <Loader2 size={12} className="animate-spin" />}
              Save
            </button>
          </div>
        ) : (
          <button
            type="button" onClick={startEdit}
            className="rounded-lg border border-gray-200 px-3 py-1 text-xs font-medium text-gray-700 hover:bg-gray-50"
          >
            Edit
          </button>
        )}
      </div>

      {editing ? (
        <div className="space-y-4">
          <div>
            <label className={lblCls}>EA Codes <span className="font-normal text-gray-300">(comma-separated)</span></label>
            <input
              type="text" className={inputCls} value={eaText}
              onChange={(e) => setEaText(e.target.value)} placeholder="EA 3, EA 18, EA 29"
            />
          </div>

          <div>
            <div className="mb-2 flex items-center justify-between">
              <label className="block text-sm font-medium text-gray-700">Standard qualifications</label>
              <button type="button" onClick={addRow} className="inline-flex items-center gap-1 text-xs font-medium text-certiva-primary hover:opacity-70">
                <Plus size={12} /> Add standard
              </button>
            </div>
            <div className="space-y-2">
              {rows.length === 0 && (
                <p className="text-xs text-gray-400">No qualifications yet. Click “Add standard” to add one.</p>
              )}
              {rows.map((r, i) => (
                <div key={i} className="flex flex-wrap items-center gap-2">
                  <input
                    type="text" placeholder="ISO 9001" className={`${inputCls} w-28`}
                    value={r.standard_code}
                    onChange={(e) => patchRow(i, { standard_code: e.target.value })}
                  />
                  <input
                    type="text" placeholder="UAF" className={`${inputCls} w-20`}
                    value={r.accreditation_body}
                    onChange={(e) => patchRow(i, { accreditation_body: e.target.value })}
                  />
                  <input
                    type="text" placeholder="EA 3, EA 18" className={`${inputCls} flex-1 min-w-[8rem]`}
                    value={r.scope_category}
                    onChange={(e) => patchRow(i, { scope_category: e.target.value })}
                    title="EA codes this auditor is qualified for under this standard"
                  />
                  <select
                    className={`${inputCls} w-36`} value={r.technical_depth}
                    onChange={(e) => patchRow(i, { technical_depth: e.target.value })}
                  >
                    <option value="">—</option>
                    {TECH_DEPTH_OPTIONS.map((o) => <option key={o} value={o}>{o}</option>)}
                  </select>
                  <input
                    type="number" min={0} placeholder="Yrs" className={`${inputCls} w-14`}
                    value={r.experience_years}
                    onChange={(e) => patchRow(i, { experience_years: e.target.value })}
                  />
                  <button
                    type="button" onClick={() => removeRow(i)}
                    className="rounded p-2 text-gray-400 hover:bg-gray-50 hover:text-red-500"
                    aria-label="Remove row"
                  >
                    <Trash2 size={14} />
                  </button>
                </div>
              ))}
            </div>
          </div>

          {validationErr && <p className="text-xs text-red-600">{validationErr}</p>}
          {saveErr        && <div className="rounded-lg border border-red-300 bg-red-50 p-3 text-sm text-red-600">{saveErr}</div>}
        </div>
      ) : qs.length === 0 ? (
        <p className="text-sm text-gray-400">No qualified standards on record. Click “Edit” to add some.</p>
      ) : (
        <div className="grid grid-cols-3 gap-3">
          {qs.map((q, i) => {
            const code = q.standard_code as string
            const iso  = STANDARDS_FULL[code] ?? ''
            return (
              <div
                key={`${code}-${i}`}
                className="rounded-lg border"
                style={{ background: '#F0FAF4', borderColor: 'rgba(34, 168, 92, 0.3)', padding: '0.75rem' }}
              >
                <p className="font-medium text-gray-800" style={{ fontSize: 13 }}>
                  {code}{iso && ` — ${iso}`}
                </p>
                {q.technical_depth && (
                  <span className="mt-2 inline-block rounded px-1.5 py-0.5 text-certiva-primary" style={{ fontSize: 11, background: 'white' }}>
                    {q.technical_depth}
                  </span>
                )}
                {q.scope_category && (
                  <p className="mt-1 text-gray-500" style={{ fontSize: 11 }} title="Sector scope (EA codes)">
                    🏭 {q.scope_category}
                  </p>
                )}
                {q.accreditation_body && (
                  <p className="mt-0.5 text-gray-400" style={{ fontSize: 11 }}>{q.accreditation_body}</p>
                )}
                {q.experience_years != null && q.experience_years > 0 && (
                  <p className="mt-0.5 text-gray-500" style={{ fontSize: 11 }}>{q.experience_years} yrs</p>
                )}
              </div>
            )
          })}
        </div>
      )}
    </div>
  )
}

// ── Eligibility checker ───────────────────────────────────────────────────────

function EligibilityChecker({ id }: { id: string }) {
  const [form, setForm] = useState<EligibilityCheckRequest>({
    standard_code: '', company_ea_code: '', accreditation_body: 'UAF', role: 'lead_auditor',
  })
  const [result, setResult] = useState<EligibilityResult | null>(null)
  const [serverError, setServerError] = useState<string | null>(null)

  const { mutate, isPending } = useMutation<EligibilityResult>({
    mutationFn: async () => {
      const res = await api.post<EligibilityResult>(`/auditors/${id}/check-eligibility`, form)
      return res.data
    },
    onSuccess: (data) => { setResult(data); setServerError(null) },
    onError: (err: unknown) => {
      const detail = (err as { response?: { data?: { detail?: string } } })?.response?.data?.detail
      setServerError(detail ?? 'Could not check eligibility.')
      setResult(null)
    },
  })

  function onSubmit(e: React.FormEvent) {
    e.preventDefault()
    if (!form.standard_code || !form.company_ea_code.trim()) return
    mutate()
  }

  return (
    <div className="rounded-lg border border-gray-100 bg-white p-5">
      <p className="text-sm font-medium text-gray-700">Check eligibility</p>
      <p className="mb-4 mt-0.5 text-xs text-gray-500">Check if this auditor can be assigned to an audit.</p>

      <form onSubmit={onSubmit} className="grid grid-cols-2 gap-3">
        <div>
          <label className={lblCls}>Standard</label>
          <select className={inputCls} value={form.standard_code}
            onChange={(e) => setForm({ ...form, standard_code: e.target.value })}>
            <option value="">Select…</option>
            {STANDARDS.map((s) => <option key={s} value={s}>{s}</option>)}
          </select>
        </div>
        <div>
          <label className={lblCls}>Company EA code</label>
          <input type="text" placeholder="e.g. 17, 29" className={inputCls} value={form.company_ea_code}
            onChange={(e) => setForm({ ...form, company_ea_code: e.target.value })} />
        </div>
        <div>
          <label className={lblCls}>Accreditation body</label>
          <select className={inputCls} value={form.accreditation_body}
            onChange={(e) => setForm({ ...form, accreditation_body: e.target.value })}>
            {BODIES.map((b) => <option key={b} value={b}>{b}</option>)}
          </select>
        </div>
        <div>
          <label className={lblCls}>Role</label>
          <select className={inputCls} value={form.role}
            onChange={(e) => setForm({ ...form, role: e.target.value as EligibilityRoleValue })}>
            {ROLE_OPTIONS.map((r) => <option key={r.value} value={r.value}>{r.label}</option>)}
          </select>
        </div>
        <div className="col-span-2">
          <button
            type="submit" disabled={isPending}
            className="flex items-center gap-1.5 rounded-lg px-4 py-2 text-sm font-medium text-white disabled:opacity-60 hover:opacity-90"
            style={{ background: '#1A4731' }}
          >
            {isPending && <Loader2 size={14} className="animate-spin" />}
            Check
          </button>
        </div>
      </form>

      {serverError && (
        <div className="mt-3 rounded-lg border border-red-200 bg-red-50 p-3 text-sm text-red-700">{serverError}</div>
      )}

      {result && (
        <div className="mt-4">
          {result.eligible ? (
            <div className="rounded-lg border border-green-200 bg-green-50 p-3">
              <div className="flex items-center gap-2 font-medium" style={{ color: '#1A4731' }}>
                <CheckCircle2 size={16} /> Eligible
              </div>
              {result.warnings.length > 0 && (
                <ul className="mt-2 space-y-0.5" style={{ fontSize: 13, color: '#92400E' }}>
                  {result.warnings.map((w, i) => <li key={i}>• {w}</li>)}
                </ul>
              )}
            </div>
          ) : (
            <div className="rounded-lg border border-red-200 bg-red-50 p-3">
              <div className="flex items-center gap-2 font-medium text-red-700">
                <XCircle size={16} /> Not eligible
              </div>
              <ul className="mt-2 space-y-0.5 text-red-600" style={{ fontSize: 13 }}>
                {result.blocking_reasons.map((r, i) => <li key={i}>• {r}</li>)}
              </ul>
              {result.warnings.length > 0 && (
                <ul className="mt-2 space-y-0.5" style={{ fontSize: 13, color: '#92400E' }}>
                  {result.warnings.map((w, i) => <li key={i}>• {w}</li>)}
                </ul>
              )}
            </div>
          )}
        </div>
      )}
    </div>
  )
}

// ── Audit history ─────────────────────────────────────────────────────────────

function AuditHistory({ a }: { a: AuditorResponse }) {
  const total    = a.audit_log.length
  const lastIso  = mostRecent(a.audit_log.map((r) => r.audit_date))
  const lastText = total === 0 ? 'Never' : formatDate(lastIso)

  return (
    <div className="rounded-lg border border-gray-100 bg-white p-5">
      <p className="mb-4 text-sm font-medium text-gray-700">Audit history</p>
      <div className="grid grid-cols-2 gap-x-6">
        <Field label="Total audits" value={String(total)} />
        <Field label="Last audit" value={lastText} />
      </div>
    </div>
  )
}

// ── Witness audit panel ───────────────────────────────────────────────────────

const OUTCOME_OPTIONS = ['Satisfactory', 'Needs Improvement', 'Unsatisfactory'] as const
const ROLE_WITNESSED_OPTIONS = ['Lead Auditor', 'Team Auditor', 'Technical Expert'] as const

function outcomeBadge(outcome: WitnessRecord['outcome']) {
  if (!outcome) return null
  const styles: Record<string, { bg: string; color: string }> = {
    'Satisfactory':      { bg: '#F0FAF4', color: '#1A4731' },
    'Needs Improvement': { bg: '#FEF3C7', color: '#92400E' },
    'Unsatisfactory':    { bg: '#FEE2E2', color: '#991B1B' },
  }
  const s = styles[outcome] ?? { bg: '#F3F4F6', color: '#6B7280' }
  return (
    <span className="rounded px-2 py-0.5 text-xs" style={s}>{outcome}</span>
  )
}

const BLANK_FORM = {
  witness_date: '', client_name: '', standard_code: '', ea_code: '',
  role_witnessed: 'Lead Auditor', observer_name: '', outcome: 'Satisfactory' as string, notes: '',
}

function WitnessPanel({ id }: { id: string }) {
  const queryClient = useQueryClient()
  const [showForm, setShowForm] = useState(false)
  const [form, setForm] = useState({ ...BLANK_FORM })
  const [formErr, setFormErr] = useState<string | null>(null)

  const { data: ws, isLoading } = useQuery<WitnessStatus>({
    queryKey: ['witness-status', id],
    queryFn: () => api.get<WitnessStatus>(`/auditors/${id}/witness`).then((r) => r.data),
  })

  const addRecord = useMutation({
    mutationFn: () => api.post(`/auditors/${id}/witness`, form),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['witness-status', id] })
      queryClient.invalidateQueries({ queryKey: ['witness-summary'] })
      setForm({ ...BLANK_FORM })
      setShowForm(false)
      setFormErr(null)
    },
    onError: (err: unknown) => {
      const detail = (err as { response?: { data?: { detail?: string } } })?.response?.data?.detail
      setFormErr(detail ?? 'Failed to save.')
    },
  })

  const deleteRecord = useMutation({
    mutationFn: (recId: number) => api.delete(`/auditors/${id}/witness/${recId}`),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['witness-status', id] })
      queryClient.invalidateQueries({ queryKey: ['witness-summary'] })
    },
  })

  function patch(k: string, v: string) { setForm((f) => ({ ...f, [k]: v })) }

  const isOverdue = ws?.witness_overdue || ws?.new_auditor_unwitnessed

  return (
    <div className="rounded-lg border border-gray-100 bg-white p-5">
      <div className="mb-4 flex items-center justify-between">
        <p className="text-sm font-medium text-gray-700">Witness audits <span className="ml-1 text-xs font-normal text-gray-400">(ISO 17021-1 §7.1)</span></p>
        <button
          type="button"
          onClick={() => setShowForm((v) => !v)}
          className="inline-flex items-center gap-1 rounded-lg px-3 py-1.5 text-xs font-medium text-white hover:opacity-90"
          style={{ background: '#1A4731' }}
        >
          <Plus size={12} /> Log witness audit
        </button>
      </div>

      {isLoading && <div className="py-4 text-center"><Loader2 size={16} className="animate-spin text-certiva-primary" /></div>}

      {ws && (
        <>
          {/* Status banner */}
          {isOverdue ? (
            <div className="mb-4 rounded-md p-3 text-sm" style={{ background: '#FEE2E2', color: '#991B1B' }}>
              ⚠ Witness audit overdue. ISO 17021-1 §7.1 requires witnessing at least once every 3 years per auditor.
              {' '}Last witnessed: <strong>{ws.last_witness_date ?? 'Never'}</strong>
            </div>
          ) : (
            <div className="mb-4 rounded-md p-3 text-sm" style={{ background: '#F0FAF4', color: '#1A4731' }}>
              ✓ Witness audit up to date. Last: <strong>{ws.last_witness_date}</strong> ({ws.days_since_last_witness} days ago)
            </div>
          )}

          {/* Log form */}
          {showForm && (
            <div className="mb-4 rounded-lg border border-gray-100 p-4">
              <p className="mb-3 text-sm font-medium text-gray-700">New witness record</p>
              <div className="grid grid-cols-2 gap-3">
                <div><label className={lblCls}>Witness date *</label>
                  <input type="date" className={inputCls} value={form.witness_date} onChange={(e) => patch('witness_date', e.target.value)} /></div>
                <div><label className={lblCls}>Client name</label>
                  <input type="text" className={inputCls} value={form.client_name} onChange={(e) => patch('client_name', e.target.value)} /></div>
                <div><label className={lblCls}>Standard</label>
                  <input type="text" className={inputCls} placeholder="ISO 9001" value={form.standard_code} onChange={(e) => patch('standard_code', e.target.value)} /></div>
                <div><label className={lblCls}>EA Code</label>
                  <input type="text" className={inputCls} placeholder="EA 3" value={form.ea_code} onChange={(e) => patch('ea_code', e.target.value)} /></div>
                <div><label className={lblCls}>Role witnessed</label>
                  <select className={inputCls} value={form.role_witnessed} onChange={(e) => patch('role_witnessed', e.target.value)}>
                    {ROLE_WITNESSED_OPTIONS.map((r) => <option key={r} value={r}>{r}</option>)}
                  </select></div>
                <div><label className={lblCls}>Observer name</label>
                  <input type="text" className={inputCls} value={form.observer_name} onChange={(e) => patch('observer_name', e.target.value)} /></div>
                <div><label className={lblCls}>Outcome</label>
                  <select className={inputCls} value={form.outcome} onChange={(e) => patch('outcome', e.target.value)}>
                    {OUTCOME_OPTIONS.map((o) => <option key={o} value={o}>{o}</option>)}
                  </select></div>
                <div className="col-span-2"><label className={lblCls}>Notes</label>
                  <textarea rows={2} className={inputCls} value={form.notes} onChange={(e) => patch('notes', e.target.value)} /></div>
              </div>
              {formErr && <p className="mt-2 text-xs text-red-600">{formErr}</p>}
              <div className="mt-3 flex gap-2">
                <button type="button" onClick={() => setShowForm(false)} className="rounded-lg border border-gray-200 px-4 py-2 text-sm text-gray-700 hover:bg-gray-50">Cancel</button>
                <button
                  type="button"
                  disabled={!form.witness_date || addRecord.isPending}
                  onClick={() => { setFormErr(null); addRecord.mutate() }}
                  className="flex items-center gap-1.5 rounded-lg px-4 py-2 text-sm font-medium text-white disabled:opacity-60 hover:opacity-90"
                  style={{ background: '#1A4731' }}
                >
                  {addRecord.isPending && <Loader2 size={14} className="animate-spin" />}
                  Save
                </button>
              </div>
            </div>
          )}

          {/* Records table */}
          {ws.records.length === 0 ? (
            <p className="text-xs text-gray-400">No witness records logged yet.</p>
          ) : (
            <div className="overflow-x-auto">
              <table className="w-full text-xs">
                <thead>
                  <tr className="border-b border-gray-100 text-left text-gray-400 uppercase tracking-wide">
                    {['Date', 'Client', 'Standard', 'EA Code', 'Role', 'Observer', 'Outcome', ''].map((h) => (
                      <th key={h} className="px-2 py-2">{h}</th>
                    ))}
                  </tr>
                </thead>
                <tbody className="divide-y divide-gray-50">
                  {ws.records.map((r) => (
                    <tr key={r.id} className="text-gray-700">
                      <td className="px-2 py-2">{formatDate(r.witness_date)}</td>
                      <td className="px-2 py-2">{r.client_name || '—'}</td>
                      <td className="px-2 py-2">{r.standard_code || '—'}</td>
                      <td className="px-2 py-2">{r.ea_code || '—'}</td>
                      <td className="px-2 py-2">{r.role_witnessed || '—'}</td>
                      <td className="px-2 py-2">{r.observer_name || '—'}</td>
                      <td className="px-2 py-2">{outcomeBadge(r.outcome)}</td>
                      <td className="px-2 py-2">
                        <button
                          type="button"
                          onClick={() => deleteRecord.mutate(r.id)}
                          className="rounded p-1 text-gray-400 hover:bg-gray-50 hover:text-red-500"
                          aria-label="Delete record"
                        >
                          <Trash2 size={12} />
                        </button>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </>
      )}
    </div>
  )
}

// ── Main page ─────────────────────────────────────────────────────────────────

export default function AuditorDetailPage({ params }: { params: { id: string } }) {
  const { id } = params

  const { data, isLoading, isError } = useQuery<AuditorResponse>({
    queryKey: ['auditor', id],
    queryFn: () => api.get<AuditorResponse>(`/auditors/${id}`).then((r) => r.data),
  })

  if (isLoading) return (
    <div className="flex items-center justify-center py-24">
      <Loader2 size={24} className="animate-spin text-certiva-primary" />
    </div>
  )
  if (isError || !data) return (
    <div className="py-12 text-center text-sm text-red-500">Auditor not found.</div>
  )

  return (
    <div className="mx-auto max-w-[900px] space-y-5 py-4">
      <Link href="/auditors" className="flex items-center gap-1 text-certiva-primary hover:opacity-70" style={{ fontSize: 13 }}>
        <ArrowLeft size={13} /> Auditors
      </Link>

      {/* Header */}
      <div className="flex items-start justify-between">
        <div className="flex items-center gap-3">
          <h1 className="text-gray-800" style={{ fontSize: 22, fontWeight: 500 }}>{data.name}</h1>
          {data.role && (
            <span className="rounded px-2 py-0.5 text-xs" style={{ background: '#F0FAF4', color: '#1A4731' }}>{data.role}</span>
          )}
        </div>
        {data.is_active ? (
          <span className="rounded-lg px-3 py-1 text-sm font-medium" style={{ background: '#F0FAF4', color: '#1A4731' }}>Active</span>
        ) : (
          <span className="rounded-lg px-3 py-1 text-sm font-medium" style={{ background: '#F3F4F6', color: '#6B7280' }}>Inactive</span>
        )}
      </div>

      <ProfileOverview a={data} />
      <QualifiedStandards a={data} id={id} />
      <EligibilityChecker id={id} />
      <AuditHistory a={data} />
      <WitnessPanel id={id} />
    </div>
  )
}
