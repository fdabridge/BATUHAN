'use client'

import { useRef, useState } from 'react'
import Link from 'next/link'
import { useRouter } from 'next/navigation'
import {
  AlertTriangle, Loader2, Plus, Upload, X, FileText, Trash2,
} from 'lucide-react'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import api from '@/lib/api'
import {
  ENMS_ENERGY_COMPLEXITY_OPTIONS,
  normalizeEnmsEnergyComplexity,
  qualificationScopeType,
} from '@/lib/isoStandards'
import type { AuditorDashboardEntry, AuditorIngestResult, AuditorQualificationSummary, WitnessStatus } from '@/types'

// ── Helpers ───────────────────────────────────────────────────────────────────

function hasWarnings(a: AuditorDashboardEntry): boolean {
  return a.qualifications.some((q) => q.training_expiry_warning || q.verification_warning)
}

function lastAuditLabel(a: AuditorDashboardEntry): string {
  if (a.total_audits === 0) return 'Never'
  if (a.days_since_last_audit == null) return '—'
  return `${a.days_since_last_audit} days ago`
}

function uniq(arr: (string | null | undefined)[]): string[] {
  return Array.from(new Set(arr.filter((x): x is string => !!x)))
}

// ── Stat card ─────────────────────────────────────────────────────────────────

function StatCard({ label, value }: { label: string; value: number }) {
  return (
    <div className="rounded-lg border border-gray-100 bg-white" style={{ padding: '0.875rem 1rem' }}>
      <p className="text-certiva-primary" style={{ fontSize: 24, fontWeight: 500 }}>{value}</p>
      <p className="mt-1 uppercase tracking-wide text-gray-400" style={{ fontSize: 11 }}>{label}</p>
    </div>
  )
}

// ── Status badge ──────────────────────────────────────────────────────────────

function StatusBadge({ a }: { a: AuditorDashboardEntry }) {
  if (!a.is_active) {
    return <span className="rounded px-2 py-0.5 text-xs" style={{ background: '#F3F4F6', color: '#6B7280' }}>Inactive</span>
  }
  if (hasWarnings(a)) {
    return (
      <span className="inline-flex items-center gap-1 rounded px-2 py-0.5 text-xs" style={{ background: '#FEF3C7', color: '#92400E' }}>
        <AlertTriangle size={12} /> Warnings
      </span>
    )
  }
  return <span className="rounded px-2 py-0.5 text-xs" style={{ background: '#F0FAF4', color: '#1A4731' }}>Active</span>
}

// ── Skeleton row ──────────────────────────────────────────────────────────────

function SkeletonRow() {
  return (
    <tr className="border-b border-gray-50">
      {Array.from({ length: 8 }).map((_, i) => (
        <td key={i} className="px-4 py-3">
          <div className="h-3 w-3/4 animate-pulse rounded bg-gray-100" />
        </td>
      ))}
    </tr>
  )
}

// ── Row ───────────────────────────────────────────────────────────────────────

function AuditorRow({ a, quals, witness, onClick }: {
  a:       AuditorDashboardEntry
  quals:   AuditorQualificationSummary[]
  witness: WitnessStatus | undefined
  onClick: () => void
}) {
  const witnessOverdue = witness?.witness_overdue || witness?.new_auditor_unwitnessed
  const visible  = quals.slice(0, 3)
  const overflow = quals.length - visible.length

  return (
    <tr className="cursor-pointer hover:bg-gray-50" onClick={onClick}>
      <td className="px-4 py-3">
        <div className="font-medium text-gray-800">{a.name}</div>
        {a.role && <div className="text-gray-400" style={{ fontSize: 12 }}>{a.role}</div>}
      </td>
      <td className="px-4 py-3">
        <div className="flex flex-wrap gap-1">
          {visible.map((q) => {
            const stype = qualificationScopeType(q.standard_code ?? '')
            const cats  = q.scope_category
              ? q.scope_category.split(',').map((s) => s.trim()).filter(Boolean)
              : []

            // Food chain categories → amber pills per code
            if (stype === 'food' && cats.length > 0) return (
              <span key={q.standard_code} className="flex flex-wrap gap-0.5 items-center">
                <span className="rounded px-1.5 py-0.5 font-medium" style={{ fontSize: 11, background: '#F0FAF4', color: '#1A4731' }}>{q.standard_code}</span>
                {cats.map((c) => (
                  <span key={c} className="rounded px-1 py-0.5 font-mono" style={{ fontSize: 10, background: '#FEF3C7', color: '#92400E', border: '1px solid #FDE68A' }}>{c}</span>
                ))}
              </span>
            )

            // Medical device TAs → purple pills per code
            if (stype === 'medical' && cats.length > 0) return (
              <span key={q.standard_code} className="flex flex-wrap gap-0.5 items-center">
                <span className="rounded px-1.5 py-0.5 font-medium" style={{ fontSize: 11, background: '#F0FAF4', color: '#1A4731' }}>{q.standard_code}</span>
                {cats.map((c) => (
                  <span key={c} className="rounded px-1 py-0.5 font-mono" style={{ fontSize: 10, background: '#EDE9FE', color: '#5B21B6', border: '1px solid #DDD6FE' }}>{c}</span>
                ))}
              </span>
            )

            if (stype === 'isms' && cats.length > 0) return (
              <span key={q.standard_code} className="flex flex-wrap items-center gap-0.5">
                <span className="rounded px-1.5 py-0.5 font-medium" style={{ fontSize: 11, background: '#F0FAF4', color: '#1A4731' }}>{q.standard_code}</span>
                {cats.map((area) => (
                  <span key={area} className="rounded border border-blue-200 bg-blue-50 px-1 py-0.5 font-mono text-blue-700" style={{ fontSize: 10 }}>{area}</span>
                ))}
              </span>
            )

            // Sector type → blue badge
            if (stype === 'sector' && q.scope_category) return (
              <span key={q.standard_code} className="flex gap-0.5 items-center">
                <span className="rounded px-1.5 py-0.5 font-medium" style={{ fontSize: 11, background: '#F0FAF4', color: '#1A4731' }}>{q.standard_code}</span>
                <span className="rounded px-1 py-0.5" style={{ fontSize: 10, background: '#EFF6FF', color: '#1D4ED8', border: '1px solid #BFDBFE' }}>{q.scope_category}</span>
              </span>
            )

            // Energy complexity → colored badge
            if (stype === 'energy' && q.scope_category) {
              const badgeStyle = q.scope_category === 'High'
                ? { background: '#FEF2F2', color: '#991B1B', border: '1px solid #FECACA' }
                : q.scope_category === 'Medium'
                ? { background: '#FEF3C7', color: '#92400E', border: '1px solid #FDE68A' }
                : { background: '#F0FDF4', color: '#166534', border: '1px solid #BBF7D0' }
              return (
                <span key={q.standard_code} className="flex gap-0.5 items-center">
                  <span className="rounded px-1.5 py-0.5 font-medium" style={{ fontSize: 11, background: '#F0FAF4', color: '#1A4731' }}>{q.standard_code}</span>
                  <span className="rounded px-1 py-0.5" style={{ fontSize: 10, ...badgeStyle }}>{q.scope_category}</span>
                </span>
              )
            }

            // EA / fallback → green Certiva pill, scope appended as subtitle
            return (
              <span key={q.standard_code} className="rounded px-1.5 py-0.5 font-medium" style={{ fontSize: 11, background: '#F0FAF4', color: '#1A4731' }}
                title={q.scope_category ? `Scope: ${q.scope_category}` : undefined}
              >
                {q.standard_code}
                {q.scope_category && (
                  <span style={{ color: '#256D46', fontWeight: 400 }}> · {q.scope_category}</span>
                )}
              </span>
            )
          })}
          {overflow > 0 && (
            <span className="rounded px-1.5 py-0.5 text-gray-500" style={{ fontSize: 11, background: '#F3F4F6' }}>
              +{overflow}
            </span>
          )}
        </div>
      </td>
      <td className="px-4 py-3 text-gray-500" style={{ fontSize: 13 }}>{a.ea_codes.join(', ') || '—'}</td>
      <td className="px-4 py-3">
        <div className="flex flex-wrap gap-1">
          {a.accreditation_bodies.length === 0 && <span className="text-gray-400">—</span>}
          {a.accreditation_bodies.map((b) => (
            <span key={b} className="rounded px-1.5 py-0.5 text-gray-600" style={{ fontSize: 12, background: '#F3F4F6' }}>{b}</span>
          ))}
        </div>
      </td>
      <td className="px-4 py-3 text-gray-500" style={{ fontSize: 13 }}>{lastAuditLabel(a)}</td>
      <td className="px-4 py-3"><StatusBadge a={a} /></td>
      <td className="px-4 py-3">
        {witnessOverdue && (
          <span className="inline-flex items-center gap-1 rounded px-2 py-0.5 text-xs" style={{ background: '#FEE2E2', color: '#991B1B' }}>
            <AlertTriangle size={12} /> Witness Due
          </span>
        )}
      </td>
      <td className="px-4 py-3">
        <Link
          href={`/auditors/${a.auditor_id}`}
          onClick={(e) => e.stopPropagation()}
          className="text-certiva-primary hover:underline"
          style={{ fontSize: 13 }}
        >
          View
        </Link>
      </td>
    </tr>
  )
}

// ── Add-auditor slide-over ────────────────────────────────────────────────────

const inputCls = 'w-full rounded-lg border border-gray-200 px-3 py-2 text-sm text-gray-800 placeholder-gray-400 outline-none focus:border-certiva-primary focus:ring-2 focus:ring-certiva-primary/20'
const lblCls   = 'mb-1 block text-xs font-medium text-gray-500'

interface QualRow {
  standard_code:      string
  accreditation_body: string
  technical_depth:    string
  experience_years:   string   // kept as string for the input; parsed on save
  ea_codes:           string[] // per-standard EA codes — used only for EA-code standards
  scope_category:     string   // food categories / TA codes / sector / risk level
}

const BLANK_QUAL: QualRow = {
  standard_code: '', accreditation_body: 'UAF', technical_depth: '',
  experience_years: '', ea_codes: [], scope_category: '',
}

function toQualRows(p: AuditorIngestResult): QualRow[] {
  return (p.standard_qualifications ?? []).map((q) => ({
    standard_code:      q.standard_code ?? '',
    accreditation_body: q.accreditation_body ?? (p.accreditation_bodies?.[0]) ?? 'UAF',
    technical_depth:    q.technical_depth ?? '',
    experience_years:   q.experience_years != null ? String(q.experience_years) : '',
    ea_codes:           q.ea_codes ?? [],
    scope_category:     q.scope_category ?? '',
  }))
}

// ── Scope input helpers (shared by modal and detail edit) ─────────────────────

const FOOD_CHAIN_CATEGORIES = ['BIII','C0','CI','CII','CIII','CIV','D','E','FI','FII','G','I','K']
const MEDICAL_DEVICE_TAS    = ['A1.1','A1.2','A1.3','A1.4','A1.5','A1.6','A1.7','A2.1','A2.2','A2.3','A2.4']
const ISMS_TECHNICAL_AREAS  = [
  { code: 'A', label: 'A — Standard IT and office systems' },
  { code: 'B', label: 'B — Industrial and operational technology' },
  { code: 'C', label: 'C — Telecom and service-provider infrastructure' },
  { code: 'D', label: 'D — Specialized and critical infrastructure' },
]
const EA_CODES: string[] = [
  'EA 1','EA 2','EA 3','EA 4','EA 5','EA 6','EA 7','EA 8','EA 9','EA 10',
  'EA 11','EA 12','EA 13','EA 14','EA 15','EA 16','EA 17','EA 18','EA 19','EA 20',
  'EA 21','EA 22','EA 23','EA 24','EA 25','EA 26','EA 27','EA 28','EA 29','EA 30',
  'EA 31','EA 32','EA 33','EA 34','EA 35','EA 36','EA 37','EA 38','EA 39','EA 40',
  'EA 41','EA 42',
]
const STANDARD_OPTIONS  = [
  'ISO 9001', 'ISO 14001', 'ISO 45001', 'ISO 27001', 'ISO 22000',
  'FSSC 22000', 'ISO 13485', 'ISO 50001', 'ISO 37001', 'ISO 37301',
]

function ScopeInput({ standardCode, eaCodes, scopeCategory, onChangeEA, onChangeScope }: {
  standardCode:  string
  eaCodes:       string[]
  scopeCategory: string
  onChangeEA:    (v: string[]) => void
  onChangeScope: (v: string) => void
}) {
  const type = qualificationScopeType(standardCode)
  const c    = standardCode.toLowerCase()

  const riskLabel   = c.includes('14001') ? 'EMS complexity'
    : c.includes('45001') ? 'OH&S risk level'
    : 'Risk category'
  const riskOptions = c.includes('14001') ? ['High','Medium','Low','Limited'] : ['High','Medium','Low']

  if (type === 'food') {
    const selected = scopeCategory.split(',').map((s) => s.trim()).filter(Boolean)
    return (
      <div className="mt-2">
        <label className="block text-xs text-gray-400 mb-1">Food chain categories</label>
        <div className="flex flex-wrap gap-1">
          {FOOD_CHAIN_CATEGORIES.map((cat) => {
            const active = selected.includes(cat)
            return (
              <button key={cat} type="button"
                className="rounded px-2 py-0.5 text-xs font-mono border transition-colors"
                style={active
                  ? { background: '#FEF3C7', color: '#92400E', borderColor: '#FDE68A' }
                  : { background: 'white', color: '#9CA3AF', borderColor: '#E5E7EB' }}
                onClick={() => {
                  const next = active ? selected.filter((x) => x !== cat) : [...selected, cat]
                  onChangeScope(next.join(', '))
                }}>
                {cat}
              </button>
            )
          })}
        </div>
      </div>
    )
  }

  if (type === 'medical') {
    const selected = scopeCategory.split(',').map((s) => s.trim()).filter(Boolean)
    return (
      <div className="mt-2">
        <label className="block text-xs text-gray-400 mb-1">Technical areas (MD)</label>
        <div className="flex flex-wrap gap-1">
          {MEDICAL_DEVICE_TAS.map((ta) => {
            const active = selected.includes(ta)
            return (
              <button key={ta} type="button"
                className="rounded px-2 py-0.5 text-xs font-mono border transition-colors"
                style={active
                  ? { background: '#EDE9FE', color: '#5B21B6', borderColor: '#DDD6FE' }
                  : { background: 'white', color: '#9CA3AF', borderColor: '#E5E7EB' }}
                onClick={() => {
                  const next = active ? selected.filter((x) => x !== ta) : [...selected, ta]
                  onChangeScope(next.join(', '))
                }}>
                {ta}
              </button>
            )
          })}
        </div>
      </div>
    )
  }

  if (type === 'isms') {
    const selected = scopeCategory.split(',').map((s) => s.trim()).filter(Boolean)
    return (
      <div className="mt-2">
        <label className="mb-1 block text-xs text-gray-400">ISMS technical areas</label>
        <div className="grid gap-1 sm:grid-cols-2">
          {ISMS_TECHNICAL_AREAS.map((area) => {
            const active = selected.includes(area.code)
            return (
              <label
                key={area.code}
                className={`flex cursor-pointer items-start gap-2 rounded border px-2 py-1.5 text-xs ${
                  active
                    ? 'border-blue-300 bg-blue-50 text-blue-800'
                    : 'border-gray-200 bg-white text-gray-500'
                }`}
              >
                <input
                  type="checkbox"
                  checked={active}
                  onChange={() => {
                    const next = active
                      ? selected.filter((item) => item !== area.code)
                      : [...selected, area.code]
                    onChangeScope(next.join(', '))
                  }}
                />
                <span>{area.label}</span>
              </label>
            )
          })}
        </div>
      </div>
    )
  }

  if (type === 'sector') {
    return (
      <div className="mt-2">
        <label className="block text-xs text-gray-400 mb-1">Sector type</label>
        <select
          className="w-full rounded border border-gray-200 px-2 py-1.5 text-sm"
          value={scopeCategory}
          onChange={(e) => onChangeScope(e.target.value)}>
          <option value="">— Select —</option>
          <option>Public</option>
          <option>Private</option>
          <option>Third sector/NGO</option>
        </select>
      </div>
    )
  }

  if (type === 'energy') {
    const selectedComplexity = normalizeEnmsEnergyComplexity(scopeCategory)
    return (
      <div className="mt-2">
        <label className="block text-xs text-gray-400 mb-1">Energy complexity</label>
        <select
          className="w-full rounded border border-gray-200 px-2 py-1.5 text-sm"
          value={selectedComplexity}
          onChange={(e) => onChangeScope(e.target.value)}>
          <option value="" disabled>— Select energy complexity —</option>
          {ENMS_ENERGY_COMPLEXITY_OPTIONS.map((level) => (
            <option key={level} value={level}>{level}</option>
          ))}
        </select>
        <p className="mt-1 text-[11px] text-gray-400">Required for ISO 50001 auditor matching in Planner.</p>
      </div>
    )
  }

  // EA-code standards only: ISO 9001, 14001, 45001.
  return (
    <div className="mt-2 space-y-2">
      <div>
        <label className="block text-xs text-gray-400 mb-1">EA codes</label>
        <div className="flex flex-wrap gap-1">
          {EA_CODES.map((ea) => {
            const active = eaCodes.includes(ea)
            return (
              <button
                key={ea}
                type="button"
                className="rounded border px-1.5 py-0.5 font-mono text-xs transition-colors"
                style={active
                  ? { background: '#D1FAE5', color: '#065F46', borderColor: '#6EE7B7' }
                  : { background: 'white', color: '#9CA3AF', borderColor: '#E5E7EB' }}
                onClick={() => {
                  const next = active ? eaCodes.filter((x) => x !== ea) : [...eaCodes, ea]
                  onChangeEA(next)
                }}
              >
                {ea}
              </button>
            )
          })}
        </div>
        <p className="mt-1 text-[11px] text-gray-400">Select the EA sector codes this auditor is qualified to audit.</p>
      </div>
      <div>
        <label className="block text-xs text-gray-400 mb-1">{riskLabel}</label>
        <select
          className="w-full rounded border border-gray-200 px-2 py-1.5 text-sm"
          value={scopeCategory}
          onChange={(e) => onChangeScope(e.target.value)}>
          <option value="">— Select —</option>
          {riskOptions.map((o) => <option key={o}>{o}</option>)}
        </select>
      </div>
    </div>
  )
}

function AddAuditorPanel({ onClose, onCreated }: { onClose: () => void; onCreated: () => void }) {
  const fileRef = useRef<HTMLInputElement | null>(null)
  const [file,         setFile]         = useState<File | null>(null)
  const [preview,      setPreview]      = useState<AuditorIngestResult | null>(null)
  const [quals,        setQuals]        = useState<QualRow[]>([])
  const [activeSince,  setActiveSince]  = useState('')
  const [ingestErr,    setIngestErr]    = useState<string | null>(null)   // Step-1 inline error
  const [manualNotice, setManualNotice] = useState<string | null>(null)   // Step-2 amber notice
  const [saveErr,      setSaveErr]      = useState<string | null>(null)
  const [validationErr, setValidationErr] = useState<string | null>(null)

  function resetForBlank() {
    setQuals([{ ...BLANK_QUAL }])
    setActiveSince('')
    setSaveErr(null)
    setValidationErr(null)
  }

  const ingest = useMutation({
    mutationFn: async (f: File) => {
      const fd = new FormData()
      fd.append('file', f)
      const res = await api.post<AuditorIngestResult>('/auditors/ingest', fd, {
        headers: { 'Content-Type': 'multipart/form-data' },
      })
      return res.data
    },
    onSuccess: (data) => {
      const extractedQuals = toQualRows(data)
      setPreview(data)
      setQuals(extractedQuals.length ? extractedQuals : [{ ...BLANK_QUAL }])
      setActiveSince(data.active_since ?? '')
      setIngestErr(null)
      setManualNotice(null)
    },
    onError: () => {
      // Surface a friendly message and drop the user straight into a blank manual form
      // instead of stranding them on Step 1 with a raw Python traceback.
      setIngestErr(null)
      setPreview({})
      resetForBlank()
      setManualNotice('Could not extract fields from this document. You can fill in the details manually below.')
    },
  })

  const save = useMutation({
    mutationFn: async () => {
      if (!preview) throw new Error('No preview')
      const cleanQuals = quals.filter((q) => q.standard_code.trim())
      const derivedEaCodes = Array.from(new Set(
        cleanQuals
          .filter((q) => qualificationScopeType(q.standard_code.trim()) === 'ea')
          .flatMap((q) => q.ea_codes)
          .map((code) => code.trim())
          .filter(Boolean),
      ))
      const accBodies = Array.from(new Set(cleanQuals.map((q) => q.accreditation_body.trim()).filter(Boolean)))
      const body = {
        name:                  (preview.name ?? '').trim(),
        email:                 preview.email  ?? null,
        phone:                 preview.phone  ?? null,
        mobile:                preview.mobile ?? null,
        role:                  preview.role   ?? null,
        field_of_expertise:    preview.field_of_expertise ?? null,
        active_since:          activeSince || null,
        ea_codes:              derivedEaCodes.length ? derivedEaCodes : null,
        accreditation_bodies:  accBodies.length ? accBodies : null,
        education:             preview.education       ?? [],
        languages:             preview.languages       ?? [],
        standard_qualifications: cleanQuals.map((q) => {
          const yrs  = parseInt(q.experience_years, 10)
          const stype = qualificationScopeType(q.standard_code.trim())
          const isEA  = stype === 'ea'
          return {
            standard_code:      q.standard_code.trim(),
            accreditation_body: q.accreditation_body.trim() || null,
            technical_depth:    q.technical_depth || null,
            experience_years:   Number.isFinite(yrs) ? yrs : null,
            // EA-code standards get ea_codes; all others get empty array
            ea_codes:           isEA ? (q.ea_codes.length ? q.ea_codes : []) : [],
            scope_category:     stype === 'energy'
              ? (normalizeEnmsEnergyComplexity(q.scope_category) || null)
              : (q.scope_category || null),
            is_qualified:       true,
          }
        }),
        work_experience:       preview.work_experience ?? [],
        training_records:      preview.training_records ?? [],
        audit_log:             [],
      }
      await api.post('/auditors/', body)
    },
    onSuccess: () => { onCreated(); onClose() },
    onError: (err) => {
      // eslint-disable-next-line @typescript-eslint/no-explicit-any
      const anyErr = err as any
      setSaveErr(String(anyErr?.response?.data?.detail ?? anyErr?.message ?? 'Failed to save.'))
    },
  })

  function patchPreview(p: Partial<AuditorIngestResult>) {
    setPreview((prev) => (prev ? { ...prev, ...p } : prev))
  }

  function pickFile(f: File | null) {
    setFile(f); setPreview(null); setIngestErr(null); setSaveErr(null); setManualNotice(null)
  }

  function goManual() {
    setPreview({})
    resetForBlank()
    setIngestErr(null)
    setManualNotice(null)
  }

  function attemptSave() {
    if (!preview) return
    if (!(preview.name ?? '').trim()) {
      setValidationErr('Name is required.')
      return
    }
    if (!quals.some((q) => q.standard_code.trim())) {
      setValidationErr('Add at least one qualification with a standard code.')
      return
    }
    if (quals.some((q) =>
      qualificationScopeType(q.standard_code) === 'energy'
      && !normalizeEnmsEnergyComplexity(q.scope_category)
    )) {
      setValidationErr('Select an Energy complexity for every ISO 50001 qualification.')
      return
    }
    setValidationErr(null)
    setSaveErr(null)
    save.mutate()
  }

  return (
    <>
      <div className="fixed inset-0 z-40 bg-black/30" onClick={onClose} />
      <div className="fixed right-0 top-0 z-50 flex h-full w-full max-w-3xl flex-col bg-white shadow-xl">
        <div className="flex items-center justify-between border-b border-gray-100 px-5 py-4">
          <h2 className="text-base font-semibold text-gray-800">Add auditor</h2>
          <button type="button" onClick={onClose} className="rounded p-1 text-gray-400 hover:bg-gray-50">
            <X size={18} />
          </button>
        </div>

        <div className="flex-1 overflow-y-auto px-5 py-5">
          {!preview ? (
            <>
              <p className="mb-3 text-sm text-gray-500">
                Upload a CV or FR.201 form (PDF or DOCX). Fields will be extracted for review before saving.
              </p>

              <div
                className="rounded-lg border border-dashed border-gray-200 p-6 text-center"
                style={{ background: '#F0FAF4' }}
              >
                <Upload size={20} className="mx-auto text-certiva-primary" />
                {file
                  ? <p className="mt-2 inline-flex items-center gap-1 text-sm text-gray-700"><FileText size={14} /> {file.name}</p>
                  : <p className="mt-2 text-sm text-gray-500">Drag a file here or click to choose</p>}
                <input
                  ref={fileRef} type="file" accept=".pdf,.docx" className="hidden"
                  onChange={(e) => pickFile(e.target.files?.[0] ?? null)}
                />
                <button
                  type="button" onClick={() => fileRef.current?.click()}
                  className="mt-3 rounded-lg border border-certiva-primary px-3 py-1.5 text-sm font-medium text-certiva-primary hover:bg-white"
                >
                  Choose file
                </button>
              </div>

              {ingestErr && <p className="mt-3 text-xs text-red-600">{ingestErr}</p>}

              <button
                type="button"
                disabled={!file || ingest.isPending}
                onClick={() => file && ingest.mutate(file)}
                className="mt-4 flex w-full items-center justify-center gap-2 rounded-lg bg-certiva-primary px-4 py-2.5 text-sm font-medium text-white hover:opacity-90 disabled:opacity-60"
              >
                {ingest.isPending && <Loader2 size={14} className="animate-spin" />}
                {ingest.isPending ? 'Extracting…' : 'Extract fields'}
              </button>

              <div className="mt-3 text-center">
                <button
                  type="button" onClick={goManual}
                  className="text-sm text-certiva-primary underline cursor-pointer hover:opacity-70"
                >
                  Skip upload and enter details manually →
                </button>
              </div>
            </>
          ) : (
            <AuditorPreviewForm
              preview={preview} quals={quals} activeSince={activeSince}
              notice={manualNotice}
              validationErr={validationErr}
              onPreviewChange={patchPreview}
              onQualsChange={setQuals}
              onActiveSinceChange={setActiveSince}
              saving={save.isPending}
              saveErr={saveErr}
              onBack={() => { setPreview(null); setSaveErr(null); setManualNotice(null); setValidationErr(null) }}
              onSave={attemptSave}
            />
          )}
        </div>
      </div>
    </>
  )
}

// ── JSON Bulk Import ──────────────────────────────────────────────────────────

function JsonImportButton() {
  const [loading, setLoading] = useState(false)
  const [result, setResult]   = useState<null | { summary: Record<string, number>; credentials: Record<string, string>[]; errors: Record<string, unknown>[] }>(null)
  const [err, setErr]         = useState<string | null>(null)
  const fileRef = useRef<HTMLInputElement>(null)
  const queryClient = useQueryClient()

  async function handleFile(e: React.ChangeEvent<HTMLInputElement>) {
    const file = e.target.files?.[0]
    if (!file) return
    setLoading(true); setErr(null); setResult(null)
    try {
      const text = await file.text()
      const auditors = JSON.parse(text)
      const res = await api.post('/auditors/bulk-import-json', {
        auditors,
        replace_all: true,
      })
      setResult(res.data)
      queryClient.invalidateQueries({ queryKey: ['auditors-dashboard'] })
      queryClient.invalidateQueries({ queryKey: ['auditors-active'] })
    } catch (e: unknown) {
      const detail = (e as { response?: { data?: { detail?: string } } })?.response?.data?.detail
      setErr(detail ?? 'Import failed.')
    } finally {
      setLoading(false)
      if (fileRef.current) fileRef.current.value = ''
    }
  }

  function downloadCredentials() {
    if (!result) return
    const header = 'full_name,username,password\n'
    const rows = result.credentials.map(c => `"${c.name}","${c.username}","${c.password}"`)
    const blob = new Blob([header + rows.join('\n')], { type: 'text/csv' })
    const url = URL.createObjectURL(blob)
    const a = document.createElement('a'); a.href = url; a.download = 'auditor_credentials.csv'; a.click()
    URL.revokeObjectURL(url)
  }

  return (
    <>
      <input ref={fileRef} type="file" accept=".json" className="hidden" onChange={handleFile} />
      <button
        type="button"
        onClick={() => fileRef.current?.click()}
        disabled={loading}
        className="flex items-center gap-1 rounded-lg border border-certiva-primary px-3 py-1.5
          text-sm font-medium text-certiva-primary hover:bg-certiva-primary/5 disabled:opacity-50"
      >
        {loading ? <Loader2 size={14} className="animate-spin" /> : null}
        {loading ? 'Importing…' : 'Import JSON'}
      </button>

      {(result || err) && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 p-4">
          <div className="w-full max-w-lg rounded-xl bg-white shadow-xl p-6">
            {err && (
              <div className="text-sm text-red-700 mb-4">{err}</div>
            )}
            {result && (
              <>
                <h2 className="text-base font-semibold text-gray-800 mb-3">Import complete</h2>
                <div className="grid grid-cols-3 gap-3 text-center text-xs mb-4">
                  <div className="rounded-lg bg-green-50 p-3">
                    <p className="text-2xl font-bold text-green-700">{result.summary.created}</p>
                    <p className="text-green-600">Created</p>
                  </div>
                  <div className="rounded-lg bg-gray-50 p-3">
                    <p className="text-2xl font-bold text-gray-600">{result.summary.skipped ?? 0}</p>
                    <p className="text-gray-500">Skipped</p>
                  </div>
                  <div className={`rounded-lg p-3 ${result.errors.length > 0 ? 'bg-red-50' : 'bg-gray-50'}`}>
                    <p className={`text-2xl font-bold ${result.errors.length > 0 ? 'text-red-600' : 'text-gray-600'}`}>{result.errors.length}</p>
                    <p className={result.errors.length > 0 ? 'text-red-500' : 'text-gray-500'}>Errors</p>
                  </div>
                </div>
                {result.errors.length > 0 && (
                  <div className="mb-3 max-h-24 overflow-y-auto rounded border border-red-100 bg-red-50 p-2 text-xs text-red-600">
                    {result.errors.map((e, i) => (
                      <p key={i}>{String(e.name)}: {String(e.reason)}</p>
                    ))}
                  </div>
                )}
                <p className="text-xs text-amber-700 bg-amber-50 border border-amber-200 rounded-lg px-3 py-2 mb-4">
                  Download the credentials CSV now — passwords cannot be recovered later.
                </p>
                <button
                  onClick={downloadCredentials}
                  className="mb-2 w-full rounded-lg bg-certiva-primary px-4 py-2 text-sm font-medium text-white hover:opacity-90"
                >
                  Download credentials CSV
                </button>
              </>
            )}
            <button
              onClick={() => { setResult(null); setErr(null) }}
              className="w-full rounded-lg border border-gray-200 px-4 py-2 text-sm text-gray-600 hover:bg-gray-50"
            >
              Close
            </button>
          </div>
        </div>
      )}
    </>
  )
}

// ── Main page ─────────────────────────────────────────────────────────────────

export default function AuditorsPage() {
  const router       = useRouter()
  const queryClient  = useQueryClient()
  const [adding, setAdding] = useState(false)

  const { data, isLoading } = useQuery<AuditorDashboardEntry[]>({
    queryKey: ['auditors-dashboard'],
    queryFn: () => api.get<AuditorDashboardEntry[]>('/auditors/dashboard').then((r) => r.data),
  })

  const { data: witnessSummary } = useQuery<WitnessStatus[]>({
    queryKey: ['witness-summary'],
    queryFn: () => api.get<WitnessStatus[]>('/auditors/witness-summary').then((r) => r.data),
  })

  const rows = data ?? []
  const totalCount   = rows.length
  const activeCount  = rows.filter((a) => a.is_active).length
  const warningCount = rows.filter((a) => a.is_active && hasWarnings(a)).length

  function refreshLists() {
    queryClient.invalidateQueries({ queryKey: ['auditors-dashboard'] })
    queryClient.invalidateQueries({ queryKey: ['auditors-active'] })
  }

  return (
    <>
      {/* Header */}
      <div className="mb-5 flex items-center justify-between">
        <h1 className="text-xl font-semibold text-gray-800">Auditors</h1>
        <div className="flex items-center gap-2">
          <JsonImportButton />
          <button
            type="button"
            onClick={() => setAdding(true)}
            className="flex items-center gap-1.5 rounded-lg px-3 py-1.5 text-sm font-medium text-white hover:opacity-90"
            style={{ background: '#1A4731' }}
          >
            <Plus size={14} /> Add auditor
          </button>
        </div>
      </div>

      {/* Stat row */}
      <div className="mb-5 grid grid-cols-3 gap-3">
        <StatCard label="Total auditors"   value={totalCount} />
        <StatCard label="Active"           value={activeCount} />
        <StatCard label="Expiry warnings"  value={warningCount} />
      </div>

      {/* Table */}
      <div className="rounded-lg border border-gray-100 bg-white">
        <div className="overflow-x-auto">
          <table className="w-full text-sm">
            <thead>
              <tr className="border-b border-gray-100 text-left text-xs font-medium uppercase tracking-wide text-gray-400">
                <th className="px-4 py-2.5">Auditor</th>
                <th className="px-4 py-2.5">Qualified standards</th>
                <th className="px-4 py-2.5">EA codes</th>
                <th className="px-4 py-2.5">Accreditation bodies</th>
                <th className="px-4 py-2.5">Last audit</th>
                <th className="px-4 py-2.5">Status</th>
                <th className="px-4 py-2.5">Witness</th>
                <th className="px-4 py-2.5">Actions</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-gray-50">
              {isLoading
                ? Array.from({ length: 6 }).map((_, i) => <SkeletonRow key={i} />)
                : rows.length === 0
                ? (
                  <tr>
                    <td colSpan={8} className="px-4 py-12 text-center text-sm text-gray-400">
                      No auditors yet.
                    </td>
                  </tr>
                )
                : rows.map((a) => {
                  const witness = witnessSummary?.find((w) => w.auditor_id === a.auditor_id)
                  return (
                    <AuditorRow
                      key={a.auditor_id}
                      a={a}
                      quals={a.qualifications as AuditorQualificationSummary[]}
                      witness={witness}
                      onClick={() => router.push(`/auditors/${a.auditor_id}`)}
                    />
                  )
                })}
            </tbody>
          </table>
        </div>
      </div>

      {adding && <AddAuditorPanel onClose={() => setAdding(false)} onCreated={refreshLists} />}
    </>
  )
}

// ── Preview / edit form (Step 2 of add-auditor flow) ──────────────────────────

const ROLE_OPTIONS = ['Lead Auditor', 'Auditor', 'Technical Expert'] as const
const BODY_OPTIONS = ['UAF', 'TURKAK'] as const

function AuditorPreviewForm({
  preview, quals, activeSince,
  notice, validationErr,
  onPreviewChange, onQualsChange, onActiveSinceChange,
  saving, saveErr, onBack, onSave,
}: {
  preview:             AuditorIngestResult
  quals:               QualRow[]
  activeSince:         string
  notice:              string | null
  validationErr:       string | null
  onPreviewChange:     (p: Partial<AuditorIngestResult>) => void
  onQualsChange:       (q: QualRow[]) => void
  onActiveSinceChange: (v: string) => void
  saving:              boolean
  saveErr:             string | null
  onBack:              () => void
  onSave:              () => void
}) {
  function patchQual(i: number, p: Partial<QualRow>) {
    onQualsChange(quals.map((q, idx) => (idx === i ? { ...q, ...p } : q)))
  }
  function addQual()    { onQualsChange([...quals, { ...BLANK_QUAL }]) }
  function removeQual(i: number) { onQualsChange(quals.filter((_, idx) => idx !== i)) }

  const nameMissing  = !(preview.name ?? '').trim()
  const hasAnyQual   = quals.some((q) => q.standard_code.trim())
  const canSave      = !saving && !nameMissing && hasAnyQual

  return (
    <div className="space-y-4">
      {notice && (
        <div className="rounded-lg border border-amber-200 bg-amber-50 p-3 text-sm text-amber-800">
          {notice}
        </div>
      )}

      <p className="text-sm text-gray-500">
        Review the fields and correct anything before saving.
      </p>

      <div className="grid grid-cols-2 gap-3">
        <div className="col-span-2">
          <label className={lblCls}>Name *</label>
          <input
            type="text" className={inputCls}
            value={preview.name ?? ''}
            onChange={(e) => onPreviewChange({ name: e.target.value })}
          />
          {nameMissing && <p className="mt-1 text-xs text-red-500">Name is required.</p>}
        </div>

        <div>
          <label className={lblCls}>Role</label>
          <select
            className={inputCls} value={preview.role ?? ''}
            onChange={(e) => onPreviewChange({ role: e.target.value || null })}
          >
            <option value="">—</option>
            {ROLE_OPTIONS.map((r) => <option key={r} value={r}>{r}</option>)}
          </select>
        </div>

        <div>
          <label className={lblCls}>Email</label>
          <input
            type="email" className={inputCls} value={preview.email ?? ''}
            onChange={(e) => onPreviewChange({ email: e.target.value || null })}
          />
        </div>

        <div>
          <label className={lblCls}>Active since</label>
          <input
            type="date" className={inputCls} value={activeSince}
            onChange={(e) => onActiveSinceChange(e.target.value)}
          />
        </div>
      </div>

      <div>
        <div className="mb-2 flex items-center justify-between">
          <div>
            <label className="block text-sm font-medium text-gray-700">Qualifications *</label>
            <p className="mt-0.5 text-xs text-gray-400">Add one card per standard, then select the exact scope or EA codes for that standard.</p>
          </div>
          <button type="button" onClick={addQual} className="inline-flex items-center gap-1 text-xs font-medium text-certiva-primary hover:opacity-70">
            <Plus size={12} /> Add standard
          </button>
        </div>
        <div className="space-y-2">
          {quals.length === 0 && (
            <p className="text-xs text-gray-400">No qualifications yet. Click “Add” to add one.</p>
          )}
          {quals.map((q, i) => (
            <div key={i} className="rounded-lg border border-gray-100 p-3 space-y-2">
              <div className="flex items-center justify-between gap-2">
                <p className="text-xs font-medium uppercase tracking-wide text-gray-400">Standard {i + 1}</p>
                <button type="button" onClick={() => removeQual(i)} className="rounded p-1 text-gray-400 hover:bg-gray-50 hover:text-red-500" aria-label="Remove qualification">
                  <Trash2 size={13} />
                </button>
              </div>
              <div className="flex flex-wrap items-center gap-2">
                <select
                  className={`${inputCls} min-w-40 flex-1`}
                  value={q.standard_code}
                  onChange={(e) => patchQual(i, { standard_code: e.target.value, ea_codes: [], scope_category: '' })}
                >
                  <option value="">— Standard —</option>
                  {STANDARD_OPTIONS.map((s) => (
                    <option key={s} value={s}>{s}</option>
                  ))}
                </select>
                <select
                  className={`${inputCls} w-28`} value={q.accreditation_body}
                  onChange={(e) => patchQual(i, { accreditation_body: e.target.value })}
                >
                  {BODY_OPTIONS.map((b) => <option key={b} value={b}>{b}</option>)}
                </select>
                <select
                  className={`${inputCls} w-36`} value={q.technical_depth}
                  onChange={(e) => patchQual(i, { technical_depth: e.target.value })}
                >
                  <option value="">— Role —</option>
                  <option>Lead Auditor</option>
                  <option>Team Auditor</option>
                  <option>Technical Expert</option>
                </select>
                <input
                  type="number" min={0} placeholder="Yrs" className={`${inputCls} w-20`}
                  value={q.experience_years}
                  onChange={(e) => patchQual(i, { experience_years: e.target.value })}
                />
              </div>
              {/* Scope input — adapts based on the standard code typed above */}
              <ScopeInput
                standardCode={q.standard_code}
                eaCodes={q.ea_codes}
                scopeCategory={q.scope_category}
                onChangeEA={(v) => patchQual(i, { ea_codes: v })}
                onChangeScope={(v) => patchQual(i, { scope_category: v })}
              />
            </div>
          ))}
        </div>
      </div>

      {validationErr && (
        <div className="rounded-lg border border-red-200 bg-red-50 p-3 text-sm text-red-700">{validationErr}</div>
      )}
      {saveErr && (
        <div className="rounded-lg border border-red-200 bg-red-50 p-3 text-sm text-red-700">{saveErr}</div>
      )}

      <div className="flex gap-2 pt-2">
        <button
          type="button" onClick={onBack} disabled={saving}
          className="flex-1 rounded-lg border border-gray-200 px-4 py-2 text-sm text-gray-700 hover:bg-gray-50 disabled:opacity-60"
        >
          Back
        </button>
        <button
          type="button" onClick={onSave}
          disabled={!canSave}
          className="flex flex-1 items-center justify-center gap-2 rounded-lg bg-certiva-primary px-4 py-2 text-sm font-medium text-white hover:opacity-90 disabled:opacity-60"
        >
          {saving && <Loader2 size={14} className="animate-spin" />}
          {saving ? 'Saving…' : 'Confirm & save'}
        </button>
      </div>
    </div>
  )
}
