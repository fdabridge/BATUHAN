'use client'

import { useEffect, useState } from 'react'
import api from '@/lib/api'

interface PendingSig {
  id: string
  audit_set_id: string
  plan_number: number | null
  company_name: string
  document_label: string
  document_type: string
}

export function PendingSignaturesWidget() {
  const [sigs, setSigs]           = useState<PendingSig[]>([])
  const [loading, setLoading]     = useState(true)
  const [signingId, setSigningId] = useState<string | null>(null)
  const [otpSent, setOtpSent]     = useState(false)
  const [otpValue, setOtpValue]   = useState('')
  const [error, setError]         = useState('')
  const [busy, setBusy]           = useState(false)

  async function load() {
    try {
      const r = await api.get<PendingSig[]>('/audit-sets/my-pending-signatures')
      setSigs(r.data)
    } catch {
      // Not CB user or network error — fail silently
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => { load() }, [])

  async function requestOtp(sig: PendingSig) {
    setSigningId(sig.id)
    setOtpSent(false)
    setError('')
    setBusy(true)
    try {
      await api.post(`/audit-sets/${sig.audit_set_id}/signatures/${sig.id}/request-otp`)
      setOtpSent(true)
    } catch (e: unknown) {
      const detail = (e as { response?: { data?: { detail?: string } } })?.response?.data?.detail
      setError(detail || 'Failed to send code')
    } finally {
      setBusy(false)
    }
  }

  async function verifyOtp(sig: PendingSig) {
    setBusy(true)
    setError('')
    try {
      await api.post(
        `/audit-sets/${sig.audit_set_id}/signatures/${sig.id}/verify?otp=${otpValue}`,
      )
      setSigningId(null)
      setOtpValue('')
      setOtpSent(false)
      await load()
    } catch (e: unknown) {
      const detail = (e as { response?: { data?: { detail?: string } } })?.response?.data?.detail
      setError(detail || 'Invalid code')
    } finally {
      setBusy(false)
    }
  }

  if (loading || sigs.length === 0) return null

  return (
    <div className="rounded-lg border border-amber-200 bg-amber-50 p-5">
      <h2 className="mb-3 text-sm font-semibold text-amber-900">
        ✍ Pending Signatures ({sigs.length})
      </h2>
      <div className="space-y-3">
        {sigs.map((sig) => (
          <div key={sig.id} className="rounded-lg border border-amber-100 bg-white p-4">
            <div className="flex items-center justify-between">
              <div>
                <p className="text-sm font-medium text-gray-900">{sig.document_label}</p>
                <p className="mt-0.5 text-xs text-gray-400">
                  {sig.plan_number ? `#${sig.plan_number} · ` : ''}{sig.company_name}
                </p>
              </div>
              {signingId !== sig.id && (
                <button
                  type="button"
                  onClick={() => requestOtp(sig)}
                  disabled={busy}
                  className="rounded-lg bg-[#1A4731] px-3 py-1.5 text-xs font-medium text-white disabled:opacity-40"
                >
                  Sign
                </button>
              )}
            </div>

            {signingId === sig.id && (
              <div className="mt-3 rounded-lg border bg-gray-50 p-3">
                {!otpSent ? (
                  <p className="text-xs text-gray-500">
                    {busy ? 'Sending code…' : 'Sending a 6-digit code to your email…'}
                  </p>
                ) : (
                  <div className="flex items-center gap-2">
                    <input
                      className="w-32 rounded border px-2 py-1.5 text-center font-mono text-sm tracking-widest focus:outline-none focus:ring-2 focus:ring-[#1A4731]/30"
                      placeholder="000000"
                      maxLength={6}
                      value={otpValue}
                      onChange={(e) => setOtpValue(e.target.value.replace(/\D/g, ''))}
                    />
                    <button
                      type="button"
                      onClick={() => verifyOtp(sig)}
                      disabled={otpValue.length !== 6 || busy}
                      className="rounded bg-[#1A4731] px-3 py-1.5 text-xs text-white disabled:opacity-40"
                    >
                      {busy ? '…' : 'Confirm'}
                    </button>
                    <button
                      type="button"
                      onClick={() => { setSigningId(null); setOtpSent(false); setOtpValue('') }}
                      className="text-xs text-gray-400"
                    >
                      Cancel
                    </button>
                    <button
                      type="button"
                      onClick={() => requestOtp(sig)}
                      className="text-xs text-gray-400 underline"
                    >
                      Resend
                    </button>
                  </div>
                )}
                {error && <p className="mt-1 text-xs text-red-500">{error}</p>}
              </div>
            )}
          </div>
        ))}
      </div>
    </div>
  )
}
