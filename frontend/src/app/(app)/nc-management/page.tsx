'use client'

import { useEffect, useState } from 'react'
import { useRouter } from 'next/navigation'
import api from '@/lib/api'
import { useAuth } from '@/lib/auth'

interface NCSummaryRow {
  audit_set_id:    string
  company_name:    string
  plan_number:     number
  no_nc:           boolean
  decided_at:      string | null
  open_count:      number
  closed_count:    number
  total_count:     number
  has_overdue:     boolean
  workflow_status: string
}

const STATUS_PILL: Record<string, string> = {
  certified: 'bg-green-100 text-green-800',
  committee_review: 'bg-blue-100 text-blue-800',
  stage2_complete: 'bg-yellow-100 text-yellow-800',
}

export default function NCManagementPage() {
  const { user } = useAuth()
  const router   = useRouter()
  const [rows, setRows]       = useState<NCSummaryRow[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError]     = useState<string | null>(null)

  useEffect(() => {
    api.get<NCSummaryRow[]>('/nc-management/summary')
      .then((r) => setRows(r.data))
      .catch((e) => setError(e.response?.data?.detail || 'Failed to load'))
      .finally(() => setLoading(false))
  }, [])

  if (loading) return <div className="p-8 text-sm text-gray-500">Loading…</div>
  if (error)   return <div className="p-8 text-sm text-red-500">{error}</div>

  const withNCs  = rows.filter((r) => !r.no_nc)
  const noNC     = rows.filter((r) => r.no_nc)
  const overdue  = withNCs.filter((r) => r.has_overdue)

  return (
    <div className="mx-auto max-w-5xl space-y-6">
      <div>
        <h1 className="text-xl font-semibold text-gray-900">NC Management</h1>
        <p className="mt-1 text-sm text-gray-500">
          Cross-company nonconformity tracking. This view is read-only — NC decisions
          are submitted by auditors inside each client's audit task.
        </p>
      </div>

      {/* Summary stats */}
      <div className="grid grid-cols-3 gap-4">
        <div className="rounded-lg border bg-white p-4">
          <p className="text-xs text-gray-500">Audits with open NCs</p>
          <p className="mt-1 text-2xl font-bold text-gray-900">
            {withNCs.filter((r) => r.open_count > 0).length}
          </p>
        </div>
        <div className="rounded-lg border bg-white p-4">
          <p className="text-xs text-gray-500">Overdue NCs</p>
          <p className={`mt-1 text-2xl font-bold ${overdue.length ? 'text-red-600' : 'text-gray-900'}`}>
            {overdue.length}
          </p>
        </div>
        <div className="rounded-lg border bg-white p-4">
          <p className="text-xs text-gray-500">No NC declared</p>
          <p className="mt-1 text-2xl font-bold text-green-700">{noNC.length}</p>
        </div>
      </div>

      {/* Table */}
      {rows.length === 0 ? (
        <div className="rounded-lg border bg-white p-8 text-center text-sm text-gray-400">
          No NC decisions have been submitted yet.
        </div>
      ) : (
        <div className="overflow-hidden rounded-lg border bg-white">
          <table className="min-w-full divide-y divide-gray-200 text-sm">
            <thead className="bg-gray-50">
              <tr>
                <th className="px-4 py-3 text-left font-medium text-gray-500">Company</th>
                <th className="px-4 py-3 text-left font-medium text-gray-500">Plan #</th>
                <th className="px-4 py-3 text-left font-medium text-gray-500">NCs</th>
                <th className="px-4 py-3 text-left font-medium text-gray-500">Status</th>
                <th className="px-4 py-3 text-left font-medium text-gray-500">Workflow</th>
                <th className="px-4 py-3 text-left font-medium text-gray-500">Decided</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-gray-100">
              {rows.map((row) => (
                <tr
                  key={row.audit_set_id}
                  className="cursor-pointer hover:bg-gray-50"
                  onClick={() => router.push(`/clients/${row.audit_set_id}`)}
                >
                  <td className="px-4 py-3 font-medium text-gray-900">{row.company_name}</td>
                  <td className="px-4 py-3 text-gray-500">{row.plan_number}</td>
                  <td className="px-4 py-3">
                    {row.no_nc ? (
                      <span className="inline-flex items-center rounded-full bg-green-50 px-2 py-0.5 text-xs font-medium text-green-700">
                        No NC
                      </span>
                    ) : (
                      <span className={`inline-flex items-center gap-1 text-xs ${row.has_overdue ? 'text-red-600 font-semibold' : 'text-gray-700'}`}>
                        {row.open_count} open / {row.closed_count} closed
                        {row.has_overdue && ' ⚠ Overdue'}
                      </span>
                    )}
                  </td>
                  <td className="px-4 py-3">
                    {!row.no_nc && (
                      <div className="h-1.5 w-24 rounded-full bg-gray-200">
                        <div
                          className="h-1.5 rounded-full bg-green-500"
                          style={{ width: row.total_count ? `${(row.closed_count / row.total_count) * 100}%` : '0%' }}
                        />
                      </div>
                    )}
                  </td>
                  <td className="px-4 py-3">
                    <span className={`inline-flex items-center rounded-full px-2 py-0.5 text-xs font-medium ${STATUS_PILL[row.workflow_status] ?? 'bg-gray-100 text-gray-700'}`}>
                      {row.workflow_status?.replace(/_/g, ' ')}
                    </span>
                  </td>
                  <td className="px-4 py-3 text-gray-400 text-xs">
                    {row.decided_at ? new Date(row.decided_at).toLocaleDateString() : '—'}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  )
}
