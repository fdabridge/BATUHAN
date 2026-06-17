# AUGMENT PROMPT — Portal 47c: Dashboard Sign Button Uses sign-direct for FR218/FR222

## Problem

`frontend/src/components/ui/PendingSignaturesWidget.tsx`

When a CB user clicks "Sign" on the dashboard for an FR218 or FR222 slot, the widget
falls into the OTP branch (`requestOtp` → `/request-otp`). FR218/FR222 slots have no
OTP path — they use `sign-direct`. The result is "Not Found" and the CM/planner
can never sign from the dashboard.

`quotation` and `agreement` types correctly route to the viewer. Everything else
falls to OTP. FR218/FR222 need a third branch: `sign-direct` with the same
signature-preview modal that `InternalApprovalsSection` uses.

---

## Fix — `frontend/src/components/ui/PendingSignaturesWidget.tsx`

Replace the entire file with the version below. Changes:
- Add `sigPreviewSlot`, `sigPreviewImage`, `signedDate` state
- Internal document types (`FR218`, `FR222`) → fetch `/me/signature` → show
  preview modal → call `sign-direct`. No OTP.
- `quotation` / `agreement` → Open to Sign (unchanged).
- Anything else → OTP (unchanged, for future use).

```tsx
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
  document_id: string | null
  signer_role_label: string
}

const INTERNAL_TYPES = new Set(['FR218', 'FR222'])

export function PendingSignaturesWidget() {
  const [sigs, setSigs]                     = useState<PendingSig[]>([])
  const [loading, setLoading]               = useState(true)
  const [busy, setBusy]                     = useState(false)

  // OTP flow (non-internal, non-viewer docs)
  const [otpSigningId, setOtpSigningId]     = useState<string | null>(null)
  const [otpSent, setOtpSent]               = useState(false)
  const [otpValue, setOtpValue]             = useState('')

  // sign-direct flow (FR218, FR222)
  const [sigPreviewSlot, setSigPreviewSlot] = useState<PendingSig | null>(null)
  const [sigPreviewImage, setSigPreviewImage] = useState<string | null>(null)
  const [signedDate, setSignedDate]         = useState(() => new Date().toISOString().slice(0, 10))

  const [error, setError] = useState('')

  async function load() {
    try {
      const r = await api.get<PendingSig[]>('/audit-sets/my-pending-signatures')
      setSigs(r.data)
    } catch {
      // Not CB user — fail silently
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => { load() }, [])

  // ── sign-direct flow ──────────────────────────────────────────────────────

  async function openDirectSign(sig: PendingSig) {
    setError('')
    setBusy(true)
    setSigPreviewSlot(null)
    setSigPreviewImage(null)
    try {
      const r = await api.get('/me/signature')
      if (r.data?.image_data) {
        setSigPreviewImage(r.data.image_data)
      }
      setSigPreviewSlot(sig)
    } catch {
      setSigPreviewSlot(sig)
    } finally {
      setBusy(false)
    }
  }

  async function confirmDirectSign() {
    const slot = sigPreviewSlot
    setSigPreviewSlot(null)
    setSigPreviewImage(null)
    if (!slot) return
    setBusy(true)
    setError('')
    try {
      await api.post(
        `/audit-sets/${slot.audit_set_id}/signatures/${slot.id}/sign-direct`,
        { signed_date: signedDate || new Date().toISOString().slice(0, 10) },
      )
      await load()
    } catch (e: unknown) {
      const detail = (e as { response?: { data?: { detail?: string } } })?.response?.data?.detail
      setError(detail || 'Failed to sign. Please try again.')
    } finally {
      setBusy(false)
    }
  }

  // ── OTP flow (kept for future doc types) ─────────────────────────────────

  async function requestOtp(sig: PendingSig) {
    setOtpSigningId(sig.id)
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
      setOtpSigningId(null)
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
    <>
      <div className="rounded-lg border border-amber-200 bg-amber-50 p-5">
        <h2 className="mb-3 text-sm font-semibold text-amber-900">
          ✍ Pending Signatures ({sigs.length})
        </h2>
        <div className="space-y-3">
          {sigs.map((sig) => {
            const isInternal = INTERNAL_TYPES.has(sig.document_type)
            const isViewer   = sig.document_type === 'quotation' || sig.document_type === 'agreement'
            const isOtpSigning = otpSigningId === sig.id

            return (
              <div key={sig.id} className="rounded-lg border border-amber-100 bg-white p-4">
                <div className="flex items-center justify-between">
                  <div>
                    <p className="text-sm font-medium text-gray-900">{sig.document_label}</p>
                    <p className="mt-0.5 text-xs text-gray-400">
                      {sig.plan_number ? `#${sig.plan_number} · ` : ''}{sig.company_name}
                    </p>
                  </div>

                  {/* ── Viewer (quotation / agreement) ── */}
                  {isViewer && sig.document_id && (
                    <a
                      href={`/viewer/shared_doc/${sig.document_id}`}
                      className="rounded-lg bg-[#1A4731] px-3 py-1.5 text-xs font-medium text-white hover:bg-[#143828]"
                    >
                      Open to Sign
                    </a>
                  )}

                  {/* ── sign-direct (FR218, FR222) ── */}
                  {isInternal && !isOtpSigning && (
                    <button
                      type="button"
                      onClick={() => openDirectSign(sig)}
                      disabled={busy}
                      className="rounded-lg bg-[#1A4731] px-3 py-1.5 text-xs font-medium text-white disabled:opacity-40"
                    >
                      Sign
                    </button>
                  )}

                  {/* ── OTP (everything else) ── */}
                  {!isInternal && !isViewer && !isOtpSigning && (
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

                {/* OTP entry panel */}
                {isOtpSigning && (
                  <div className="mt-3 rounded-lg border bg-gray-50 p-3">
                    {!otpSent ? (
                      <p className="text-xs text-gray-500">
                        {busy ? 'Sending code…' : 'Sending a 6-digit code to your email…'}
                      </p>
                    ) : (
                      <div className="flex items-center gap-2">
                        <input
                          className="w-32 rounded border px-2 py-1.5 text-center font-mono text-sm tracking-widest"
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
                          onClick={() => { setOtpSigningId(null); setOtpSent(false); setOtpValue('') }}
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
            )
          })}
        </div>
      </div>

      {/* sign-direct confirmation modal */}
      {sigPreviewSlot && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/50 p-4">
          <div className="w-full max-w-sm overflow-hidden rounded-xl bg-white shadow-2xl">
            <div className="flex items-center justify-between border-b px-5 py-4">
              <p className="text-sm font-semibold text-gray-900">
                Confirm signature — {sigPreviewSlot.document_label}
              </p>
              <button
                type="button"
                onClick={() => { setSigPreviewSlot(null); setSigPreviewImage(null) }}
                className="text-gray-400 hover:text-gray-600"
              >✕</button>
            </div>
            <div className="px-5 py-4 space-y-4">
              <p className="text-sm text-gray-600">
                Your saved signature will be recorded for{' '}
                <strong>{sigPreviewSlot.company_name}</strong>.
                Click <strong>Sign</strong> to confirm.
              </p>
              <div>
                <label className="mb-1 block text-xs font-medium text-gray-600">Signing date</label>
                <input
                  type="date"
                  value={signedDate}
                  onChange={(e) => setSignedDate(e.target.value)}
                  className="rounded border border-gray-200 px-2 py-1 text-sm text-gray-700 focus:border-[#1A4731] focus:outline-none"
                />
              </div>
              {sigPreviewImage ? (
                <div
                  className="flex items-center justify-center rounded-lg p-4"
                  style={{
                    background: 'repeating-conic-gradient(#e5e7eb 0% 25%, #fff 0% 50%) 0 0 / 12px 12px',
                    minHeight: 80,
                  }}
                >
                  <img src={sigPreviewImage} alt="Your signature" className="max-h-16 max-w-full object-contain" />
                </div>
              ) : (
                <p className="text-xs text-gray-400 italic">
                  No signature image on file.{' '}
                  <a href="/settings/signature" target="_blank" className="underline text-[#1A4731]">
                    Add signature →
                  </a>
                </p>
              )}
              {error && <p className="text-xs text-red-500">{error}</p>}
              <button
                type="button"
                onClick={confirmDirectSign}
                disabled={busy}
                className="w-full rounded-lg bg-[#1A4731] py-2.5 text-sm font-medium text-white hover:bg-[#1A4731]/90 disabled:opacity-40"
              >
                {busy ? 'Signing…' : 'Sign'}
              </button>
              <button
                type="button"
                onClick={() => { setSigPreviewSlot(null); setSigPreviewImage(null) }}
                className="w-full text-sm text-gray-500 hover:text-gray-700"
              >
                Cancel
              </button>
            </div>
          </div>
        </div>
      )}
    </>
  )
}
```

---

## What NOT to change

- Do not touch `InternalApprovalsSection.tsx` — it already works correctly.
- Do not touch `signatures_router.py` — backend is correct after Portal 47b.
- Do not touch any other file.

---

## Verification

1. Log in as **Certification Manager** → Dashboard shows "Pending Signatures (1) — Fr218"
2. Click **Sign** → signature preview modal opens (no OTP, no "Not Found")
3. Confirm date → click Sign → ✓ slot signed
4. After planner also signs → workflow auto-advances to `fr218_complete`
