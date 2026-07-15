'use client'

import { useState } from 'react'
import axios from 'axios'
import { CertivaAdSlot } from '@/components/ads/CertivaAdSlot'

// ── Constants ─────────────────────────────────────────────────────────────────

const STANDARDS = [
  { code: 'QMS',   label: 'ISO 9001:2015',      desc: 'Quality Management' },
  { code: 'EMS',   label: 'ISO 14001:2015',     desc: 'Environmental Management' },
  { code: 'OHSMS', label: 'ISO 45001:2018',     desc: 'Occupational Health & Safety' },
  { code: 'FSMS',  label: 'ISO 22000:2018',     desc: 'Food Safety Management' },
  { code: 'ISMS',  label: 'ISO/IEC 27001:2022', desc: 'Information Security' },
  { code: 'ENMS',  label: 'ISO 50001:2018',     desc: 'Energy Management' },
  { code: 'MDQMS', label: 'ISO 13485:2016',     desc: 'Medical Devices Quality' },
  { code: 'ABMS',  label: 'ISO 37001:2016',     desc: 'Anti-Bribery Management' },
]


const FOOD_CHAIN_CATEGORIES = [
  { code: 'CI',   label: 'CI — Animal farming / perishable animal products' },
  { code: 'CII',  label: 'CII — Perishable plant products (fresh produce)' },
  { code: 'CIII', label: 'CIII — Processed perishable / ready-to-eat' },
  { code: 'CIV',  label: 'CIV — Ambient-stable food (bakery, confectionery, beverages, dried)' },
  { code: 'C0',   label: 'C0 — Slaughter / primary processing of animal products' },
  { code: 'D',    label: 'D — Production of animal feed / pet food' },
  { code: 'E',    label: 'E — Catering / food service / restaurant' },
  { code: 'FI',   label: 'FI — Food retail' },
  { code: 'FII',  label: 'FII — Food wholesale / distribution / brokerage' },
  { code: 'G',    label: 'G — Food storage / cold-chain logistics' },
  { code: 'I',    label: 'I — Food packaging materials / food contact materials' },
  { code: 'K',    label: 'K — Food chemicals / additives / ingredient manufacture' },
  { code: 'BIII', label: 'BIII — Plant pre-processing (sorting, cleaning, packing whole plants)' },
]

const MDQMS_DEVICE_CLASSES = [
  'Class I (low risk)', 'Class IIa (medium risk)', 'Class IIb (medium-high risk)',
  'Class III (high risk)', 'In-vitro diagnostics (IVD)', 'Active implantable devices',
]

const MDQMS_TERRITORIES = [
  'EU MDR 2017/745', 'EU IVDR 2017/746', 'FDA 21 CFR 820',
  'ISO 13485 only (non-regulatory)', 'MDSAP (multi-country)',
]

// ── Form state type ───────────────────────────────────────────────────────────

interface FormState {
  // Company
  company_name: string; company_address: string; city: string; country: string
  phone: string; website: string
  // Contact
  representative_name: string; representative_email: string
  // Certification
  standards: string[]; audit_type: string; scope_description: string
  // Personnel — IAF MD5
  full_time_employees: string; part_time_employees: string
  subcontractor_employees: string; seasonal_employees: string
  shift_count: string; shift_same_process: boolean
  has_additional_sites: boolean
  site_details: Array<{ name: string; address: string; employee_count: string; process: string }>
  // EnMS (ISO 50001)
  enms_annual_energy_tj: string; enms_num_energy_types: string; enms_num_seus: string
  // FSMS (ISO 22000 / FSSC 22000)
  fsms_food_chain_categories: string[]; fsms_haccp_studies: string
  fsms_offsite_storage_count: string; fsms_separate_head_office: boolean
  fsms_fssc22000: boolean; fsms_seasonal_production: boolean
  // ISMS (ISO 27001)
  isms_technical_area: string; isms_data_role: string
  // MDQMS (ISO 13485)
  mdqms_device_classes: string[]; mdqms_regulatory_territories: string[]
}

const INITIAL: FormState = {
  company_name: '', company_address: '', city: '', country: '',
  phone: '', website: '',
  representative_name: '', representative_email: '',
  standards: [], audit_type: 'initial', scope_description: '',
  full_time_employees: '', part_time_employees: '',
  subcontractor_employees: '', seasonal_employees: '',
  shift_count: '1', shift_same_process: false,
  has_additional_sites: false,
  site_details: [],
  enms_annual_energy_tj: '', enms_num_energy_types: '', enms_num_seus: '',
  fsms_food_chain_categories: [], fsms_haccp_studies: '',
  fsms_offsite_storage_count: '', fsms_separate_head_office: false,
  fsms_fssc22000: false, fsms_seasonal_production: false,
  isms_technical_area: '', isms_data_role: '',
  mdqms_device_classes: [], mdqms_regulatory_territories: [],
}

// ── Helpers ───────────────────────────────────────────────────────────────────

function toggleArr<T>(arr: T[], val: T): T[] {
  return arr.includes(val) ? arr.filter(x => x !== val) : [...arr, val]
}

function pInt(s: string): number { return parseInt(s) || 0 }
function pFloat(s: string): number | null {
  const n = parseFloat(s); return isNaN(n) ? null : n
}

// ── Shared components ─────────────────────────────────────────────────────────

const inputCls = "w-full rounded-xl border border-slate-200 bg-slate-50/80 px-3.5 py-2.5 text-sm text-slate-900 transition focus:outline-none focus:ring-2 focus:ring-[#1A4731]/25 focus:border-[#1A4731] focus:bg-white"
const sectionHdCls = "text-xs font-semibold text-[#1A4731] uppercase tracking-[0.18em] mb-4"
const formSectionCls = "border-b border-slate-100 px-5 py-6 md:px-7"
const applicationBackdrop = {
  backgroundColor: '#071E25',
  backgroundImage: `
    linear-gradient(115deg, rgba(7,30,37,0.98), rgba(14,58,44,0.94) 42%, rgba(227,237,232,0.92) 42.2%, rgba(246,249,247,0.98)),
    radial-gradient(circle at 18% 16%, rgba(210,174,94,0.35), transparent 24%),
    radial-gradient(circle at 70% 8%, rgba(255,255,255,0.5), transparent 18%),
    radial-gradient(circle at 8% 85%, rgba(65,128,104,0.45), transparent 28%)
  `,
}

function Field({ label, hint, children }: { label: string; hint?: string; children: React.ReactNode }) {
  return (
    <div>
      <label className="block text-sm font-semibold text-slate-700 mb-1">{label}</label>
      {hint && <p className="text-xs text-slate-400 mb-1.5">{hint}</p>}
      {children}
    </div>
  )
}

function SectionPanel({ title, icon, children }: { title: string; icon: string; children: React.ReactNode }) {
  return (
    <div className={formSectionCls}>
      <h3 className="flex items-center gap-2 text-xs font-semibold uppercase tracking-[0.16em] text-[#1A4731] mb-4">
        <span className="text-base">{icon}</span>{title}
      </h3>
      <div className="space-y-4">{children}</div>
    </div>
  )
}

// ── Main page ─────────────────────────────────────────────────────────────────

export default function ApplyPage() {
  const [form, setForm] = useState<FormState>(INITIAL)
  const [loading, setLoading] = useState(false)
  const [success, setSuccess]         = useState(false)
  const [credentials, setCredentials] = useState<{ username: string; password: string } | null>(null)
  const [error, setError]             = useState('')
  const [consultantCode, setConsultantCode] = useState('')

  const sel = (patch: Partial<FormState>) => setForm(f => ({ ...f, ...patch }))
  const hasStd = (code: string) => form.standards.includes(code)

  function toggleStandard(code: string) {
    sel({ standards: toggleArr(form.standards, code) })
  }

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault()
    setError('')
    if (form.standards.length === 0) { setError('Please select at least one standard.'); return }
    if (!form.representative_email) { setError('Email address is required.'); return }

    setLoading(true)
    try {
      const apiBase = process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8000'
      const res = await axios.post(`${apiBase}/apply`, {
        company_name:      form.company_name,
        company_address:   form.company_address,
        city:              form.city,
        country:           form.country,
        phone:             form.phone,
        website:           form.website,
        representative_name:  form.representative_name,
        representative_email: form.representative_email,
        standards:         form.standards,
        audit_type:        form.audit_type,
        scope_description: form.scope_description,
        // Personnel
        full_time_employees:      pInt(form.full_time_employees),
        part_time_employees:      pInt(form.part_time_employees),
        subcontractor_employees:  pInt(form.subcontractor_employees),
        seasonal_employees:       pInt(form.seasonal_employees),
        shift_count:              pInt(form.shift_count) || 1,
        shift_same_process:       form.shift_same_process,
        has_additional_sites:     form.has_additional_sites && form.site_details.length > 0,
        additional_site_count:    form.site_details.length,
        site_details:             form.site_details.map(s => ({
          name:           s.name.trim(),
          address:        s.address.trim(),
          employee_count: pInt(s.employee_count),
          process:        s.process.trim(),
        })),
        // EnMS
        ...(hasStd('ENMS') && {
          enms_annual_energy_tj:  pFloat(form.enms_annual_energy_tj),
          enms_num_energy_types:  pInt(form.enms_num_energy_types) || null,
          enms_num_seus:          pInt(form.enms_num_seus) || null,
        }),
        // FSMS
        ...((hasStd('FSMS')) && {
          fsms_food_chain_categories: form.fsms_food_chain_categories,
          fsms_haccp_studies:      pInt(form.fsms_haccp_studies) || null,
          fsms_offsite_storage_count: pInt(form.fsms_offsite_storage_count),
          fsms_separate_head_office: form.fsms_separate_head_office,
          fsms_fssc22000:          form.fsms_fssc22000,
          fsms_seasonal_production: form.fsms_seasonal_production,
        }),
        // ISMS
        ...(hasStd('ISMS') && {
          isms_technical_area: form.isms_technical_area || null,
          isms_data_role:      form.isms_data_role || null,
        }),
        // MDQMS
        ...(hasStd('MDQMS') && {
          mdqms_device_classes:           form.mdqms_device_classes,
          mdqms_regulatory_territories:   form.mdqms_regulatory_territories,
        }),
        // Consultant referral
        consultant_code: consultantCode || undefined,
      })
      setCredentials({
        username: res.data.username      || form.representative_email,
        password: res.data.temp_password || '',
      })
      setSuccess(true)
    } catch (err: unknown) {
      const detail = (err as { response?: { data?: { detail?: string } } })?.response?.data?.detail
      setError(detail || 'Submission failed. Please try again.')
    } finally {
      setLoading(false)
    }
  }

  if (success) {
    return (
      <div className="relative flex min-h-screen items-center justify-center overflow-hidden p-6" style={applicationBackdrop}>
        <div className="absolute inset-0 opacity-[0.18]"
          style={{
            backgroundImage:
              'linear-gradient(rgba(26,71,49,.22) 1px, transparent 1px), linear-gradient(90deg, rgba(26,71,49,.22) 1px, transparent 1px)',
            backgroundSize: '52px 52px',
          }}
        />
        <div className="relative bg-white/95 rounded-xl shadow-xl shadow-emerald-900/10 border border-white/70 p-10 max-w-lg w-full backdrop-blur">
          {/* Header */}
          <div className="flex flex-col items-center text-center mb-8">
            <div className="w-14 h-14 bg-green-100 rounded-full flex items-center justify-center mb-4">
              <svg className="w-7 h-7 text-green-700" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M5 13l4 4L19 7" />
              </svg>
            </div>
            <h2 className="text-xl font-bold text-gray-900 mb-1">Application Submitted</h2>
            <p className="text-sm text-gray-500">
              Thank you. Your application is under review.
            </p>
          </div>

          {/* Credentials box */}
          {credentials && (
            <div className="mb-8 rounded-xl border-2 border-amber-200 bg-amber-50 p-5">
              <div className="flex items-center gap-2 mb-3">
                <svg className="w-4 h-4 text-amber-600 shrink-0" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2}
                    d="M12 9v2m0 4h.01M10.29 3.86L1.82 18a2 2 0 001.71 3h16.94a2 2 0 001.71-3L13.71 3.86a2 2 0 00-3.42 0z" />
                </svg>
                <p className="text-sm font-semibold text-amber-800">
                  Save your login credentials — you won&rsquo;t see them again
                </p>
              </div>

              <div className="space-y-3">
                {/* Username row */}
                <div className="flex items-center justify-between gap-3 rounded-lg bg-white border border-amber-200 px-3 py-2.5">
                  <div className="min-w-0">
                    <p className="text-[11px] font-medium text-gray-400 uppercase tracking-wide mb-0.5">Username</p>
                    <p className="text-sm font-mono text-gray-800 truncate">{credentials.username}</p>
                  </div>
                  <button
                    type="button"
                    onClick={() => navigator.clipboard.writeText(credentials.username)}
                    className="shrink-0 text-xs text-amber-700 hover:text-amber-900 font-medium border border-amber-300 rounded px-2 py-1"
                  >
                    Copy
                  </button>
                </div>

                {/* Password row */}
                <div className="flex items-center justify-between gap-3 rounded-lg bg-white border border-amber-200 px-3 py-2.5">
                  <div className="min-w-0">
                    <p className="text-[11px] font-medium text-gray-400 uppercase tracking-wide mb-0.5">Temporary Password</p>
                    <p className="text-sm font-mono text-gray-800 tracking-widest">{credentials.password}</p>
                  </div>
                  <button
                    type="button"
                    onClick={() => navigator.clipboard.writeText(credentials.password)}
                    className="shrink-0 text-xs text-amber-700 hover:text-amber-900 font-medium border border-amber-300 rounded px-2 py-1"
                  >
                    Copy
                  </button>
                </div>
              </div>

              <p className="mt-3 text-xs text-amber-700">
                These credentials have also been sent to your email address as a backup.
              </p>
            </div>
          )}

          <a
            href="/login"
            className="block w-full text-center bg-[#1A4731] text-white px-6 py-2.5 rounded-lg text-sm font-medium hover:opacity-90"
          >
            Go to Portal Login
          </a>
        </div>
      </div>
    )
  }

  return (
    <div className="relative min-h-screen overflow-hidden px-4 py-8 md:px-6 md:py-12" style={applicationBackdrop}>
      <div className="absolute inset-0 opacity-[0.16]"
        style={{
          backgroundImage:
            'linear-gradient(rgba(255,255,255,.24) 1px, transparent 1px), linear-gradient(90deg, rgba(255,255,255,.18) 1px, transparent 1px)',
          backgroundSize: '56px 56px',
        }}
      />
      <div className="pointer-events-none absolute left-[-12%] top-[18%] h-[460px] w-[460px] rounded-full border border-white/10" />
      <div className="pointer-events-none absolute left-[4%] top-[34%] h-[220px] w-[220px] rounded-full border border-white/10" />
      <div className="relative mx-auto max-w-6xl">
        {/* Header */}
        <div className="mb-7 grid gap-6 text-white lg:grid-cols-[minmax(0,1fr)_360px] lg:items-end">
          <div>
            <p className="text-xs font-semibold uppercase tracking-[0.24em] text-white/60">
              IFC Global LLC Certification Application
            </p>
            <h1 className="mt-4 max-w-3xl text-4xl font-semibold leading-tight md:text-6xl">
              You have made the right choice.
            </h1>
            <p className="mt-4 max-w-2xl text-base leading-7 text-white/74">
              Begin certification with a system that carries the file forward: scope, planning,
              audit duration, documents, signatures, reports, committee decision, certificate lifecycle,
              CRM follow-up, and training visibility.
            </p>
          </div>
          <div className="rounded-2xl border border-white/20 bg-white/10 p-2 shadow-2xl shadow-black/20 backdrop-blur-md">
            <CertivaAdSlot placement="apply_top" className="border-white/35 bg-white/95 text-slate-950" />
          </div>
        </div>

        <form onSubmit={handleSubmit} className="mx-auto max-w-4xl overflow-hidden rounded-[2rem] border border-white/75 bg-white/95 shadow-2xl shadow-emerald-950/20 backdrop-blur">
          <div className="border-b border-slate-100 px-5 py-5 md:px-7">
            <p className="text-xs font-semibold uppercase tracking-[0.2em] text-slate-400">
              Application intake
            </p>
            <p className="mt-1 text-sm text-slate-500">
              Complete the essentials below. The platform will use this information to prepare the certification workflow.
            </p>
          </div>

          {/* ── 1. Company Information ─────────────────────────────────── */}
          <div className={`${formSectionCls} space-y-4`}>
            <h2 className={sectionHdCls}>Company Information</h2>
            <Field label="Company Name *">
              <input className={inputCls} value={form.company_name}
                onChange={e => sel({ company_name: e.target.value })} required />
            </Field>
            <Field label="Company Address *">
              <input className={inputCls} value={form.company_address}
                onChange={e => sel({ company_address: e.target.value })} required />
            </Field>
            <div className="grid gap-4 md:grid-cols-2">
              <Field label="City">
                <input className={inputCls} value={form.city} onChange={e => sel({ city: e.target.value })} />
              </Field>
              <Field label="Country">
                <input className={inputCls} value={form.country} onChange={e => sel({ country: e.target.value })} />
              </Field>
            </div>
            <div className="grid gap-4 md:grid-cols-2">
              <Field label="Phone">
                <input className={inputCls} type="tel" value={form.phone} onChange={e => sel({ phone: e.target.value })} />
              </Field>
              <Field label="Website">
                <input className={inputCls} type="url" placeholder="https://" value={form.website}
                  onChange={e => sel({ website: e.target.value })} />
              </Field>
            </div>
          </div>

          {/* ── 2. Contact Person ─────────────────────────────────────── */}
          <div className={`${formSectionCls} space-y-4`}>
            <h2 className={sectionHdCls}>Contact Person</h2>
            <Field label="Full Name *">
              <input className={inputCls} value={form.representative_name}
                onChange={e => sel({ representative_name: e.target.value })} required />
            </Field>
            <Field label="Email Address *" hint="Your portal login credentials will be sent to this address.">
              <input className={inputCls} type="email" value={form.representative_email}
                onChange={e => sel({ representative_email: e.target.value })} required />
            </Field>
          </div>

          {/* ── 3. Standards Requested ────────────────────────────────── */}
          <div className={formSectionCls}>
            <h2 className={sectionHdCls}>Standards Requested *</h2>
            <div className="grid gap-2 md:grid-cols-2">
              {STANDARDS.map(s => (
                <label key={s.code} className={`flex items-center gap-3 p-3 rounded-lg border cursor-pointer transition-colors ${
                  hasStd(s.code) ? 'border-[#1A4731] bg-[#1A4731]/5' : 'border-gray-200 hover:bg-gray-50'
                }`}>
                  <input type="checkbox" checked={hasStd(s.code)} onChange={() => toggleStandard(s.code)}
                    className="w-4 h-4 accent-[#1A4731]" />
                  <div>
                    <span className="text-sm font-medium text-gray-800">{s.label}</span>
                    <span className="text-xs text-gray-500 ml-2">— {s.desc}</span>
                  </div>
                </label>
              ))}
            </div>
          </div>

          {/* ── 4. Audit Type ─────────────────────────────────────────── */}
          <div className={formSectionCls}>
            <h2 className={sectionHdCls}>Audit Type *</h2>
            <div className="grid gap-3 md:grid-cols-3">
              {[
                { v: 'initial',          l: 'Initial Certification' },
                { v: 'surveillance',     l: 'Surveillance' },
                { v: 'recertification',  l: 'Recertification' },
              ].map(opt => (
                <label key={opt.v} className={`p-3 rounded-lg border text-center cursor-pointer text-sm transition-colors ${
                  form.audit_type === opt.v ? 'bg-[#1A4731] text-white border-[#1A4731]' : 'bg-white text-gray-700 hover:bg-gray-50'
                }`}>
                  <input type="radio" name="audit_type" value={opt.v} checked={form.audit_type === opt.v}
                    onChange={e => sel({ audit_type: e.target.value })} className="hidden" />
                  {opt.l}
                </label>
              ))}
            </div>
          </div>

          {/* ── 5. Scope ──────────────────────────────────────────────── */}
          <div className={formSectionCls}>
            <h2 className={sectionHdCls}>What Does Your Company Do? *</h2>
            <p className="text-xs text-gray-400 mb-3">
              Describe your main activities (e.g. &ldquo;Manufacturing and sales of dried fruits&rdquo;).
            </p>
            <textarea className={`${inputCls} h-24 resize-none`}
              value={form.scope_description}
              onChange={e => sel({ scope_description: e.target.value })} required />
          </div>

          {/* ── 6. Personnel ──────────────────────────────────────────── */}
          <div className={`${formSectionCls} space-y-4`}>
            <h2 className={sectionHdCls}>Personnel</h2>
            <p className="text-xs text-gray-500 -mt-2 mb-2">
              Accurate personnel data is required to calculate your audit duration per IAF MD5.
            </p>
            <div className="grid gap-4 md:grid-cols-2">
              <Field label="Full-time employees *" hint="Permanent workforce">
                <input className={inputCls} type="number" min="0" value={form.full_time_employees}
                  onChange={e => sel({ full_time_employees: e.target.value })} required />
              </Field>
              <Field label="Part-time employees" hint="Counted as 0.5 FTE each">
                <input className={inputCls} type="number" min="0" value={form.part_time_employees}
                  onChange={e => sel({ part_time_employees: e.target.value })} />
              </Field>
              <Field label="Subcontractors (in scope)" hint="Working under your management system">
                <input className={inputCls} type="number" min="0" value={form.subcontractor_employees}
                  onChange={e => sel({ subcontractor_employees: e.target.value })} />
              </Field>
              <Field label="Seasonal employees (peak)" hint="Maximum headcount during peak season">
                <input className={inputCls} type="number" min="0" value={form.seasonal_employees}
                  onChange={e => sel({ seasonal_employees: e.target.value })} />
              </Field>
            </div>

            <div className="grid gap-4 md:grid-cols-2">
              <Field label="Number of work shifts">
                <select className={inputCls} value={form.shift_count}
                  onChange={e => sel({ shift_count: e.target.value })}>
                  <option value="1">1 shift</option>
                  <option value="2">2 shifts</option>
                  <option value="3">3 shifts</option>
                </select>
              </Field>
              {parseInt(form.shift_count) > 1 && (
                <Field label="Shifts run the same process">
                  <label className="flex items-center gap-2 mt-2 cursor-pointer">
                    <input type="checkbox" checked={form.shift_same_process}
                      onChange={e => sel({ shift_same_process: e.target.checked })}
                      className="w-4 h-4 accent-[#1A4731]" />
                    <span className="text-sm text-gray-700">Yes, same work in each shift</span>
                  </label>
                </Field>
              )}
            </div>

            {/* Additional sites */}
            <label className="flex items-center gap-2 cursor-pointer">
              <input type="checkbox" checked={form.has_additional_sites}
                onChange={e => sel({ has_additional_sites: e.target.checked })}
                className="w-4 h-4 accent-[#1A4731]" />
              <span className="text-sm text-gray-700">We have additional sites / branches</span>
            </label>
            {form.has_additional_sites && (
              <div className="space-y-4 mt-2">
                {form.site_details.map((site, i) => (
                  <div key={i} className="rounded-lg border border-gray-200 bg-gray-50 p-4 space-y-3">
                    <div className="flex items-center justify-between">
                      <span className="text-sm font-medium text-gray-700">Site {i + 1}</span>
                      <button type="button"
                        onClick={() => sel({ site_details: form.site_details.filter((_, idx) => idx !== i) })}
                        className="text-xs text-red-500 hover:text-red-700">Remove</button>
                    </div>
                    <Field label="Site name / label">
                      <input className={inputCls} placeholder="e.g. Branch in İstanbul"
                        value={site.name}
                        onChange={e => sel({ site_details: form.site_details.map((s, idx) => idx === i ? { ...s, name: e.target.value } : s) })} />
                    </Field>
                    <Field label="Address">
                      <input className={inputCls} placeholder="Street, City, Country"
                        value={site.address}
                        onChange={e => sel({ site_details: form.site_details.map((s, idx) => idx === i ? { ...s, address: e.target.value } : s) })} />
                    </Field>
                    <Field label="Employees at this site">
                      <input className={inputCls} type="number" min="0" placeholder="0"
                        value={site.employee_count}
                        onChange={e => sel({ site_details: form.site_details.map((s, idx) => idx === i ? { ...s, employee_count: e.target.value } : s) })} />
                    </Field>
                    <Field label="Main activities at this site">
                      <input className={inputCls} placeholder="e.g. Warehousing and distribution"
                        value={site.process}
                        onChange={e => sel({ site_details: form.site_details.map((s, idx) => idx === i ? { ...s, process: e.target.value } : s) })} />
                    </Field>
                  </div>
                ))}
                <button type="button"
                  onClick={() => sel({ site_details: [...form.site_details, { name: '', address: '', employee_count: '', process: '' }] })}
                  className="text-sm text-[#1A4731] hover:underline">
                  + Add another site
                </button>
              </div>
            )}
          </div>

          {/* ── 7. Standard-specific sections (dynamic) ───────────────── */}

          {/* ISO 50001 — EnMS Energy Profile */}
          {hasStd('ENMS') && (
            <SectionPanel title="ISO 50001 — Energy Management System Details" icon="⚡">
              <p className="text-xs text-blue-700 -mt-2 mb-2">
                Required to calculate audit duration using the ISO 50003 K-factor method.
              </p>
              <div className="grid gap-4">
                <Field
                  label="Annual energy consumption (TJ)"
                  hint="Total energy used by all sites in scope, per year"
                >
                  <select className={inputCls} value={form.enms_annual_energy_tj}
                    onChange={e => sel({ enms_annual_energy_tj: e.target.value })}>
                    <option value="">— Select range —</option>
                    <option value="10">≤ 20 TJ (small facility)</option>
                    <option value="100">20–200 TJ (medium)</option>
                    <option value="1000">200–2,000 TJ (large industrial)</option>
                    <option value="5000">&gt; 2,000 TJ (very large / heavy industry)</option>
                  </select>
                </Field>
                <Field
                  label="Number of energy types (sources)"
                  hint="e.g. electricity, natural gas, diesel, steam = 4"
                >
                  <select className={inputCls} value={form.enms_num_energy_types}
                    onChange={e => sel({ enms_num_energy_types: e.target.value })}>
                    <option value="">— Select —</option>
                    <option value="1">1 energy type</option>
                    <option value="2">2 energy types</option>
                    <option value="3">3 energy types</option>
                    <option value="4">4 or more energy types</option>
                  </select>
                </Field>
                <Field
                  label="Number of Significant Energy Uses (SEUs)"
                  hint="Equipment / processes that account for the majority (≥80%) of energy consumption"
                >
                  <select className={inputCls} value={form.enms_num_seus}
                    onChange={e => sel({ enms_num_seus: e.target.value })}>
                    <option value="">— Select —</option>
                    <option value="2">1–3 SEUs</option>
                    <option value="5">4–6 SEUs</option>
                    <option value="8">7–10 SEUs</option>
                    <option value="12">11–15 SEUs</option>
                    <option value="20">&gt; 15 SEUs</option>
                  </select>
                </Field>
              </div>
            </SectionPanel>
          )}

          {/* ISO 22000 / FSSC 22000 — FSMS Details */}
          {hasStd('FSMS') && (
            <SectionPanel title="ISO 22000 — Food Safety Management System Details" icon="🍽️">
              <p className="text-xs text-blue-700 -mt-2 mb-2">
                Required for audit duration calculation per ISO 22003-1:2022.
              </p>

              {/* Food chain categories */}
              <div>
                <label className="block text-sm font-medium text-gray-700 mb-2">
                  Food chain categories in scope *
                </label>
                <p className="text-xs text-gray-500 mb-2">Select all that apply.</p>
                <div className="space-y-1.5 max-h-64 overflow-y-auto pr-1">
                  {FOOD_CHAIN_CATEGORIES.map(cat => (
                    <label key={cat.code} className="flex items-start gap-2 cursor-pointer group">
                      <input type="checkbox"
                        checked={form.fsms_food_chain_categories.includes(cat.code)}
                        onChange={() => sel({ fsms_food_chain_categories: toggleArr(form.fsms_food_chain_categories, cat.code) })}
                        className="mt-0.5 w-4 h-4 accent-[#1A4731] shrink-0" />
                      <span className="text-xs text-gray-700 group-hover:text-gray-900">{cat.label}</span>
                    </label>
                  ))}
                </div>
              </div>

              <div className="grid gap-4 md:grid-cols-2">
                <Field label="Number of HACCP / food safety studies" hint="Distinct HACCP plans in scope">
                  <input className={inputCls} type="number" min="0" value={form.fsms_haccp_studies}
                    onChange={e => sel({ fsms_haccp_studies: e.target.value })} />
                </Field>
                <Field label="Off-site storage facilities in scope" hint="+0.25 audit day each (ISO 22003-1 §B.2.5)">
                  <input className={inputCls} type="number" min="0" value={form.fsms_offsite_storage_count}
                    onChange={e => sel({ fsms_offsite_storage_count: e.target.value })} />
                </Field>
              </div>

              <div className="space-y-2">
                {[
                  { key: 'fsms_separate_head_office' as const, label: 'Head office is separate from production site (+0.5 audit day)' },
                  { key: 'fsms_fssc22000' as const,            label: 'Applying for FSSC 22000 certification scheme (+1.0 day reporting surcharge)' },
                  { key: 'fsms_seasonal_production' as const,  label: 'Seasonal production (production stops for part of the year)' },
                ].map(({ key, label }) => (
                  <label key={key} className="flex items-center gap-2 cursor-pointer">
                    <input type="checkbox" checked={form[key] as boolean}
                      onChange={e => sel({ [key]: e.target.checked } as Partial<FormState>)}
                      className="w-4 h-4 accent-[#1A4731]" />
                    <span className="text-sm text-gray-700">{label}</span>
                  </label>
                ))}
              </div>
            </SectionPanel>
          )}

          {/* ISO 27001 — ISMS Details */}
          {hasStd('ISMS') && (
            <SectionPanel title="ISO/IEC 27001 — Information Security Management System Details" icon="🔐">
              <p className="text-xs text-blue-700 -mt-2 mb-2">
                Used for EPS calculation per ISO/IEC 27006-1:2024 and technical area classification.
              </p>
              <Field
                label="Technical area"
                hint="Your organization's primary ISMS technical domain per ISO/IEC 27006-1"
              >
                <select className={inputCls} value={form.isms_technical_area}
                  onChange={e => sel({ isms_technical_area: e.target.value })}>
                  <option value="">— Select —</option>
                  <option value="A">A — Standard IT (office-type: desktops, servers, cloud, HR/finance systems)</option>
                  <option value="B">B — Industrial / OT systems (ICS, SCADA, manufacturing IT)</option>
                  <option value="C">C — Telecom / service provider infrastructure</option>
                  <option value="D">D — Specialized (data centres, crypto, medical devices, critical infrastructure)</option>
                </select>
              </Field>
              <Field label="Data role under GDPR / data protection law">
                <select className={inputCls} value={form.isms_data_role}
                  onChange={e => sel({ isms_data_role: e.target.value })}>
                  <option value="">— Select —</option>
                  <option value="Controller">Data Controller (you decide the purpose of data processing)</option>
                  <option value="Processor">Data Processor (you process data on behalf of others)</option>
                  <option value="Both">Both Controller and Processor</option>
                </select>
              </Field>
            </SectionPanel>
          )}

          {/* ISO 13485 — MDQMS Details */}
          {hasStd('MDQMS') && (
            <SectionPanel title="ISO 13485 — Medical Devices Quality System Details" icon="🏥">
              <div>
                <label className="block text-sm font-medium text-gray-700 mb-2">
                  Medical device class(es) in scope
                </label>
                <div className="space-y-1.5">
                  {MDQMS_DEVICE_CLASSES.map(cls => (
                    <label key={cls} className="flex items-center gap-2 cursor-pointer">
                      <input type="checkbox"
                        checked={form.mdqms_device_classes.includes(cls)}
                        onChange={() => sel({ mdqms_device_classes: toggleArr(form.mdqms_device_classes, cls) })}
                        className="w-4 h-4 accent-[#1A4731]" />
                      <span className="text-sm text-gray-700">{cls}</span>
                    </label>
                  ))}
                </div>
              </div>
              <div>
                <label className="block text-sm font-medium text-gray-700 mb-2">
                  Regulatory framework(s) in scope
                </label>
                <div className="space-y-1.5">
                  {MDQMS_TERRITORIES.map(t => (
                    <label key={t} className="flex items-center gap-2 cursor-pointer">
                      <input type="checkbox"
                        checked={form.mdqms_regulatory_territories.includes(t)}
                        onChange={() => sel({ mdqms_regulatory_territories: toggleArr(form.mdqms_regulatory_territories, t) })}
                        className="w-4 h-4 accent-[#1A4731]" />
                      <span className="text-sm text-gray-700">{t}</span>
                    </label>
                  ))}
                </div>
              </div>
            </SectionPanel>
          )}

          {/* ── Consultant Referral ─────────────────────────────────────── */}
          <div className={`${formSectionCls} space-y-4`}>
            <h2 className={sectionHdCls}>Consultant Referral</h2>
            <div>
              <label className="block text-sm font-medium text-gray-700">
                Consultant Code <span className="font-normal text-gray-400">(optional)</span>
              </label>
              <input
                type="text"
                value={consultantCode}
                onChange={(e) => setConsultantCode(e.target.value)}
                placeholder="e.g. ali.yilmaz"
                className={inputCls}
              />
              <p className="mt-1 text-xs text-gray-400">
                If a consultant referred you to IFC Global, enter their referral code here.
              </p>
            </div>
          </div>

          {/* ── 8. Error + Submit ──────────────────────────────────────── */}
          <div className="px-5 py-6 md:px-7 space-y-4">
            {error && (
              <div className="bg-red-50 border border-red-200 text-red-700 text-sm rounded-lg p-3">
                {error}
              </div>
            )}
            <button
              type="submit" disabled={loading}
              className="w-full bg-[#1A4731] text-white py-3 rounded-lg font-medium hover:bg-[#143828] transition-colors disabled:opacity-60"
            >
              {loading ? 'Submitting…' : 'Submit Application'}
            </button>
            <p className="text-xs text-center text-gray-400">
              Already have an account?{' '}
              <a href="/login" className="text-[#1A4731] underline">Sign in here</a>
            </p>
          </div>

        </form>
      </div>
    </div>
  )
}
