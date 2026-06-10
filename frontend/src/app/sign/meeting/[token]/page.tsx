'use client'

import { useEffect, useState, useCallback } from 'react'
import { useParams } from 'next/navigation'

const API_BASE = process.env.NEXT_PUBLIC_API_URL || ''

interface SigningInfo {
  full_name:         string
  title:             string | null
  company_name:      string
  stage_label:       string
  opening_signed:    boolean
  opening_signed_at: string | null
  closing_signed:    boolean
  closing_signed_at: string | null
  token_expires_at:  string | null
}

function fmtDate(iso: string | null) {
  if (!iso) return ''
  return new Date(iso).toLocaleString('en-GB', {
    day: 'numeric', month: 'short', year: 'numeric', hour: '2-digit', minute: '2-digit',
  })
}

type EventType = 'opening' | 'closing'

function EventCard({
  type, label, signed, signedAt, token, onSigned,
}: {
  type:     EventType
  label:    string
  signed:   boolean
  signedAt: string | null
  token:    string
  onSigned: () => void
}) {
  const [step, setStep]   = useState<'idle' | 'sending' | 'otp' | 'verifying' | 'done'>('idle')
  const [otp, setOtp]     = useState('')
  const [error, setError] = useState('')

  if (signed) {
    return (
      <div className="rounded-xl border border-green-200 bg-green-50 p-5">
        <p className="font-semibold text-green-700">{label} ✓</p>
        <p className="mt-1 text-xs text-green-600">Signed {fmtDate(signedAt)}</p>
      </div>
    )
  }

  async function requestOtp() {
    setStep('sending')
    setError('')
    try {
      const r = await fetch(`${API_BASE}/sign/meeting/${token}/request-otp?event_type=${type}`, {
        method: 'POST',
      })
      if (!r.ok) {
        const d = await r.json()
        throw new Error(d.detail || 'Failed to send code')
      }
      setStep('otp')
    } catch (e: unknown) {
      setError((e as Error).message || 'Failed to send code')
      setStep('idle')
    }
  }

  async function verifyOtp() {
    setStep('verifying')
    setError('')
    try {
      const r = await fetch(
        `${API_BASE}/sign/meeting/${token}/verify?event_type=${type}&otp=${encodeURIComponent(otp)}`,
        { method: 'POST' },
      )
      if (!r.ok) {
        const d = await r.json()
        throw new Error(d.detail || 'Invalid code')
      }
      setStep('done')
      onSigned()
    } catch (e: unknown) {
      setError((e as Error).message || 'Verification failed')
      setStep('otp')
    }
  }

  return (
    <div className="rounded-xl border bg-white p-5">
      <p className="font-semibold text-gray-800">{label}</p>
      <p className="mt-0.5 text-xs text-gray-400">Not yet signed</p>

      {step === 'idle' && (
        <button
          type="button"
          onClick={requestOtp}
          className="mt-4 rounded-lg bg-[#1A4731] px-5 py-2.5 text-sm font-medium text-white hover:bg-[#143828]"
        >
          Sign {label}
        </button>
      )}

      {step === 'sending' && (
        <p className="mt-4 text-sm text-gray-400">Sending code to your email…</p>
      )}

      {step === 'otp' && (
        <div className="mt-4 space-y-3">
          <p className="text-sm text-gray-600">
            A 6-digit code has been sent to your email address. Enter it below:
          </p>
          <input
            className="w-40 rounded-lg border px-3 py-2 text-center font-mono text-xl tracking-widest focus:outline-none focus:ring-2 focus:ring-[#1A4731]/30"
            placeholder="000000"
            maxLength={6}
            value={otp}
            onChange={e => setOtp(e.target.value.replace(/\D/g, ''))}
          />
          <div className="flex items-center gap-3">
            <button
              type="button"
              onClick={verifyOtp}
              disabled={otp.length !== 6}
              className="rounded-lg bg-[#1A4731] px-5 py-2 text-sm font-medium text-white disabled:opacity-40"
            >
              Confirm Signature
            </button>
            <button
              type="button"
              onClick={requestOtp}
              className="text-sm text-gray-400 underline"
            >
              Resend code
            </button>
          </div>
        </div>
      )}

      {step === 'verifying' && (
        <p className="mt-4 text-sm text-gray-400">Verifying…</p>
      )}

      {step === 'done' && (
        <p className="mt-4 text-sm font-medium text-green-600">Signed ✓</p>
      )}

      {error && <p className="mt-2 text-xs text-red-500">{error}</p>}
    </div>
  )
}

export default function MeetingSigningPage() {
  const { token } = useParams<{ token: string }>()
  const [info, setInfo]     = useState<SigningInfo | null>(null)
  const [status, setStatus] = useState<'loading' | 'ready' | 'error' | 'expired'>('loading')
  const [errMsg, setErrMsg] = useState('')

  const load = useCallback(async () => {
    try {
      const r = await fetch(`${API_BASE}/sign/meeting/${token}`)
      if (r.status === 410) {
        setStatus('expired')
        return
      }
      if (!r.ok) {
        const d = await r.json().catch(() => ({}))
        throw new Error(d.detail || 'Link not found')
      }
      const data: SigningInfo = await r.json()
      setInfo(data)
      setStatus('ready')
    } catch (e: unknown) {
      setErrMsg((e as Error).message || 'An error occurred')
      setStatus('error')
    }
  }, [token])

  useEffect(() => { load() }, [load])

  if (status === 'loading') {
    return (
      <main className="flex min-h-screen items-center justify-center bg-gray-50">
        <p className="text-sm text-gray-400">Loading…</p>
      </main>
    )
  }

  if (status === 'expired') {
    return (
      <main className="flex min-h-screen items-center justify-center bg-gray-50 p-6">
        <div className="max-w-md rounded-2xl bg-white p-8 text-center shadow-sm">
          <p className="text-2xl">⏰</p>
          <h1 className="mt-3 text-xl font-bold text-gray-800">Link Expired</h1>
          <p className="mt-2 text-sm text-gray-500">
            This signing link has expired. Please contact IFC Global LLC for a new link.
          </p>
          <p className="mt-4 text-xs text-gray-400">application@ifcglobal.us</p>
        </div>
      </main>
    )
  }

  if (status === 'error' || !info) {
    return (
      <main className="flex min-h-screen items-center justify-center bg-gray-50 p-6">
        <div className="max-w-md rounded-2xl bg-white p-8 text-center shadow-sm">
          <h1 className="text-xl font-bold text-gray-800">Link Not Found</h1>
          <p className="mt-2 text-sm text-gray-500">{errMsg || 'This signing link is invalid.'}</p>
        </div>
      </main>
    )
  }

  const bothSigned = info.opening_signed && info.closing_signed

  return (
    <main className="min-h-screen bg-gray-50 p-6">
      <div className="mx-auto max-w-md">
        <div className="mb-6 text-center">
          <div
            className="mx-auto mb-3 flex h-12 w-12 items-center justify-center rounded-full"
            style={{ background: '#1A4731' }}
          >
            <span className="text-2xl text-white">✓</span>
          </div>
          <h1 className="text-xl font-bold text-gray-900">Audit Meeting Attendance</h1>
          <p className="mt-1 text-sm text-gray-500">{info.company_name}</p>
          <p className="text-xs text-gray-400">{info.stage_label}</p>
        </div>

        <div className="mb-5 rounded-xl border bg-white p-4 text-center">
          <p className="font-semibold text-gray-800">{info.full_name}</p>
          {info.title && <p className="text-xs text-gray-400">{info.title}</p>}
        </div>

        {bothSigned ? (
          <div className="rounded-xl border border-green-200 bg-green-50 p-6 text-center">
            <p className="text-2xl">🎉</p>
            <p className="mt-2 font-semibold text-green-700">All signatures complete</p>
            <p className="mt-1 text-xs text-green-600">
              Opening: {fmtDate(info.opening_signed_at)}<br />
              Closing: {fmtDate(info.closing_signed_at)}
            </p>
          </div>
        ) : (
          <div className="space-y-3">
            <EventCard
              type="opening"
              label="Opening Meeting"
              signed={info.opening_signed}
              signedAt={info.opening_signed_at}
              token={token}
              onSigned={load}
            />
            <EventCard
              type="closing"
              label="Closing Meeting"
              signed={info.closing_signed}
              signedAt={info.closing_signed_at}
              token={token}
              onSigned={load}
            />
            <p className="text-center text-xs text-gray-400">
              Each signature requires a one-time code sent to your email.
            </p>
          </div>
        )}

        <p className="mt-6 text-center text-xs text-gray-300">
          IFC Global LLC · Powered by Certiva
        </p>
      </div>
    </main>
  )
}
