'use client'

import { useEffect, useState } from 'react'
import { useRouter } from 'next/navigation'
import api from '@/lib/api'

const STATUS_LABELS: Record<string, string> = {
  pending_review:    'Pending Review',
  in_planning:       'In Planning',
  quotation_sent:    'Quotation Sent',
  agreement_signed:  'Agreement Signed',
  fr218_in_progress: 'FR.218 In Progress',
  fr218_complete:    'FR.218 Complete',
  stage1_scheduled:  'Stage 1 Scheduled',
  stage1_in_progress:'Stage 1 In Progress',
  stage1_complete:   'Stage 1 Complete',
  stage2_scheduled:  'Stage 2 Scheduled',
  stage2_in_progress:'Stage 2 In Progress',
  audit_scheduled:   'Audit Scheduled',
  audit_in_progress: 'In Progress',
  under_review:      'Under Review',
  certified:         'Certified',
}

interface PendingApplication {
  id: string
  plan_number: number
  company_name: string
  company_address: string | null
  email: string | null
  phone: string | null
  standards: string[] | null
  audit_type: string | null
  scope_en: string | null
  workflow_status: string
  created_at: string | null
}

export default function ApplicationsPage() {
  const router = useRouter()
  const [apps, setApps] = useState<PendingApplication[]>([])
  const [loading, setLoading] = useState(true)

  useEffect(() => {
    api.get<PendingApplication[]>('/audit-sets/pending-applications')
      .then((r) => setApps(r.data))
      .finally(() => setLoading(false))
  }, [])

  if (loading) {
    return <div className="p-8 text-sm text-gray-500">Loading applications…</div>
  }

  return (
    <div className="mx-auto max-w-5xl p-6">
      <div className="mb-6 flex items-center justify-between">
        <div>
          <h1 className="text-xl font-bold text-gray-900">Client Applications</h1>
          <p className="mt-0.5 text-sm text-gray-500">
            Applications submitted via the client portal awaiting review
          </p>
        </div>
        <span className="rounded-full bg-amber-100 px-3 py-1 text-xs font-semibold text-amber-800">
          {apps.length} pending
        </span>
      </div>

      {apps.length === 0 ? (
        <div className="py-16 text-center text-gray-400">
          <p className="text-sm">No pending applications</p>
        </div>
      ) : (
        <div className="space-y-3">
          {apps.map((app) => (
            <div
              key={app.id}
              className="flex items-center justify-between rounded-xl border bg-white p-5 transition-shadow hover:shadow-sm"
            >
              <div className="min-w-0 flex-1">
                <div className="flex items-center gap-3">
                  <h3 className="truncate font-semibold text-gray-900">{app.company_name}</h3>
                  <span className="shrink-0 rounded-full border border-amber-200 bg-amber-50 px-2 py-0.5 text-xs text-amber-700">
                    {STATUS_LABELS[app.workflow_status] || app.workflow_status}
                  </span>
                </div>
                {app.company_address && (
                  <p className="mt-1 truncate text-sm text-gray-500">{app.company_address}</p>
                )}
                <div className="mt-2 flex items-center gap-2 text-xs text-gray-400">
                  <span>{(app.standards || []).join(', ') || '—'}</span>
                  <span>·</span>
                  <span>{app.audit_type?.replace('_', ' ') ?? '—'}</span>
                  {app.email && (
                    <>
                      <span>·</span>
                      <span>{app.email}</span>
                    </>
                  )}
                  {app.created_at && (
                    <>
                      <span>·</span>
                      <span>Submitted {new Date(app.created_at).toLocaleDateString()}</span>
                    </>
                  )}
                </div>
                {app.scope_en && (
                  <p className="mt-1 truncate text-xs italic text-gray-400">&ldquo;{app.scope_en}&rdquo;</p>
                )}
              </div>
              <button
                type="button"
                onClick={() => router.push(`/clients/${app.id}`)}
                className="ml-4 shrink-0 rounded-lg px-4 py-2 text-sm text-white transition-colors hover:opacity-90"
                style={{ background: '#1A4731' }}
              >
                Open &amp; Review
              </button>
            </div>
          ))}
        </div>
      )}
    </div>
  )
}
