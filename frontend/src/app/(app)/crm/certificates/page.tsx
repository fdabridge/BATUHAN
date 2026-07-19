'use client'

import { useEffect, useState } from 'react'
import Link from 'next/link'
import api from '@/lib/api'
import { useAuth } from '@/lib/auth'

const CRM_ROLES = new Set(['crm', 'admin'])

interface CertificateSummary {
  active_certificates: number
  expiring_in_90_days: number
  surveillance_due_in_30_days: number
  overdue_surveillance: number
  expired: number
  total_outstanding: number
  total_collected: number
}

interface CertificateRow {
  audit_set_id: string
  plan_number: number
  company_name: string
  standard: string
  certificate_number: string | null
  lifecycle_status: string
  cert_issued_date: string | null
  cert_expiry_date: string | null
  next_surveillance_due: string | null
  countdown_days: number | null
  last_surveillance_completed: string | null
  payment_status: string
  amount_due: number | null
  amount_received: number | null
  outstanding: number | null
  notes: string | null
  consultant_name: string | null
  assigned_auditor: string | null
}

interface CertificateCockpitResponse {
  summary: CertificateSummary
  certificates: CertificateRow[]
}

function fmtDate(iso: string | null | undefined) {
  if (!iso) return '\u2014'
  return new Date(iso).toLocaleDateString('en-GB', { day: 'numeric', month: 'short', year: 'numeric' })
}

function fmtMoney(val: number | null | undefined) {
  if (val == null) return '\u2014'
  return `$${val.toLocaleString()}`
}

const STATUS_COLORS: Record<string, string> = {
  active: 'bg-green-100 text-green-700',
  expiring_soon: 'bg-orange-100 text-orange-700',
  expired: 'bg-red-100 text-red-700',
  suspended: 'bg-gray-100 text-gray-500',
  withdrawn: 'bg-gray-100 text-gray-500',
  in_progress: 'bg-blue-100 text-blue-700',
}

const PAYMENT_COLORS: Record<string, string> = {
  paid: 'bg-green-100 text-green-700',
  partially_paid: 'bg-yellow-100 text-yellow-700',
  unpaid: 'bg-gray-100 text-gray-500',
  overdue: 'bg-red-100 text-red-700',
}

export default function CertificatesCockpit() {
  const { user } = useAuth()
  const [data, setData] = useState<CertificateCockpitResponse | null>(null)
  const [loading, setLoading] = useState(true)
  const [search, setSearch] = useState('')
  const [statusFilter, setStatusFilter] = useState('')
  const [standardFilter, setStandardFilter] = useState('')
  const [paymentFilter, setPaymentFilter] = useState('')
  const [consultantFilter, setConsultantFilter] = useState('')
  const [overdueBucket, setOverdueBucket] = useState('')

  function fetchData() {
    const params: Record<string, string> = {}
    if (statusFilter) params.status = statusFilter
    if (standardFilter) params.standard = standardFilter
    if (paymentFilter) params.payment = paymentFilter
    if (consultantFilter) params.consultant_id = consultantFilter
    if (overdueBucket) params.overdue_bucket = overdueBucket

    setLoading(true)
    api.get<CertificateCockpitResponse>('/crm/certificates', { params })
      .then((r) => setData(r.data))
      .catch(() => {})
      .finally(() => setLoading(false))
  }

  useEffect(() => {
    fetchData()
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [statusFilter, standardFilter, paymentFilter, consultantFilter, overdueBucket])

  async function handleExport() {
    try {
      const res = await api.get('/crm/certificates/export', { responseType: 'blob' })
      const url = window.URL.createObjectURL(new Blob([res.data]))
      const link = document.createElement('a')
      link.href = url
      link.setAttribute('download', 'certificates_export.xlsx')
      document.body.appendChild(link)
      link.click()
      link.remove()
      window.URL.revokeObjectURL(url)
    } catch {
      // silent
    }
  }

  if (!user || !CRM_ROLES.has(user.role)) {
    return <div className="p-8 text-sm text-red-500">Access denied.</div>
  }

  const filtered = data?.certificates.filter((c) =>
    c.company_name.toLowerCase().includes(search.toLowerCase())
  ) ?? []

  const summary = data?.summary

  return (
    <div className="space-y-6">
      {/* Header */}
      <div className="flex items-center justify-between">
        <h1 className="text-xl font-semibold text-gray-900">Certification Cockpit</h1>
        <button
          onClick={handleExport}
          className="rounded-lg bg-emerald-600 px-4 py-2 text-sm font-medium text-white hover:bg-emerald-700 transition-colors"
        >
          Export Excel
        </button>
      </div>

      {/* Summary Tiles */}
      {summary && (
        <div className="grid grid-cols-2 gap-4 sm:grid-cols-4 lg:grid-cols-7">
          <Tile label="Active" value={summary.active_certificates} color="text-green-700" />
          <Tile label="Expiring (90d)" value={summary.expiring_in_90_days} color="text-orange-700" />
          <Tile label="Surv Due (30d)" value={summary.surveillance_due_in_30_days} color="text-yellow-700" />
          <Tile label="Overdue Surv" value={summary.overdue_surveillance} color="text-red-700" />
          <Tile label="Expired" value={summary.expired} color="text-red-700" />
          <Tile label="Outstanding" value={fmtMoney(summary.total_outstanding)} color="text-gray-900" />
          <Tile label="Collected" value={fmtMoney(summary.total_collected)} color="text-emerald-700" />
        </div>
      )}

      {/* Filters */}
      <div className="flex flex-wrap items-center gap-3">
        <input
          className="rounded-lg border border-gray-200 px-3 py-1.5 text-sm focus:outline-none focus:ring-2 focus:ring-emerald-500"
          placeholder="Search company..."
          value={search}
          onChange={(e) => setSearch(e.target.value)}
        />
        <select
          className="rounded-lg border border-gray-200 px-3 py-1.5 text-sm focus:outline-none focus:ring-2 focus:ring-emerald-500"
          value={statusFilter}
          onChange={(e) => setStatusFilter(e.target.value)}
        >
          <option value="">All Statuses</option>
          <option value="active">Active</option>
          <option value="expiring_soon">Expiring Soon</option>
          <option value="expired">Expired</option>
          <option value="suspended">Suspended</option>
          <option value="withdrawn">Withdrawn</option>
          <option value="in_progress">In Progress</option>
        </select>
        <select
          className="rounded-lg border border-gray-200 px-3 py-1.5 text-sm focus:outline-none focus:ring-2 focus:ring-emerald-500"
          value={standardFilter}
          onChange={(e) => setStandardFilter(e.target.value)}
        >
          <option value="">All Standards</option>
          <option value="ISO 9001">ISO 9001</option>
          <option value="ISO 14001">ISO 14001</option>
          <option value="ISO 45001">ISO 45001</option>
          <option value="ISO 22000">ISO 22000</option>
          <option value="ISO 27001">ISO 27001</option>
        </select>
        <select
          className="rounded-lg border border-gray-200 px-3 py-1.5 text-sm focus:outline-none focus:ring-2 focus:ring-emerald-500"
          value={paymentFilter}
          onChange={(e) => setPaymentFilter(e.target.value)}
        >
          <option value="">All Payments</option>
          <option value="paid">Paid</option>
          <option value="partially_paid">Partially Paid</option>
          <option value="unpaid">Unpaid</option>
          <option value="overdue">Overdue</option>
        </select>
        <input
          className="rounded-lg border border-gray-200 px-3 py-1.5 text-sm focus:outline-none focus:ring-2 focus:ring-emerald-500"
          placeholder="Consultant ID..."
          value={consultantFilter}
          onChange={(e) => setConsultantFilter(e.target.value)}
        />
        <select
          className="rounded-lg border border-gray-200 px-3 py-1.5 text-sm focus:outline-none focus:ring-2 focus:ring-emerald-500"
          value={overdueBucket}
          onChange={(e) => setOverdueBucket(e.target.value)}
        >
          <option value="">All Buckets</option>
          <option value="due_this_month">Due This Month</option>
          <option value="due_in_30_days">Due in 30 Days</option>
          <option value="overdue">Overdue</option>
          <option value="recert_due">Recert Due</option>
          <option value="expiring_soon">Expiring Soon</option>
          <option value="expired">Expired</option>
        </select>
      </div>

      {/* Table */}
      {loading ? (
        <p className="text-sm text-gray-400">Loading...</p>
      ) : (
        <div className="overflow-x-auto rounded-xl border border-gray-200 bg-white shadow-sm">
          <table className="w-full text-sm">
            <thead>
              <tr className="border-b border-gray-100 text-left text-xs text-gray-400">
                <th className="px-4 py-3">Company</th>
                <th className="px-4 py-3">Standard</th>
                <th className="px-4 py-3">Cert #</th>
                <th className="px-4 py-3">Status</th>
                <th className="px-4 py-3">Issued</th>
                <th className="px-4 py-3">Expires</th>
                <th className="px-4 py-3">Next Surv Due</th>
                <th className="px-4 py-3">Countdown</th>
                <th className="px-4 py-3">Payment</th>
                <th className="px-4 py-3">Outstanding</th>
                <th className="px-4 py-3">Auditor</th>
                <th className="px-4 py-3">Consultant</th>
                <th className="px-4 py-3"></th>
              </tr>
            </thead>
            <tbody>
              {filtered.length === 0 ? (
                <tr>
                  <td colSpan={13} className="px-4 py-8 text-center text-sm text-gray-400">No certificates found.</td>
                </tr>
              ) : filtered.map((c, i) => (
                <tr key={`${c.audit_set_id}-${c.standard}`} className={i % 2 === 0 ? 'bg-white' : 'bg-gray-50'}>
                  <td className="px-4 py-3 font-medium text-gray-900">{c.company_name}</td>
                  <td className="px-4 py-3 text-gray-600 text-xs">{c.standard}</td>
                  <td className="px-4 py-3 text-gray-600 text-xs">{c.certificate_number || '\u2014'}</td>
                  <td className="px-4 py-3">
                    <span className={`rounded-full px-2 py-0.5 text-xs font-medium ${STATUS_COLORS[c.lifecycle_status] ?? 'bg-gray-100 text-gray-600'}`}>
                      {c.lifecycle_status.replace(/_/g, ' ')}
                    </span>
                  </td>
                  <td className="px-4 py-3 text-gray-600">{fmtDate(c.cert_issued_date)}</td>
                  <td className="px-4 py-3 text-gray-600">{fmtDate(c.cert_expiry_date)}</td>
                  <td className="px-4 py-3 text-gray-600">{fmtDate(c.next_surveillance_due)}</td>
                  <td className="px-4 py-3">
                    {c.countdown_days != null ? (
                      <span className={`text-xs font-medium ${c.countdown_days < 0 ? 'text-red-600' : c.countdown_days < 30 ? 'text-orange-600' : 'text-gray-600'}`}>
                        {c.countdown_days}d
                      </span>
                    ) : '\u2014'}
                  </td>
                  <td className="px-4 py-3">
                    <span className={`rounded-full px-2 py-0.5 text-xs font-medium ${PAYMENT_COLORS[c.payment_status] ?? 'bg-gray-100 text-gray-600'}`}>
                      {c.payment_status.replace(/_/g, ' ')}
                    </span>
                  </td>
                  <td className="px-4 py-3 text-gray-600">{fmtMoney(c.outstanding)}</td>
                  <td className="px-4 py-3 text-gray-600 text-xs">{c.assigned_auditor || '\u2014'}</td>
                  <td className="px-4 py-3 text-gray-600 text-xs">{c.consultant_name || '\u2014'}</td>
                  <td className="px-4 py-3">
                    <Link href={`/crm/certificates/${c.audit_set_id}`} className="text-xs text-emerald-700 hover:underline">View &rarr;</Link>
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

function Tile({ label, value, color }: { label: string; value: string | number; color: string }) {
  return (
    <div className="rounded-xl border border-gray-200 bg-white p-4 shadow-sm">
      <p className="text-xs font-semibold uppercase tracking-wide text-gray-400">{label}</p>
      <p className={`mt-1 text-lg font-bold ${color}`}>{value}</p>
    </div>
  )
}
