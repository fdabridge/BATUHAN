'use client'

import { useState } from 'react'
import Link from 'next/link'
import { ArrowLeft, AlertTriangle, CheckCircle2, Loader2, XCircle } from 'lucide-react'
import { useQuery, useMutation } from '@tanstack/react-query'
import api from '@/lib/api'
import type {
  AuditorResponse, EligibilityCheckRequest, EligibilityResult, EligibilityRoleValue,
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


// ── Qualified standards ───────────────────────────────────────────────────────

function QualifiedStandards({ a }: { a: AuditorResponse }) {
  const qs = a.standard_qualifications.filter((q) => q.is_qualified !== false && q.standard_code)
  if (qs.length === 0) return null

  return (
    <div className="rounded-lg border border-gray-100 bg-white p-5">
      <p className="mb-4 text-sm font-medium text-gray-700">Qualified standards</p>
      <div className="grid grid-cols-4 gap-3">
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
              {q.experience_years != null && q.experience_years > 0 && (
                <p className="mt-1 text-gray-500" style={{ fontSize: 11 }}>{q.experience_years} yrs</p>
              )}
            </div>
          )
        })}
      </div>
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
      <QualifiedStandards a={data} />
      <EligibilityChecker id={id} />
      <AuditHistory a={data} />
    </div>
  )
}
