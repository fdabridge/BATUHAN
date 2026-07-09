'use client'

import { useCallback, useEffect, useState } from 'react'
import Link from 'next/link'
import api from '@/lib/api'
import { useAuth } from '@/lib/auth'

interface FR233Member {
  id:        string
  user_id:   string
  user_name: string
  role:      'reviewer' | 'decision_maker'
  sig_key:   string | null
  ea_codes:  string[]
  signed:    boolean
}

interface FR233Status {
  status:                'pending' | 'signing' | 'complete'
  document_id:           string | null
  members:               FR233Member[]
  cert_manager_signed:   boolean
  all_committee_signed:  boolean
}

const SHOW_STAGES = new Set([
  'stage2_complete', 'committee_review', 'under_review',
  'stage2_in_progress', 'certified',
])

const ROLE_LABELS: Record<string, string> = {
  decision_maker: 'Chairperson',
  reviewer:       'Member',
}

export function FR233Panel({
  auditSetId, workflowStatus,
}: { auditSetId: string; workflowStatus: string | null }) {
  const { user } = useAuth()
  const [data,    setData]    = useState<FR233Status | null>(null)
  const [loading, setLoading] = useState(true)

  const load = useCallback(async () => {
    try {
      const r = await api.get<FR233Status>(`/audit-sets/${auditSetId}/fr233`)
      setData(r.data)
    } catch {
      setData(null)
    } finally {
      setLoading(false)
    }
  }, [auditSetId])

  useEffect(() => {
    load()
    const handleUpdate = (event: Event) => {
      const detail = (event as CustomEvent<{ auditSetId?: string }>).detail
      if (!detail?.auditSetId || detail.auditSetId === auditSetId) {
        setLoading(true)
        load()
      }
    }
    window.addEventListener('certiva:fr233-updated', handleUpdate)
    return () => window.removeEventListener('certiva:fr233-updated', handleUpdate)
  }, [auditSetId, load])

  if (!workflowStatus || !SHOW_STAGES.has(workflowStatus)) return null
  if (loading) return null

  const canManage      = user && [
    'admin', 'planner', 'planner_us', 'executive', 'certification_manager',
  ].includes(user.role)
  const canCertManager = user && ['admin', 'executive', 'certification_manager'].includes(user.role)
  const status         = data?.status ?? 'pending'
  const documentId     = data?.document_id ?? null
  const members        = data?.members ?? []
  const cmSigned       = data?.cert_manager_signed ?? false
  const allSigned      = data?.all_committee_signed ?? false

  const statusPill =
    status === 'complete' ? 'bg-green-100 text-green-700'
    : status === 'signing' ? 'bg-amber-100 text-amber-700'
    : 'bg-gray-100 text-gray-500'

  return (
    <div className="mt-6">
      <div className="mb-3 flex items-center gap-2">
        <div className="flex items-center gap-2">
          <h2 className="text-sm font-semibold uppercase tracking-wide text-gray-700">
            FR.233 Review &amp; Decision
          </h2>
          <span className={`rounded-full px-2 py-0.5 text-xs font-semibold ${statusPill}`}>
            {status}
          </span>
        </div>
      </div>

      <div className="rounded-xl border bg-white">
        {status === 'pending' ? (
          <div className="px-4 py-5">
            <p className="text-xs text-gray-500">
              {canManage
                ? 'Release Review & Decision (FR.233) from Shared Documents to begin committee signing.'
                : 'Waiting for a planner to release Review & Decision (FR.233).'}
            </p>
            {canManage && (
              <a
                href="#shared-documents"
                className="mt-3 inline-flex rounded-lg bg-[#1A4731] px-3 py-1.5 text-xs font-medium text-white hover:bg-[#143b27]"
              >
                Go to Shared Documents
              </a>
            )}
          </div>
        ) : (
          <div className="divide-y divide-gray-100">
            {members.length === 0 && (
              <div className="px-4 py-3 text-xs text-gray-400">
                FR.233 released — appoint committee members to enable signing.
              </div>
            )}
            {members.map(m => (
              <div key={m.id} className="flex items-center justify-between px-4 py-3">
                <div>
                  <p className="text-sm font-medium text-gray-800">{m.user_name}</p>
                  <p className="mt-0.5 text-xs text-gray-400">
                    {ROLE_LABELS[m.role] ?? m.role}
                    {m.sig_key ? ` · slot: ${m.sig_key}` : ' · no slot assigned'}
                    {m.ea_codes.length > 0 ? ` · EA: ${m.ea_codes.join(', ')}` : ''}
                  </p>
                </div>
                <span className={`rounded-full px-2 py-0.5 text-xs font-semibold ${m.signed ? 'bg-green-100 text-green-700' : 'bg-gray-100 text-gray-500'}`}>
                  {m.signed ? '✓ Signed' : 'Pending'}
                </span>
              </div>
            ))}
            <div className="flex items-center justify-between bg-gray-50 px-4 py-3">
              <div>
                <p className="text-sm font-medium text-gray-800">Certification Manager Approval</p>
                <p className="mt-0.5 text-xs text-gray-400">
                  slot: CB_CERT_MANAGER · advances workflow to <code>certified</code>
                </p>
              </div>
              <span className={`rounded-full px-2 py-0.5 text-xs font-semibold ${cmSigned ? 'bg-green-100 text-green-700' : allSigned ? 'bg-amber-100 text-amber-700' : 'bg-gray-100 text-gray-500'}`}>
                {cmSigned ? '✓ Signed' : allSigned ? 'Awaiting CM' : 'Locked'}
              </span>
            </div>
          </div>
        )}
      </div>

      {documentId && (
        <div className="mt-3 flex items-center gap-3">
          <Link
            href={`/viewer/shared_doc/${documentId}`}
            className="rounded-lg border px-3 py-1.5 text-xs font-medium text-gray-700 hover:bg-gray-50"
          >
            Open FR.233 in viewer
          </Link>
          {canCertManager && documentId && !cmSigned && (
            <Link
              href={`/viewer/shared_doc/${documentId}?slot=CB_CERT_MANAGER`}
              className="rounded-lg bg-[#1A4731] px-3 py-1.5 text-xs font-medium text-white hover:bg-[#143b27]"
            >
              Sign as Certification Manager
            </Link>
          )}
        </div>
      )}
    </div>
  )
}
