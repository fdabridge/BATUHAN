'use client'

import Link from 'next/link'
import { Plus } from 'lucide-react'
import { useQuery } from '@tanstack/react-query'
import api from '@/lib/api'
import type { JobListEntry } from '@/types'

// ── Helpers ───────────────────────────────────────────────────────────────────

function shortId(id: string): string {
  return (id || '').slice(0, 8)
}

function formatDateTime(iso: string | null | undefined): string {
  if (!iso) return '—'
  try {
    const d = new Date(iso)
    if (isNaN(d.getTime())) return '—'
    return d.toLocaleString(undefined, {
      year: 'numeric', month: 'short', day: '2-digit',
      hour: '2-digit', minute: '2-digit',
    })
  } catch { return '—' }
}

type StatusKind = 'done' | 'failed' | 'progress'

function statusKind(state: string): StatusKind {
  const s = (state || '').toUpperCase()
  if (s === 'COMPLETE' || s === 'DONE') return 'done'
  if (s === 'FAILED') return 'failed'
  return 'progress'
}

// ── Sub-components ────────────────────────────────────────────────────────────

function StatusBadge({ state }: { state: string }) {
  const kind = statusKind(state)
  if (kind === 'done') {
    return (
      <span className="rounded px-2 py-0.5 text-xs font-medium" style={{ background: '#F0FAF4', color: '#1A4731' }}>
        Done
      </span>
    )
  }
  if (kind === 'failed') {
    return (
      <span className="rounded px-2 py-0.5 text-xs font-medium" style={{ background: '#FEF2F2', color: '#B91C1C' }}>
        Failed
      </span>
    )
  }
  return (
    <span
      className="inline-flex items-center gap-1.5 rounded px-2 py-0.5 text-xs font-medium"
      style={{ background: '#FEF3C7', color: '#92400E' }}
    >
      <span
        className="inline-block h-1.5 w-1.5 animate-pulse rounded-full"
        style={{ background: '#92400E' }}
      />
      In progress
    </span>
  )
}

function SkeletonRow() {
  return (
    <tr className="border-b border-gray-50 last:border-0">
      {Array.from({ length: 7 }).map((_, i) => (
        <td key={i} className="px-4 py-3">
          <div className="h-3 w-full animate-pulse rounded bg-gray-100" />
        </td>
      ))}
    </tr>
  )
}

function EmptyState() {
  return (
    <div className="flex flex-col items-center justify-center py-16 text-center">
      <p className="text-gray-500" style={{ fontSize: 14 }}>No reports yet.</p>
      <Link
        href="/reports/new"
        className="mt-2 text-certiva-primary hover:underline"
        style={{ fontSize: 13 }}
      >
        Generate your first report →
      </Link>
    </div>
  )
}


// ── Main page ────────────────────────────────────────────────────────────────

export default function ReportsPage() {
  const { data, isLoading, isError } = useQuery<JobListEntry[]>({
    queryKey: ['jobs'],
    queryFn:  () => api.get<JobListEntry[]>('/jobs/').then((r) => r.data),
    refetchInterval: 5000,
  })

  const jobs = data ?? []

  return (
    <div className="mx-auto max-w-[1200px] space-y-5 py-4">
      {/* Header */}
      <div className="flex items-center justify-between">
        <h1 className="text-gray-800" style={{ fontSize: 22, fontWeight: 500 }}>AI Reports</h1>
        <Link
          href="/reports/new"
          className="flex items-center gap-1 rounded-lg bg-certiva-primary px-3 py-2 text-sm font-medium text-white hover:opacity-90"
        >
          <Plus size={14} /> New report
        </Link>
      </div>

      {/* Table */}
      <div className="overflow-hidden rounded-lg border border-gray-100 bg-white">
        <table className="w-full text-sm">
          <thead>
            <tr className="border-b border-gray-100 bg-gray-50 text-left text-xs font-medium text-gray-500">
              <th className="px-4 py-3">Job ID</th>
              <th className="px-4 py-3">Company</th>
              <th className="px-4 py-3">Standard</th>
              <th className="px-4 py-3">Stage</th>
              <th className="px-4 py-3">Status</th>
              <th className="px-4 py-3">Submitted</th>
              <th className="px-4 py-3 text-right">Actions</th>
            </tr>
          </thead>
          <tbody>
            {isLoading && Array.from({ length: 5 }).map((_, i) => <SkeletonRow key={i} />)}
            {isError && (
              <tr><td colSpan={7} className="py-10 text-center text-sm text-red-500">Failed to load reports.</td></tr>
            )}
            {!isLoading && !isError && jobs.length === 0 && (
              <tr><td colSpan={7}><EmptyState /></td></tr>
            )}
            {!isLoading && !isError && jobs.map((j) => (
              <tr key={j.job_id} className="border-b border-gray-50 last:border-0">
                <td className="px-4 py-3">
                  <span className="font-mono text-gray-700" style={{ fontSize: 13 }}>{shortId(j.job_id)}</span>
                </td>
                <td className="px-4 py-3 text-gray-800" style={{ fontWeight: 500 }}>
                  {j.company || <span className="text-gray-400">—</span>}
                </td>
                <td className="px-4 py-3 text-gray-700" style={{ fontSize: 13 }}>
                  {(j.standards && j.standards.length > 0) ? j.standards.join(', ') : '—'}
                </td>
                <td className="px-4 py-3 text-gray-700" style={{ fontSize: 13 }}>{j.stage || '—'}</td>
                <td className="px-4 py-3"><StatusBadge state={j.state} /></td>
                <td className="px-4 py-3 text-gray-500" style={{ fontSize: 13 }}>{formatDateTime(j.submitted_at)}</td>
                <td className="px-4 py-3 text-right">
                  <Link
                    href={`/reports/${j.job_id}`}
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
      </div>
    </div>
  )
}
