'use client'

import { useEffect, useState } from 'react'
import api from '@/lib/api'

interface NCForm {
  id:               string
  stage_type:       string
  label:            string
  file_name:        string | null
  status:           string
  la_signed_at:     string | null
  client_signed_at: string | null
}

const STAGE_LABELS: Record<string, string> = {
  stage_1: 'Stage 1', stage_2: 'Stage 2',
  surveillance: 'Surveillance', recertification: 'Recertification',
}

function fmtDate(iso: string | null) {
  if (!iso) return ''
  return new Date(iso).toLocaleDateString('en-GB', {
    day: 'numeric', month: 'short', year: 'numeric',
  })
}

const todayStr = () => new Date().toISOString().slice(0, 10)

export function NCFormClientSection() {
  const [forms, setForms]     = useState<NCForm[]>([])
  const [loading, setLoading] = useState(true)
  const [signing, setSigning] = useState<Record<string, boolean>>({})
  const [signErrs, setSignErrs] = useState<Record<string, string>>({})
  const [signDates, setSignDates] = useState<Record<string, string>>({})

  async function load() {
    try {
      const r = await api.get<NCForm[]>('/client/my-audit-set/nc-forms')
      setForms(r.data)
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => { load() }, [])

  async function download(id: string, fileName: string | null) {
    const r = await api.get(`/client/my-audit-set/nc-forms/${id}/download`, {
      responseType: 'blob',
    })
    const url = window.URL.createObjectURL(new Blob([r.data]))
    const a   = document.createElement('a')
    a.href = url; a.download = fileName || 'nc_form.docx'
    document.body.appendChild(a); a.click(); a.remove()
    window.URL.revokeObjectURL(url)
  }

  async function handleSign(id: string) {
    setSigning(s => ({ ...s, [id]: true }))
    setSignErrs(e => ({ ...e, [id]: '' }))
    try {
      const signed_date = signDates[id] || todayStr()
      await api.post(`/client/my-audit-set/nc-forms/${id}/sign/direct`, { signed_date })
      setForms(prev => prev.map(f => f.id === id
        ? { ...f, status: 'complete', client_signed_at: new Date().toISOString() }
        : f
      ))
    } catch (err: unknown) {
      const detail = (err as { response?: { data?: { detail?: string } } })?.response?.data?.detail
      setSignErrs(e => ({ ...e, [id]: detail || 'Signing failed' }))
    } finally {
      setSigning(s => ({ ...s, [id]: false }))
    }
  }

  if (loading) return null
  if (forms.length === 0) return null

  return (
    <div className="mt-8">
      <h2 className="mb-3 text-base font-semibold text-gray-900">
        Nonconformity Forms (FR.230)
      </h2>
      <div className="space-y-3">
        {forms.map(f => (
          <NCFormRow
            key={f.id}
            f={f}
            signing={!!signing[f.id]}
            signErr={signErrs[f.id] || ''}
            signDate={signDates[f.id] || todayStr()}
            onSignDateChange={d => setSignDates(prev => ({ ...prev, [f.id]: d }))}
            onDownload={() => download(f.id, f.file_name)}
            onSign={() => handleSign(f.id)}
          />
        ))}
      </div>
    </div>
  )
}

interface NCFormRowProps {
  f:              NCForm
  signing:        boolean
  signErr:        string
  signDate:       string
  onSignDateChange: (d: string) => void
  onDownload:     () => void
  onSign:         () => void
}

function NCFormRow({ f, signing, signErr, signDate, onSignDateChange, onDownload, onSign }: NCFormRowProps) {
  const isSigned = f.status === 'complete'

  if (isSigned) {
    return (
      <div className="flex items-center justify-between rounded-xl border border-green-200 bg-green-50 px-4 py-3">
        <div>
          <p className="font-medium text-gray-800">{f.label}</p>
          <p className="mt-0.5 text-xs text-gray-400">
            {STAGE_LABELS[f.stage_type] ?? f.stage_type} · Signed {fmtDate(f.client_signed_at)}
          </p>
        </div>
        <div className="flex items-center gap-3">
          <span className="rounded-full bg-green-100 px-2.5 py-0.5 text-xs font-semibold text-green-700">
            ✓ Signed
          </span>
          <button type="button" onClick={onDownload} className="text-xs text-[#1A4731] underline">
            Download
          </button>
        </div>
      </div>
    )
  }

  return (
    <div className="rounded-xl border bg-white p-4">
      <div className="mb-3 flex items-start justify-between">
        <div>
          <p className="font-medium text-gray-800">{f.label}</p>
          <p className="mt-0.5 text-xs text-gray-500">
            {STAGE_LABELS[f.stage_type] ?? f.stage_type}
            {f.la_signed_at && ` · Auditor signed ${fmtDate(f.la_signed_at)}`}
          </p>
        </div>
        <button type="button" onClick={onDownload} className="text-xs text-[#1A4731] underline">
          Download
        </button>
      </div>

      <div className="flex items-center gap-3">
        <div>
          <label className="block text-xs text-gray-500 mb-1">Signing date</label>
          <input
            type="date"
            value={signDate}
            onChange={e => onSignDateChange(e.target.value)}
            className="rounded-lg border px-2 py-1 text-sm"
          />
        </div>
        <button
          type="button"
          onClick={onSign}
          disabled={signing}
          className="self-end rounded-lg bg-[#1A4731] px-4 py-2 text-sm text-white disabled:opacity-40 hover:bg-[#143828]"
        >
          {signing ? 'Signing…' : 'Sign NC Form'}
        </button>
      </div>

      {signErr && (
        <p className="mt-1 text-xs text-red-500">{signErr}</p>
      )}
    </div>
  )
}
