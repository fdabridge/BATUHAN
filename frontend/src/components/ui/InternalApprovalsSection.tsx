'use client'

import { useEffect, useState, useCallback } from 'react'
import api from '@/lib/api'

interface SigSlot {
  id: string
  document_type: 'FR222'
  document_id: string | null
  signer_role_label: string
  signer_name: string | null
  is_signed: boolean
  signed_at: string | null
  required: boolean
  order_index: number
}

const ROLE_LABELS: Record<string, string> = {
  cb_planner:      'Planning Officer',
  cb_cert_manager: 'Certification Manager',
  cb_reviewer:     'Independent Reviewer',
}

function fmtDate(iso: string | null) {
  if (!iso) return ''
  return new Date(iso).toLocaleDateString('en-GB', { day: 'numeric', month: 'short', year: 'numeric' })
}

export function InternalApprovalsSection({
  auditSetId,
  workflowStatus,
  auditType,
}: {
  auditSetId: string
  workflowStatus: string | null
  auditType?: string | null
}) {
  const [slots, setSlots]   = useState<SigSlot[]>([])
  const [loading, setLoading] = useState(true)

  const load = useCallback(async () => {
    try {
      const r = await api.get<SigSlot[]>(`/audit-sets/${auditSetId}/internal-signatures`)
      // Only FR222 slots — FR218 is now handled via the fr218_review shared document upload
      setSlots((r.data as SigSlot[]).filter(s => s.document_type === 'FR222'))
    } catch {
      // 403 for non-CB users — leave slots empty
    } finally {
      setLoading(false)
    }
  }, [auditSetId])

  useEffect(() => { load() }, [load])

  // Surveillance audits do not use FR.222 — hide section entirely.
  if (auditType && auditType.startsWith('surveillance')) return null

  const showSection = workflowStatus && workflowStatus !== 'pending_review'
  if (!showSection) return null

  const FR222_STAGES = [
    'fr218_in_progress', 'fr218_complete',
    'stage1_scheduled', 'stage1_in_progress', 'stage1_complete',
    'stage2_scheduled', 'stage2_in_progress',
    'audit_scheduled', 'audit_in_progress',
    'under_review', 'certified',
  ]
  const showFR222 = workflowStatus != null && FR222_STAGES.includes(workflowStatus)

  const hasFR222 = slots.length > 0

  if (!showFR222) return null

  return (
    <div className="mt-8">
      <h2 className="mb-3 text-sm font-semibold uppercase tracking-wide text-gray-700">
        Internal Approvals
      </h2>

      <div className="rounded-xl border bg-white p-4">
        <div className="mb-3 flex items-center justify-between">
          <p className="text-sm font-medium text-gray-800">FR.222 — Audit Programme</p>
          {hasFR222 && slots.every(s => s.is_signed) && (
            <span className="rounded-full bg-green-100 px-2 py-0.5 text-xs font-semibold text-green-700">
              Fully Signed ✓
            </span>
          )}
        </div>
        {loading ? (
          <p className="text-xs text-gray-400">Loading…</p>
        ) : !hasFR222 ? (
          <p className="text-xs text-gray-400 italic">
            Upload the Audit Programme DOCX via Shared Documents to initiate signing.
          </p>
        ) : (
          <div className="space-y-2">
            {slots.map(slot => <SignerRow key={slot.id} slot={slot} />)}
          </div>
        )}
      </div>
    </div>
  )
}

function SignerRow({ slot }: { slot: SigSlot }) {
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
              : slot.signer_name
              ? `Assigned: ${slot.signer_name}`
              : 'Eligible users can sign via viewer'}
          </p>
        </div>
        <div>
          {slot.is_signed ? (
            <span className="rounded-full bg-green-100 px-2 py-0.5 text-xs font-semibold text-green-700">✓</span>
          ) : slot.document_id ? (
            <a
              href={`/viewer/shared_doc/${slot.document_id}`}
              className="rounded bg-[#1A4731] px-2.5 py-1 text-xs text-white hover:bg-[#143828] transition-colors"
            >
              Open to Sign
            </a>
          ) : (
            <span className="rounded-full bg-gray-200 px-2 py-0.5 text-xs text-gray-500">
              Awaiting document upload
            </span>
          )}
        </div>
      </div>
    </div>
  )
}
