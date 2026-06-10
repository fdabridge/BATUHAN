'use client'

import { useState } from 'react'
import Link from 'next/link'
import { useQuery } from '@tanstack/react-query'
import api from '@/lib/api'
import { CertBadge } from '@/components/ui/CertBadge'
import { PendingSignaturesWidget } from '@/components/ui/PendingSignaturesWidget'
import type { DashboardStats, ClientSummary } from '@/types'

// ── Helpers ───────────────────────────────────────────────────────────────────

function formatDate(iso: string | null): string {
  if (!iso) return '—'
  const [y, m, d] = iso.split('-')
  return `${d}/${m}/${y}`
}

// ── Stat cards ────────────────────────────────────────────────────────────────

type StatKey = keyof Pick<
  DashboardStats,
  'total_plans' | 'active_certificates' | 'approaching_expiry' | 'expired'
>

const CARD_CONFIGS: { key: StatKey; label: string; color: string }[] = [
  { key: 'total_plans',         label: 'Total plans',         color: '#1A4731' },
  { key: 'active_certificates', label: 'Active certificates', color: '#52B788' },
  { key: 'approaching_expiry',  label: 'Approaching renewal', color: '#F4A261' },
  { key: 'expired',             label: 'Expired',             color: '#E63946' },
]

function StatCards({
  stats,
  isLoading,
}: {
  stats?: DashboardStats
  isLoading: boolean
}) {
  return (
    <div className="grid grid-cols-4 gap-4">
      {CARD_CONFIGS.map(({ key, label, color }) => (
        <div key={key} className="rounded-lg border border-gray-100 bg-white p-5">
          <p
            className="mb-1 uppercase"
            style={{ fontSize: 11, fontWeight: 500, color: '#9CA3AF', letterSpacing: '0.08em' }}
          >
            {label}
          </p>
          {isLoading ? (
            <div className="mt-1 h-7 w-12 animate-pulse rounded bg-gray-100" />
          ) : (
            <p style={{ fontSize: 28, fontWeight: 500, color, lineHeight: 1.1 }}>
              {stats?.[key] ?? 0}
            </p>
          )}
        </div>
      ))}
    </div>
  )
}

// ── Skeleton row ──────────────────────────────────────────────────────────────

function SkeletonRow() {
  return (
    <tr>
      {[60, 180, 100, 90, 80, 50].map((w, i) => (
        <td key={i} className="px-4 py-3">
          <div className="h-3 animate-pulse rounded bg-gray-100" style={{ width: w }} />
        </td>
      ))}
    </tr>
  )
}

// ── Client table ─────────────────────────────────────────────────────────────

const LIMIT = 20

function ClientTable() {
  const [page, setPage] = useState(1)
  const offset = (page - 1) * LIMIT

  const { data: clients, isLoading } = useQuery<ClientSummary[]>({
    queryKey: ['dashboard-clients', page],
    queryFn: () =>
      api
        .get<ClientSummary[]>('/dashboard/clients', { params: { limit: LIMIT, offset } })
        .then((r) => r.data),
  })

  const hasNext = (clients?.length ?? 0) === LIMIT

  return (
    <div className="rounded-lg border border-gray-100 bg-white">

      {/* Header row */}
      <div className="flex items-center justify-between px-5 py-4">
        <span style={{ fontSize: 14, fontWeight: 500 }}>Certification plans</span>
        <Link
          href="/clients/new"
          className="rounded-md px-3 py-1.5 text-white transition-opacity hover:opacity-90"
          style={{ background: '#1A4731', fontSize: 13 }}
        >
          + New plan
        </Link>
      </div>

      {/* Table */}
      <div className="overflow-x-auto">
        <table className="w-full text-sm">
          <thead>
            <tr className="border-t border-gray-100 text-left text-xs font-medium uppercase tracking-wide text-gray-400">
              <th className="px-4 py-2.5" style={{ width: 60 }}>Plan no.</th>
              <th className="px-4 py-2.5">Company</th>
              <th className="px-4 py-2.5">Standards</th>
              <th className="px-4 py-2.5">Cert status</th>
              <th className="px-4 py-2.5">Expiry date</th>
              <th className="px-4 py-2.5">Actions</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-gray-50">
            {isLoading
              ? Array.from({ length: 5 }).map((_, i) => <SkeletonRow key={i} />)
              : clients?.map((c) => (
                  <tr key={c.id} className="hover:bg-gray-50/40">
                    <td className="px-4 py-3 font-mono text-xs text-gray-500">
                      #{c.plan_number}
                    </td>
                    <td className="px-4 py-3 font-medium">{c.company_name}</td>
                    <td className="px-4 py-3 text-gray-500" style={{ fontSize: 13 }}>
                      {c.standards.join(', ')}
                    </td>
                    <td className="px-4 py-3">
                      <CertBadge status={c.cert_status} />
                    </td>
                    <td className="px-4 py-3 text-gray-500" style={{ fontSize: 13 }}>
                      {formatDate(c.cert_expiry_date)}
                    </td>
                    <td className="px-4 py-3">
                      <Link
                        href={`/clients/${c.id}`}
                        className="text-certiva-primary hover:underline"
                        style={{ fontSize: 13 }}
                      >
                        View
                      </Link>
                    </td>
                  </tr>
                ))}
          </tbody>
        </table>

        {/* Empty state */}
        {!isLoading && (clients?.length ?? 0) === 0 && (
          <div className="flex flex-col items-center gap-2 py-16 text-center text-gray-400">
            <p>No certification plans yet.</p>
            <Link
              href="/clients/new"
              className="text-sm text-certiva-primary hover:underline"
            >
              + Create your first plan
            </Link>
          </div>
        )}
      </div>

      {/* Pagination */}
      <div className="flex items-center justify-between border-t border-gray-100 px-5 py-3">
        <button
          onClick={() => setPage((p) => Math.max(1, p - 1))}
          disabled={page === 1}
          className="rounded px-3 py-1.5 text-sm text-gray-500 hover:bg-gray-50 disabled:opacity-40"
        >
          Previous
        </button>
        <span className="text-xs text-gray-400">Page {page}</span>
        <button
          onClick={() => setPage((p) => p + 1)}
          disabled={!hasNext}
          className="rounded px-3 py-1.5 text-sm text-gray-500 hover:bg-gray-50 disabled:opacity-40"
        >
          Next
        </button>
      </div>

    </div>
  )
}

// ── Page ──────────────────────────────────────────────────────────────────────

export default function DashboardPage() {
  const { data: stats, isLoading: statsLoading } = useQuery<DashboardStats>({
    queryKey: ['dashboard-stats'],
    queryFn: () => api.get<DashboardStats>('/dashboard/stats').then((r) => r.data),
  })

  return (
    <div className="flex flex-col gap-6">
      <StatCards stats={stats} isLoading={statsLoading} />
      <PendingSignaturesWidget />
      <ClientTable />
    </div>
  )
}
