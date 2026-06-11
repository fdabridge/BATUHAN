'use client'

/**
 * SignatureConfirmDialog — Signs a [SIG:KEY] field via OTP.
 *
 * Flow:
 *   1. Fetches user's saved signature from /me/signature.
 *   2. Shows preview + "Send code" button.
 *   3. User clicks → POST /viewer/sign/request-otp.
 *   4. Shows OTP input + "Confirm signature" button.
 *   5. User enters code → POST /viewer/sign/verify.
 *   6. On success: calls onSigned(sigKey) and auto-closes.
 */

import { useEffect, useRef, useState } from 'react'
import { AlertCircle, CheckCircle2, Loader2, PenLine, X } from 'lucide-react'
import api from '@/lib/api'

type Stage = 'loading' | 'no_signature' | 'preview' | 'otp_sent' | 'verifying' | 'success'

interface Props {
  isOpen:       boolean
  sigKey:       string
  documentType: string
  docId:        string
  onClose:      () => void
  onSigned:     (sigKey: string) => void
}

function getSignatureSettingsUrl(): string {
  if (typeof window === 'undefined') return '/settings/signature'
  const p = window.location.pathname
  if (p.startsWith('/client/'))  return '/client/signature'
  if (p.startsWith('/auditor/')) return '/auditor/signature'
  return '/settings/signature'
}

const SIG_KEY_LABELS: Record<string, string> = {
  CB_PLANNER:      'Planning Officer',
  CB_CERT_MANAGER: 'Certification Manager',
  CB_REVIEWER:     'Committee Reviewer',
  LEAD_AUDITOR:    'Lead Auditor',
  CLIENT:          'Organisation Representative',
  AUDITOR_MEMBER:  'Audit Team Member',
}

export function SignatureConfirmDialog({
  isOpen, sigKey, documentType, docId, onClose, onSigned,
}: Props) {
  const [stage,     setStage]     = useState<Stage>('loading')
  const [sigImage,  setSigImage]  = useState<string | null>(null)
  const [otp,       setOtp]       = useState('')
  const [errorMsg,  setErrorMsg]  = useState('')
  const [statusMsg, setStatusMsg] = useState('')
  const otpRef = useRef<HTMLInputElement>(null)

  useEffect(() => {
    if (!isOpen) return
    setStage('loading')
    setOtp('')
    setErrorMsg('')
    setStatusMsg('')

    api.get('/me/signature')
      .then((r) => {
        if (r.data?.image_data) {
          setSigImage(r.data.image_data)
          setStage('preview')
        } else {
          setSigImage(null)
          setStage('no_signature')
        }
      })
      .catch(() => {
        setSigImage(null)
        setStage('no_signature')
      })
  }, [isOpen, sigKey])

  useEffect(() => {
    if (stage === 'otp_sent') {
      const t = setTimeout(() => otpRef.current?.focus(), 80)
      return () => clearTimeout(t)
    }
  }, [stage])

  async function handleRequestOtp() {
    setErrorMsg('')
    setStatusMsg('Sending verification code…')
    try {
      const r = await api.post('/viewer/sign/request-otp', {
        document_type: documentType,
        doc_id:        docId,
        sig_key:       sigKey,
      })
      setStatusMsg(r.data.message ?? 'Code sent to your email.')
      setStage('otp_sent')
    } catch (e: unknown) {
      const err = e as { response?: { data?: { detail?: string } } }
      setErrorMsg(err.response?.data?.detail ?? 'Failed to send code. Please try again.')
      setStatusMsg('')
    }
  }

  async function handleVerify() {
    if (otp.length !== 6) return
    setStage('verifying')
    setErrorMsg('')
    try {
      await api.post('/viewer/sign/verify', {
        document_type: documentType,
        doc_id:        docId,
        sig_key:       sigKey,
        otp:           otp.trim(),
      })
      setStage('success')
      setTimeout(() => onSigned(sigKey), 1400)
    } catch (e: unknown) {
      const err = e as { response?: { data?: { detail?: string } } }
      setErrorMsg(err.response?.data?.detail ?? 'Invalid code. Please try again.')
      setStage('otp_sent')
    }
  }

  if (!isOpen) return null

  const roleLabel = SIG_KEY_LABELS[sigKey] ?? sigKey
  const busy      = stage === 'verifying'

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/50 p-4">
      <div className="w-full max-w-md overflow-hidden rounded-xl bg-white shadow-2xl">
        {/* Header */}
        <div className="flex items-center justify-between border-b px-6 py-4">
          <div className="flex items-center gap-2.5">
            <PenLine size={17} className="text-[#1A4731]" />
            <h2 className="text-sm font-semibold text-gray-900">Sign as {roleLabel}</h2>
          </div>
          <button type="button" onClick={onClose} disabled={busy}
            className="rounded p-1 text-gray-400 hover:text-gray-600 disabled:opacity-40">
            <X size={17} />
          </button>
        </div>

        {/* Body */}
        <div className="px-6 py-5 space-y-4">

          {stage === 'loading' && (
            <div className="flex items-center justify-center gap-2 py-10 text-sm text-gray-400">
              <Loader2 size={18} className="animate-spin" /> Loading…
            </div>
          )}

          {stage === 'no_signature' && (
            <>
              <p className="text-sm text-gray-600">
                You don&apos;t have a saved signature yet. Go to{' '}
                <strong>Settings → My Signature</strong> to draw or upload your signature, then come back.
              </p>
              <a href={getSignatureSettingsUrl()} target="_blank" rel="noreferrer"
                className="block w-full rounded-lg border-2 border-dashed border-[#1A4731] py-3 text-center
                  text-sm font-medium text-[#1A4731] hover:bg-[#1A4731]/5 transition-colors">
                Set up my signature →
              </a>
              <p className="text-xs text-gray-400 text-center">
                Opens in a new tab. Save your signature, then close this dialog and try again.
              </p>
            </>
          )}

          {stage === 'preview' && (
            <>
              <p className="text-sm text-gray-600">
                Your saved signature will be placed on the document. Click{' '}
                <strong>Send verification code</strong> to proceed.
              </p>
              <div className="flex items-center justify-center rounded-lg p-4" style={{
                background: 'repeating-conic-gradient(#e5e7eb 0% 25%, #fff 0% 50%) 0 0 / 12px 12px',
                minHeight: 90,
              }}>
                {sigImage
                  ? <img src={sigImage} alt="Your signature" className="max-h-20 max-w-full object-contain drop-shadow" />
                  : <span className="text-xs italic text-gray-400">No image preview</span>}
              </div>
              {statusMsg && <p className="text-xs text-[#1A4731]">{statusMsg}</p>}
              {errorMsg && (
                <div className="flex items-start gap-1.5 rounded-lg bg-red-50 p-3 text-sm text-red-600">
                  <AlertCircle size={15} className="mt-0.5 shrink-0" />{errorMsg}
                </div>
              )}
              <button type="button" onClick={handleRequestOtp}
                className="w-full rounded-lg bg-[#1A4731] py-2.5 text-sm font-medium
                  text-white hover:bg-[#1A4731]/90 active:scale-[0.98] transition-all">
                Send verification code
              </button>
            </>
          )}

          {stage === 'otp_sent' && (
            <>
              <p className="text-sm text-gray-600">
                {statusMsg || 'A 6-digit code has been sent to your email address.'}
              </p>
              <input ref={otpRef} type="text" inputMode="numeric" maxLength={6}
                value={otp}
                onChange={(e) => setOtp(e.target.value.replace(/\D/g, '').slice(0, 6))}
                onKeyDown={(e) => e.key === 'Enter' && otp.length === 6 && handleVerify()}
                placeholder="000000"
                className="w-full rounded-lg border border-gray-300 px-4 py-3.5 text-center
                  text-2xl font-mono tracking-[0.5em]
                  focus:border-[#1A4731] focus:outline-none focus:ring-2 focus:ring-[#1A4731]/20"
              />
              {errorMsg && (
                <div className="flex items-start gap-1.5 rounded-lg bg-red-50 p-3 text-sm text-red-600">
                  <AlertCircle size={15} className="mt-0.5 shrink-0" />{errorMsg}
                </div>
              )}
              <button type="button" onClick={handleVerify} disabled={otp.length !== 6}
                className="w-full rounded-lg bg-[#1A4731] py-2.5 text-sm font-medium
                  text-white hover:bg-[#1A4731]/90 disabled:opacity-40 active:scale-[0.98] transition-all">
                Confirm signature
              </button>
              <button type="button"
                onClick={() => { setStage('preview'); setOtp(''); setErrorMsg('') }}
                className="w-full text-sm text-gray-500 hover:text-gray-700">
                ← Back
              </button>
            </>
          )}

          {stage === 'verifying' && (
            <div className="flex items-center justify-center gap-2 py-10 text-sm text-gray-500">
              <Loader2 size={18} className="animate-spin text-[#1A4731]" />
              Verifying signature…
            </div>
          )}

          {stage === 'success' && (
            <div className="flex flex-col items-center gap-3 py-8 text-center">
              <CheckCircle2 size={44} className="text-[#1A4731]" />
              <p className="font-semibold text-gray-800">Signed successfully</p>
              <p className="text-sm text-gray-500">Your signature has been recorded on this document.</p>
            </div>
          )}

        </div>
      </div>
    </div>
  )
}
