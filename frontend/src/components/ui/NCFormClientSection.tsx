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

export function NCFormClientSection() {
  const [forms, setForms]   = useState<NCForm[]>([])
  const [loading, setLoading] = useState(true)
  const [otpState, setOtpState]   = useState<Record<string, 'idle' | 'otp_sent' | 'done'>>({})
  const [otpValues, setOtpValues] = useState<Record<string, string>>({})
  const [messages, setMessages]   = useState<Record<string, string>>({})
  const [busy, setBusy]           = useState<Record<string, boolean>>({})

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

  async function requestOtp(id: string) {
    setBusy(b => ({ ...b, [id]: true }))
    setMessages(m => ({ ...m, [id]: '' }))
    try {
      await api.post(`/client/my-audit-set/nc-forms/${id}/sign/request-otp`)
      setOtpState(s => ({ ...s, [id]: 'otp_sent' }))
    } catch (err: unknown) {
      const detail = (err as { response?: { data?: { detail?: string } } })?.response?.data?.detail
      setMessages(m => ({ ...m, [id]: detail || 'Failed to send code' }))
    } finally {
      setBusy(b => ({ ...b, [id]: false }))
    }
  }

  async function verifyOtp(id: string) {
    setBusy(b => ({ ...b, [id]: true }))
    setMessages(m => ({ ...m, [id]: '' }))
    try {
      await api.post(`/client/my-audit-set/nc-forms/${id}/sign/verify?otp=${otpValues[id] ?? ''}`)
      setOtpState(s => ({ ...s, [id]: 'done' }))
      setForms(prev => prev.map(f => f.id === id
        ? { ...f, status: 'complete', client_signed_at: new Date().toISOString() }
        : f
      ))
    } catch (err: unknown) {
      const detail = (err as { response?: { data?: { detail?: string } } })?.response?.data?.detail
      setMessages(m => ({ ...m, [id]: detail || 'Invalid code' }))
    } finally {
      setBusy(b => ({ ...b, [id]: false }))
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
            state={otpState[f.id] || 'idle'}
            otpValue={otpValues[f.id] ?? ''}
            busy={!!busy[f.id]}
            message={messages[f.id] || ''}
            onDownload={() => download(f.id, f.file_name)}
            onRequestOtp={() => requestOtp(f.id)}
            onVerifyOtp={() => verifyOtp(f.id)}
            onOtpChange={v => setOtpValues(prev => ({ ...prev, [f.id]: v }))}
          />
        ))}
      </div>
    </div>
  )
}

interface NCFormRowProps {
  f: NCForm
  state: 'idle' | 'otp_sent' | 'done'
  otpValue: string
  busy: boolean
  message: string
  onDownload: () => void
  onRequestOtp: () => void
  onVerifyOtp: () => void
  onOtpChange: (v: string) => void
}

function NCFormRow({
  f, state, otpValue, busy, message,
  onDownload, onRequestOtp, onVerifyOtp, onOtpChange,
}: NCFormRowProps) {
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

      {state === 'idle' && (
        <button
          type="button"
          onClick={onRequestOtp}
          disabled={busy}
          className="rounded-lg bg-[#1A4731] px-4 py-2 text-sm text-white disabled:opacity-40 hover:bg-[#143828]"
        >
          {busy ? 'Sending code…' : 'Sign NC Form'}
        </button>
      )}

      {state === 'otp_sent' && (
        <div className="flex items-center gap-3">
          <input
            className="w-36 rounded-lg border px-3 py-2 text-center font-mono text-lg tracking-widest focus:outline-none focus:ring-2 focus:ring-[#1A4731]/30"
            placeholder="000000" maxLength={6}
            value={otpValue}
            onChange={e => onOtpChange(e.target.value.replace(/\D/g, ''))}
          />
          <button
            type="button"
            onClick={onVerifyOtp}
            disabled={otpValue.length !== 6 || busy}
            className="rounded-lg bg-[#1A4731] px-4 py-2 text-sm text-white disabled:opacity-40"
          >
            {busy ? '…' : 'Confirm Signature'}
          </button>
          <button type="button" onClick={onRequestOtp} className="text-xs text-gray-400 underline">
            Resend
          </button>
        </div>
      )}

      {state === 'done' && (
        <p className="text-sm font-medium text-green-600">NC Form signed ✓</p>
      )}

      {message && (
        <p className="mt-1 text-xs text-red-500">{message}</p>
      )}
    </div>
  )
}
