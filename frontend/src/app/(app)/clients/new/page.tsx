'use client'

import { useState } from 'react'
import { useRouter } from 'next/navigation'
import { Check, Loader2, Plus } from 'lucide-react'
import { useMutation } from '@tanstack/react-query'
import api from '@/lib/api'
import type { AuditSetResponse } from '@/types'

// ── Local types ───────────────────────────────────────────────────────────────

interface Step1Data {
  company_name: string; client_reference: string; company_address: string; country: string; city: string
  phone: string; email: string; website: string; representative: string; standards: string[]
  audit_type: string; is_transfer: boolean; scope_tr: string; scope_en: string; non_applicable_clauses: string; accreditation_body: string
  audit_language: string; document_language: string
}

interface SiteRow { _key: string; address: string; employee_count: number }

interface Step2Data {
  full_time: number; part_time: number; subcontractors: number; seasonal: number
  shift_1_count: number; shift_2_count: number; shift_3_count: number
  shift_same_process: boolean
  multiSite: boolean; sites: SiteRow[]
  pairIntegration: Record<string, 'Full' | 'Partial' | 'None'>
  // EnMS (ISO 50001)
  enms_annual_energy_tj: string
  enms_num_energy_types: string
  enms_num_seus: string
  // FSMS (ISO 22000 / FSSC 22000)
  fsms_food_chain_categories: string[]
  fsms_haccp_studies: string
  fsms_offsite_storage_count: string
  fsms_separate_head_office: boolean
  fsms_fssc22000: boolean
  fsms_seasonal_production: boolean
  // ISMS (ISO 27001)
  isms_technical_area: string
  isms_data_role: string
  // MDQMS (ISO 13485)
  mdqms_device_classes: string[]
  mdqms_regulatory_territories: string[]
}

// ── Constants ─────────────────────────────────────────────────────────────────

const STANDARDS_GRID = [
  { code: 'QMS',   iso: 'ISO 9001'  }, { code: 'EMS',   iso: 'ISO 14001' },
  { code: 'OHSMS', iso: 'ISO 45001' }, { code: 'FSMS',  iso: 'ISO 22000' },
  { code: 'ISMS',  iso: 'ISO 27001' }, { code: 'MDQMS', iso: 'ISO 13485' },
  { code: 'ABMS',  iso: 'ISO 37001' }, { code: 'ENMS',  iso: 'ISO 50001' },
]

// Country → default spoken audit language (must mirror backend COUNTRY_LANGUAGE).
const COUNTRY_LANGUAGE: Record<string, string> = {
  Turkey: 'Turkish', 'Türkiye': 'Turkish',
  Russia: 'Russian', Bangladesh: 'Bengali',
  'United States': 'English', 'United Kingdom': 'English',
  Germany: 'German', France: 'French',
}

function suggestLanguage(country: string): string {
  return COUNTRY_LANGUAGE[country] ?? 'English'
}

function getPairs(stds: string[]): string[] {
  const pairs: string[] = []
  for (let i = 0; i < stds.length; i++)
    for (let j = i + 1; j < stds.length; j++)
      pairs.push(`${stds[i]}+${stds[j]}`)
  return pairs
}

function deriveIntegrationLevel(pi: Record<string, 'Full' | 'Partial' | 'None'>) {
  const vals = Object.values(pi)
  const any = vals.some((v) => v !== 'None')
  const all = vals.length > 0 && vals.every((v) => v === 'Full')
  return {
    document_management: any, management_review: any,
    internal_audit: any,      policy_objectives: any,
    process_approach: all,    improvement_mechanism: all,
    management_support: all,  risk_based_thinking: all,
  }
}

// ── Shared styles ─────────────────────────────────────────────────────────────

const inputCls   = 'w-full rounded-lg border border-gray-200 px-3 py-2 text-sm text-gray-800 placeholder-gray-400 outline-none focus:border-certiva-primary focus:ring-2 focus:ring-certiva-primary/20'
const lblCls     = 'mb-1 block text-xs font-medium text-gray-500'
const errCls     = 'mt-1 text-xs text-red-500'
const sectionHd  = 'mb-3 text-sm font-medium text-gray-700'

// ── Default state ─────────────────────────────────────────────────────────────

const DEFAULT_S1: Step1Data = {
  company_name: '', client_reference: '', company_address: '', country: 'Turkey', city: '',
  phone: '', email: '', website: '', representative: '', standards: [],
  audit_type: '', is_transfer: false, scope_tr: '', scope_en: '', non_applicable_clauses: '', accreditation_body: 'UAF',
  audit_language: 'Turkish', document_language: 'turkish',
}

const DEFAULT_S2: Step2Data = {
  full_time: 0, part_time: 0, subcontractors: 0, seasonal: 0,
  shift_1_count: 0, shift_2_count: 0, shift_3_count: 0,
  shift_same_process: false,
  multiSite: false, sites: [{ _key: '1', address: '', employee_count: 0 }],
  pairIntegration: {},
  enms_annual_energy_tj: '', enms_num_energy_types: '', enms_num_seus: '',
  fsms_food_chain_categories: [], fsms_haccp_studies: '',
  fsms_offsite_storage_count: '', fsms_separate_head_office: false,
  fsms_fssc22000: false, fsms_seasonal_production: false,
  isms_technical_area: '', isms_data_role: '',
  mdqms_device_classes: [], mdqms_regulatory_territories: [],
}

// ── Step 1 — Company info ─────────────────────────────────────────────────────

function Step1({
  data, onChange, errors,
}: {
  data: Step1Data
  onChange: (patch: Partial<Step1Data>) => void
  errors: Partial<Record<keyof Step1Data, string>>
}) {
  function toggleStd(code: string) {
    const next = data.standards.includes(code)
      ? data.standards.filter((s) => s !== code)
      : [...data.standards, code]
    onChange({ standards: next })
  }

  return (
    <div className="space-y-5">
      <div>
        <label className={lblCls}>Company name <span className="text-red-400">*</span></label>
        <input className={inputCls} value={data.company_name} onChange={(e) => onChange({ company_name: e.target.value })} placeholder="Acme Ltd." />
        {errors.company_name && <p className={errCls}>{errors.company_name}</p>}
      </div>

      <div>
        <label className={lblCls}>Client Reference / Agreement No <span className="text-gray-300 font-normal">(optional)</span></label>
        <input className={inputCls} value={data.client_reference} onChange={(e) => onChange({ client_reference: e.target.value })} placeholder="e.g. 202601" />
        <p className="mt-1 text-xs text-gray-400">Used as the Agreement No and Quotation No in all documents. Leave blank to use the auto-assigned plan number.</p>
      </div>

      <div>
        <label className={lblCls}>Company address <span className="text-red-400">*</span></label>
        <input className={inputCls} value={data.company_address} onChange={(e) => onChange({ company_address: e.target.value })} placeholder="Full address" />
        {errors.company_address && <p className={errCls}>{errors.company_address}</p>}
      </div>

      <div className="grid grid-cols-2 gap-4">
        <div>
          <label className={lblCls}>Country</label>
          <input className={inputCls} value={data.country} onChange={(e) => onChange({ country: e.target.value, audit_language: suggestLanguage(e.target.value) })} />
        </div>
        <div>
          <label className={lblCls}>City</label>
          <input className={inputCls} value={data.city} onChange={(e) => onChange({ city: e.target.value })} placeholder="Istanbul" />
        </div>
      </div>

      <div className="grid grid-cols-2 gap-4">
        <div>
          <label className={lblCls}>Phone</label>
          <input className={inputCls} type="tel" value={data.phone} onChange={(e) => onChange({ phone: e.target.value })} placeholder="+90 ..." />
        </div>
        <div>
          <label className={lblCls}>Email</label>
          <input className={inputCls} type="email" value={data.email} onChange={(e) => onChange({ email: e.target.value })} placeholder="info@company.com" />
        </div>
      </div>

      <div>
        <label className={lblCls}>Website <span className="text-gray-300 font-normal">(optional)</span></label>
        <input className={inputCls} value={data.website} onChange={(e) => onChange({ website: e.target.value })} placeholder="https://..." />
      </div>

      <div>
        <label className={lblCls}>Organization Representative <span className="text-gray-300 font-normal">(contact person)</span></label>
        <input className={inputCls} value={data.representative} onChange={(e) => onChange({ representative: e.target.value })} placeholder="Full name" />
      </div>

      <div>
        <label className={lblCls}>Standards <span className="text-red-400">*</span></label>
        <div className="grid grid-cols-3 gap-2">
          {STANDARDS_GRID.map(({ code, iso }) => (
            <label key={code} className="flex cursor-pointer items-center gap-2 rounded-lg border border-gray-200 p-2.5 hover:bg-gray-50">
              <input type="checkbox" className="accent-certiva-primary" checked={data.standards.includes(code)} onChange={() => toggleStd(code)} />
              <span className="text-sm font-medium">{code}</span>
              <span className="text-xs text-gray-400">{iso}</span>
            </label>
          ))}
        </div>
        {errors.standards && <p className={errCls}>{errors.standards}</p>}
      </div>

      {data.standards.length > 1 && (
        <div className="border-l-4 border-certiva-primary bg-certiva-surface px-4 py-3 text-certiva-primary" style={{ fontSize: 13 }}>
          Integrated audit detected. Integration reduction will be applied automatically.
        </div>
      )}

      <div>
        <label className={lblCls}>Audit type <span className="text-red-400">*</span></label>
        <div className="flex gap-5">
          {[
            { value: 'initial',         label: 'Initial certification' },
            { value: 'surveillance_1',  label: 'Surveillance 1'        },
            { value: 'surveillance_2',  label: 'Surveillance 2'        },
            { value: 'recertification', label: 'Recertification'       },
            { value: 'special',         label: 'Special Audit'         },
          ].map(({ value, label }) => (
            <label key={value} className="flex cursor-pointer items-center gap-2 text-sm">
              <input type="radio" className="accent-certiva-primary" name="audit_type" value={value} checked={data.audit_type === value} onChange={() => onChange({ audit_type: value })} />
              {label}
            </label>
          ))}
        </div>
        {errors.audit_type && <p className={errCls}>{errors.audit_type}</p>}
      </div>

      <label className="flex cursor-pointer items-start gap-3 rounded-lg border border-amber-200 bg-amber-50 p-3 text-sm text-amber-950">
        <input
          type="checkbox"
          className="mt-0.5 accent-certiva-primary"
          checked={data.is_transfer}
          onChange={(e) => onChange({ is_transfer: e.target.checked })}
        />
        <span>
          <span className="font-medium">Transfer application</span>
          <span className="block text-xs text-amber-800">
            Adds FR.250 and requires an independent Transfer Reviewer.
          </span>
        </span>
      </label>

      <div>
        <label className={lblCls}>Scope (Turkish) <span className="text-red-400">*</span></label>
        <textarea className={inputCls} rows={3} value={data.scope_tr} onChange={(e) => onChange({ scope_tr: e.target.value })} placeholder="Belgelendirme kapsamı..." />
        {errors.scope_tr && <p className={errCls}>{errors.scope_tr}</p>}
      </div>

      <div>
        <label className={lblCls}>Scope (English) <span className="text-red-400">*</span></label>
        <textarea className={inputCls} rows={3} value={data.scope_en} onChange={(e) => onChange({ scope_en: e.target.value })} placeholder="Certification scope..." />
        {errors.scope_en && <p className={errCls}>{errors.scope_en}</p>}
      </div>

      <div>
        <label className={lblCls}>Not Applicable Clauses <span className="text-gray-300 font-normal">(e.g. 7.1.5, 8.3)</span></label>
        <input className={inputCls} value={data.non_applicable_clauses} onChange={(e) => onChange({ non_applicable_clauses: e.target.value })} placeholder="e.g. 7.1.5, 8.3" />
      </div>

      <div>
        <label className={lblCls}>Accreditation body <span className="text-red-400">*</span></label>
        <select className={inputCls} value={data.accreditation_body} onChange={(e) => onChange({ accreditation_body: e.target.value })}>
          <option value="UAF">UAF</option>
          <option value="TURKAK">TURKAK</option>
        </select>
        {errors.accreditation_body && <p className={errCls}>{errors.accreditation_body}</p>}
      </div>

      <div>
        <label className={lblCls}>Audit language</label>
        <input
          className={inputCls}
          value={data.audit_language}
          onChange={(e) => onChange({ audit_language: e.target.value })}
          placeholder="e.g. Turkish"
        />
        <p className="mt-1 text-xs text-gray-400">Suggested from country — editable.</p>
      </div>

      {(data.accreditation_body === 'TURKAK' || data.accreditation_body === 'TÜRKAK') && (
        <div>
          <label className={lblCls}>Document language</label>
          <div className="flex gap-5">
            {[
              { value: 'turkish', label: 'Turkish' },
              { value: 'english', label: 'English' },
            ].map(({ value, label }) => (
              <label key={value} className="flex cursor-pointer items-center gap-2 text-sm">
                <input type="radio" className="accent-certiva-primary" name="document_language" value={value} checked={data.document_language === value} onChange={() => onChange({ document_language: value })} />
                {label}
              </label>
            ))}
          </div>
        </div>
      )}
    </div>
  )
}

// ── Step indicator ────────────────────────────────────────────────────────────

const STEP_LABELS = ['Company info', 'Personnel & sites', 'Review & create']

function StepIndicator({ current }: { current: number }) {
  return (
    <div className="mb-8 flex items-start">
      {STEP_LABELS.map((label, idx) => {
        const done   = idx < current
        const active = idx === current
        return (
          <div key={idx} className="flex flex-1 flex-col items-center">
            <div className="flex w-full items-center">
              <div className={`h-px flex-1 ${idx === 0 ? 'invisible' : done || active ? 'bg-certiva-primary' : 'bg-gray-200'}`} />
              <div
                className="flex h-8 w-8 shrink-0 items-center justify-center rounded-full text-sm font-semibold"
                style={{ background: done || active ? '#1A4731' : '#E5E7EB', color: done || active ? '#fff' : '#9CA3AF' }}
              >
                {done ? <Check size={14} strokeWidth={3} /> : idx + 1}
              </div>
              <div className={`h-px flex-1 ${idx === STEP_LABELS.length - 1 ? 'invisible' : done ? 'bg-certiva-primary' : 'bg-gray-200'}`} />
            </div>
            <p className="mt-2 text-center" style={{ fontSize: 12, color: done || active ? '#1A4731' : '#9CA3AF', fontWeight: active ? 500 : 400 }}>
              {label}
            </p>
          </div>
        )
      })}
    </div>
  )
}


// ── Step 2 — Personnel & sites ────────────────────────────────────────────────

function Step2({
  data, onChange, standards, errors,
}: {
  data: Step2Data
  onChange: (patch: Partial<Step2Data>) => void
  standards: string[]
  errors: Partial<Record<string, string>>
}) {
  function numInput(field: keyof Step2Data, label: string) {
    return (
      <div>
        <label className={lblCls}>{label}</label>
        <input
          type="number" min={0} className={inputCls}
          value={data[field] as number}
          onChange={(e) => onChange({ [field]: Math.max(0, parseInt(e.target.value) || 0) } as Partial<Step2Data>)}
        />
      </div>
    )
  }

  function addSite() {
    onChange({ sites: [...data.sites, { _key: Date.now().toString(), address: '', employee_count: 0 }] })
  }
  function removeSite(key: string) {
    onChange({ sites: data.sites.filter((s) => s._key !== key) })
  }
  function patchSite(key: string, patch: Partial<SiteRow>) {
    onChange({ sites: data.sites.map((s) => s._key === key ? { ...s, ...patch } : s) })
  }

  const pairs = getPairs(standards)

  return (
    <div className="space-y-6">
      {/* Personnel */}
      <div>
        <p className={sectionHd}>Personnel data</p>
        <div className="grid grid-cols-4 gap-3">
          {numInput('full_time', 'Full-time')}
          {numInput('part_time', 'Part-time')}
          {numInput('subcontractors', 'Contractor')}
          {numInput('seasonal', 'Seasonal')}
        </div>
        {errors.personnel && <p className={errCls}>{errors.personnel}</p>}
        <div className="mt-3 grid grid-cols-3 gap-3">
          {numInput('shift_1_count', 'Shift 1 headcount')}
          {numInput('shift_2_count', 'Shift 2 headcount')}
          {numInput('shift_3_count', 'Shift 3 headcount')}
        </div>
        {(data.shift_1_count > 0 && data.shift_2_count > 0) && (
          <label className="flex items-center gap-2 cursor-pointer col-span-full mt-2">
            <input type="checkbox" checked={data.shift_same_process}
              onChange={e => onChange({ shift_same_process: e.target.checked })}
              className="w-4 h-4 accent-certiva-primary" />
            <span className="text-sm text-gray-700">
              All shifts perform the same process (IAF MD5 repetitive reduction may apply)
            </span>
          </label>
        )}
      </div>

      {/* Sites */}
      <div>
        <p className={sectionHd}>Sites</p>
        <div className="mb-3 flex gap-2">
          {['Single site', 'Multiple sites'].map((opt, i) => (
            <button
              key={opt} type="button"
              onClick={() => onChange({ multiSite: i === 1 })}
              className="rounded-md border px-3 py-1 text-sm transition-colors"
              style={{
                background:  data.multiSite === (i === 1) ? '#1A4731' : 'white',
                color:       data.multiSite === (i === 1) ? 'white'   : '#374151',
                borderColor: data.multiSite === (i === 1) ? '#1A4731' : '#E5E7EB',
              }}
            >
              {opt}
            </button>
          ))}
        </div>

        {data.multiSite && (
          <>
            <table className="mb-2 w-full text-sm">
              <thead>
                <tr className="text-left text-xs font-medium uppercase text-gray-400">
                  <th className="pb-2 pr-3">Site address</th>
                  <th className="pb-2 pr-3" style={{ width: 130 }}>Employees</th>
                  <th className="pb-2" style={{ width: 70 }}></th>
                </tr>
              </thead>
              <tbody className="divide-y divide-gray-50">
                {data.sites.map((site) => (
                  <tr key={site._key}>
                    <td className="py-1.5 pr-3">
                      <input className={inputCls} value={site.address} onChange={(e) => patchSite(site._key, { address: e.target.value })} placeholder="Full address" />
                    </td>
                    <td className="py-1.5 pr-3">
                      <input type="number" min={0} className={inputCls} value={site.employee_count} onChange={(e) => patchSite(site._key, { employee_count: parseInt(e.target.value) || 0 })} />
                    </td>
                    <td className="py-1.5 text-right">
                      {data.sites.length > 1 && (
                        <button type="button" onClick={() => removeSite(site._key)} className="text-xs text-red-400 hover:text-red-600">Remove</button>
                      )}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
            <button type="button" onClick={addSite} className="flex items-center gap-1 text-xs text-certiva-primary hover:opacity-70">
              <Plus size={12} /> Add site
            </button>
          </>
        )}
      </div>

      {/* Integration level — only shown if >1 standard */}
      {standards.length > 1 && pairs.length > 0 && (
        <div>
          <p className={sectionHd}>Integration level</p>
          <div className="space-y-2">
            {pairs.map((pair) => {
              const [a, b] = pair.split('+')
              const isoA = STANDARDS_GRID.find((s) => s.code === a)?.iso ?? a
              const isoB = STANDARDS_GRID.find((s) => s.code === b)?.iso ?? b
              return (
                <div key={pair} className="flex items-center justify-between rounded-lg border border-gray-100 px-3 py-2">
                  <span className="text-sm text-gray-700">{isoA} + {isoB}</span>
                  <select
                    className="rounded-md border border-gray-200 px-2 py-1 text-sm outline-none focus:ring-2 focus:ring-certiva-primary/20"
                    value={data.pairIntegration[pair] ?? 'Full'}
                    onChange={(e) => onChange({ pairIntegration: { ...data.pairIntegration, [pair]: e.target.value as 'Full' | 'Partial' | 'None' } })}
                  >
                    <option>Full</option>
                    <option>Partial</option>
                    <option>None</option>
                  </select>
                </div>
              )
            })}
          </div>
        </div>
      )}

      {/* ── EnMS panel — ISO 50001 ───────────────────────────────── */}
      {standards.includes('ENMS') && (
        <div className="rounded-xl border border-blue-100 bg-blue-50/40 p-5 space-y-4">
          <p className="text-sm font-semibold text-blue-900">⚡ ISO 50001 — Energy Profile</p>
          <p className="text-xs text-blue-700">
            Required for the ISO 50003 K-factor calculation. Used to select the correct audit time table.
          </p>
          <div className="grid grid-cols-2 gap-4">
            <div>
              <label className={lblCls}>Annual energy consumption</label>
              <select className={inputCls} value={data.enms_annual_energy_tj}
                onChange={e => onChange({ enms_annual_energy_tj: e.target.value })}>
                <option value="">— Select range —</option>
                <option value="10">≤ 20 TJ</option>
                <option value="100">20–200 TJ</option>
                <option value="1000">200–2,000 TJ</option>
                <option value="5000">&gt; 2,000 TJ</option>
              </select>
            </div>
            <div>
              <label className={lblCls}>Number of energy types</label>
              <select className={inputCls} value={data.enms_num_energy_types}
                onChange={e => onChange({ enms_num_energy_types: e.target.value })}>
                <option value="">— Select —</option>
                <option value="1">1</option>
                <option value="2">2</option>
                <option value="3">3</option>
                <option value="4">4 or more</option>
              </select>
            </div>
            <div>
              <label className={lblCls}>Number of Significant Energy Uses (SEUs)</label>
              <select className={inputCls} value={data.enms_num_seus}
                onChange={e => onChange({ enms_num_seus: e.target.value })}>
                <option value="">— Select —</option>
                <option value="2">1–3 SEUs</option>
                <option value="5">4–6 SEUs</option>
                <option value="8">7–10 SEUs</option>
                <option value="12">11–15 SEUs</option>
                <option value="20">&gt; 15 SEUs</option>
              </select>
            </div>
          </div>
        </div>
      )}

      {/* ── FSMS panel — ISO 22000 ───────────────────────────────── */}
      {standards.includes('FSMS') && (
        <div className="rounded-xl border border-blue-100 bg-blue-50/40 p-5 space-y-4">
          <p className="text-sm font-semibold text-blue-900">🍽️ ISO 22000 — Food Safety Details</p>
          <div>
            <label className={lblCls}>Food chain categories in scope</label>
            <p className="text-xs text-gray-500 mb-2">Select all that apply (ISO 22003-1:2022 Annex B).</p>
            <div className="grid grid-cols-1 gap-1 max-h-52 overflow-y-auto">
              {[
                { code: 'CI',   label: 'CI — Animal farming / perishable animal products' },
                { code: 'CII',  label: 'CII — Perishable plant (fresh produce)' },
                { code: 'CIII', label: 'CIII — Processed perishable / ready-to-eat' },
                { code: 'CIV',  label: 'CIV — Ambient-stable food (bakery, confectionery, beverages)' },
                { code: 'C0',   label: 'C0 — Slaughter / abattoir' },
                { code: 'D',    label: 'D — Animal feed' },
                { code: 'E',    label: 'E — Catering / food service' },
                { code: 'FI',   label: 'FI — Food retail' },
                { code: 'FII',  label: 'FII — Food wholesale / brokerage' },
                { code: 'G',    label: 'G — Food storage / cold-chain logistics' },
                { code: 'I',    label: 'I — Food packaging / food contact materials' },
                { code: 'K',    label: 'K — Food additives / ingredients' },
                { code: 'BIII', label: 'BIII — Plant pre-processing' },
              ].map(cat => (
                <label key={cat.code} className="flex items-center gap-2 cursor-pointer py-0.5">
                  <input type="checkbox"
                    checked={data.fsms_food_chain_categories.includes(cat.code)}
                    onChange={() => onChange({
                      fsms_food_chain_categories: data.fsms_food_chain_categories.includes(cat.code)
                        ? data.fsms_food_chain_categories.filter(c => c !== cat.code)
                        : [...data.fsms_food_chain_categories, cat.code]
                    })}
                    className="w-4 h-4 accent-certiva-primary shrink-0" />
                  <span className="text-xs text-gray-700">{cat.label}</span>
                </label>
              ))}
            </div>
          </div>
          <div className="grid grid-cols-2 gap-4">
            <div>
              <label className={lblCls}>HACCP studies</label>
              <input className={inputCls} type="number" min="0" placeholder="0"
                value={data.fsms_haccp_studies}
                onChange={e => onChange({ fsms_haccp_studies: e.target.value })} />
            </div>
            <div>
              <label className={lblCls}>Off-site storage facilities in scope</label>
              <input className={inputCls} type="number" min="0" placeholder="0"
                value={data.fsms_offsite_storage_count}
                onChange={e => onChange({ fsms_offsite_storage_count: e.target.value })} />
              <p className="text-xs text-gray-400 mt-1">+0.25 audit day each (ISO 22003-1 §B.2.5)</p>
            </div>
          </div>
          <div className="space-y-2">
            {([
              { key: 'fsms_separate_head_office', label: 'Head office separate from production site (+0.5 day)' },
              { key: 'fsms_fssc22000',            label: 'FSSC 22000 scheme (+1.0 day reporting surcharge)' },
              { key: 'fsms_seasonal_production',  label: 'Seasonal production' },
            ] as { key: keyof Step2Data; label: string }[]).map(({ key, label }) => (
              <label key={String(key)} className="flex items-center gap-2 cursor-pointer">
                <input type="checkbox" checked={data[key] as boolean}
                  onChange={e => onChange({ [key]: e.target.checked })}
                  className="w-4 h-4 accent-certiva-primary" />
                <span className="text-sm text-gray-700">{label}</span>
              </label>
            ))}
          </div>
        </div>
      )}

      {/* ── ISMS panel — ISO 27001 ───────────────────────────────── */}
      {standards.includes('ISMS') && (
        <div className="rounded-xl border border-blue-100 bg-blue-50/40 p-5 space-y-4">
          <p className="text-sm font-semibold text-blue-900">🔐 ISO 27001 — ISMS Details</p>
          <div className="grid grid-cols-1 gap-4">
            <div>
              <label className={lblCls}>Technical area (ISO/IEC 27006-1:2024)</label>
              <select className={inputCls} value={data.isms_technical_area}
                onChange={e => onChange({ isms_technical_area: e.target.value })}>
                <option value="">— Select —</option>
                <option value="A">A — Standard IT (office systems, cloud, ERP)</option>
                <option value="B">B — Industrial / OT (ICS, SCADA, manufacturing IT)</option>
                <option value="C">C — Telecom / service provider infrastructure</option>
                <option value="D">D — Specialized (data centres, medical devices, critical infrastructure)</option>
              </select>
            </div>
            <div>
              <label className={lblCls}>Data role</label>
              <select className={inputCls} value={data.isms_data_role}
                onChange={e => onChange({ isms_data_role: e.target.value })}>
                <option value="">— Select —</option>
                <option value="Controller">Data Controller</option>
                <option value="Processor">Data Processor</option>
                <option value="Both">Both Controller and Processor</option>
              </select>
            </div>
          </div>
        </div>
      )}

      {/* ── MDQMS panel — ISO 13485 ──────────────────────────────── */}
      {standards.includes('MDQMS') && (
        <div className="rounded-xl border border-blue-100 bg-blue-50/40 p-5 space-y-4">
          <p className="text-sm font-semibold text-blue-900">🏥 ISO 13485 — Medical Device Details</p>
          <div className="grid grid-cols-1 gap-1">
            {['Class I (low risk)', 'Class IIa', 'Class IIb', 'Class III (high risk)', 'IVD', 'Active implants'].map(cls => (
              <label key={cls} className="flex items-center gap-2 cursor-pointer">
                <input type="checkbox"
                  checked={data.mdqms_device_classes.includes(cls)}
                  onChange={() => onChange({
                    mdqms_device_classes: data.mdqms_device_classes.includes(cls)
                      ? data.mdqms_device_classes.filter(c => c !== cls)
                      : [...data.mdqms_device_classes, cls]
                  })}
                  className="w-4 h-4 accent-certiva-primary" />
                <span className="text-sm text-gray-700">{cls}</span>
              </label>
            ))}
          </div>
        </div>
      )}
    </div>
  )
}


// ── Step 3 — Review & create ──────────────────────────────────────────────────

function Step3({ s1, s2, error }: { s1: Step1Data; s2: Step2Data; error: string }) {
  const rows: [string, string][] = [
    ['Company',      s1.company_name],
    ...(s1.client_reference ? [['Client ref / Agreement No', s1.client_reference] as [string, string]] : []),
    ['Address',      s1.company_address],
    ['Standards',    s1.standards.join(', ')],
    ['Audit type',   s1.audit_type ? s1.audit_type.replace('_', ' ').replace(/\b\w/g, c => c.toUpperCase()) : '—'],
    ['Transfer',     s1.is_transfer ? 'Yes' : 'No'],
    ['Accreditation', s1.accreditation_body],
    ['Personnel',    `${s2.full_time} FT, ${s2.part_time} PT, ${s2.subcontractors} contractor, ${s2.seasonal} seasonal`],
    ['Sites',        `${s2.multiSite ? s2.sites.length : 1} site(s)`],
  ]
  return (
    <div className="space-y-4">
      <div className="divide-y divide-gray-50 rounded-lg border border-gray-100">
        {rows.map(([label, value]) => (
          <div key={label} className="flex items-start px-4 py-2.5 text-sm">
            <span className="w-36 shrink-0 font-medium text-gray-500">{label}</span>
            <span className="text-gray-800">{value || '—'}</span>
          </div>
        ))}
      </div>
      <p className="text-xs italic text-gray-400">
        Man-day calculation will run automatically when the plan is created.
      </p>
      {error && (
        <div className="rounded-lg border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-600">
          {error}
        </div>
      )}
    </div>
  )
}

// ── Main page ─────────────────────────────────────────────────────────────────

export default function NewClientPage() {
  const router = useRouter()
  const [step, setStep] = useState(0)
  const [s1, setS1] = useState<Step1Data>(DEFAULT_S1)
  const [s2, setS2] = useState<Step2Data>(DEFAULT_S2)
  const [s1Errors, setS1Errors] = useState<Partial<Record<keyof Step1Data, string>>>({})
  const [s2Errors, setS2Errors] = useState<Partial<Record<string, string>>>({})
  const [submitError, setSubmitError] = useState('')

  const { mutate, isPending } = useMutation({
    mutationFn: async () => {
      const sites = s2.multiSite
        ? s2.sites.map(({ address, employee_count }) => ({ address, employee_count }))
        : []
      const payload = {
        company_name: s1.company_name, client_reference: s1.client_reference || null,
        company_address: s1.company_address,
        country: s1.country, city: s1.city, phone: s1.phone,
        email: s1.email, website: s1.website, representative: s1.representative,
        standards: s1.standards, audit_type: s1.audit_type, is_transfer: s1.is_transfer,
        scope_tr: s1.scope_tr, scope_en: s1.scope_en,
        non_applicable_clauses: s1.non_applicable_clauses,
        accreditation_body: s1.accreditation_body,
        audit_language: s1.audit_language,
        document_language: s1.document_language,
        personnel: {
          full_time: s2.full_time, part_time: s2.part_time,
          subcontractors: s2.subcontractors, seasonal: s2.seasonal,
          shift_1_count: s2.shift_1_count, shift_2_count: s2.shift_2_count,
          shift_3_count: s2.shift_3_count,
          shift_same_process: s2.shift_same_process,
        },
        sites,
        ...(s1.standards.length > 1 && { integration_level: deriveIntegrationLevel(s2.pairIntegration) }),
        application_data: {
          enms_annual_energy_tj:         s2.enms_annual_energy_tj    ? parseFloat(s2.enms_annual_energy_tj)    : null,
          enms_num_energy_types:         s2.enms_num_energy_types     ? parseInt(s2.enms_num_energy_types)      : null,
          enms_num_seus:                 s2.enms_num_seus             ? parseInt(s2.enms_num_seus)              : null,
          fsms_food_chain_categories:    s2.fsms_food_chain_categories,
          fsms_haccp_studies:            s2.fsms_haccp_studies        ? parseInt(s2.fsms_haccp_studies)         : null,
          fsms_offsite_storage_count:    s2.fsms_offsite_storage_count ? parseInt(s2.fsms_offsite_storage_count) : 0,
          fsms_separate_head_office:     s2.fsms_separate_head_office,
          fsms_fssc22000:                s2.fsms_fssc22000,
          fsms_seasonal_production:      s2.fsms_seasonal_production,
          isms_technical_area:           s2.isms_technical_area  || null,
          isms_data_role:                s2.isms_data_role        || null,
          mdqms_device_classes:          s2.mdqms_device_classes,
          mdqms_regulatory_territories:  s2.mdqms_regulatory_territories,
          part_time_fte_factor:          0.5,
          subcontractors_in_scope:       true,
        },
      }
      const res = await api.post<AuditSetResponse>('/audit-sets/', payload)
      return res.data
    },
    onSuccess: (data) => router.push(`/clients/${data.id}`),
    onError: (err: any) => setSubmitError(err?.response?.data?.detail ?? 'Failed to create plan.'),
  })

  function validateS1(): boolean {
    const errs: Partial<Record<keyof Step1Data, string>> = {}
    if (!s1.company_name.trim())    errs.company_name    = 'Required'
    if (!s1.company_address.trim()) errs.company_address = 'Required'
    if (s1.standards.length === 0)  errs.standards       = 'Select at least one standard'
    if (!s1.audit_type)             errs.audit_type      = 'Required'
    if (!s1.scope_tr.trim())        errs.scope_tr        = 'Required'
    if (!s1.scope_en.trim())        errs.scope_en        = 'Required'
    if (!s1.accreditation_body)     errs.accreditation_body = 'Required'
    setS1Errors(errs)
    return Object.keys(errs).length === 0
  }

  function validateS2(): boolean {
    const errs: Partial<Record<string, string>> = {}
    if (s2.full_time + s2.part_time === 0)
      errs.personnel = 'Enter at least 1 full-time or part-time employee'
    setS2Errors(errs)
    return Object.keys(errs).length === 0
  }

  function next() {
    if (step === 0 && !validateS1()) return
    if (step === 1 && !validateS2()) return
    setStep((s) => s + 1)
  }

  return (
    <div className="mx-auto max-w-[760px] py-4">
      <h1 className="mb-6 text-xl font-semibold text-gray-800">New client</h1>
      <div className="rounded-xl bg-white p-8 shadow-sm">
        <StepIndicator current={step} />

        {step === 0 && (
          <Step1 data={s1} onChange={(p) => setS1((prev) => ({ ...prev, ...p }))} errors={s1Errors} />
        )}
        {step === 1 && (
          <Step2 data={s2} onChange={(p) => setS2((prev) => ({ ...prev, ...p }))} standards={s1.standards} errors={s2Errors} />
        )}
        {step === 2 && <Step3 s1={s1} s2={s2} error={submitError} />}

        {/* Navigation buttons */}
        <div className="mt-8 flex items-center justify-between">
          {step > 0 ? (
            <button type="button" onClick={() => setStep((s) => s - 1)} className="rounded-lg border border-gray-200 px-4 py-2 text-sm text-gray-600 hover:bg-gray-50">
              Back
            </button>
          ) : <div />}

          {step < 2 ? (
            <button type="button" onClick={next} className="rounded-lg px-5 py-2 text-sm font-medium text-white hover:opacity-90" style={{ background: '#1A4731' }}>
              Next
            </button>
          ) : (
            <button
              type="button" disabled={isPending}
              onClick={() => { setSubmitError(''); mutate() }}
              className="flex w-full items-center justify-center gap-2 rounded-lg py-2.5 text-sm font-medium text-white hover:opacity-90 disabled:opacity-60"
              style={{ background: '#1A4731' }}
            >
              {isPending && <Loader2 size={16} className="animate-spin" />}
              Create certification plan
            </button>
          )}
        </div>
      </div>
    </div>
  )
}
