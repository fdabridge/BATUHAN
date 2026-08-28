'use client'

import { useMemo, useState } from 'react'
import Link from 'next/link'
import { ArrowLeft, CalendarPlus, Download, FileUp, Loader2, Plus, Sparkles, Trash2, Wand2 } from 'lucide-react'
import api from '@/lib/api'
import { apiErrorMessage } from '@/lib/apiError'

type DayWindow = {
  date: string
  start_time: string
  end_time: string
  lunch_start: string
  lunch_end: string
  site: string
}

const STANDARD_OPTIONS = [
  'ISO 9001:2015',
  'ISO 14001:2015',
  'ISO 45001:2018',
  'ISO 22000:2018',
  'ISO 27001:2022',
  'ISO 13485:2016',
  'ISO 37001:2016',
  'ISO 50001:2018',
]

const AUDIT_TYPES = ['Stage 1', 'Stage 2', 'Surveillance 1', 'Surveillance 2', 'Recertification']

const emptyDay = (): DayWindow => ({
  date: '',
  start_time: '09:00',
  end_time: '17:00',
  lunch_start: '13:00',
  lunch_end: '14:00',
  site: '',
})

function toggleValue(values: string[], value: string): string[] {
  return values.includes(value) ? values.filter((item) => item !== value) : [...values, value]
}

function filenameFromDisposition(header: string | undefined): string {
  if (!header) return 'AuditPlan_CertivAI.docx'
  const match = header.match(/filename="?([^";]+)"?/i)
  return match?.[1] || 'AuditPlan_CertivAI.docx'
}

export default function CertivAIAuditPlanPage() {
  const [template, setTemplate] = useState<File | null>(null)
  const [standards, setStandards] = useState<string[]>(['ISO 9001:2015'])
  const [auditType, setAuditType] = useState('Stage 2')
  const [eaCode, setEaCode] = useState('')
  const [category, setCategory] = useState('')
  const [scope, setScope] = useState('')
  const [orgName, setOrgName] = useState('')
  const [address, setAddress] = useState('')
  const [days, setDays] = useState<DayWindow[]>([emptyDay()])
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState('')
  const [successName, setSuccessName] = useState('')

  const readyScore = useMemo(() => {
    let score = 0
    if (template) score += 25
    if (standards.length > 0) score += 25
    if (days.every((day) => day.date && day.start_time && day.end_time)) score += 35
    if (eaCode || category || scope) score += 15
    return score
  }, [template, standards, days, eaCode, category, scope])

  const updateDay = (index: number, patch: Partial<DayWindow>) => {
    setDays((current) => current.map((day, i) => (i === index ? { ...day, ...patch } : day)))
  }

  const removeDay = (index: number) => {
    setDays((current) => current.length === 1 ? current : current.filter((_, i) => i !== index))
  }

  const submit = async () => {
    setError('')
    setSuccessName('')
    if (!template) {
      setError('Upload the FR.223 DOCX template first.')
      return
    }
    if (standards.length === 0) {
      setError('Select at least one standard.')
      return
    }
    const incompleteDay = days.findIndex((day) => !day.date || !day.start_time || !day.end_time)
    if (incompleteDay >= 0) {
      setError(`Complete date, start time, and end time for day ${incompleteDay + 1}.`)
      return
    }

    const form = new FormData()
    form.append('template', template)
    form.append('standards', JSON.stringify(standards))
    form.append('audit_type', auditType)
    form.append('ea_code', eaCode)
    form.append('category', category)
    form.append('scope', scope)
    form.append('org_name', orgName)
    form.append('address', address)
    form.append('day_windows', JSON.stringify(days))

    setLoading(true)
    try {
      const response = await api.post('/audit-plan/generate', form, {
        responseType: 'blob',
        headers: { 'Content-Type': 'multipart/form-data' },
      })
      const blob = new Blob([response.data], {
        type: 'application/vnd.openxmlformats-officedocument.wordprocessingml.document',
      })
      const filename = filenameFromDisposition(response.headers['content-disposition'])
      const url = window.URL.createObjectURL(blob)
      const link = document.createElement('a')
      link.href = url
      link.download = filename
      document.body.appendChild(link)
      link.click()
      link.remove()
      window.URL.revokeObjectURL(url)
      setSuccessName(filename)
    } catch (err: unknown) {
      setError(await apiErrorMessage(
        err,
        'Could not generate the audit plan.',
        'audit-plan service',
      ))
    } finally {
      setLoading(false)
    }
  }

  return (
    <div className="min-h-[calc(100vh-52px)] bg-[#06110D] text-white">
      <div className="mx-auto max-w-[1320px] px-6 py-6">
        <Link href="/certivai" className="mb-5 inline-flex items-center gap-2 text-sm text-emerald-200 hover:text-white">
          <ArrowLeft size={16} />
          Certiv.AI
        </Link>

        <div className="grid gap-5 xl:grid-cols-[0.95fr_1.45fr]">
          <section className="space-y-5">
            <div className="border border-emerald-300/20 bg-white/[0.045] p-5" style={{ borderRadius: 8 }}>
              <div className="flex items-center gap-3">
                <span className="flex h-11 w-11 items-center justify-center rounded bg-emerald-400/15 text-emerald-200">
                  <Wand2 size={22} />
                </span>
                <div>
                  <h1 className="text-3xl font-semibold">Audit Plan Generator</h1>
                  <p className="mt-1 text-sm text-slate-300">FR.223 template in, mapped schedule out.</p>
                </div>
              </div>

              <div className="mt-6">
                <div className="mb-2 flex items-center justify-between text-xs font-semibold text-slate-300">
                  <span>Generation readiness</span>
                  <span>{readyScore}%</span>
                </div>
                <div className="h-2 overflow-hidden rounded bg-white/10">
                  <div className="h-full rounded bg-emerald-400 transition-all" style={{ width: `${readyScore}%` }} />
                </div>
              </div>
            </div>

            <div className="border border-white/10 bg-white/[0.045] p-5" style={{ borderRadius: 8 }}>
              <div className="mb-4 flex items-center gap-2">
                <FileUp size={18} className="text-cyan-200" />
                <h2 className="text-lg font-semibold">Template</h2>
              </div>
              <label className="flex min-h-[150px] cursor-pointer flex-col items-center justify-center border border-dashed border-cyan-200/35 bg-cyan-300/[0.05] p-5 text-center transition hover:border-cyan-200/70" style={{ borderRadius: 8 }}>
                <input
                  type="file"
                  accept=".doc,.docx"
                  className="hidden"
                  onChange={(event) => setTemplate(event.target.files?.[0] ?? null)}
                />
                <FileUp size={28} className="mb-3 text-cyan-200" />
                <span className="text-sm font-semibold text-white">{template?.name || 'Upload FR.223 DOCX template'}</span>
                <span className="mt-1 text-xs text-slate-400">The schedule table will be filled automatically.</span>
              </label>
            </div>

            <div className="border border-white/10 bg-white/[0.045] p-5" style={{ borderRadius: 8 }}>
              <h2 className="mb-4 text-lg font-semibold">Audit intelligence</h2>
              <div className="space-y-4">
                <div>
                  <label className="mb-2 block text-xs font-semibold uppercase text-slate-400">Audit type</label>
                  <select
                    value={auditType}
                    onChange={(event) => setAuditType(event.target.value)}
                    className="w-full rounded border border-white/10 bg-black/30 px-3 py-2 text-sm text-white outline-none focus:border-emerald-300"
                  >
                    {AUDIT_TYPES.map((type) => <option key={type}>{type}</option>)}
                  </select>
                </div>
                <div className="grid gap-3 sm:grid-cols-2">
                  <input
                    value={eaCode}
                    onChange={(event) => setEaCode(event.target.value)}
                    placeholder="EA / IAF code"
                    className="rounded border border-white/10 bg-black/30 px-3 py-2 text-sm text-white outline-none placeholder:text-slate-500 focus:border-emerald-300"
                  />
                  <input
                    value={category}
                    onChange={(event) => setCategory(event.target.value)}
                    placeholder="Category / technical area"
                    className="rounded border border-white/10 bg-black/30 px-3 py-2 text-sm text-white outline-none placeholder:text-slate-500 focus:border-emerald-300"
                  />
                </div>
                <textarea
                  value={scope}
                  onChange={(event) => setScope(event.target.value)}
                  placeholder="Scope/process notes for smarter clause mapping"
                  rows={4}
                  className="w-full rounded border border-white/10 bg-black/30 px-3 py-2 text-sm text-white outline-none placeholder:text-slate-500 focus:border-emerald-300"
                />
              </div>
            </div>
          </section>

          <section className="space-y-5">
            <div className="border border-white/10 bg-white/[0.045] p-5" style={{ borderRadius: 8 }}>
              <div className="mb-4 flex items-center justify-between gap-3">
                <div>
                  <h2 className="text-lg font-semibold">Standards</h2>
                  <p className="mt-1 text-sm text-slate-400">Integrated audits are mapped across selected standards.</p>
                </div>
                <Sparkles size={20} className="text-amber-200" />
              </div>
              <div className="grid gap-2 sm:grid-cols-2 lg:grid-cols-4">
                {STANDARD_OPTIONS.map((standard) => {
                  const active = standards.includes(standard)
                  return (
                    <button
                      key={standard}
                      type="button"
                      onClick={() => setStandards((current) => toggleValue(current, standard))}
                      className={[
                        'rounded border px-3 py-2 text-left text-sm font-semibold transition',
                        active
                          ? 'border-emerald-300 bg-emerald-400/15 text-emerald-100'
                          : 'border-white/10 bg-black/20 text-slate-300 hover:border-white/25',
                      ].join(' ')}
                    >
                      {standard}
                    </button>
                  )
                })}
              </div>
            </div>

            <div className="border border-white/10 bg-white/[0.045] p-5" style={{ borderRadius: 8 }}>
              <h2 className="mb-4 text-lg font-semibold">Template overrides</h2>
              <div className="grid gap-3 md:grid-cols-2">
                <input
                  value={orgName}
                  onChange={(event) => setOrgName(event.target.value)}
                  placeholder="Organisation name override"
                  className="rounded border border-white/10 bg-black/30 px-3 py-2 text-sm text-white outline-none placeholder:text-slate-500 focus:border-cyan-300"
                />
                <input
                  value={address}
                  onChange={(event) => setAddress(event.target.value)}
                  placeholder="HQ address override"
                  className="rounded border border-white/10 bg-black/30 px-3 py-2 text-sm text-white outline-none placeholder:text-slate-500 focus:border-cyan-300"
                />
              </div>
            </div>

            <div className="border border-white/10 bg-white/[0.045] p-5" style={{ borderRadius: 8 }}>
              <div className="mb-4 flex items-center justify-between gap-3">
                <div>
                  <h2 className="text-lg font-semibold">Day map</h2>
                  <p className="mt-1 text-sm text-slate-400">The AI must build inside these exact windows.</p>
                </div>
                <button
                  type="button"
                  onClick={() => setDays((current) => [...current, emptyDay()])}
                  className="inline-flex items-center gap-2 rounded bg-emerald-500 px-3 py-2 text-sm font-semibold text-white hover:bg-emerald-400"
                >
                  <Plus size={16} />
                  Add day
                </button>
              </div>

              <div className="space-y-3">
                {days.map((day, index) => (
                  <div key={index} className="border border-white/10 bg-black/20 p-4" style={{ borderRadius: 8 }}>
                    <div className="mb-3 flex items-center justify-between">
                      <div className="inline-flex items-center gap-2 text-sm font-semibold text-white">
                        <CalendarPlus size={16} className="text-emerald-200" />
                        Day {index + 1}
                      </div>
                      <button
                        type="button"
                        onClick={() => removeDay(index)}
                        disabled={days.length === 1}
                        className="rounded p-2 text-slate-400 hover:bg-white/10 hover:text-red-200 disabled:cursor-not-allowed disabled:opacity-30"
                        aria-label={`Remove day ${index + 1}`}
                      >
                        <Trash2 size={16} />
                      </button>
                    </div>
                    <div className="grid gap-3 md:grid-cols-5">
                      <input
                        type="date"
                        value={day.date}
                        onChange={(event) => updateDay(index, { date: event.target.value })}
                        className="rounded border border-white/10 bg-black/30 px-3 py-2 text-sm text-white outline-none focus:border-emerald-300"
                      />
                      <input
                        type="time"
                        value={day.start_time}
                        onChange={(event) => updateDay(index, { start_time: event.target.value })}
                        className="rounded border border-white/10 bg-black/30 px-3 py-2 text-sm text-white outline-none focus:border-emerald-300"
                      />
                      <input
                        type="time"
                        value={day.end_time}
                        onChange={(event) => updateDay(index, { end_time: event.target.value })}
                        className="rounded border border-white/10 bg-black/30 px-3 py-2 text-sm text-white outline-none focus:border-emerald-300"
                      />
                      <input
                        type="time"
                        value={day.lunch_start}
                        onChange={(event) => updateDay(index, { lunch_start: event.target.value })}
                        className="rounded border border-white/10 bg-black/30 px-3 py-2 text-sm text-white outline-none focus:border-amber-300"
                      />
                      <input
                        type="time"
                        value={day.lunch_end}
                        onChange={(event) => updateDay(index, { lunch_end: event.target.value })}
                        className="rounded border border-white/10 bg-black/30 px-3 py-2 text-sm text-white outline-none focus:border-amber-300"
                      />
                    </div>
                    <input
                      value={day.site}
                      onChange={(event) => updateDay(index, { site: event.target.value })}
                      placeholder="Site for this day"
                      className="mt-3 w-full rounded border border-white/10 bg-black/30 px-3 py-2 text-sm text-white outline-none placeholder:text-slate-500 focus:border-cyan-300"
                    />
                  </div>
                ))}
              </div>
            </div>

            {(error || successName) && (
              <div
                className="border p-4 text-sm"
                style={{
                  borderRadius: 8,
                  borderColor: error ? 'rgba(248,113,113,0.35)' : 'rgba(52,211,153,0.35)',
                  background: error ? 'rgba(127,29,29,0.18)' : 'rgba(6,78,59,0.2)',
                  color: error ? '#FCA5A5' : '#A7F3D0',
                }}
              >
                {error || `Generated and downloaded: ${successName}`}
              </div>
            )}

            <button
              type="button"
              onClick={submit}
              disabled={loading}
              className="flex w-full items-center justify-center gap-3 rounded bg-emerald-500 px-5 py-4 text-base font-semibold text-white shadow-xl shadow-emerald-950/40 transition hover:bg-emerald-400 disabled:cursor-wait disabled:opacity-70"
            >
              {loading ? <Loader2 size={20} className="animate-spin" /> : <Download size={20} />}
              {loading ? 'Generating FR.223 map' : 'Generate filled audit plan'}
            </button>
          </section>
        </div>
      </div>
    </div>
  )
}
