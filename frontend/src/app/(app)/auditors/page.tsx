'use client'

import Link from 'next/link'
import { useRouter } from 'next/navigation'
import { AlertTriangle } from 'lucide-react'
import { useQuery } from '@tanstack/react-query'
import api from '@/lib/api'
import type { AuditorDashboardEntry } from '@/types'

// ── Helpers ───────────────────────────────────────────────────────────────────

function hasWarnings(a: AuditorDashboardEntry): boolean {
  return a.qualifications.some((q) => q.training_expiry_warning || q.verification_warning)
}

function lastAuditLabel(a: AuditorDashboardEntry): string {
  if (a.total_audits === 0) return 'Never'
  if (a.days_since_last_audit == null) return '—'
  return `${a.days_since_last_audit} days ago`
}

function uniq(arr: (string | null | undefined)[]): string[] {
  return Array.from(new Set(arr.filter((x): x is string => !!x)))
}

// ── Stat card ─────────────────────────────────────────────────────────────────

function StatCard({ label, value }: { label: string; value: number }) {
  return (
    <div className="rounded-lg border border-gray-100 bg-white" style={{ padding: '0.875rem 1rem' }}>
      <p className="text-certiva-primary" style={{ fontSize: 24, fontWeight: 500 }}>{value}</p>
      <p className="mt-1 uppercase tracking-wide text-gray-400" style={{ fontSize: 11 }}>{label}</p>
    </div>
  )
}

// ── Status badge ──────────────────────────────────────────────────────────────

function StatusBadge({ a }: { a: AuditorDashboardEntry }) {
  if (!a.is_active) {
    return <span className="rounded px-2 py-0.5 text-xs" style={{ background: '#F3F4F6', color: '#6B7280' }}>Inactive</span>
  }
  if (hasWarnings(a)) {
    return (
      <span className="inline-flex items-center gap-1 rounded px-2 py-0.5 text-xs" style={{ background: '#FEF3C7', color: '#92400E' }}>
        <AlertTriangle size={12} /> Warnings
      </span>
    )
  }
  return <span className="rounded px-2 py-0.5 text-xs" style={{ background: '#F0FAF4', color: '#1A4731' }}>Active</span>
}

// ── Skeleton row ──────────────────────────────────────────────────────────────

function SkeletonRow() {
  return (
    <tr className="border-b border-gray-50">
      {Array.from({ length: 7 }).map((_, i) => (
        <td key={i} className="px-4 py-3">
          <div className="h-3 w-3/4 animate-pulse rounded bg-gray-100" />
        </td>
      ))}
    </tr>
  )
}

// ── Row ───────────────────────────────────────────────────────────────────────

function AuditorRow({ a, stds, overflow, onClick }: {
  a: AuditorDashboardEntry; stds: string[]; overflow: number; onClick: () => void
}) {
  return (
    <tr className="cursor-pointer hover:bg-gray-50" onClick={onClick}>
      <td className="px-4 py-3">
        <div className="font-medium text-gray-800">{a.name}</div>
        {a.role && <div className="text-gray-400" style={{ fontSize: 12 }}>{a.role}</div>}
      </td>
      <td className="px-4 py-3">
        <div className="flex flex-wrap gap-1">
          {stds.map((s) => (
            <span key={s} className="rounded px-1.5 py-0.5 font-medium" style={{ fontSize: 11, background: '#F0FAF4', color: '#1A4731' }}>
              {s}
            </span>
          ))}
          {overflow > 0 && (
            <span className="rounded px-1.5 py-0.5 text-gray-500" style={{ fontSize: 11, background: '#F3F4F6' }}>
              +{overflow}
            </span>
          )}
        </div>
      </td>
      <td className="px-4 py-3 text-gray-500" style={{ fontSize: 13 }}>{a.ea_codes.join(', ') || '—'}</td>
      <td className="px-4 py-3">
        <div className="flex flex-wrap gap-1">
          {a.accreditation_bodies.length === 0 && <span className="text-gray-400">—</span>}
          {a.accreditation_bodies.map((b) => (
            <span key={b} className="rounded px-1.5 py-0.5 text-gray-600" style={{ fontSize: 12, background: '#F3F4F6' }}>{b}</span>
          ))}
        </div>
      </td>
      <td className="px-4 py-3 text-gray-500" style={{ fontSize: 13 }}>{lastAuditLabel(a)}</td>
      <td className="px-4 py-3"><StatusBadge a={a} /></td>
      <td className="px-4 py-3">
        <Link
          href={`/auditors/${a.auditor_id}`}
          onClick={(e) => e.stopPropagation()}
          className="text-certiva-primary hover:underline"
          style={{ fontSize: 13 }}
        >
          View
        </Link>
      </td>
    </tr>
  )
}

// ── Main page ─────────────────────────────────────────────────────────────────

export default function AuditorsPage() {
  const router = useRouter()

  const { data, isLoading } = useQuery<AuditorDashboardEntry[]>({
    queryKey: ['auditors-dashboard'],
    queryFn: () => api.get<AuditorDashboardEntry[]>('/auditors/dashboard').then((r) => r.data),
  })

  const rows = data ?? []
  const totalCount   = rows.length
  const activeCount  = rows.filter((a) => a.is_active).length
  const warningCount = rows.filter((a) => a.is_active && hasWarnings(a)).length

  return (
    <>
      {/* Header */}
      <div className="mb-5 flex items-center justify-between">
        <h1 className="text-xl font-semibold text-gray-800">Auditors</h1>
      </div>

      {/* Stat row */}
      <div className="mb-5 grid grid-cols-3 gap-3">
        <StatCard label="Total auditors"   value={totalCount} />
        <StatCard label="Active"           value={activeCount} />
        <StatCard label="Expiry warnings"  value={warningCount} />
      </div>

      {/* Table */}
      <div className="rounded-lg border border-gray-100 bg-white">
        <div className="overflow-x-auto">
          <table className="w-full text-sm">
            <thead>
              <tr className="border-b border-gray-100 text-left text-xs font-medium uppercase tracking-wide text-gray-400">
                <th className="px-4 py-2.5">Auditor</th>
                <th className="px-4 py-2.5">Qualified standards</th>
                <th className="px-4 py-2.5">EA codes</th>
                <th className="px-4 py-2.5">Accreditation bodies</th>
                <th className="px-4 py-2.5">Last audit</th>
                <th className="px-4 py-2.5">Status</th>
                <th className="px-4 py-2.5">Actions</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-gray-50">
              {isLoading
                ? Array.from({ length: 6 }).map((_, i) => <SkeletonRow key={i} />)
                : rows.length === 0
                ? (
                  <tr>
                    <td colSpan={7} className="px-4 py-12 text-center text-sm text-gray-400">
                      No auditors yet.
                    </td>
                  </tr>
                )
                : rows.map((a) => {
                  const stds = uniq(a.qualifications.map((q) => q.standard_code))
                  const visible = stds.slice(0, 4)
                  const overflow = stds.length - visible.length
                  return (
                    <AuditorRow
                      key={a.auditor_id}
                      a={a}
                      stds={visible}
                      overflow={overflow}
                      onClick={() => router.push(`/auditors/${a.auditor_id}`)}
                    />
                  )
                })}
            </tbody>
          </table>
        </div>
      </div>
    </>
  )
}
