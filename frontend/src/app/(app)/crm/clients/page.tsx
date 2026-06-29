'use client'

import { useEffect, useState } from 'react'
import Link from 'next/link'
import api from '@/lib/api'

interface CRMClient {
  id: string
  company_name: string
  city: string
  standards: string[]
  audit_type: string
  simple_status: string
  cert_issued_date: string | null
  surv1_due: string | null
  surv2_due: string | null
  recert_due: string | null
  certification_fee: number | null
  surveillance_fee: number | null
  currency: string
  contact_name: string
  contact_email: string
  contact_phone: string
}

function fmtDate(iso: string | null | undefined) {
  if (!iso) return '—'
  return new Date(iso).toLocaleDateString('en-GB', { day: 'numeric', month: 'short', year: 'numeric' })
}

function dateBadge(iso: string | null) {
  if (!iso) return null
  const days = Math.round((new Date(iso).getTime() - Date.now()) / 86_400_000)
  if (days < 0)  return <span className="ml-1 rounded-full bg-red-100 px-1.5 py-0.5 text-[10px] font-medium text-red-700">Overdue</span>
  if (days < 30) return <span className="ml-1 rounded-full bg-orange-100 px-1.5 py-0.5 text-[10px] font-medium text-orange-700">{days}d</span>
  if (days < 90) return <span className="ml-1 rounded-full bg-yellow-100 px-1.5 py-0.5 text-[10px] font-medium text-yellow-700">{days}d</span>
  return null
}

const STATUS_COLORS: Record<string, string> = {
  'Certified':            'bg-green-100 text-green-700',
  'Application Received': 'bg-gray-100 text-gray-500',
  'In Planning':          'bg-blue-100 text-blue-700',
  'Quotation Sent':       'bg-indigo-100 text-indigo-700',
  'Agreement Signed':     'bg-purple-100 text-purple-700',
  'Under Review':         'bg-yellow-100 text-yellow-700',
  'Stage 1 Audit':        'bg-orange-100 text-orange-700',
  'Stage 2 Audit':        'bg-orange-100 text-orange-700',
  'Surveillance Audit':   'bg-orange-100 text-orange-700',
}

export default function CRMClients() {
  const [clients, setClients] = useState<CRMClient[]>([])
  const [loading, setLoading] = useState(true)
  const [search, setSearch]   = useState('')

  useEffect(() => {
    api.get<CRMClient[]>('/crm/clients')
      .then((r) => setClients(r.data))
      .catch(() => {})
      .finally(() => setLoading(false))
  }, [])

  const filtered = clients.filter((c) =>
    c.company_name.toLowerCase().includes(search.toLowerCase()) ||
    c.contact_name.toLowerCase().includes(search.toLowerCase()),
  )

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <h1 className="text-xl font-semibold text-gray-900">All Clients</h1>
        <input
          className="rounded-lg border border-gray-200 px-3 py-1.5 text-sm focus:outline-none focus:ring-2 focus:ring-emerald-500"
          placeholder="Search by company or contact…"
          value={search}
          onChange={(e) => setSearch(e.target.value)}
        />
      </div>

      {loading ? (
        <p className="text-sm text-gray-400">Loading…</p>
      ) : (
        <div className="overflow-x-auto rounded-xl border border-gray-200 bg-white shadow-sm">
          <table className="w-full text-sm">
            <thead>
              <tr className="border-b border-gray-100 text-left text-xs text-gray-400">
                <th className="px-4 py-3">Company</th>
                <th className="px-4 py-3">Standards</th>
                <th className="px-4 py-3">Type</th>
                <th className="px-4 py-3">Status</th>
                <th className="px-4 py-3">Certified</th>
                <th className="px-4 py-3">Surv 1</th>
                <th className="px-4 py-3">Surv 2</th>
                <th className="px-4 py-3">Recert</th>
                <th className="px-4 py-3">Contact</th>
                <th className="px-4 py-3"></th>
              </tr>
            </thead>
            <tbody>
              {filtered.length === 0 ? (
                <tr>
                  <td colSpan={10} className="px-4 py-8 text-center text-sm text-gray-400">No clients found.</td>
                </tr>
              ) : filtered.map((c, i) => (
                <tr key={c.id} className={i % 2 === 0 ? 'bg-white' : 'bg-gray-50'}>
                  <td className="px-4 py-3 font-medium text-gray-900">
                    {c.company_name}
                    {c.city && <span className="ml-1 text-xs text-gray-400">· {c.city}</span>}
                  </td>
                  <td className="px-4 py-3 text-gray-500 text-xs">{(c.standards || []).join(', ')}</td>
                  <td className="px-4 py-3 capitalize text-gray-500">{c.audit_type}</td>
                  <td className="px-4 py-3">
                    <span className={`rounded-full px-2 py-0.5 text-xs font-medium ${STATUS_COLORS[c.simple_status] ?? 'bg-gray-100 text-gray-600'}`}>
                      {c.simple_status}
                    </span>
                  </td>
                  <td className="px-4 py-3 text-gray-600">{fmtDate(c.cert_issued_date)}</td>
                  <td className="px-4 py-3 text-gray-600">{fmtDate(c.surv1_due)}{dateBadge(c.surv1_due)}</td>
                  <td className="px-4 py-3 text-gray-600">{fmtDate(c.surv2_due)}{dateBadge(c.surv2_due)}</td>
                  <td className="px-4 py-3 text-gray-600">{fmtDate(c.recert_due)}{dateBadge(c.recert_due)}</td>
                  <td className="px-4 py-3">
                    <div className="text-xs text-gray-700">{c.contact_name}</div>
                    <div className="text-xs text-gray-400">{c.contact_email}</div>
                    {c.contact_phone && <div className="text-xs text-gray-400">{c.contact_phone}</div>}
                  </td>
                  <td className="px-4 py-3">
                    <Link href={`/crm/clients/${c.id}`} className="text-xs text-emerald-700 hover:underline">View →</Link>
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
