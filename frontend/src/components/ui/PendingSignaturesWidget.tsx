'use client'

import { useEffect, useState } from 'react'
import api from '@/lib/api'
import { useManualActionDates } from '@/lib/useManualActionDates'

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

/** Map notification document_type to the viewer URL segment. */
function viewerDocType(documentType: string): 'shared_doc' | 'audit_report' | 'nc_form' {
  if (documentType === 'nc_form') return 'nc_form'
  if (documentType === 'stage1_report' || documentType === 'stage2_report') {
    return 'audit_report'
  }
  return 'shared_doc'
}

interface PendingSignaturesWidgetProps {
  viewerBasePath?: string
}

export function PendingSignaturesWidget({ viewerBasePath = '/viewer' }: PendingSignaturesWidgetProps = {}) {
  const [sigs, setSigs]                       = useState<PendingSig[]>([])
  const [loading, setLoading]                 = useState(true)
  const [busy, setBusy]                       = useState(false)

  const [sigPreviewSlot, setSigPreviewSlot]   = useState<PendingSig | null>(null)
  const [sigPreviewImage, setSigPreviewImage] = useState<string | null>(null)
  const [signedDate, setSignedDate]           = useState(() => new Date().toISOString().slice(0, 10))
  const { manualActionDatesEnabled } = useManualActionDates()

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

  useEffect(() => {
    load()
    const id = setInterval(load, 60_000)
    return () => clearInterval(id)
  }, [])

  async function openDirectSign(sig: PendingSig) {
    setError('')
    setBusy(true)
    setSigPreviewSlot(null)
    setSigPreviewImage(null)
    try {
      const r = await api.get('/me/signature')
      if (r.data?.image_data) setSigPreviewImage(r.data.image_data)
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
        { signed_date: manualActionDatesEnabled ? (signedDate || new Date().toISOString().slice(0, 10)) : undefined },
      )
      await load()
    } catch (e: unknown) {
      const detail = (e as { response?: { data?: { detail?: string } } })?.response?.data?.detail
      setError(detail || 'Failed to sign. Please try again.')
    } finally {
      setBusy(false)
    }
  }

  const visibleSigs = sigs.filter(sig => !(sig.document_type === 'FR218' && !sig.document_id))

  if (loading || visibleSigs.length === 0) return null

  return (
    <>
      <div className="rounded-lg border border-amber-200 bg-amber-50 p-5">
        <div className="mb-3 flex items-center justify-between gap-3">
          <div>
            <h2 className="text-sm font-semibold text-amber-900">
              Signature Action Center ({visibleSigs.length})
            </h2>
            <p className="mt-0.5 text-xs text-amber-800/70">
              Documents ready for your signature are refreshed automatically.
            </p>
          </div>
          <button
            type="button"
            onClick={load}
            className="rounded-md border border-amber-200 bg-white px-2.5 py-1 text-xs font-medium text-amber-800 hover:bg-amber-100"
          >
            Refresh
          </button>
        </div>
        <div className="space-y-3">
          {visibleSigs.map((sig) => {
            const isViewer = !!sig.document_id
            return (
              <div key={sig.id} className="rounded-lg border border-amber-100 bg-white p-4">
                <div className="flex items-center justify-between">
                  <div>
                    <p className="text-sm font-medium text-gray-900">{sig.document_label}</p>
                    <p className="mt-0.5 text-xs text-gray-400">
                      {sig.plan_number ? `#${sig.plan_number} · ` : ''}{sig.company_name}
                      {sig.signer_role_label ? ` · ${sig.signer_role_label.replace(/_/g, ' ')}` : ''}
                    </p>
                  </div>

                  {isViewer && sig.document_id && (
                    <a
                      href={`${viewerBasePath}/${viewerDocType(sig.document_type)}/${sig.document_id}`}
                      className="rounded-lg bg-[#1A4731] px-3 py-1.5 text-xs font-medium text-white hover:bg-[#143828]"
                    >
                      Open to Sign
                    </a>
                  )}

                  {!isViewer && (
                    sig.document_type === 'FR222' && !sig.document_id ? (
                      <span className="rounded-full bg-gray-200 px-2 py-0.5 text-xs text-gray-500">
                        Awaiting document upload
                      </span>
                    ) : (
                      <button
                        type="button"
                        onClick={() => openDirectSign(sig)}
                        disabled={busy}
                        className="rounded-lg bg-[#1A4731] px-3 py-1.5 text-xs font-medium text-white disabled:opacity-40"
                      >
                        Sign
                      </button>
                    )
                  )}
                </div>
              </div>
            )
          })}
        </div>
      </div>

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
              {manualActionDatesEnabled && <div>
                <label className="mb-1 block text-xs font-medium text-gray-600">Signing date</label>
                <input
                  type="date"
                  value={signedDate}
                  onChange={(e) => setSignedDate(e.target.value)}
                  className="rounded border border-gray-200 px-2 py-1 text-sm text-gray-700 focus:border-[#1A4731] focus:outline-none"
                />
              </div>}
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
