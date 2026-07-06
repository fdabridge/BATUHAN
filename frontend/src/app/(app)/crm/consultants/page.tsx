'use client'

import { useEffect, useState } from 'react'
import api from '@/lib/api'

interface ConsultantSummary {
  id: string
  full_name: string
  username: string | null
  email: string
  client_count: number
  certified_count: number
  total_revenue: number
  renewals_90_days: number
}

function fmt(n: number | null, currency = 'USD') {
  if (!n) return '--'
  return new Intl.NumberFormat('en-US', { style: 'currency', currency, maximumFractionDigits: 0 }).format(n)
}

export default function CRMConsultantsPage() {
  const [consultants, setConsultants] = useState<ConsultantSummary[]>([])
  const [loading, setLoading]         = useState(true)

  useEffect(() => {
    api.get<ConsultantSummary[]>('/crm/consultants')
      .then((r) => setConsultants(r.data))
      .catch(() => {})
      .finally(() => setLoading(false))
  }, [])

  const totalRevenue = consultants.reduce((s, c) => s + c.total_revenue, 0)
  const totalClients = consultants.reduce((s, c) => s + c.client_count, 0)

  return (
    <div className="space-y-6">
      <h1 className="text-xl font-semibold text-gray-900">Consultants</h1>

      {/* Summary KPIs */}
      <div className="grid grid-cols-3 gap-4">
        {[
          { label: 'Consultants', value: consultants.length },
          { label: 'Referred Clients', value: totalClients },
          { label: 'Total Revenue', value: fmt(totalRevenue) },
        ].map((k) => (
          <div key={k.label} className="rounded-xl border bg-white p-5">
            <p className="text-xs font-medium uppercase tracking-wide text-gray-400">{k.label}</p>
            <p className="mt-1 text-2xl font-bold text-gray-900">{k.value}</p>
          </div>
        ))}
      </div>

      {loading ? (
        <p className="text-sm text-gray-400">Loading...</p>
      ) : consultants.length === 0 ? (
        <p className="text-sm text-gray-400">No consultants found. Create consultant accounts in Admin - Users.</p>
      ) : (
        <div className="overflow-x-auto rounded-xl border bg-white shadow-sm">
          <table className="w-full text-sm">
            <thead>
              <tr className="border-b border-gray-100 text-left text-xs text-gray-400">
                <th className="px-4 py-3">Name</th>
                <th className="px-4 py-3">Referral Code</th>
                <th className="px-4 py-3">Email</th>
                <th className="px-4 py-3 text-right">Clients</th>
                <th className="px-4 py-3 text-right">Certified</th>
                <th className="px-4 py-3 text-right">Renewals (90d)</th>
                <th className="px-4 py-3 text-right">Revenue</th>
              </tr>
            </thead>
            <tbody>
              {consultants.map((c, i) => (
                <tr key={c.id} className={i % 2 === 0 ? 'bg-white' : 'bg-gray-50'}>
                  <td className="px-4 py-3 font-medium text-gray-900">{c.full_name}</td>
                  <td className="px-4 py-3">
                    <span className="rounded bg-gray-100 px-2 py-0.5 font-mono text-xs text-gray-700">
                      {c.username || '--'}
                    </span>
                  </td>
                  <td className="px-4 py-3 text-gray-500 text-xs">{c.email}</td>
                  <td className="px-4 py-3 text-right tabular-nums">{c.client_count}</td>
                  <td className="px-4 py-3 text-right tabular-nums text-green-700">{c.certified_count}</td>
                  <td className="px-4 py-3 text-right tabular-nums">
                    {c.renewals_90_days > 0 ? (
                      <span className="rounded-full bg-amber-100 px-2 py-0.5 text-xs font-medium text-amber-700">
                        {c.renewals_90_days}
                      </span>
                    ) : '--'}
                  </td>
                  <td className="px-4 py-3 text-right font-medium tabular-nums">
                    {fmt(c.total_revenue)}
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
