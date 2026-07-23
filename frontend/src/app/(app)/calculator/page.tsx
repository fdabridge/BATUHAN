'use client'

import axios from 'axios'
import {
  AlertTriangle,
  Building2,
  Calculator,
  CheckCircle2,
  ClipboardCheck,
  FileText,
  Layers3,
  Loader2,
  MapPin,
  Plus,
  ShieldCheck,
  SlidersHorizontal,
  Trash2,
  Users,
} from 'lucide-react'
import { ReactNode, useMemo, useState } from 'react'

import api from '@/lib/api'
import {
  AdvancedCalculationResult,
  AdvancedCalculatorRequest,
  AuditType,
  CALCULATOR_STANDARDS,
  CalculatorSite,
  CalculatorStandard,
  Category,
} from '@/lib/advancedCalculator'

const inputClass =
  'w-full rounded-lg border border-gray-200 bg-white px-3 py-2.5 text-sm text-gray-800 outline-none transition focus:border-certiva-primary focus:ring-2 focus:ring-certiva-primary/15'
const labelClass = 'mb-1.5 block text-xs font-medium text-gray-600'

const MD5_INCREASE_FACTORS = [
  'Complex logistics or multiple buildings',
  'Multiple languages or interpreter required',
  'Very large site for the personnel count',
  'High regulatory burden',
  'Complex or numerous unique processes',
  'Temporary sites must be visited',
  'Outsourced functions or processes',
  'Higher environmental or OH&S risk',
]

const MD5_DECREASE_FACTORS = [
  'No design responsibility (QMS)',
  'Very small site for the personnel count',
  'Mature, demonstrably effective management system',
  'Prior CB knowledge of the management system',
  'High automation (not OH&S)',
  'Substantial off-location personnel auditable through records (not OH&S)',
]

const INTEGRATION_CRITERIA: Array<{
  key: keyof AdvancedCalculatorRequest['integration']
  label: string
}> = [
  { key: 'integrated_documentation', label: 'Integrated documentation and work instructions' },
  { key: 'integrated_management_review', label: 'One integrated management review' },
  { key: 'integrated_internal_audits', label: 'Integrated internal audit programme' },
  { key: 'integrated_policy_objectives', label: 'Integrated policy and objectives' },
  { key: 'integrated_processes', label: 'Integrated system processes' },
  { key: 'integrated_improvement', label: 'Integrated corrective action and improvement' },
  { key: 'integrated_responsibilities', label: 'Integrated management support and responsibilities' },
]

const MULTISITE_CRITERIA: Array<{
  key: keyof AdvancedCalculatorRequest['multi_site_eligibility']
  label: string
}> = [
  { key: 'single_management_system', label: 'One management system covers all sites' },
  { key: 'central_function_identified', label: 'Central function is identified and has authority' },
  { key: 'centralized_management_review', label: 'Centralized management review covers every site' },
  { key: 'centralized_internal_audit', label: 'All sites are in the internal audit programme' },
  { key: 'similar_processes', label: 'Sampling-eligible sites perform very similar activities' },
]

const initialForm: AdvancedCalculatorRequest = {
  organization_name: '',
  scope: '',
  standards: ['QMS'],
  audit_type: 'initial',
  accreditation_body: 'UAF',
  full_time_personnel: 50,
  part_time_personnel: 0,
  part_time_hours_per_day: 4,
  normal_hours_per_day: 8,
  subcontractors: 0,
  subcontractors_in_scope: true,
  seasonal_temporary_personnel: 0,
  office_personnel: 0,
  repetitive_personnel: 0,
  shift_count: 1,
  same_process_all_shifts: true,
  sites: [],
  multi_site_sampling_requested: false,
  multi_site_eligibility: {
    single_management_system: false,
    central_function_identified: false,
    centralized_management_review: false,
    centralized_internal_audit: false,
    similar_processes: false,
  },
  mature_management_system: false,
  sampled_site_reduction_pct: 0,
  sampled_site_reduction_justification: '',
  manual_ea_codes: [],
  category_overrides: {},
  integration: {
    enabled: false,
    integrated_documentation: false,
    integrated_management_review: false,
    integrated_internal_audits: false,
    integrated_policy_objectives: false,
    integrated_processes: false,
    integrated_improvement: false,
    integrated_responsibilities: false,
    combined_audit_capability_pct: 20,
  },
  md5_adjustment_pct: 0,
  adjustment_justification: '',
  increase_factors: [],
  decrease_factors: [],
  remote_audit_pct: 0,
  food_chain_categories: [],
  fsms_offsite_storage_count: 0,
  fsms_separate_head_office: false,
  fsms_fssc22000: false,
  annual_energy_tj: null,
  num_energy_types: null,
  num_seus: null,
}

function Section({
  icon,
  title,
  description,
  children,
}: {
  icon: ReactNode
  title: string
  description?: string
  children: ReactNode
}) {
  return (
    <section className="rounded-xl border border-gray-100 bg-white p-5 shadow-sm">
      <div className="mb-4 flex items-start gap-3">
        <div className="rounded-lg bg-certiva-primary/8 p-2 text-certiva-primary">{icon}</div>
        <div>
          <h2 className="text-sm font-semibold text-gray-800">{title}</h2>
          {description && <p className="mt-0.5 text-xs leading-5 text-gray-500">{description}</p>}
        </div>
      </div>
      {children}
    </section>
  )
}

function NumberField({
  label,
  value,
  onChange,
  min = 0,
  max,
  step = 1,
  hint,
}: {
  label: string
  value: number | null
  onChange: (value: number | null) => void
  min?: number
  max?: number
  step?: number
  hint?: string
}) {
  return (
    <div>
      <label className={labelClass}>{label}</label>
      <input
        type="number"
        min={min}
        max={max}
        step={step}
        value={value ?? ''}
        onChange={(event) => {
          if (event.target.value === '') onChange(null)
          else onChange(Number(event.target.value))
        }}
        className={inputClass}
      />
      {hint && <p className="mt-1 text-[11px] leading-4 text-gray-400">{hint}</p>}
    </div>
  )
}

function CheckRow({
  checked,
  onChange,
  label,
  detail,
}: {
  checked: boolean
  onChange: (checked: boolean) => void
  label: string
  detail?: string
}) {
  return (
    <label className="flex cursor-pointer items-start gap-2.5 rounded-lg border border-gray-100 px-3 py-2.5 hover:bg-gray-50">
      <input
        type="checkbox"
        checked={checked}
        onChange={(event) => onChange(event.target.checked)}
        className="mt-0.5 h-4 w-4 accent-certiva-primary"
      />
      <span>
        <span className="block text-xs font-medium text-gray-700">{label}</span>
        {detail && <span className="mt-0.5 block text-[11px] leading-4 text-gray-400">{detail}</span>}
      </span>
    </label>
  )
}

function ResultsPanel({ result }: { result: AdvancedCalculationResult }) {
  const auditTypeLabel =
    result.audit_type === 'initial'
      ? 'Initial certification'
      : result.audit_type === 'surveillance'
        ? 'Surveillance'
        : 'Recertification'

  return (
    <div className="space-y-4">
      <div className="rounded-xl bg-certiva-primary p-6 text-white shadow-sm">
        <div className="flex items-start justify-between gap-4">
          <div>
            <p className="text-xs font-medium uppercase tracking-wider opacity-75">
              {auditTypeLabel} recommendation
            </p>
            <p className="mt-2 text-5xl font-semibold leading-none">
              {result.final_audit_time.toFixed(1)}
            </p>
            <p className="mt-2 text-sm opacity-85">auditor-days</p>
          </div>
          <ShieldCheck size={34} className="opacity-80" />
        </div>
        <div className="mt-5 grid grid-cols-3 gap-2 border-t border-white/20 pt-4 text-xs">
          <div>
            <p className="opacity-65">On-site</p>
            <p className="mt-1 font-semibold">{result.on_site_time.toFixed(2)}</p>
          </div>
          <div>
            <p className="opacity-65">Remote</p>
            <p className="mt-1 font-semibold">{result.remote_time.toFixed(2)}</p>
          </div>
          <div>
            <p className="opacity-65">Effective personnel</p>
            <p className="mt-1 font-semibold">{result.effective_personnel}</p>
          </div>
        </div>
        {result.stage_1_time !== null && result.stage_2_time !== null && (
          <div className="mt-3 flex gap-4 rounded-lg bg-white/10 px-3 py-2 text-xs">
            <span>Stage 1: <strong>{result.stage_1_time.toFixed(1)}</strong></span>
            <span>Stage 2: <strong>{result.stage_2_time.toFixed(1)}</strong></span>
          </div>
        )}
      </div>

      <div className="rounded-xl border border-gray-100 bg-white p-5 shadow-sm">
        <h3 className="text-sm font-semibold text-gray-800">Calculation trace</h3>
        <div className="mt-3 space-y-2 text-xs">
          <div className="flex justify-between text-gray-600">
            <span>Individual standards + audited sites</span>
            <span>{result.base_time.toFixed(2)}</span>
          </div>
          <div className="flex justify-between text-gray-600">
            <span>MD 5 documented adjustment ({result.md5_adjustment_pct}%)</span>
            <span className={result.md5_adjustment_days < 0 ? 'text-emerald-600' : 'text-amber-600'}>
              {result.md5_adjustment_days >= 0 ? '+' : ''}{result.md5_adjustment_days.toFixed(2)}
            </span>
          </div>
          <div className="flex justify-between text-gray-600">
            <span>After MD 5 adjustment</span>
            <span>{result.after_md5_adjustment.toFixed(2)}</span>
          </div>
          <div className="flex justify-between text-gray-600">
            <span>MD 11 integration ({result.md11_reduction_pct}%)</span>
            <span className="text-emerald-600">−{result.md11_reduction_days.toFixed(2)}</span>
          </div>
          <div className="flex justify-between border-t border-gray-100 pt-2 font-semibold text-gray-800">
            <span>Rounded recommendation</span>
            <span>{result.final_audit_time.toFixed(1)}</span>
          </div>
        </div>
        <p className="mt-3 rounded-lg bg-blue-50 px-3 py-2 text-[11px] leading-4 text-blue-700">
          No automatic reporting deduction is applied. Reductions require a selected factor and documented justification.
        </p>
      </div>

      <div className="rounded-xl border border-gray-100 bg-white p-5 shadow-sm">
        <h3 className="text-sm font-semibold text-gray-800">Scope classification</h3>
        <div className="mt-3 space-y-3">
          {result.classifications.map((item) => (
            <div key={item.standard} className="rounded-lg border border-gray-100 p-3">
              <div className="flex items-center justify-between gap-2">
                <p className="text-xs font-semibold text-gray-800">{item.standard}</p>
                <span className="rounded-full bg-gray-100 px-2 py-1 text-[10px] font-medium text-gray-600">
                  {item.category}
                </span>
              </div>
              <p className="mt-1 text-[11px] text-gray-400">{item.scope_type} · {item.source}</p>
              {item.codes.length > 0 ? (
                <div className="mt-2 space-y-1">
                  {item.codes.map((code, index) => (
                    <p key={`${item.standard}-${code}`} className="text-xs text-gray-600">
                      <strong>{code}</strong>
                      {item.code_names[index] && item.code_names[index] !== code
                        ? ` — ${item.code_names[index]}`
                        : ''}
                    </p>
                  ))}
                </div>
              ) : (
                <p className="mt-2 text-xs text-amber-600">Manual classification review required</p>
              )}
            </div>
          ))}
        </div>
      </div>

      <div className="rounded-xl border border-gray-100 bg-white p-5 shadow-sm">
        <h3 className="text-sm font-semibold text-gray-800">Per-standard audit time</h3>
        <div className="mt-3 overflow-x-auto">
          <table className="w-full text-xs">
            <thead>
              <tr className="border-b border-gray-100 text-left text-gray-400">
                <th className="pb-2 font-medium">Standard</th>
                <th className="pb-2 text-right font-medium">Central</th>
                <th className="pb-2 text-right font-medium">Sites</th>
                <th className="pb-2 text-right font-medium">Total</th>
              </tr>
            </thead>
            <tbody>
              {result.standard_results.map((item) => (
                <tr key={item.standard} className="border-b border-gray-50 text-gray-700">
                  <td className="py-2.5">
                    <span className="block font-medium">{item.standard}</span>
                    <span className="text-[10px] text-gray-400">{item.category} · EPS {item.eps}</span>
                  </td>
                  <td className="py-2.5 text-right">{item.central_time.toFixed(2)}</td>
                  <td className="py-2.5 text-right">{item.additional_site_time.toFixed(2)}</td>
                  <td className="py-2.5 text-right font-semibold">{item.subtotal.toFixed(2)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>

      <div className="rounded-xl border border-gray-100 bg-white p-5 shadow-sm">
        <div className="flex items-center justify-between">
          <h3 className="text-sm font-semibold text-gray-800">Multi-site plan</h3>
          <span className={`rounded-full px-2 py-1 text-[10px] font-medium ${
            result.multi_site_plan.sampling_permitted
              ? 'bg-emerald-50 text-emerald-700'
              : 'bg-gray-100 text-gray-600'
          }`}>
            {result.multi_site_plan.sampling_permitted ? 'Sampling permitted' : 'All sites'}
          </span>
        </div>
        <div className="mt-3 grid grid-cols-3 gap-2 text-center text-xs">
          <div className="rounded-lg bg-gray-50 p-2">
            <p className="text-gray-400">Eligible</p>
            <p className="mt-1 font-semibold text-gray-700">{result.multi_site_plan.eligible_sites}</p>
          </div>
          <div className="rounded-lg bg-gray-50 p-2">
            <p className="text-gray-400">Sample</p>
            <p className="mt-1 font-semibold text-gray-700">{result.multi_site_plan.required_sample_size}</p>
          </div>
          <div className="rounded-lg bg-gray-50 p-2">
            <p className="text-gray-400">Min. random</p>
            <p className="mt-1 font-semibold text-gray-700">{result.multi_site_plan.minimum_random_sites}</p>
          </div>
        </div>
        <p className="mt-2 text-[11px] text-gray-400">{result.multi_site_plan.formula}</p>
      </div>

      {result.warnings.length > 0 && (
        <div className="rounded-xl border border-amber-200 bg-amber-50 p-4">
          <div className="flex items-center gap-2 text-amber-800">
            <AlertTriangle size={16} />
            <h3 className="text-xs font-semibold">Planner review required</h3>
          </div>
          <ul className="mt-2 space-y-1.5 pl-5 text-[11px] leading-4 text-amber-800">
            {result.warnings.map((warning) => <li key={warning} className="list-disc">{warning}</li>)}
          </ul>
        </div>
      )}

      <div className="rounded-xl border border-emerald-100 bg-emerald-50/60 p-4">
        <div className="flex items-center gap-2 text-emerald-800">
          <CheckCircle2 size={16} />
          <h3 className="text-xs font-semibold">Compliance record</h3>
        </div>
        <ul className="mt-2 space-y-1.5 text-[11px] leading-4 text-emerald-800">
          {result.compliance_notes.map((note) => <li key={note}>• {note}</li>)}
        </ul>
      </div>
    </div>
  )
}

export default function CalculatorPage() {
  const [form, setForm] = useState<AdvancedCalculatorRequest>(initialForm)
  const [manualEaText, setManualEaText] = useState('')
  const [result, setResult] = useState<AdvancedCalculationResult | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [loading, setLoading] = useState(false)

  const multiStandard = form.standards.length > 1
  const hasEaStandard = form.standards.some((code) => ['QMS', 'EMS', 'OHSMS'].includes(code))
  const hasFsms = form.standards.includes('FSMS')
  const hasEnms = form.standards.includes('ENMS')
  const estimatedFte = useMemo(() => {
    const partTime = form.part_time_personnel * form.part_time_hours_per_day / form.normal_hours_per_day
    return form.full_time_personnel
      + partTime
      + form.seasonal_temporary_personnel
      + (form.subcontractors_in_scope ? form.subcontractors : 0)
  }, [
    form.full_time_personnel,
    form.normal_hours_per_day,
    form.part_time_hours_per_day,
    form.part_time_personnel,
    form.seasonal_temporary_personnel,
    form.subcontractors,
    form.subcontractors_in_scope,
  ])

  function update<K extends keyof AdvancedCalculatorRequest>(
    key: K,
    value: AdvancedCalculatorRequest[K],
  ) {
    setForm((current) => ({ ...current, [key]: value }))
  }

  function toggleStandard(code: CalculatorStandard) {
    setForm((current) => {
      const exists = current.standards.includes(code)
      const standards = exists
        ? current.standards.filter((item) => item !== code)
        : [...current.standards, code]
      return {
        ...current,
        standards,
        integration: {
          ...current.integration,
          enabled: standards.length > 1 ? current.integration.enabled : false,
        },
      }
    })
    setResult(null)
  }

  function toggleList(key: 'increase_factors' | 'decrease_factors', value: string) {
    setForm((current) => {
      const values = current[key]
      return {
        ...current,
        [key]: values.includes(value)
          ? values.filter((item) => item !== value)
          : [...values, value],
      }
    })
  }

  function addSite() {
    const site: CalculatorSite = {
      id: `site-${Date.now()}-${form.sites.length + 1}`,
      name: '',
      address: '',
      process_description: '',
      employee_count: 0,
      site_type: 'permanent',
      sampling_eligible: true,
    }
    update('sites', [...form.sites, site])
  }

  function updateSite(id: string, patch: Partial<CalculatorSite>) {
    update('sites', form.sites.map((site) => site.id === id ? { ...site, ...patch } : site))
  }

  async function calculate() {
    setError(null)
    if (form.scope.trim().length < 5) {
      setError('Enter a sufficiently detailed certification scope.')
      return
    }
    if (form.standards.length === 0) {
      setError('Select at least one standard.')
      return
    }
    if (form.md5_adjustment_pct !== 0 && form.adjustment_justification.trim().length < 10) {
      setError('Document the reason for the MD 5 adjustment.')
      return
    }
    if (
      form.sampled_site_reduction_pct !== 0
      && form.sampled_site_reduction_justification.trim().length < 10
    ) {
      setError('Document the reason for reducing time at audited sites.')
      return
    }

    setLoading(true)
    try {
      const payload: AdvancedCalculatorRequest = {
        ...form,
        manual_ea_codes: manualEaText
          .split(/[,;/\n]+/)
          .map((value) => value.trim())
          .filter(Boolean),
      }
      const response = await api.post<AdvancedCalculationResult>(
        '/calculator/standalone/calculate',
        payload,
      )
      setResult(response.data)
    } catch (caught: unknown) {
      if (axios.isAxiosError(caught)) {
        const detail = caught.response?.data?.detail
        setError(typeof detail === 'string' ? detail : 'The calculation could not be completed.')
      } else {
        setError('The calculation could not be completed.')
      }
    } finally {
      setLoading(false)
    }
  }

  return (
    <div className="mx-auto max-w-[1450px] py-4">
      <div className="mb-6 flex flex-wrap items-end justify-between gap-4">
        <div>
          <div className="flex items-center gap-2 text-certiva-primary">
            <Calculator size={22} />
            <h1 className="text-xl font-semibold text-gray-900">Advanced audit-time calculator</h1>
          </div>
          <p className="mt-2 max-w-3xl text-sm leading-6 text-gray-500">
            Independent planning tool for scope classification, effective personnel, multi-site sampling,
            integrated audits and documented audit-time adjustments. It does not create or modify a client application.
          </p>
        </div>
        <div className="flex gap-2">
          {['IAF MD 5', 'IAF MD 1', 'IAF MD 11'].map((document) => (
            <span key={document} className="rounded-full border border-blue-100 bg-blue-50 px-3 py-1 text-[11px] font-medium text-blue-700">
              {document}
            </span>
          ))}
        </div>
      </div>

      <div className="grid items-start gap-6 xl:grid-cols-[minmax(0,1.45fr)_minmax(410px,0.75fr)]">
        <div className="space-y-5">
          <Section
            icon={<FileText size={18} />}
            title="Certification scope and audit basis"
            description="The scope is used to suggest EA, technical-area and scheme categories. All suggestions remain reviewable."
          >
            <div className="grid gap-4 md:grid-cols-2">
              <div>
                <label className={labelClass}>Organization name</label>
                <input
                  value={form.organization_name}
                  onChange={(event) => update('organization_name', event.target.value)}
                  placeholder="Optional reference"
                  className={inputClass}
                />
              </div>
              <div className="grid grid-cols-2 gap-3">
                <div>
                  <label className={labelClass}>Audit type</label>
                  <select
                    value={form.audit_type}
                    onChange={(event) => update('audit_type', event.target.value as AuditType)}
                    className={inputClass}
                  >
                    <option value="initial">Initial certification</option>
                    <option value="surveillance">Surveillance</option>
                    <option value="recertification">Recertification</option>
                  </select>
                </div>
                <div>
                  <label className={labelClass}>Accreditation</label>
                  <select
                    value={form.accreditation_body}
                    onChange={(event) => update('accreditation_body', event.target.value as 'UAF' | 'TURKAK')}
                    className={inputClass}
                  >
                    <option value="UAF">UAF</option>
                    <option value="TURKAK">TÜRKAK</option>
                  </select>
                </div>
              </div>
            </div>
            <div className="mt-4">
              <label className={labelClass}>Certification scope</label>
              <textarea
                value={form.scope}
                onChange={(event) => update('scope', event.target.value)}
                rows={4}
                placeholder="Describe products/services, design responsibility, processes, technologies, outsourced activities and regulated operations."
                className={inputClass}
              />
            </div>
            <div className="mt-4">
              <label className={labelClass}>Standards in the calculation</label>
              <div className="grid gap-2 sm:grid-cols-2 lg:grid-cols-4">
                {CALCULATOR_STANDARDS.map((standard) => {
                  const selected = form.standards.includes(standard.code)
                  return (
                    <button
                      key={standard.code}
                      type="button"
                      onClick={() => toggleStandard(standard.code)}
                      className={`rounded-lg border px-3 py-2.5 text-left transition ${
                        selected
                          ? 'border-certiva-primary bg-certiva-primary/5'
                          : 'border-gray-200 hover:border-gray-300'
                      }`}
                    >
                      <span className={`block text-xs font-semibold ${selected ? 'text-certiva-primary' : 'text-gray-700'}`}>
                        {standard.label}
                      </span>
                      <span className="mt-0.5 block text-[10px] text-gray-400">{standard.detail}</span>
                    </button>
                  )
                })}
              </div>
            </div>
          </Section>

          <Section
            icon={<Users size={18} />}
            title="Effective personnel and shifts"
            description="Main/central-site personnel. Add other permanent or temporary locations in the Sites section."
          >
            <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
              <NumberField label="Full-time personnel" value={form.full_time_personnel} onChange={(value) => update('full_time_personnel', value ?? 0)} />
              <NumberField label="Part-time personnel" value={form.part_time_personnel} onChange={(value) => update('part_time_personnel', value ?? 0)} />
              <NumberField label="Part-time hours/day" value={form.part_time_hours_per_day} onChange={(value) => update('part_time_hours_per_day', value ?? 0)} step={0.5} max={24} />
              <NumberField label="Normal hours/day" value={form.normal_hours_per_day} onChange={(value) => update('normal_hours_per_day', value ?? 8)} step={0.5} min={1} max={24} />
              <NumberField label="Office personnel" value={form.office_personnel} onChange={(value) => update('office_personnel', value ?? 0)} hint="Subset of personnel, not added again." />
              <NumberField label="Repetitive personnel" value={form.repetitive_personnel} onChange={(value) => update('repetitive_personnel', value ?? 0)} hint="Subset performing similar/repetitive work." />
              <NumberField label="Seasonal / temporary" value={form.seasonal_temporary_personnel} onChange={(value) => update('seasonal_temporary_personnel', value ?? 0)} />
              <NumberField label="Subcontractors" value={form.subcontractors} onChange={(value) => update('subcontractors', value ?? 0)} />
              <NumberField label="Number of shifts" value={form.shift_count} onChange={(value) => update('shift_count', value ?? 1)} min={1} />
            </div>
            <div className="mt-4 grid gap-2 sm:grid-cols-2">
              <CheckRow
                checked={form.subcontractors_in_scope}
                onChange={(checked) => update('subcontractors_in_scope', checked)}
                label="Subcontractors are included in the certification scope"
              />
              <CheckRow
                checked={form.same_process_all_shifts}
                onChange={(checked) => update('same_process_all_shifts', checked)}
                label="All shifts perform substantially the same processes"
                detail="Shift coverage still requires documented audit planning."
              />
            </div>
            <div className="mt-3 rounded-lg bg-gray-50 px-3 py-2 text-xs text-gray-600">
              Estimated central-site effective personnel: <strong>{estimatedFte.toFixed(2)}</strong>
            </div>
          </Section>

          <Section
            icon={<MapPin size={18} />}
            title="Permanent and temporary sites"
            description="Each additional audited site is calculated from its own personnel count. The main/central site is represented above."
          >
            <div className="space-y-3">
              {form.sites.map((site, index) => (
                <div key={site.id} className="rounded-lg border border-gray-100 p-4">
                  <div className="mb-3 flex items-center justify-between">
                    <p className="text-xs font-semibold text-gray-700">Additional site {index + 1}</p>
                    <button
                      type="button"
                      onClick={() => update('sites', form.sites.filter((item) => item.id !== site.id))}
                      className="rounded p-1 text-gray-400 hover:bg-red-50 hover:text-red-500"
                      aria-label={`Remove site ${index + 1}`}
                    >
                      <Trash2 size={15} />
                    </button>
                  </div>
                  <div className="grid gap-3 md:grid-cols-2">
                    <div>
                      <label className={labelClass}>Site name</label>
                      <input value={site.name} onChange={(event) => updateSite(site.id, { name: event.target.value })} className={inputClass} />
                    </div>
                    <div>
                      <label className={labelClass}>Address / country</label>
                      <input value={site.address} onChange={(event) => updateSite(site.id, { address: event.target.value })} className={inputClass} />
                    </div>
                    <div>
                      <label className={labelClass}>Processes / activities</label>
                      <input value={site.process_description} onChange={(event) => updateSite(site.id, { process_description: event.target.value })} className={inputClass} />
                    </div>
                    <div className="grid grid-cols-2 gap-3">
                      <NumberField label="Personnel" value={site.employee_count} onChange={(value) => updateSite(site.id, { employee_count: value ?? 0 })} />
                      <div>
                        <label className={labelClass}>Site type</label>
                        <select value={site.site_type} onChange={(event) => updateSite(site.id, { site_type: event.target.value as CalculatorSite['site_type'] })} className={inputClass}>
                          <option value="permanent">Permanent</option>
                          <option value="temporary">Temporary</option>
                        </select>
                      </div>
                    </div>
                  </div>
                  <div className="mt-3">
                    <CheckRow
                      checked={site.sampling_eligible}
                      onChange={(checked) => updateSite(site.id, { sampling_eligible: checked })}
                      label="Eligible for the same MD 1 sampling group"
                      detail="Use only when this permanent site performs very similar processes and activities."
                    />
                  </div>
                </div>
              ))}
              <button
                type="button"
                onClick={addSite}
                className="flex w-full items-center justify-center gap-2 rounded-lg border border-dashed border-gray-300 px-3 py-3 text-xs font-medium text-gray-600 hover:border-certiva-primary hover:text-certiva-primary"
              >
                <Plus size={15} /> Add site
              </button>
            </div>
          </Section>

          {form.sites.length > 0 && (
            <Section
              icon={<Building2 size={18} />}
              title="IAF MD 1 multi-site methodology"
              description="Sampling is enabled only when all eligibility conditions are confirmed."
            >
              <CheckRow
                checked={form.multi_site_sampling_requested}
                onChange={(checked) => update('multi_site_sampling_requested', checked)}
                label="Evaluate this organization for multi-site sampling"
              />
              {form.multi_site_sampling_requested && (
                <div className="mt-3 space-y-2">
                  {MULTISITE_CRITERIA.map((criterion) => (
                    <CheckRow
                      key={criterion.key}
                      checked={form.multi_site_eligibility[criterion.key]}
                      onChange={(checked) => update('multi_site_eligibility', {
                        ...form.multi_site_eligibility,
                        [criterion.key]: checked,
                      })}
                      label={criterion.label}
                    />
                  ))}
                  {form.audit_type === 'recertification' && (
                    <CheckRow
                      checked={form.mature_management_system}
                      onChange={(checked) => update('mature_management_system', checked)}
                      label="Management system proved effective throughout the cycle"
                      detail="Allows the 0.8 × √x recertification sampling coefficient."
                    />
                  )}
                </div>
              )}
              <div className="mt-4 grid gap-3 md:grid-cols-[180px_1fr]">
                <NumberField
                  label="Per-audited-site reduction %"
                  value={form.sampled_site_reduction_pct}
                  onChange={(value) => update('sampled_site_reduction_pct', value ?? 0)}
                  max={50}
                  step={5}
                  hint="MD 1 maximum is 50%; default is zero."
                />
                <div>
                  <label className={labelClass}>Site-time justification</label>
                  <input
                    value={form.sampled_site_reduction_justification}
                    onChange={(event) => update('sampled_site_reduction_justification', event.target.value)}
                    placeholder="Required when a per-site reduction is used"
                    className={inputClass}
                  />
                </div>
              </div>
            </Section>
          )}

          <Section
            icon={<ClipboardCheck size={18} />}
            title="Scope codes and scheme-specific inputs"
            description="Automatic classification is a planning aid. Enter known codes or category overrides when authoritative information is available."
          >
            {hasEaStandard && (
              <div>
                <label className={labelClass}>Known EA codes</label>
                <input
                  value={manualEaText}
                  onChange={(event) => setManualEaText(event.target.value)}
                  placeholder="Optional, e.g. EA 28, EA 34"
                  className={inputClass}
                />
                <div className="mt-3 grid gap-3 sm:grid-cols-3">
                  {form.standards.filter((code) => ['QMS', 'EMS', 'OHSMS'].includes(code)).map((code) => (
                    <div key={code}>
                      <label className={labelClass}>
                        {CALCULATOR_STANDARDS.find((item) => item.code === code)?.label} category
                      </label>
                      <select
                        value={form.category_overrides[code] ?? ''}
                        onChange={(event) => {
                          const value = event.target.value as Category | ''
                          const next = { ...form.category_overrides }
                          if (value) next[code] = value
                          else delete next[code]
                          update('category_overrides', next)
                        }}
                        className={inputClass}
                      >
                        <option value="">Automatic from scope / EA</option>
                        <option value="High">High</option>
                        <option value="Medium">Medium</option>
                        <option value="Low">Low</option>
                        {code === 'EMS' && <option value="Limited">Limited</option>}
                      </select>
                    </div>
                  ))}
                </div>
              </div>
            )}

            {hasFsms && (
              <div className={`${hasEaStandard ? 'mt-5 border-t border-gray-100 pt-5' : ''}`}>
                <p className="mb-3 text-xs font-semibold text-gray-700">ISO 22000 / food-safety inputs</p>
                <div className="grid gap-3 md:grid-cols-3">
                  <div className="md:col-span-2">
                    <label className={labelClass}>Food-chain categories</label>
                    <input
                      value={form.food_chain_categories.join(', ')}
                      onChange={(event) => update('food_chain_categories', event.target.value.split(/[,;/]+/).map((item) => item.trim()).filter(Boolean))}
                      placeholder="Optional, e.g. CI, CIV, G"
                      className={inputClass}
                    />
                  </div>
                  <NumberField
                    label="Off-site storage facilities"
                    value={form.fsms_offsite_storage_count}
                    onChange={(value) => update('fsms_offsite_storage_count', value ?? 0)}
                  />
                </div>
                <div className="mt-3 grid gap-2 sm:grid-cols-2">
                  <CheckRow checked={form.fsms_separate_head_office} onChange={(checked) => update('fsms_separate_head_office', checked)} label="Separate head office" />
                  <CheckRow checked={form.fsms_fssc22000} onChange={(checked) => update('fsms_fssc22000', checked)} label="Include FSSC 22000 scheme add-on" />
                </div>
              </div>
            )}

            {hasEnms && (
              <div className={`${hasEaStandard || hasFsms ? 'mt-5 border-t border-gray-100 pt-5' : ''}`}>
                <p className="mb-3 text-xs font-semibold text-gray-700">ISO 50001 energy complexity</p>
                <div className="grid gap-3 sm:grid-cols-3">
                  <NumberField label="Annual energy (TJ)" value={form.annual_energy_tj} onChange={(value) => update('annual_energy_tj', value)} step={0.1} />
                  <NumberField label="Energy types" value={form.num_energy_types} onChange={(value) => update('num_energy_types', value)} />
                  <NumberField label="Significant energy uses" value={form.num_seus} onChange={(value) => update('num_seus', value)} />
                </div>
              </div>
            )}
          </Section>

          {multiStandard && (
            <Section
              icon={<Layers3 size={18} />}
              title="IAF MD 11 integrated audit"
              description="The reduction is determined from the integration evidence and the audit team's cross-standard capability."
            >
              <CheckRow
                checked={form.integration.enabled}
                onChange={(checked) => update('integration', { ...form.integration, enabled: checked })}
                label="Plan this as an integrated management-system audit"
              />
              {form.integration.enabled && (
                <>
                  <div className="mt-3 grid gap-2 md:grid-cols-2">
                    {INTEGRATION_CRITERIA.map((criterion) => (
                      <CheckRow
                        key={criterion.key}
                        checked={Boolean(form.integration[criterion.key])}
                        onChange={(checked) => update('integration', {
                          ...form.integration,
                          [criterion.key]: checked,
                        })}
                        label={criterion.label}
                      />
                    ))}
                  </div>
                  <div className="mt-4">
                    <label className={labelClass}>
                      Combined-audit capability of the proposed team: {form.integration.combined_audit_capability_pct}%
                    </label>
                    <input
                      type="range"
                      min={20}
                      max={100}
                      step={20}
                      value={form.integration.combined_audit_capability_pct}
                      onChange={(event) => update('integration', {
                        ...form.integration,
                        combined_audit_capability_pct: Number(event.target.value),
                      })}
                      className="w-full accent-certiva-primary"
                    />
                    <div className="flex justify-between text-[10px] text-gray-400">
                      <span>20%</span><span>40%</span><span>60%</span><span>80%</span><span>100%</span>
                    </div>
                  </div>
                </>
              )}
            </Section>
          )}

          <Section
            icon={<SlidersHorizontal size={18} />}
            title="Documented adjustments and remote activities"
            description="Reductions are not automatic. Select the applicable considerations and record the final adjustment."
          >
            <div className="grid gap-4 lg:grid-cols-2">
              <div>
                <p className="mb-2 text-xs font-semibold text-gray-700">Factors that may increase time</p>
                <div className="space-y-1.5">
                  {MD5_INCREASE_FACTORS.map((factor) => (
                    <CheckRow key={factor} checked={form.increase_factors.includes(factor)} onChange={() => toggleList('increase_factors', factor)} label={factor} />
                  ))}
                </div>
              </div>
              <div>
                <p className="mb-2 text-xs font-semibold text-gray-700">Factors that may decrease time</p>
                <div className="space-y-1.5">
                  {MD5_DECREASE_FACTORS.map((factor) => (
                    <CheckRow key={factor} checked={form.decrease_factors.includes(factor)} onChange={() => toggleList('decrease_factors', factor)} label={factor} />
                  ))}
                </div>
              </div>
            </div>
            <div className="mt-4 grid gap-3 md:grid-cols-[180px_1fr_180px]">
              <NumberField
                label="Net MD 5 adjustment %"
                value={form.md5_adjustment_pct}
                onChange={(value) => update('md5_adjustment_pct', value ?? 0)}
                min={-30}
                max={100}
                step={5}
                hint="Negative reductions are capped at −30%."
              />
              <div>
                <label className={labelClass}>Documented rationale</label>
                <input
                  value={form.adjustment_justification}
                  onChange={(event) => update('adjustment_justification', event.target.value)}
                  placeholder="Required for any non-zero adjustment"
                  className={inputClass}
                />
              </div>
              <NumberField
                label="Remote activity share %"
                value={form.remote_audit_pct}
                onChange={(value) => update('remote_audit_pct', value ?? 0)}
                max={20}
                step={5}
                hint="Shown separately; it does not reduce total time."
              />
            </div>
          </Section>

          {error && (
            <div className="flex items-start gap-2 rounded-lg border border-red-200 bg-red-50 p-3 text-sm text-red-700">
              <AlertTriangle size={17} className="mt-0.5 shrink-0" />
              <span>{error}</span>
            </div>
          )}

          <button
            type="button"
            onClick={calculate}
            disabled={loading}
            className="flex w-full items-center justify-center gap-2 rounded-xl bg-certiva-primary px-5 py-3.5 text-sm font-semibold text-white shadow-sm transition hover:opacity-95 disabled:cursor-not-allowed disabled:opacity-60"
          >
            {loading ? <Loader2 size={18} className="animate-spin" /> : <Calculator size={18} />}
            {loading ? 'Calculating…' : 'Calculate documented audit time'}
          </button>
        </div>

        <aside className="xl:sticky xl:top-4">
          {result ? (
            <ResultsPanel result={result} />
          ) : (
            <div className="rounded-xl border border-dashed border-gray-200 bg-white p-8 text-center">
              <div className="mx-auto flex h-14 w-14 items-center justify-center rounded-full bg-gray-50">
                <Calculator size={28} className="text-gray-300" />
              </div>
              <h2 className="mt-4 text-sm font-semibold text-gray-700">Calculation record</h2>
              <p className="mx-auto mt-2 max-w-xs text-xs leading-5 text-gray-400">
                Complete the scope, personnel and applicable MD sections. Results will show classification,
                per-standard time, site sampling, adjustments and review warnings.
              </p>
              <div className="mt-5 space-y-2 text-left text-xs text-gray-500">
                {[
                  'Scope-driven EA and category suggestions',
                  'Per-site audit-time calculation',
                  'MD 1 sampling eligibility and sample size',
                  'MD 11 evidence-based integration reduction',
                  'Transparent adjustment and remote-time record',
                ].map((item) => (
                  <div key={item} className="flex items-center gap-2">
                    <CheckCircle2 size={14} className="shrink-0 text-gray-300" />
                    <span>{item}</span>
                  </div>
                ))}
              </div>
            </div>
          )}
        </aside>
      </div>
    </div>
  )
}
