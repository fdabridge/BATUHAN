'use client'

import { useEffect, useState } from 'react'
import api from '@/lib/api'
import { useAuth } from '@/lib/auth'

interface ConsultantClient {
  id: string
  company_name: string
  city: string | null
  standards: string[]
  audit_type: string
  simple_status: string
  workflow_status: string | null
  cert_issued_date: string | null
  cert_expiry_date: string | null
  contact_name: string | null
  contact_email: string | null
}

interface ConsultantProfile {
  full_name: string
  referral_code: string
}

const STATUS_COLORS: Record<string, string> = {
  'Application Received': 'bg-gray-100 text-gray-500',
  'In Planning':          'bg-blue-100 text-blue-700',
  'Quotation Sent':       'bg-indigo-100 text-indigo-700',
  'Agreement Signed':     'bg-purple-100 text-purple-700',
  'Under Review':         'bg-yellow-100 text-yellow-700',
  'Stage 1 Audit':        'bg-orange-100 text-orange-700',
  'Stage 2 Audit':        'bg-orange-100 text-orange-700',
  'Surveillance Audit':   'bg-orange-100 text-orange-700',
  'Certified':            'bg-green-100 text-green-700',
}

function fmtDate(iso: string | null | undefined) {
  if (!iso) return '--'
  return new Date(iso).toLocaleDateString('en-GB', { day: 'numeric', month: 'short', year: 'numeric' })
}

export default function ConsultantClientsPage() {
  const { user } = useAuth()
  const [clients, setClients]   = useState<ConsultantClient[]>([])
  const [profile, setProfile]   = useState<ConsultantProfile | null>(null)
  const [loading, setLoading]   = useState(true)
  const [search, setSearch]     = useState('')

  useEffect(() => {
    Promise.all([
      api.get<ConsultantClient[]>('/consultant/clients'),
      api.get<ConsultantProfile>('/consultant/me'),
    ]).then(([clientsRes, meRes]) => {
      setClients(clientsRes.data)
      setProfile(meRes.data)
    }).catch(() => {}).finally(() => setLoading(false))
  }, [])

  const filtered = clients.filter((c) =>
    c.company_name.toLowerCase().includes(search.toLowerCase())
  )

  return (
    <div className="space-y-6">
      <div className="rounded-xl border bg-white p-5">
        <p className="text-xs font-medium uppercase tracking-wide text-gray-400">Your referral code</p>
        <p className="mt-1 text-2xl font-bold tracking-tight" style={{ color: '#1A4731' }}>
          {profile?.referral_code ?? '--'}
        </p>
        <p className="mt-0.5 text-sm text-gray-500">
          Share this code with clients so they can enter it on the application form.
        </p>
      </div>

      <div className="flex items-center justify-between">
        <h1 className="text-xl font-semibold text-gray-900">
          My Clients <span className="ml-1 text-sm font-normal text-gray-400">({clients.length})</span>
        </h1>
        <input
          className="rounded-lg border border-gray-200 px-3 py-1.5 text-sm focus:outline-none focus:ring-2 focus:ring-emerald-500"
          placeholder="Search by company..."
          value={search}
          onChange={(e) => setSearch(e.target.value)}
        />
      </div>

      {loading ? (
        <p className="text-sm text-gray-400">Loading...</p>
      ) : clients.length === 0 ? (
        <div className="rounded-xl border bg-white p-10 text-center">
          <p className="text-sm text-gray-400">No clients referred yet.</p>
          <p className="mt-1 text-xs text-gray-300">Share your referral code with clients to get started.</p>
        </div>
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
                <th className="px-4 py-3">Expires</th>
                <th className="px-4 py-3">Contact</th>
              </tr>
            </thead>
            <tbody>
              {filtered.map((c, i) => (
                <tr key={c.id} className={i % 2 === 0 ? 'bg-white' : 'bg-gray-50'}>
                  <td className="px-4 py-3 font-medium text-gray-900">
                    {c.company_name}
                    {c.city && <span className="ml-1 text-xs text-gray-400">· {c.city}</span>}
                  </td>
                  <td className="px-4 py-3 text-xs text-gray-500">{(c.standards || []).join(', ')}</td>
                  <td className="px-4 py-3 capitalize text-gray-500">{c.audit_type}</td>
                  <td className="px-4 py-3">
                    <span className={`rounded-full px-2 py-0.5 text-xs font-medium ${STATUS_COLORS[c.simple_status] ?? 'bg-gray-100 text-gray-600'}`}>
                      {c.simple_status}
                    </span>
                  </td>
                  <td className="px-4 py-3 text-gray-600">{fmtDate(c.cert_issued_date)}</td>
                  <td className="px-4 py-3 text-gray-600">{fmtDate(c.cert_expiry_date)}</td>
                  <td className="px-4 py-3">
                    <div className="text-xs text-gray-700">{c.contact_name || '--'}</div>
                    <div className="text-xs text-gray-400">{c.contact_email || ''}</div>
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
