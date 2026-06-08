'use client'

import { useState } from 'react'
import axios from 'axios'

const STANDARDS = [
  { code: 'QMS',   label: 'ISO 9001:2015 — Quality Management' },
  { code: 'EMS',   label: 'ISO 14001:2015 — Environmental Management' },
  { code: 'OHSMS', label: 'ISO 45001:2018 — Occupational Health & Safety' },
  { code: 'FSMS',  label: 'ISO 22000:2018 — Food Safety Management' },
  { code: 'ISMS',  label: 'ISO/IEC 27001:2022 — Information Security' },
  { code: 'ENMS',  label: 'ISO 50001:2018 — Energy Management' },
  { code: 'MDQMS', label: 'ISO 13485:2016 — Medical Devices Quality' },
  { code: 'ABMS',  label: 'ISO 37001:2016 — Anti-Bribery Management' },
]

const SCOPE_EXAMPLES = [
  'Manufacturing and sales of dried fruits and roasted nuts',
  'Design, development and production of electronic control units',
  'Provision of road freight transport and logistics services',
  'Construction and installation of mechanical systems',
]

export default function ApplyPage() {
  const [form, setForm] = useState({
    company_name: '', company_address: '', city: '', country: '',
    phone: '', website: '',
    representative_name: '', representative_email: '',
    standards: [] as string[],
    audit_type: 'initial',
    scope_description: '',
    total_employees: '',
    has_additional_sites: false,
    additional_site_count: '',
  })
  const [loading, setLoading] = useState(false)
  const [success, setSuccess] = useState(false)
  const [error, setError] = useState('')

  function toggleStandard(code: string) {
    setForm(f => ({
      ...f,
      standards: f.standards.includes(code)
        ? f.standards.filter(s => s !== code)
        : [...f.standards, code],
    }))
  }

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault()
    setError('')
    if (form.standards.length === 0) {
      setError('Please select at least one standard.')
      return
    }
    setLoading(true)
    try {
      const apiBase = process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8000'
      await axios.post(`${apiBase}/apply`, {
        ...form,
        total_employees: parseInt(form.total_employees as string) || 0,
        additional_site_count: parseInt(form.additional_site_count as string) || 0,
      })
      setSuccess(true)
    } catch (err: any) {
      setError(err?.response?.data?.detail || 'Submission failed. Please try again.')
    } finally {
      setLoading(false)
    }
  }

  if (success) {
    return (
      <div className="min-h-screen bg-gray-50 flex items-center justify-center p-6">
        <div className="bg-white rounded-xl shadow-sm border p-10 max-w-md text-center">
          <div className="w-16 h-16 bg-green-100 rounded-full flex items-center justify-center mx-auto mb-4">
            <svg className="w-8 h-8 text-green-700" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M5 13l4 4L19 7" />
            </svg>
          </div>
          <h2 className="text-xl font-bold text-gray-900 mb-2">Application Submitted</h2>
          <p className="text-gray-600 mb-6">
            Thank you. We have received your application and will review it shortly.
            Login credentials have been sent to your email address.
          </p>
          <a
            href="/login"
            className="inline-block bg-[#1A4731] text-white px-6 py-2.5 rounded-lg text-sm font-medium"
          >
            Go to Portal Login
          </a>
        </div>
      </div>
    )
  }

  return (
    <div className="min-h-screen bg-gray-50 py-10 px-4">
      <div className="max-w-2xl mx-auto">
        {/* Header */}
        <div className="text-center mb-8">
          <h1 className="text-2xl font-bold text-[#1A4731]">IFC Global LLC</h1>
          <p className="text-gray-500 mt-1">Certification Application Form</p>
        </div>

        <form onSubmit={handleSubmit} className="bg-white rounded-xl shadow-sm border p-8 space-y-6">

          {/* Company Info */}
          <section>
            <h2 className="text-sm font-semibold text-gray-700 uppercase tracking-wide mb-4">Company Information</h2>
            <div className="grid grid-cols-1 gap-4">
              <Field label="Company Name *" required>
                <input className={inputCls} value={form.company_name} onChange={e => setForm({...form, company_name: e.target.value})} required />
              </Field>
              <Field label="Company Address *" required>
                <input className={inputCls} value={form.company_address} onChange={e => setForm({...form, company_address: e.target.value})} required />
              </Field>
              <div className="grid grid-cols-2 gap-4">
                <Field label="City">
                  <input className={inputCls} value={form.city} onChange={e => setForm({...form, city: e.target.value})} />
                </Field>
                <Field label="Country">
                  <input className={inputCls} value={form.country} onChange={e => setForm({...form, country: e.target.value})} />
                </Field>
              </div>
              <div className="grid grid-cols-2 gap-4">
                <Field label="Phone">
                  <input className={inputCls} type="tel" value={form.phone} onChange={e => setForm({...form, phone: e.target.value})} />
                </Field>
                <Field label="Website">
                  <input className={inputCls} type="url" placeholder="https://" value={form.website} onChange={e => setForm({...form, website: e.target.value})} />
                </Field>
              </div>
            </div>
          </section>

          {/* Contact Person */}
          <section>
            <h2 className="text-sm font-semibold text-gray-700 uppercase tracking-wide mb-4">Contact Person</h2>
            <div className="grid grid-cols-1 gap-4">
              <Field label="Full Name *" required>
                <input className={inputCls} value={form.representative_name} onChange={e => setForm({...form, representative_name: e.target.value})} required />
              </Field>
              <Field label="Email Address *" required>
                <input className={inputCls} type="email" value={form.representative_email} onChange={e => setForm({...form, representative_email: e.target.value})} required />
                <p className="text-xs text-gray-400 mt-1">Your portal login credentials will be sent to this address.</p>
              </Field>
            </div>
          </section>


          {/* Standards */}
          <section>
            <h2 className="text-sm font-semibold text-gray-700 uppercase tracking-wide mb-4">Standards Requested *</h2>
            <div className="grid grid-cols-1 gap-2">
              {STANDARDS.map(s => (
                <label key={s.code} className="flex items-center gap-3 p-3 rounded-lg border cursor-pointer hover:bg-gray-50 transition-colors">
                  <input
                    type="checkbox"
                    checked={form.standards.includes(s.code)}
                    onChange={() => toggleStandard(s.code)}
                    className="w-4 h-4 accent-[#1A4731]"
                  />
                  <span className="text-sm text-gray-700">{s.label}</span>
                </label>
              ))}
            </div>
          </section>

          {/* Audit Type */}
          <section>
            <h2 className="text-sm font-semibold text-gray-700 uppercase tracking-wide mb-4">Audit Type *</h2>
            <div className="grid grid-cols-3 gap-3">
              {[
                {v:'initial', l:'Initial Certification'},
                {v:'surveillance', l:'Surveillance'},
                {v:'recertification', l:'Recertification'},
              ].map(opt => (
                <label key={opt.v} className={`p-3 rounded-lg border text-center cursor-pointer text-sm transition-colors ${form.audit_type === opt.v ? 'bg-[#1A4731] text-white border-[#1A4731]' : 'bg-white text-gray-700 hover:bg-gray-50'}`}>
                  <input type="radio" name="audit_type" value={opt.v} checked={form.audit_type === opt.v} onChange={e => setForm({...form, audit_type: e.target.value})} className="hidden" />
                  {opt.l}
                </label>
              ))}
            </div>
          </section>

          {/* Scope */}
          <section>
            <h2 className="text-sm font-semibold text-gray-700 uppercase tracking-wide mb-1">What Does Your Company Do? *</h2>
            <p className="text-xs text-gray-400 mb-3">Describe your main activities. Examples: {SCOPE_EXAMPLES.slice(0,2).join('; ')}</p>
            <textarea
              className={`${inputCls} h-24 resize-none`}
              placeholder={SCOPE_EXAMPLES[0]}
              value={form.scope_description}
              onChange={e => setForm({...form, scope_description: e.target.value})}
              required
            />
          </section>

          {/* Employees */}
          <section>
            <h2 className="text-sm font-semibold text-gray-700 uppercase tracking-wide mb-4">Personnel</h2>
            <div className="grid grid-cols-2 gap-4">
              <Field label="Total Number of Employees *" required>
                <input className={inputCls} type="number" min="1" value={form.total_employees} onChange={e => setForm({...form, total_employees: e.target.value})} required />
              </Field>
            </div>
            <label className="flex items-center gap-2 mt-4 cursor-pointer">
              <input type="checkbox" checked={form.has_additional_sites} onChange={e => setForm({...form, has_additional_sites: e.target.checked})} className="w-4 h-4 accent-[#1A4731]" />
              <span className="text-sm text-gray-700">We have additional sites / branches</span>
            </label>
            {form.has_additional_sites && (
              <div className="mt-3">
                <Field label="Number of Additional Sites">
                  <input className={inputCls} type="number" min="1" value={form.additional_site_count} onChange={e => setForm({...form, additional_site_count: e.target.value})} />
                </Field>
              </div>
            )}
          </section>

          {error && (
            <div className="bg-red-50 border border-red-200 text-red-700 text-sm rounded-lg p-3">
              {error}
            </div>
          )}

          <button
            type="submit"
            disabled={loading}
            className="w-full bg-[#1A4731] text-white py-3 rounded-lg font-medium hover:bg-[#143828] transition-colors disabled:opacity-60"
          >
            {loading ? 'Submitting...' : 'Submit Application'}
          </button>

          <p className="text-xs text-center text-gray-400">
            Already have an account? <a href="/login" className="text-[#1A4731] underline">Sign in here</a>
          </p>
        </form>
      </div>
    </div>
  )
}

const inputCls = "w-full border border-gray-200 rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-[#1A4731]/30 focus:border-[#1A4731]"

function Field({ label, children }: { label: string; children: React.ReactNode; required?: boolean }) {
  return (
    <div>
      <label className="block text-sm font-medium text-gray-700 mb-1">{label}</label>
      {children}
    </div>
  )
}
