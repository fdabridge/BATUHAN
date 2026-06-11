'use client'

import { useEffect, useState, useCallback } from 'react'
import api from '@/lib/api'

interface SigSlot {
  id: string
  document_type: 'FR218' | 'FR222'
  signer_role_label: string
  signer_name: string | null
  is_signed: boolean
  signed_at: string | null
  is_mine: boolean
  can_claim: boolean
  pending_appointment: boolean
  required: boolean
  order_index: number
}

const ROLE_LABELS: Record<string, string> = {
  cb_planner:      'Planning Officer',
  cb_cert_manager: 'Certification Manager',
  cb_reviewer:     'Independent Reviewer',
}

const DOC_LABELS: Record<string, string> = {
  FR218: 'FR.218 — Application Review',
  FR222: 'FR.222 — Audit Programme',
}

function fmtDate(iso: string | null) {
  if (!iso) return ''
  return new Date(iso).toLocaleDateString('en-GB', { day: 'numeric', month: 'short', year: 'numeric' })
}

export function InternalApprovalsSection({
  auditSetId,
  workflowStatus,
}: {
  auditSetId: string
  workflowStatus: string | null
}) {
  const [slots, setSlots]         = useState<SigSlot[]>([])
  const [loading, setLoading]     = useState(true)
  const [signingId, setSigningId] = useState<string | null>(null)
  const [otpSent, setOtpSent]     = useState(false)
  const [otpValue, setOtpValue]   = useState('')
  const [error, setError]         = useState('')
  const [busy, setBusy]           = useState(false)
  const [sigPreviewImage, setSigPreviewImage] = useState<string | null>(null)
  const [sigPreviewSlot,  setSigPreviewSlot]  = useState<SigSlot | null>(null)
  const [sigPreviewBusy,  setSigPreviewBusy]  = useState(false)

  const load = useCallback(async () => {
    try {
      const r = await api.get<SigSlot[]>(`/audit-sets/${auditSetId}/internal-signatures`)
      setSlots(r.data)
    } catch {
      // 403 for non-CB users — leave slots empty
    } finally {
      setLoading(false)
    }
  }, [auditSetId])

  useEffect(() => { load() }, [load])

  const showSection = workflowStatus && workflowStatus !== 'pending_review'
  if (!showSection) return null

  const FR222_STAGES = ['audit_scheduled', 'audit_in_progress', 'under_review', 'certified']
  const showFR222 = workflowStatus != null && FR222_STAGES.includes(workflowStatus)

  async function handleSignClick(slot: SigSlot) {
    setSigPreviewBusy(true)
    setSigPreviewSlot(null)
    setSigPreviewImage(null)
    try {
      const r = await api.get('/me/signature')
      if (r.data?.image_data) {
        setSigPreviewImage(r.data.image_data)
        setSigPreviewSlot(slot)
      } else {
        window.open('/settings/signature', '_blank')
      }
    } catch {
      setSigPreviewSlot(slot)
    } finally {
      setSigPreviewBusy(false)
    }
  }

  function handleConfirmSign() {
    const slot = sigPreviewSlot
    setSigPreviewSlot(null)
    setSigPreviewImage(null)
    if (slot) requestOtp(slot)
  }

  async function createFR222() {
    setBusy(true)
    try {
      await api.post(`/audit-sets/${auditSetId}/signatures/create-fr222`)
      await load()
    } catch (e: unknown) {
      const detail = (e as { response?: { data?: { detail?: string } } })?.response?.data?.detail
      alert(detail || 'Failed to create FR.222 signatures')
    } finally {
      setBusy(false)
    }
  }

  async function requestOtp(slot: SigSlot) {
    setSigningId(slot.id)
    setOtpSent(false)
    setError('')
    setBusy(true)
    try {
      await api.post(`/audit-sets/${auditSetId}/signatures/${slot.id}/request-otp`)
      setOtpSent(true)
    } catch (e: unknown) {
      const detail = (e as { response?: { data?: { detail?: string } } })?.response?.data?.detail
      setError(detail || 'Failed to send code')
    } finally {
      setBusy(false)
    }
  }

  async function verifyOtp(slot: SigSlot) {
    setBusy(true)
    setError('')
    try {
      await api.post(`/audit-sets/${auditSetId}/signatures/${slot.id}/verify?otp=${otpValue}`)
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

  const grouped = slots.reduce<Record<string, SigSlot[]>>((acc, s) => {
    acc[s.document_type] = acc[s.document_type] || []
    acc[s.document_type].push(s)
    return acc
  }, {})

  const fr218 = grouped['FR218'] || []
  const fr222 = grouped['FR222'] || []
  const hasFR218 = fr218.length > 0
  const hasFR222 = fr222.length > 0

  // Hide entirely for non-CB users (no slots returned & not loading)
  if (!loading && !hasFR218 && !hasFR222 && workflowStatus === 'pending_review') return null

  const rowProps = {
    signingId, otpSent, otpValue, error, busy: busy || sigPreviewBusy,
    onSign:      handleSignClick,
    onVerify:    verifyOtp,
    onOtpChange: setOtpValue,
    onCancel:    () => { setSigningId(null); setOtpSent(false); setOtpValue('') },
    onResend:    requestOtp,
  }

  return (
    <div className="mt-8">
      <h2 className="mb-3 text-sm font-semibold uppercase tracking-wide text-gray-700">
        Internal Approvals
      </h2>

      <div className="space-y-4">
        <div className="rounded-xl border bg-white p-4">
          <div className="mb-3 flex items-center justify-between">
            <p className="text-sm font-medium text-gray-800">{DOC_LABELS['FR218']}</p>
            {hasFR218 && fr218.every(s => s.is_signed) && (
              <span className="rounded-full bg-green-100 px-2 py-0.5 text-xs font-semibold text-green-700">
                Fully Signed ✓
              </span>
            )}
          </div>
          {loading ? (
            <p className="text-xs text-gray-400">Loading…</p>
          ) : !hasFR218 ? (
            <p className="text-xs text-gray-400">Signature slots pending creation…</p>
          ) : (
            <div className="space-y-2">
              {fr218.map(slot => <SignerRow key={slot.id} slot={slot} {...rowProps} />)}
            </div>
          )}
        </div>

        {showFR222 && (
          <div className="rounded-xl border bg-white p-4">
            <div className="mb-3 flex items-center justify-between">
              <p className="text-sm font-medium text-gray-800">{DOC_LABELS['FR222']}</p>
              {hasFR222 && fr222.every(s => s.is_signed) && (
                <span className="rounded-full bg-green-100 px-2 py-0.5 text-xs font-semibold text-green-700">
                  Fully Signed ✓
                </span>
              )}
            </div>
            {loading ? (
              <p className="text-xs text-gray-400">Loading…</p>
            ) : !hasFR222 ? (
              <div className="flex items-center gap-3">
                <p className="text-xs text-gray-400">Not yet initiated.</p>
                <button
                  type="button"
                  onClick={createFR222}
                  disabled={busy}
                  className="rounded-lg border border-[#1A4731] px-3 py-1.5 text-xs font-medium text-[#1A4731] hover:bg-green-50 disabled:opacity-40"
                >
                  Initiate Audit Programme Signing
                </button>
              </div>
            ) : (
              <div className="space-y-2">
                {fr222.map(slot => <SignerRow key={slot.id} slot={slot} {...rowProps} />)}
              </div>
            )}
          </div>
        )}
      </div>

      {sigPreviewSlot && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/50 p-4">
          <div className="w-full max-w-sm overflow-hidden rounded-xl bg-white shadow-2xl">
            <div className="flex items-center justify-between border-b px-5 py-4">
              <p className="text-sm font-semibold text-gray-900">
                Confirm signature — {ROLE_LABELS[sigPreviewSlot.signer_role_label] ?? sigPreviewSlot.signer_role_label}
              </p>
              <button
                type="button"
                onClick={() => { setSigPreviewSlot(null); setSigPreviewImage(null) }}
                className="text-gray-400 hover:text-gray-600"
              >✕</button>
            </div>
            <div className="px-5 py-4 space-y-4">
              <p className="text-sm text-gray-600">
                Your saved signature will be recorded. Click <strong>Send verification code</strong> to continue.
              </p>
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
                <p className="text-xs text-gray-400 italic">No signature image on file.</p>
              )}
              <button
                type="button"
                onClick={handleConfirmSign}
                className="w-full rounded-lg bg-[#1A4731] py-2.5 text-sm font-medium text-white hover:bg-[#1A4731]/90"
              >
                Send verification code
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
    </div>
  )
}

function SignerRow({
  slot, signingId, otpSent, otpValue, error, busy,
  onSign, onVerify, onOtpChange, onCancel, onResend,
}: {
  slot: SigSlot
  signingId: string | null
  otpSent: boolean
  otpValue: string
  error: string
  busy: boolean
  onSign: (s: SigSlot) => void
  onVerify: (s: SigSlot) => void
  onOtpChange: (v: string) => void
  onCancel: () => void
  onResend: (s: SigSlot) => void
}) {
  const isActive = signingId === slot.id

  return (
    <div className="rounded-lg border border-gray-100 bg-gray-50 p-3">
      <div className="flex items-center justify-between">
        <div>
          <p className="text-xs font-medium text-gray-700">
            {ROLE_LABELS[slot.signer_role_label] ?? slot.signer_role_label}
          </p>
          <p className="mt-0.5 text-xs text-gray-400">
            {slot.is_signed
              ? `✓ Signed by ${slot.signer_name} on ${fmtDate(slot.signed_at)}`
              : slot.pending_appointment
              ? 'Pending committee appointment'
              : slot.signer_name
              ? `Assigned: ${slot.signer_name}`
              : 'Unassigned — eligible users can sign'}
          </p>
        </div>
        <div className="flex items-center gap-2">
          {slot.is_signed ? (
            <span className="rounded-full bg-green-100 px-2 py-0.5 text-xs font-semibold text-green-700">✓</span>
          ) : slot.pending_appointment ? (
            <span className="rounded-full bg-gray-200 px-2 py-0.5 text-xs text-gray-500">Pending</span>
          ) : (slot.is_mine || slot.can_claim) && !isActive ? (
            <button
              type="button"
              onClick={() => onSign(slot)}
              disabled={busy}
              className="rounded bg-[#1A4731] px-2.5 py-1 text-xs text-white disabled:opacity-40"
            >
              Sign
            </button>
          ) : !slot.is_mine && !slot.can_claim && !slot.is_signed ? (
            <span className="rounded-full bg-amber-100 px-2 py-0.5 text-xs text-amber-700">Awaiting</span>
          ) : null}
        </div>
      </div>

      {isActive && (
        <div className="mt-2 rounded border bg-white p-2">
          {!otpSent ? (
            <p className="text-xs text-gray-500">{busy ? 'Sending code…' : 'Sending 6-digit code to your email…'}</p>
          ) : (
            <div className="flex items-center gap-2">
              <input
                className="w-28 rounded border px-2 py-1 text-center font-mono text-sm tracking-widest focus:outline-none focus:ring-2 focus:ring-[#1A4731]/30"
                placeholder="000000"
                maxLength={6}
                value={otpValue}
                onChange={e => onOtpChange(e.target.value.replace(/\D/g, ''))}
              />
              <button
                type="button"
                onClick={() => onVerify(slot)}
                disabled={otpValue.length !== 6 || busy}
                className="rounded bg-[#1A4731] px-2.5 py-1 text-xs text-white disabled:opacity-40"
              >
                {busy ? '…' : 'Confirm'}
              </button>
              <button type="button" onClick={onCancel} className="text-xs text-gray-400">Cancel</button>
              <button type="button" onClick={() => onResend(slot)} className="text-xs text-gray-400 underline">Resend</button>
            </div>
          )}
          {error && <p className="mt-1 text-xs text-red-500">{error}</p>}
        </div>
      )}
    </div>
  )
}
