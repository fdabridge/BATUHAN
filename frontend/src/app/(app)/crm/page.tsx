'use client'

import { useEffect, useState } from 'react'
import Link from 'next/link'
import api from '@/lib/api'

interface KPIs {
  active_certifications: number
  expiring_90_days: number
  overdue_renewals: number
  in_progress: number
}

interface RenewalRow {
  audit_set_id: string
  company_name: string
  standards: string[]
  milestone: 'surv1' | 'surv2' | 'recert'
  due_date: string
  days_until: number
  cert_issued_date: string
  contact_name: string
  contact_email: string
}

interface DashboardData {
  kpis: KPIs
  upcoming_renewals: RenewalRow[]
  pipeline: Record<string, number>
}

const MILESTONE_LABELS: Record<string, string> = {
  surv1: 'Surveillance 1',
  surv2: 'Surveillance 2',
  recert: 'Recertification',
}

function urgencyBadge(daysUntil: number) {
  if (daysUntil < 0)  return { label: 'Overdue',  cls: 'bg-red-100 text-red-700' }
  if (daysUntil < 30) return { label: 'Due soon', cls: 'bg-orange-100 text-orange-700' }
  if (daysUntil < 90) return { label: 'Upcoming', cls: 'bg-yellow-100 text-yellow-700' }
  return               { label: 'On track',  cls: 'bg-green-100 text-green-700' }
}

function fmtDate(iso: string | null | undefined) {
  if (!iso) return '—'
  return new Date(iso).toLocaleDateString('en-GB', { day: 'numeric', month: 'short', year: 'numeric' })
}

export default function CRMDashboard() {
  const [data, setData]       = useState<DashboardData | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError]     = useState('')

  useEffect(() => {
    api.get<DashboardData>('/crm/dashboard')
      .then((r) => setData(r.data))
      .catch(() => setError('Could not load CRM dashboard.'))
      .finally(() => setLoading(false))
  }, [])

  if (loading) return <div className="p-8 text-sm text-gray-400">Loading…</div>
  if (error || !data) return <div className="p-8 text-sm text-red-500">{error || 'No data.'}</div>

  const { kpis, upcoming_renewals, pipeline } = data

  return (
    <div className="space-y-8">
      <h1 className="text-xl font-semibold text-gray-900">CRM Dashboard</h1>

      {/* KPI Cards */}
      <div className="grid grid-cols-2 gap-4 sm:grid-cols-4">
        {[
          { label: 'Active Certifications', value: kpis.active_certifications, color: 'text-green-700' },
          { label: 'Expiring (90 days)',     value: kpis.expiring_90_days,      color: 'text-orange-600' },
          { label: 'Overdue Renewals',       value: kpis.overdue_renewals,      color: 'text-red-600' },
          { label: 'Audits In Progress',     value: kpis.in_progress,           color: 'text-blue-600' },
        ].map((k) => (
          <div key={k.label} className="rounded-xl border border-gray-200 bg-white p-5 shadow-sm">
            <p className="text-xs text-gray-500">{k.label}</p>
            <p className={`mt-1 text-3xl font-bold ${k.color}`}>{k.value}</p>
          </div>
        ))}
      </div>

      {/* Upcoming Renewals */}
      <div className="rounded-xl border border-gray-200 bg-white shadow-sm">
        <div className="border-b border-gray-100 px-6 py-4">
          <h2 className="font-semibold text-gray-800">Upcoming Renewal Deadlines</h2>
          <p className="text-xs text-gray-400 mt-0.5">Surveillance and recertification due dates for all certified clients</p>
        </div>
        {upcoming_renewals.length === 0 ? (
          <p className="px-6 py-8 text-sm text-gray-400">No upcoming renewals in the next 18 months.</p>
        ) : (
          <table className="w-full text-sm">
            <thead>
              <tr className="border-b border-gray-100 text-left text-xs text-gray-400">
                <th className="px-6 py-3">Company</th>
                <th className="px-4 py-3">Standards</th>
                <th className="px-4 py-3">Milestone</th>
                <th className="px-4 py-3">Due Date</th>
                <th className="px-4 py-3">Status</th>
                <th className="px-4 py-3">Contact</th>
                <th className="px-4 py-3"></th>
              </tr>
            </thead>
            <tbody>
              {upcoming_renewals.map((r, i) => {
                const badge = urgencyBadge(r.days_until)
                return (
                  <tr key={`${r.audit_set_id}-${r.milestone}`} className={i % 2 === 0 ? 'bg-white' : 'bg-gray-50'}>
                    <td className="px-6 py-3 font-medium text-gray-900">{r.company_name}</td>
                    <td className="px-4 py-3 text-gray-500">{(r.standards || []).join(', ')}</td>
                    <td className="px-4 py-3 text-gray-700">{MILESTONE_LABELS[r.milestone] ?? r.milestone}</td>
                    <td className="px-4 py-3 text-gray-700">{fmtDate(r.due_date)}</td>
                    <td className="px-4 py-3">
                      <span className={`rounded-full px-2 py-0.5 text-xs font-medium ${badge.cls}`}>
                        {badge.label}{r.days_until >= 0 ? ` (${r.days_until}d)` : ` (${Math.abs(r.days_until)}d ago)`}
                      </span>
                    </td>
                    <td className="px-4 py-3 text-gray-500">
                      <div>{r.contact_name}</div>
                      <div className="text-xs text-gray-400">{r.contact_email}</div>
                    </td>
                    <td className="px-4 py-3">
                      <Link href={`/crm/clients/${r.audit_set_id}`} className="text-xs text-emerald-700 hover:underline">View →</Link>
                    </td>
                  </tr>
                )
              })}
            </tbody>
          </table>
        )}
      </div>

      {/* Pipeline Summary */}
      {Object.keys(pipeline).length > 0 && (
        <div className="rounded-xl border border-gray-200 bg-white shadow-sm">
          <div className="border-b border-gray-100 px-6 py-4">
            <h2 className="font-semibold text-gray-800">Pipeline Overview</h2>
          </div>
          <div className="flex flex-wrap gap-3 px-6 py-4">
            {Object.entries(pipeline).map(([stage, count]) => (
              <div key={stage} className="flex items-center gap-2 rounded-lg border border-gray-100 bg-gray-50 px-3 py-2">
                <span className="text-xs text-gray-500">{stage}</span>
                <span className="text-sm font-semibold text-gray-800">{count}</span>
              </div>
            ))}
          </div>
        </div>
      )}
    </div>
  )
}
