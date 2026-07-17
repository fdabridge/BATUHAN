'use client'

import { useState, useEffect, useRef } from 'react'
import Link from 'next/link'
import { useRouter } from 'next/navigation'
import { Search, Trash2, Loader2 } from 'lucide-react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import api from '@/lib/api'
import { useAuth } from '@/lib/auth'
import { CertBadge } from '@/components/ui/CertBadge'
import type { ClientSummary } from '@/types'

const CAN_DELETE_ROLES = new Set(['admin', 'planner'])

// ── Constants ─────────────────────────────────────────────────────────────────

const LIMIT = 20

const STATUS_OPTIONS = [
  { value: '',                  label: 'All statuses' },
  { value: 'active',            label: 'Active' },
  { value: 'approaching_expiry',label: 'Approaching renewal' },
  { value: 'expired',           label: 'Expired' },
  { value: 'no_certificate',    label: 'No certificate' },
]

const STANDARD_OPTIONS = [
  { value: '', label: 'All standards' },
  { value: 'QMS',   label: 'QMS' },
  { value: 'EMS',   label: 'EMS' },
  { value: 'OHSMS', label: 'OHSMS' },
  { value: 'FSMS',  label: 'FSMS' },
  { value: 'ISMS',  label: 'ISMS' },
  { value: 'MDQMS', label: 'MDQMS' },
  { value: 'ABMS',  label: 'ABMS' },
  { value: 'ENMS',  label: 'ENMS' },
]

// ── Helpers ───────────────────────────────────────────────────────────────────

function formatDate(iso: string | null): string {
  if (!iso) return '—'
  const [y, m, d] = iso.split('-')
  return `${d}/${m}/${y}`
}

function auditTypeLabel(t: string): string {
  if (t === 'initial')         return 'Initial'
  if (t === 'surveillance')    return 'Surveillance'
  if (t === 'surveillance_1')  return 'Surveillance 1'
  if (t === 'surveillance_2')  return 'Surveillance 2'
  if (t === 'recertification') return 'Recertification'
  return t
}

function Standards({ list }: { list: string[] }) {
  const shown = list.slice(0, 3)
  const extra = list.length - 3
  return (
    <span className="text-gray-500" style={{ fontSize: 13 }}>
      {shown.join(', ')}{extra > 0 && <span className="ml-1 text-gray-400">+{extra} more</span>}
    </span>
  )
}

// ── Debounce hook ─────────────────────────────────────────────────────────────

function useDebounce(value: string, delay: number) {
  const [debounced, setDebounced] = useState(value)
  useEffect(() => {
    const t = setTimeout(() => setDebounced(value), delay)
    return () => clearTimeout(t)
  }, [value, delay])
  return debounced
}

// ── Skeleton row ──────────────────────────────────────────────────────────────

function SkeletonRow() {
  return (
    <tr>
      {[64, 180, 110, 90, 80, 80, 40].map((w, i) => (
        <td key={i} className="px-4 py-3">
          <div className="h-3 animate-pulse rounded bg-gray-100" style={{ width: w }} />
        </td>
      ))}
    </tr>
  )
}

// ── Filter bar ────────────────────────────────────────────────────────────────

interface FilterBarProps {
  search: string
  status: string
  standard: string
  hasActive: boolean
  onSearch: (v: string) => void
  onStatus: (v: string) => void
  onStandard: (v: string) => void
  onClear: () => void
}

const selectClass =
  'rounded-md border border-gray-200 bg-white px-3 py-1.5 text-sm text-gray-700 outline-none focus:ring-2 focus:ring-certiva-primary/30'

function FilterBar({ search, status, standard, hasActive, onSearch, onStatus, onStandard, onClear }: FilterBarProps) {
  return (
    <div className="mb-4 flex flex-row items-center gap-3 rounded-lg border border-gray-100 bg-white px-4 py-3.5">
      {/* Search */}
      <div className="relative" style={{ width: 280 }}>
        <Search className="absolute left-2.5 top-1/2 -translate-y-1/2 text-gray-400" size={14} />
        <input
          type="text"
          placeholder="Search by company or client reference…"
          value={search}
          onChange={(e) => onSearch(e.target.value)}
          className="w-full rounded-md border border-gray-200 bg-white py-1.5 pl-8 pr-3 text-sm text-gray-700 placeholder-gray-400 outline-none focus:ring-2 focus:ring-certiva-primary/30"
        />
      </div>

      {/* Status */}
      <select value={status} onChange={(e) => onStatus(e.target.value)} className={selectClass}>
        {STATUS_OPTIONS.map((o) => (
          <option key={o.value} value={o.value}>{o.label}</option>
        ))}
      </select>

      {/* Standard */}
      <select value={standard} onChange={(e) => onStandard(e.target.value)} className={selectClass}>
        {STANDARD_OPTIONS.map((o) => (
          <option key={o.value} value={o.value}>{o.label}</option>
        ))}
      </select>

      {/* Clear */}
      {hasActive && (
        <button
          onClick={onClear}
          className="ml-auto text-certiva-primary transition-opacity hover:opacity-70"
          style={{ fontSize: 13 }}
        >
          Clear filters
        </button>
      )}
    </div>
  )
}

// ── Main page ─────────────────────────────────────────────────────────────────

export default function ClientsPage() {
  const router = useRouter()
  const queryClient = useQueryClient()
  const { user: currentUser } = useAuth()
  const canDelete = !!currentUser && CAN_DELETE_ROLES.has(currentUser.role)

  // Filter state
  const [searchRaw, setSearchRaw]   = useState('')
  const [status, setStatus]         = useState('')
  const [standard, setStandard]     = useState('')
  const [page, setPage]             = useState(1)
  const [deletingId, setDeletingId] = useState<string | null>(null)
  const [deleteError, setDeleteError] = useState<string | null>(null)

  const { mutate: deletePlan } = useMutation({
    mutationFn: (id: string) => api.delete(`/audit-sets/${id}`),
    onMutate:   (id: string) => { setDeletingId(id); setDeleteError(null) },
    onSuccess:  () => { queryClient.invalidateQueries({ queryKey: ['clients'] }) },
    onError:    (e: unknown) => {
      const detail = (e as { response?: { data?: { detail?: string } } })?.response?.data?.detail
      setDeleteError(detail ?? 'Failed to delete plan')
    },
    onSettled:  () => setDeletingId(null),
  })

  function handleDelete(c: ClientSummary, e: React.MouseEvent) {
    e.stopPropagation()
    const ref = c.client_reference || `#${c.plan_number}`
    if (window.confirm(`Delete plan ${ref} for ${c.company_name}? This cannot be undone.`)) {
      deletePlan(c.id)
    }
  }

  const search = useDebounce(searchRaw, 400)

  // Reset page when filters change
  const prevFilters = useRef({ search, status, standard })
  useEffect(() => {
    const p = prevFilters.current
    if (p.search !== search || p.status !== status || p.standard !== standard) {
      setPage(1)
      prevFilters.current = { search, status, standard }
    }
  }, [search, status, standard])

  const hasActive = !!(searchRaw || status || standard)

  function clearFilters() {
    setSearchRaw('')
    setStatus('')
    setStandard('')
    setPage(1)
  }

  // Query
  const { data: clients, isLoading } = useQuery<ClientSummary[]>({
    queryKey: ['clients', { search, status, standard, page }],
    queryFn: async () => {
      const params: Record<string, string | number> = { limit: LIMIT, offset: (page - 1) * LIMIT }
      if (search)   params.search   = search
      if (standard) params.standard = standard
      // Map cert_status filter — skip 'no_certificate' (backend doesn't have that literal)
      if (status && status !== 'no_certificate') params.cert_status = status
      const res = await api.get<ClientSummary[]>('/dashboard/clients', { params })
      return res.data
    },
  })

  // Pagination helpers
  const total   = clients?.length ?? 0
  const start   = (page - 1) * LIMIT + 1
  const end     = (page - 1) * LIMIT + total
  const hasNext = total === LIMIT
  const hasPrev = page > 1

  // Filter client-side for no_certificate
  const rows = status === 'no_certificate'
    ? (clients ?? []).filter((c) => c.cert_status === null)
    : (clients ?? [])

  return (
    <>
      {/* Page header */}
      <div className="mb-5 flex items-center justify-between">
        <h1 className="text-xl font-semibold text-gray-800">Clients</h1>
        <Link
          href="/clients/new"
          className="rounded-md px-3 py-1.5 text-white transition-opacity hover:opacity-90"
          style={{ background: '#1A4731', fontSize: 13 }}
        >
          + New client
        </Link>
      </div>

      {/* Filters */}
      <FilterBar
        search={searchRaw}
        status={status}
        standard={standard}
        hasActive={hasActive}
        onSearch={setSearchRaw}
        onStatus={setStatus}
        onStandard={setStandard}
        onClear={clearFilters}
      />

      {/* Delete error toast */}
      {deleteError && (
        <div className="mb-3 flex items-center justify-between rounded-lg border border-red-200 bg-red-50 px-4 py-2 text-sm text-red-700">
          <span>{deleteError}</span>
          <button onClick={() => setDeleteError(null)} className="text-xs text-red-600 hover:opacity-70">Dismiss</button>
        </div>
      )}

      {/* Table card */}
      <div className="rounded-lg border border-gray-100 bg-white">
        <div className="overflow-x-auto">
          <table className="w-full text-sm">
            <thead>
              <tr className="border-b border-gray-100 text-left text-xs font-medium uppercase tracking-wide text-gray-400">
                <th className="px-4 py-2.5" style={{ width: 64 }}>Plan no.</th>
                <th className="px-4 py-2.5">Company</th>
                <th className="px-4 py-2.5">Standards</th>
                <th className="px-4 py-2.5">Audit type</th>
                <th className="px-4 py-2.5">Cert status</th>
                <th className="px-4 py-2.5">Expiry</th>
                <th className="px-4 py-2.5">Actions</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-gray-50">
              {isLoading
                ? Array.from({ length: 8 }).map((_, i) => <SkeletonRow key={i} />)
                : rows.length === 0
                ? (
                  <tr>
                    <td colSpan={7} className="px-4 py-12 text-center text-sm text-gray-400">
                      No clients found.{hasActive && ' Try clearing your filters.'}
                    </td>
                  </tr>
                )
                : rows.map((c) => (
                  <tr
                    key={c.id}
                    className="cursor-pointer hover:bg-gray-50"
                    onClick={() => router.push(`/clients/${c.id}`)}
                  >
                    <td className="px-4 py-3 font-mono text-gray-400" style={{ fontSize: 13 }}>
                      {c.client_reference ? c.client_reference : `#${c.plan_number}`}
                    </td>
                    <td className="px-4 py-3 font-medium">
                      <Link
                        href={`/clients/${c.id}`}
                        className="hover:underline"
                        onClick={(e) => e.stopPropagation()}
                      >
                        {c.company_name}
                      </Link>
                      {c.client_reference && (
                        <span className="ml-2 font-mono text-gray-300" style={{ fontSize: 12 }}>
                          #{c.plan_number}
                        </span>
                      )}
                    </td>
                    <td className="px-4 py-3">
                      <Standards list={c.standards} />
                    </td>
                    <td className="px-4 py-3 text-gray-500" style={{ fontSize: 13 }}>
                      {auditTypeLabel(c.audit_type)}
                    </td>
                    <td className="px-4 py-3">
                      <CertBadge status={c.cert_status} />
                    </td>
                    <td className="px-4 py-3 text-gray-500" style={{ fontSize: 13 }}>
                      {formatDate(c.cert_expiry_date)}
                    </td>
                    <td className="px-4 py-3">
                      <div className="flex items-center gap-3">
                        <Link
                          href={`/clients/${c.id}`}
                          className="text-certiva-primary transition-opacity hover:opacity-70"
                          style={{ fontSize: 13 }}
                          onClick={(e) => e.stopPropagation()}
                        >
                          View
                        </Link>
                        {canDelete && (
                          <button
                            type="button"
                            title="Delete plan"
                            disabled={deletingId === c.id}
                            onClick={(e) => handleDelete(c, e)}
                            className="text-gray-300 transition-colors hover:text-red-600 disabled:opacity-50"
                          >
                            {deletingId === c.id
                              ? <Loader2 size={14} className="animate-spin" />
                              : <Trash2 size={14} />}
                          </button>
                        )}
                      </div>
                    </td>
                  </tr>
                ))
              }
            </tbody>
          </table>
        </div>

        {/* Pagination */}
        {!isLoading && rows.length > 0 && (
          <div className="flex items-center justify-between border-t border-gray-100 px-4 py-3">
            <span className="text-xs text-gray-400">
              Showing {start}–{end}
            </span>
            <div className="flex gap-2">
              <button
                disabled={!hasPrev}
                onClick={() => setPage((p) => p - 1)}
                className="rounded-md border border-gray-200 px-3 py-1 text-xs text-gray-600 disabled:cursor-not-allowed disabled:opacity-40 hover:enabled:bg-gray-50"
              >
                Previous
              </button>
              <button
                disabled={!hasNext}
                onClick={() => setPage((p) => p + 1)}
                className="rounded-md border border-gray-200 px-3 py-1 text-xs text-gray-600 disabled:cursor-not-allowed disabled:opacity-40 hover:enabled:bg-gray-50"
              >
                Next
              </button>
            </div>
          </div>
        )}
      </div>
    </>
  )
}
