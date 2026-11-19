'use client'

import { useEffect, useMemo, useState } from 'react'
import Link from 'next/link'
import { useParams } from 'next/navigation'
import { ArrowLeft, Calculator, CheckCircle2, Download, FileText, Loader2, RotateCcw, XCircle } from 'lucide-react'
import api from '@/lib/api'
import { useAuth } from '@/lib/auth'

interface DayLine { key: string; label: string; recommended_days: number; quoted_days: number; override_reason: string }
interface PriceLine { key: string; label: string; day_rate: number; amount: number }
interface DocumentMeta { id: string; kind: string; revision: number; file_name: string; created_at: string }
interface CycleResult {
  final_audit_time: number
  stage_1_time: number | null
  stage_2_time: number | null
  effective_personnel: number
  part_time_fte: number
  base_time: number
  md5_adjustment_pct: number
  md5_adjustment_days: number
  integration_level_pct: number
  md11_reduction_pct: number
  md11_reduction_days: number
  on_site_time: number
  remote_time: number
  classifications: Array<{ standard: string; codes: string[]; code_names: string[]; category: string; source: string }>
  standard_results: Array<{ standard: string; category: string; eps: number; central_time: number; additional_site_time: number; subtotal: number }>
  warnings: string[]
  compliance_notes: string[]
}
interface SalesCase {
  id: string
  company_name: string
  representative_name: string
  representative_email: string
  status: string
  application_data: Record<string, unknown>
  calculation_result: { initial: CycleResult; surveillance: CycleResult; recertification: CycleResult } | null
  day_breakdown: DayLine[] | null
  commercial_details: Record<string, unknown> | null
  pricing: Record<string, unknown> | null
  quotation_revision: number
  documents: DocumentMeta[]
}

const input = 'w-full rounded-lg border border-gray-200 bg-white px-3 py-2 text-sm outline-none focus:border-certiva-primary focus:ring-2 focus:ring-certiva-primary/15'
const stageKeys = ['initial_stage_1', 'initial_stage_2', 'surveillance_1', 'surveillance_2']

function DetailedCalculation({ title, result }: { title: string; result: CycleResult }) {
  return (
    <details className="rounded-xl border border-gray-100 bg-white" open={title === 'Initial certification'}>
      <summary className="cursor-pointer px-5 py-4 font-semibold text-gray-800">{title} · {result.final_audit_time} auditor-days</summary>
      <div className="space-y-5 border-t border-gray-100 p-5">
        <div className="grid gap-3 sm:grid-cols-3 lg:grid-cols-6">
          {[
            ['Effective personnel', result.effective_personnel], ['Base time', result.base_time],
            ['MD 5 adjustment', `${result.md5_adjustment_days} d`], ['MD 11 reduction', `${result.md11_reduction_days} d`],
            ['On-site', `${result.on_site_time} d`], ['Remote', `${result.remote_time} d`],
          ].map(([label, value]) => <div key={String(label)} className="rounded-lg bg-gray-50 p-3"><p className="text-[11px] uppercase tracking-wide text-gray-400">{label}</p><p className="mt-1 font-semibold text-gray-800">{value}</p></div>)}
        </div>
        <div>
          <h4 className="mb-2 text-xs font-semibold uppercase tracking-wide text-gray-500">Scope classification</h4>
          <div className="space-y-2">{result.classifications.map((row) => <div key={row.standard} className="grid gap-2 rounded-lg bg-emerald-50/50 p-3 text-sm md:grid-cols-[180px_1fr_150px]"><strong>{row.standard}</strong><span>{row.codes.join(', ') || 'Review required'} {row.code_names.length ? `· ${row.code_names.join(', ')}` : ''}</span><span>{row.category} · {row.source}</span></div>)}</div>
        </div>
        <div>
          <h4 className="mb-2 text-xs font-semibold uppercase tracking-wide text-gray-500">Standard-by-standard calculation</h4>
          <div className="overflow-x-auto"><table className="w-full text-sm"><thead className="bg-gray-50 text-left text-xs text-gray-400"><tr><th className="p-2">Standard</th><th className="p-2">Category</th><th className="p-2">EPS</th><th className="p-2">Central</th><th className="p-2">Sites</th><th className="p-2">Subtotal</th></tr></thead><tbody>{result.standard_results.map((row) => <tr key={row.standard} className="border-t border-gray-100"><td className="p-2 font-medium">{row.standard}</td><td className="p-2">{row.category}</td><td className="p-2">{row.eps}</td><td className="p-2">{row.central_time}</td><td className="p-2">{row.additional_site_time}</td><td className="p-2 font-semibold">{row.subtotal}</td></tr>)}</tbody></table></div>
        </div>
        {result.warnings.length > 0 && <div className="rounded-lg border border-amber-200 bg-amber-50 p-3 text-sm text-amber-800"><strong>Review required</strong><ul className="mt-1 list-disc pl-5">{result.warnings.map((warning) => <li key={warning}>{warning}</li>)}</ul></div>}
      </div>
    </details>
  )
}

export default function SalesQuotationCasePage() {
  const { user } = useAuth()
  const params = useParams<{ id: string }>()
  const [data, setData] = useState<SalesCase | null>(null)
  const [days, setDays] = useState<DayLine[]>([])
  const [included, setIncluded] = useState<string[]>(stageKeys)
  const [coverage, setCoverage] = useState('three_year_cycle')
  const [commercial, setCommercial] = useState({ solicitation_source: 'direct_inquiry', solicitation_method: 'email', solicitation_date: '', solicitation_reference: '', notes: '' })
  const [currency, setCurrency] = useState('USD')
  const [rates, setRates] = useState<Record<string, number>>({})
  const [fees, setFees] = useState({ application_fee: 0, certificate_fee: 0, travel_fee: 0, other_fee: 0, discount: 0 })
  const [busy, setBusy] = useState('')
  const [error, setError] = useState('')

  async function load() {
    const response = await api.get<SalesCase>(`/sales-quotations/${params.id}`)
    const item = response.data
    setData(item)
    setDays(item.day_breakdown || [])
    if (item.commercial_details) {
      const details = item.commercial_details as Record<string, unknown>
      setCoverage(String(details.coverage || 'three_year_cycle'))
      setIncluded(Array.isArray(details.included_stage_keys) ? details.included_stage_keys as string[] : stageKeys)
      setCommercial({
        solicitation_source: String(details.solicitation_source || 'direct_inquiry'), solicitation_method: String(details.solicitation_method || 'email'),
        solicitation_date: String(details.solicitation_date || ''), solicitation_reference: String(details.solicitation_reference || ''), notes: String(details.notes || ''),
      })
    }
    if (item.pricing) {
      const pricing = item.pricing as Record<string, unknown>
      setCurrency(String(pricing.currency || 'USD'))
      const lines = (pricing.line_items || []) as PriceLine[]
      setRates(Object.fromEntries(lines.map((line) => [line.key, Number(line.day_rate) || 0])))
      setFees({ application_fee: Number(pricing.application_fee) || 0, certificate_fee: Number(pricing.certificate_fee) || 0, travel_fee: Number(pricing.travel_fee) || 0, other_fee: Number(pricing.other_fee) || 0, discount: Number(pricing.discount) || 0 })
    }
  }

  useEffect(() => { if (user?.role === 'sales_manager') load().catch(() => setError('Could not load this private sales case.')) }, [params.id, user?.role]) // eslint-disable-line react-hooks/exhaustive-deps

  const total = useMemo(() => {
    const audit = days.filter((line) => included.includes(line.key)).reduce((sum, line) => sum + line.quoted_days * (rates[line.key] || 0), 0)
    return Math.max(0, audit + fees.application_fee + fees.certificate_fee + fees.travel_fee + fees.other_fee - fees.discount)
  }, [days, included, rates, fees])

  async function action(name: string, request: () => Promise<unknown>) {
    setBusy(name); setError('')
    try { await request(); await load() } catch (caught: unknown) {
      const detail = (caught as { response?: { data?: { detail?: string | Array<{ msg?: string }> } } }).response?.data?.detail
      setError(Array.isArray(detail) ? detail.map((entry) => entry.msg).join('; ') : detail || 'The action could not be completed.')
    } finally { setBusy('') }
  }

  function setCoverageMode(mode: string) {
    setCoverage(mode)
    if (mode === 'single_audit') {
      const requested = String(data?.application_data.audit_type || 'initial')
      const requestedKeys: Record<string, string[]> = {
        initial: ['initial_stage_1', 'initial_stage_2'],
        surveillance_1: ['surveillance_1'],
        surveillance_2: ['surveillance_2'],
        scope_extension: ['initial_stage_2'],
        surveillance_1_scope_extension: ['surveillance_1'],
        recertification: ['recertification'],
      }
      setIncluded(requestedKeys[requested] || ['initial_stage_1', 'initial_stage_2'])
    }
    if (mode === 'three_year_cycle') setIncluded(stageKeys)
  }

  async function savePreparation() {
    const labels: Record<string, string> = { single_audit: 'Initial certification only', three_year_cycle: 'Three-year certification cycle', custom: 'Custom selected activities' }
    await api.put(`/sales-quotations/${params.id}/prepare`, {
      day_breakdown: days,
      commercial_details: { ...commercial, coverage, coverage_label: labels[coverage], included_stage_keys: included },
      pricing: {
        currency,
        line_items: days.filter((line) => included.includes(line.key)).map((line) => ({ key: line.key, label: line.label, day_rate: rates[line.key] || 0, amount: line.quoted_days * (rates[line.key] || 0) })),
        ...fees,
      },
    })
  }

  async function download(doc: DocumentMeta) {
    const response = await api.get(`/sales-quotations/${params.id}/documents/${doc.id}`, { responseType: 'blob' })
    const url = URL.createObjectURL(response.data)
    const link = document.createElement('a'); link.href = url; link.download = doc.file_name; link.click(); URL.revokeObjectURL(url)
  }

  if (user && user.role !== 'sales_manager') return <div className="rounded-xl border border-red-200 bg-red-50 p-5 text-sm text-red-700">This private workspace is available only to sales managers.</div>
  if (!data) return <div className="flex items-center gap-2 text-sm text-gray-500"><Loader2 size={16} className="animate-spin" /> Loading quotation case…</div>

  return (
    <div className="mx-auto max-w-7xl space-y-6 pb-16">
      <Link href="/sales" className="inline-flex items-center gap-1 text-sm text-certiva-primary hover:underline"><ArrowLeft size={15} /> Sales Quotation Workspace</Link>
      <section className="rounded-2xl bg-certiva-night p-7 text-white">
        <div className="flex flex-wrap items-start justify-between gap-4"><div><p className="text-xs font-semibold uppercase tracking-[0.2em] text-certiva-signal">Private calculation · no operational side effects</p><h1 className="mt-2 text-3xl font-semibold">{data.company_name}</h1><p className="mt-2 text-sm text-white/60">{data.representative_name} · {data.representative_email}</p></div><span className="rounded-full border border-white/20 px-3 py-1 text-xs uppercase tracking-wide">{data.status.replaceAll('_', ' ')}</span></div>
      </section>

      {error && <div className="rounded-xl border border-red-200 bg-red-50 p-4 text-sm text-red-700">{error}</div>}

      {!data.calculation_result ? (
        <section className="rounded-xl border border-gray-100 bg-white p-6">
          <h2 className="text-lg font-semibold">1. Calculate the full audit cycle</h2><p className="mt-1 text-sm text-gray-500">The controlled calculator will classify the scope, calculate each standard separately, and return initial, surveillance, and recertification durations.</p>
          <button onClick={() => action('calculate', () => api.post(`/sales-quotations/${params.id}/calculate`))} disabled={!!busy} className="mt-5 inline-flex items-center gap-2 rounded-lg bg-certiva-primary px-4 py-2.5 text-sm font-semibold text-white disabled:opacity-50">{busy === 'calculate' ? <Loader2 size={16} className="animate-spin" /> : <Calculator size={16} />} Calculate detailed audit days</button>
        </section>
      ) : (
        <>
          <section className="space-y-3"><div><h2 className="text-lg font-semibold">1. Controlled calculation breakdown</h2><p className="text-sm text-gray-500">Calculated values remain immutable evidence. Any commercial override is recorded separately below.</p></div><DetailedCalculation title="Initial certification" result={data.calculation_result.initial} /><DetailedCalculation title="Surveillance" result={data.calculation_result.surveillance} /><DetailedCalculation title="Recertification" result={data.calculation_result.recertification} /></section>

          <section className="rounded-xl border border-gray-100 bg-white p-6">
            <h2 className="text-lg font-semibold">2. Quoted audit days</h2><p className="mt-1 text-sm text-gray-500">Edit only the quoted value. A reason is mandatory whenever it differs from the calculator.</p>
            <div className="mt-5 space-y-3">{days.map((line, index) => { const overridden = Math.abs(line.recommended_days - line.quoted_days) > 0.001; return <div key={line.key} className="grid gap-3 rounded-lg border border-gray-100 p-4 md:grid-cols-[1fr_130px_130px_1.5fr]"><div><p className="font-medium">{line.label}</p><p className="text-xs text-gray-400">Immutable recommendation</p></div><div><label className="text-xs text-gray-400">Calculated</label><div className="mt-1 rounded-lg bg-gray-50 px-3 py-2 text-sm">{line.recommended_days} days</div></div><div><label className="text-xs text-gray-400">Quoted</label><input type="number" min="0" step="0.5" className={input} value={line.quoted_days} onChange={(event) => setDays((current) => current.map((item, itemIndex) => itemIndex === index ? { ...item, quoted_days: Number(event.target.value) } : item))} /></div><div><label className="text-xs text-gray-400">Override reason {overridden ? '*' : ''}</label><input className={input} value={line.override_reason} disabled={!overridden} placeholder={overridden ? 'Why is this different?' : 'Not overridden'} onChange={(event) => setDays((current) => current.map((item, itemIndex) => itemIndex === index ? { ...item, override_reason: event.target.value } : item))} /></div></div> })}</div>
          </section>

          <section className="rounded-xl border border-gray-100 bg-white p-6">
            <h2 className="text-lg font-semibold">3. Solicitation and quotation coverage</h2>
            <div className="mt-5 grid gap-4 md:grid-cols-3"><label className="text-sm">How the request arrived<select className={`${input} mt-1`} value={commercial.solicitation_source} onChange={(e) => setCommercial({ ...commercial, solicitation_source: e.target.value })}><option value="direct_inquiry">Direct inquiry</option><option value="referral_consultant">Referral / consultant</option><option value="tender_rfp">Tender / RFP</option><option value="renewal_transfer">Renewal / transfer</option><option value="outbound">Outbound</option><option value="other">Other</option></select></label><label className="text-sm">Contact method<select className={`${input} mt-1`} value={commercial.solicitation_method} onChange={(e) => setCommercial({ ...commercial, solicitation_method: e.target.value })}><option>Email</option><option>Phone</option><option>Meeting</option><option>Web</option><option>Partner</option></select></label><label className="text-sm">Received date<input type="date" className={`${input} mt-1`} value={commercial.solicitation_date} onChange={(e) => setCommercial({ ...commercial, solicitation_date: e.target.value })} /></label><label className="text-sm">Reference<input className={`${input} mt-1`} value={commercial.solicitation_reference} onChange={(e) => setCommercial({ ...commercial, solicitation_reference: e.target.value })} /></label><label className="text-sm md:col-span-2">Commercial notes<input className={`${input} mt-1`} value={commercial.notes} onChange={(e) => setCommercial({ ...commercial, notes: e.target.value })} /></label></div>
            <div className="mt-5"><label className="text-sm font-medium">Quotation coverage</label><div className="mt-2 flex flex-wrap gap-2">{[['single_audit','Initial only'],['three_year_cycle','Three-year cycle'],['custom','Custom']].map(([value,label]) => <button type="button" key={value} onClick={() => setCoverageMode(value)} className={`rounded-lg border px-3 py-2 text-sm ${coverage === value ? 'border-certiva-primary bg-emerald-50 text-certiva-primary' : 'border-gray-200'}`}>{label}</button>)}</div><div className="mt-3 grid gap-2 sm:grid-cols-2 lg:grid-cols-5">{days.map((line) => <label key={line.key} className="flex items-center gap-2 rounded-lg border border-gray-100 p-3 text-sm"><input type="checkbox" checked={included.includes(line.key)} onChange={() => { setCoverage('custom'); setIncluded((current) => current.includes(line.key) ? current.filter((key) => key !== line.key) : [...current, line.key]) }} />{line.label}</label>)}</div></div>
          </section>

          <section className="rounded-xl border border-gray-100 bg-white p-6">
            <h2 className="text-lg font-semibold">4. Pricing</h2>
            <div className="mt-4 grid gap-3">{days.filter((line) => included.includes(line.key)).map((line) => <div key={line.key} className="grid items-end gap-3 rounded-lg bg-gray-50 p-3 sm:grid-cols-[1fr_100px_160px_160px]"><div><p className="font-medium">{line.label}</p></div><div className="text-sm text-gray-500">{line.quoted_days} days</div><label className="text-xs text-gray-500">Rate per day<input type="number" min="0" className={`${input} mt-1`} value={rates[line.key] || 0} onChange={(e) => setRates({ ...rates, [line.key]: Number(e.target.value) })} /></label><div className="rounded-lg bg-white px-3 py-2 text-right font-semibold">{(line.quoted_days * (rates[line.key] || 0)).toLocaleString()} {currency}</div></div>)}</div>
            <div className="mt-5 grid gap-3 sm:grid-cols-3"><label className="text-sm">Currency<input className={`${input} mt-1 uppercase`} maxLength={3} value={currency} onChange={(e) => setCurrency(e.target.value.toUpperCase())} /></label>{Object.entries(fees).map(([key, value]) => <label key={key} className="text-sm capitalize">{key.replaceAll('_', ' ')}<input type="number" min="0" className={`${input} mt-1`} value={value} onChange={(e) => setFees({ ...fees, [key]: Number(e.target.value) })} /></label>)}</div>
            <div className="mt-5 flex items-center justify-between rounded-xl bg-certiva-night p-5 text-white"><span className="text-sm text-white/65">Calculated commercial total</span><strong className="text-2xl">{total.toLocaleString(undefined, { maximumFractionDigits: 2 })} {currency}</strong></div>
          </section>

          <section className="rounded-xl border border-gray-100 bg-white p-6">
            <h2 className="text-lg font-semibold">5. Generate and record the outcome</h2><p className="mt-1 text-sm text-gray-500">Each generation creates a new retained revision. Rejected quotations stay stored. Approval automatically creates the editable agreement and ends this sales-only flow.</p>
            <div className="mt-5 flex flex-wrap gap-3"><button disabled={!!busy || data.status === 'agreed'} onClick={() => action('generate', async () => { await savePreparation(); await api.post(`/sales-quotations/${params.id}/quotation`) })} className="inline-flex items-center gap-2 rounded-lg bg-certiva-primary px-4 py-2.5 text-sm font-semibold text-white disabled:opacity-50">{busy === 'generate' ? <Loader2 size={16} className="animate-spin" /> : data.quotation_revision ? <RotateCcw size={16} /> : <FileText size={16} />}{data.quotation_revision ? 'Redo quotation as new revision' : 'Generate quotation'}</button>{data.status === 'quotation_generated' && <><button disabled={!!busy} onClick={() => action('reject', () => api.post(`/sales-quotations/${params.id}/reject`))} className="inline-flex items-center gap-2 rounded-lg border border-red-200 px-4 py-2.5 text-sm font-semibold text-red-700 disabled:opacity-50"><XCircle size={16} /> Quotation rejected</button><button disabled={!!busy} onClick={() => action('approve', () => api.post(`/sales-quotations/${params.id}/approve`))} className="inline-flex items-center gap-2 rounded-lg border border-emerald-300 bg-emerald-50 px-4 py-2.5 text-sm font-semibold text-emerald-800 disabled:opacity-50"><CheckCircle2 size={16} /> Approve and generate agreement</button></>}</div>
            {data.documents.length > 0 && <div className="mt-6 overflow-hidden rounded-lg border border-gray-100"><div className="bg-gray-50 px-4 py-2 text-xs font-semibold uppercase tracking-wide text-gray-500">Private document history</div>{data.documents.map((doc) => <div key={doc.id} className="flex items-center justify-between border-t border-gray-100 px-4 py-3 text-sm"><span><strong className="capitalize">{doc.kind}</strong> · Revision {doc.revision} · {new Date(doc.created_at).toLocaleString()}</span><button onClick={() => download(doc)} className="inline-flex items-center gap-1 font-medium text-certiva-primary hover:underline"><Download size={14} /> Download Word</button></div>)}</div>}
          </section>
        </>
      )}
    </div>
  )
}
