'use client'

import { useState } from 'react'
import { Calculator } from 'lucide-react'

// ── Constants ─────────────────────────────────────────────────────────────────

const STANDARDS = ['QMS', 'EMS', 'OHSMS', 'FSMS', 'ISMS', 'MDQMS', 'ABMS', 'ENMS'] as const
type StandardCode = typeof STANDARDS[number]

type AuditType   = 'initial' | 'surveillance' | 'recertification'
type Body        = 'UAF' | 'TURKAK'
type Integration = 'full' | 'partial' | 'none'

const inputCls = 'w-full rounded-lg border border-gray-200 px-3 py-2 text-sm text-gray-800 outline-none focus:border-certiva-primary focus:ring-2 focus:ring-certiva-primary/20'
const lblCls   = 'mb-1 block text-xs font-medium text-gray-500'
const secLbl   = 'mb-2 block text-sm font-medium text-gray-700'

// ── Calculation engine (TS port mirroring backend/calculator/engine.py) ──────

// IAF MD-5 style brackets for ISO 9001 initial audit days vs effective person count.
// The backend uses full lookup tables; these brackets capture the overall pattern
// faithfully enough for an instant client-side preview.
const QMS_BRACKETS: ReadonlyArray<readonly [number, number]> = [
  [5, 1.5],   [10, 2],    [15, 2.5],  [25, 3],    [45, 4],
  [65, 5],    [85, 6],    [125, 7],   [175, 8],   [275, 9],
  [425, 10],  [625, 11],  [875, 12],  [1175, 13], [1550, 14],
  [2025, 15], [2675, 16], [3450, 17], [4350, 18], [5450, 19],
  [6800, 20], [8500, 21], [10700, 22],
]

// Multipliers relative to QMS, capturing the relative weight of each standard
// in the backend tables (ISMS / MDQMS run heavier, ABMS lighter).
const STD_MULT: Record<StandardCode, number> = {
  QMS: 1.0, EMS: 1.0, OHSMS: 1.0, FSMS: 1.1,
  ISMS: 1.2, MDQMS: 1.2, ABMS: 0.9, ENMS: 1.1,
}

// Audit-type scaling: surveillance ≈ 1/3, recert ≈ 2/3 of initial (per IAF MD-5).
const TYPE_MULT: Record<AuditType, number> = {
  initial: 1.0, surveillance: 1 / 3, recertification: 2 / 3,
}

// Integration reduction percentages (only applied when 2+ standards selected).
const INTEG_PCT: Record<Integration, number> = { full: 0.20, partial: 0.10, none: 0.0 }

// Reporting reduction is always 20% per backend engine.py.
const REPORTING_PCT = 0.20

function lookupBaseQms(eps: number): number {
  for (const [maxEps, days] of QMS_BRACKETS) {
    if (eps <= maxEps) return days
  }
  // Linear extrapolation past the largest bracket
  const [, last]    = QMS_BRACKETS[QMS_BRACKETS.length - 1]
  const [maxEps]    = QMS_BRACKETS[QMS_BRACKETS.length - 1]
  return last + (eps - maxEps) / 1500
}

// IAF rounding: .1-.2→floor, .3-.7→.5, .8-.9→ceil
function roundAudit(v: number): number {
  const intPart  = Math.floor(v)
  const fraction = Math.round((v - intPart) * 100) / 100
  if (fraction <= 0.2) return intPart
  if (fraction <= 0.7) return intPart + 0.5
  return Math.ceil(v)
}

interface StandardLine {
  code:        StandardCode
  base:        number   // base days for this standard (post site/type, pre reductions)
  integration: number   // share of integration reduction
  reporting:   number   // share of reporting reduction
  final:       number   // base − integration − reporting (rounded)
}

interface CalcInput {
  standards:   StandardCode[]
  ftEmployees: number
  ptEmployees: number
  sites:       number
  auditType:   AuditType
  body:        Body
  integration: Integration
}

interface CalcResult {
  lines:           StandardLine[]
  totalBase:       number
  totalIntegration: number
  totalReporting:  number
  totalFinal:      number
  auditDays:       number
  auditors:        number
  effectiveEps:    number
}

function suggestAuditors(totalDays: number): number {
  if (totalDays <= 3)  return 1
  if (totalDays <= 7)  return 2
  if (totalDays <= 15) return 3
  return 4
}

function calculate(input: CalcInput): CalcResult {
  const eps      = Math.max(1, input.ftEmployees + input.ptEmployees * 0.5)
  const baseQms  = lookupBaseQms(eps)
  const typeMult = TYPE_MULT[input.auditType]
  const siteMult = 1 + 0.30 * Math.max(0, input.sites - 1)
  // TURKAK accreditation adds a small overhead vs UAF in practice.
  const bodyMult = input.body === 'TURKAK' ? 1.05 : 1.0

  const rawBases = input.standards.map((code) => {
    const days = baseQms * STD_MULT[code] * typeMult * siteMult * bodyMult
    return { code, base: Math.round(days * 10) / 10 }
  })

  const totalRaw  = rawBases.reduce((s, r) => s + r.base, 0)
  const integPct  = input.standards.length >= 2 ? INTEG_PCT[input.integration] : 0
  const totalInteg     = Math.round(totalRaw * integPct       * 10) / 10
  const totalReporting = Math.round(totalRaw * REPORTING_PCT * 10) / 10

  const lines: StandardLine[] = rawBases.map((r) => {
    const share       = totalRaw > 0 ? r.base / totalRaw : 0
    const integration = Math.round(totalInteg     * share * 10) / 10
    const reporting   = Math.round(totalReporting * share * 10) / 10
    const final       = Math.max(0, roundAudit(r.base - integration - reporting))
    return { code: r.code, base: r.base, integration, reporting, final }
  })

  const totalFinal = lines.reduce((s, l) => s + l.final, 0)
  const auditors   = suggestAuditors(totalFinal)
  const auditDays  = auditors > 0 ? Math.max(1, Math.ceil(totalFinal / auditors)) : 0

  return {
    lines,
    totalBase:        Math.round(totalRaw       * 10) / 10,
    totalIntegration: totalInteg,
    totalReporting:   totalReporting,
    totalFinal:       Math.round(totalFinal     * 10) / 10,
    auditDays,
    auditors,
    effectiveEps:     eps,
  }
}


// ── Sub-components ────────────────────────────────────────────────────────────

function CheckGrid({
  selected, onToggle,
}: { selected: Set<StandardCode>; onToggle: (s: StandardCode) => void }) {
  return (
    <div className="grid grid-cols-2 gap-2">
      {STANDARDS.map((s) => {
        const active = selected.has(s)
        return (
          <label
            key={s}
            className={`flex cursor-pointer items-center gap-2 rounded-lg border px-3 py-2 text-sm ${
              active ? 'border-certiva-primary bg-certiva-primary/5 text-certiva-primary' : 'border-gray-200 text-gray-700'
            }`}
          >
            <input type="checkbox" checked={active} onChange={() => onToggle(s)} className="h-3.5 w-3.5 accent-certiva-primary" />
            {s}
          </label>
        )
      })}
    </div>
  )
}

function Radio<T extends string>({
  name, value, options, onChange,
}: { name: string; value: T; options: { value: T; label: string }[]; onChange: (v: T) => void }) {
  return (
    <div className="space-y-1.5">
      {options.map((o) => (
        <label key={o.value} className="flex cursor-pointer items-center gap-2 text-sm text-gray-700">
          <input
            type="radio" name={name} checked={value === o.value}
            onChange={() => onChange(o.value)} className="h-3.5 w-3.5 accent-certiva-primary"
          />
          {o.label}
        </label>
      ))}
    </div>
  )
}

function ResultsPanel({ result }: { result: CalcResult }) {
  return (
    <div className="space-y-5">
      <div className="rounded-xl bg-certiva-primary p-6 text-white">
        <p className="text-5xl font-medium leading-none">{result.totalFinal.toFixed(1)}</p>
        <p className="mt-2 text-sm opacity-90">Total audit man-days</p>
        <p className="mt-3 text-xs opacity-80">
          {result.auditDays} audit day{result.auditDays === 1 ? '' : 's'} × {result.auditors} auditor{result.auditors === 1 ? '' : 's'}
          <span className="ml-3 opacity-70">EPS {result.effectiveEps.toFixed(1)}</span>
        </p>
      </div>

      <div className="rounded-lg border border-gray-100 bg-white p-5">
        <p className="mb-3 text-sm font-medium text-gray-700">Per-standard breakdown</p>
        <table className="w-full text-sm">
          <thead>
            <tr className="border-b border-gray-100 text-left text-xs font-medium text-gray-500">
              <th className="py-2">Standard</th>
              <th className="py-2 text-right">Base days</th>
              <th className="py-2 text-right">Integration</th>
              <th className="py-2 text-right">Reporting</th>
              <th className="py-2 text-right">Final</th>
            </tr>
          </thead>
          <tbody>
            {result.lines.map((l) => (
              <tr key={l.code} className="border-b border-gray-50 text-gray-700">
                <td className="py-2">{l.code}</td>
                <td className="py-2 text-right">{l.base.toFixed(1)}</td>
                <td className="py-2 text-right text-amber-600">−{l.integration.toFixed(1)}</td>
                <td className="py-2 text-right text-amber-600">−{l.reporting.toFixed(1)}</td>
                <td className="py-2 text-right font-medium">{l.final.toFixed(1)}</td>
              </tr>
            ))}
            <tr className="font-semibold text-gray-800">
              <td className="pt-3">Total</td>
              <td className="pt-3 text-right">{result.totalBase.toFixed(1)}</td>
              <td className="pt-3 text-right text-amber-700">−{result.totalIntegration.toFixed(1)}</td>
              <td className="pt-3 text-right text-amber-700">−{result.totalReporting.toFixed(1)}</td>
              <td className="pt-3 text-right">{result.totalFinal.toFixed(1)}</td>
            </tr>
          </tbody>
        </table>

        {result.totalIntegration > 0 && (
          <p className="mt-4 text-gray-400" style={{ fontSize: 13 }}>
            Integration reduction: 20% applied when 2+ standards audited together.
            Reporting reduction: 20% applied to shared reporting effort.
          </p>
        )}
      </div>
    </div>
  )
}

// ── Main page ────────────────────────────────────────────────────────────────

export default function CalculatorPage() {
  const [selected,    setSelected]    = useState<Set<StandardCode>>(new Set(['QMS']))
  const [ft,          setFt]          = useState<number>(50)
  const [pt,          setPt]          = useState<number>(0)
  const [sites,       setSites]       = useState<number>(1)
  const [auditType,   setAuditType]   = useState<AuditType>('initial')
  const [body,        setBody]        = useState<Body>('UAF')
  const [integration, setIntegration] = useState<Integration>('full')
  const [result,      setResult]      = useState<CalcResult | null>(null)
  const [error,       setError]       = useState<string | null>(null)

  const eff       = ft + pt * 0.5
  const multiStd  = selected.size >= 2

  function toggle(s: StandardCode) {
    setSelected((prev) => {
      const next = new Set(prev)
      if (next.has(s)) next.delete(s); else next.add(s)
      return next
    })
  }

  function handleCalculate() {
    setError(null)
    if (selected.size === 0) { setError('Select at least one standard.'); return }
    if (ft < 0 || pt < 0)    { setError('Employee counts cannot be negative.'); return }
    if (sites < 1)           { setError('Number of sites must be at least 1.'); return }
    setResult(calculate({
      standards: Array.from(selected),
      ftEmployees: ft, ptEmployees: pt, sites,
      auditType, body, integration,
    }))
  }

  return (
    <div className="mx-auto max-w-[1200px] py-4">
      <h1 className="mb-5 text-gray-800" style={{ fontSize: 22, fontWeight: 500 }}>Man-day calculator</h1>

      <div className="flex gap-6">
        {/* Left: inputs */}
        <aside className="w-[360px] shrink-0 rounded-lg border border-gray-100 bg-white p-5">
          <div className="mb-5">
            <span className={secLbl}>Standards</span>
            <CheckGrid selected={selected} onToggle={toggle} />
          </div>

          <div className="mb-5">
            <span className={secLbl}>Personnel</span>
            <div className="grid grid-cols-2 gap-3">
              <div>
                <label className={lblCls}>Full-time</label>
                <input
                  type="number" min={0} value={ft}
                  onChange={(e) => setFt(Math.max(0, Number(e.target.value) || 0))}
                  className={inputCls}
                />
              </div>
              <div>
                <label className={lblCls}>Part-time</label>
                <input
                  type="number" min={0} value={pt}
                  onChange={(e) => setPt(Math.max(0, Number(e.target.value) || 0))}
                  className={inputCls}
                />
              </div>
            </div>
            <p className="mt-1.5 text-xs text-gray-500">Effective total: {eff.toFixed(1)}</p>
          </div>

          <div className="mb-5">
            <span className={secLbl}>Sites</span>
            <input
              type="number" min={1} value={sites}
              onChange={(e) => setSites(Math.max(1, Number(e.target.value) || 1))}
              className={inputCls}
            />
          </div>

          <div className="mb-5">
            <span className={secLbl}>Audit type</span>
            <Radio
              name="auditType" value={auditType} onChange={setAuditType}
              options={[
                { value: 'initial',         label: 'Initial certification' },
                { value: 'surveillance',    label: 'Surveillance' },
                { value: 'recertification', label: 'Recertification' },
              ]}
            />
          </div>

          <div className="mb-5">
            <span className={secLbl}>Accreditation body</span>
            <Radio
              name="body" value={body} onChange={setBody}
              options={[{ value: 'UAF', label: 'UAF' }, { value: 'TURKAK', label: 'TURKAK' }]}
            />
          </div>

          {multiStd && (
            <div className="mb-5">
              <span className={secLbl}>Integration level</span>
              <select
                value={integration} onChange={(e) => setIntegration(e.target.value as Integration)}
                className={inputCls}
              >
                <option value="full">Full integration</option>
                <option value="partial">Partial</option>
                <option value="none">No integration</option>
              </select>
            </div>
          )}

          {error && <p className="mb-3 text-xs text-red-500">{error}</p>}

          <button
            type="button" onClick={handleCalculate}
            className="w-full rounded-lg bg-certiva-primary px-4 py-2.5 text-sm font-medium text-white hover:opacity-90"
          >
            Calculate
          </button>
        </aside>

        {/* Right: results */}
        <main className="flex-1">
          {result ? (
            <ResultsPanel result={result} />
          ) : (
            <div className="flex h-full min-h-[400px] flex-col items-center justify-center rounded-lg border border-dashed border-gray-200 bg-white">
              <Calculator size={48} className="text-gray-300" />
              <p className="mt-3 text-sm text-gray-400">Enter inputs and press Calculate</p>
            </div>
          )}
        </main>
      </div>
    </div>
  )
}
