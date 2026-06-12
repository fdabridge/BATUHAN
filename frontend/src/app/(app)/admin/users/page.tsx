'use client'

import { useEffect, useRef, useState } from 'react'
import { Key, Loader2, Pencil, Plus, ShieldOff, Trash2, Upload, X } from 'lucide-react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import api from '@/lib/api'
import { useAuth } from '@/lib/auth'
import type {
  AdminResetPasswordPayload, AdminUser, AdminUserCreatePayload,
  AdminUserUpdatePayload, UserRole,
} from '@/types'

// ── Constants ─────────────────────────────────────────────────────────────────

const ROLES: { value: UserRole; label: string }[] = [
  { value: 'admin',                 label: 'Admin' },
  { value: 'planner',               label: 'Planning Officer' },
  { value: 'gm',                    label: 'General Manager' },
  { value: 'certification_manager', label: 'Certification Manager' },
  { value: 'auditor',               label: 'Auditor' },
  { value: 'officer',               label: 'Officer' },
  { value: 'executive',             label: 'Executive' },
  { value: 'client',                label: 'Client' },
]

const ROLE_PILL: Record<UserRole, string> = {
  admin:                 'bg-purple-50 text-purple-700',
  planner:               'bg-blue-50 text-blue-700',
  auditor:               'bg-certiva-surface text-certiva-primary',
  officer:               'bg-amber-50 text-amber-700',
  executive:             'bg-gray-100 text-gray-600',
  gm:                    'bg-rose-50 text-rose-700',
  certification_manager: 'bg-emerald-50 text-emerald-700',
  client:                'bg-sky-50 text-sky-700',
}

const inputCls = 'w-full rounded-lg border border-gray-200 px-3 py-2 text-sm text-gray-800 placeholder-gray-400 outline-none focus:border-certiva-primary focus:ring-2 focus:ring-certiva-primary/20'
const lblCls   = 'mb-1 block text-xs font-medium text-gray-500'

// ── Helpers ───────────────────────────────────────────────────────────────────

function initialsOf(fullName: string): string {
  return fullName.split(' ').filter(Boolean).slice(0, 2).map((w) => w[0]?.toUpperCase() ?? '').join('') || '?'
}

function formatDateTime(iso: string | null): string {
  if (!iso) return 'Never'
  const d = new Date(iso)
  if (isNaN(d.getTime())) return 'Never'
  const pad = (n: number) => String(n).padStart(2, '0')
  return `${pad(d.getDate())}/${pad(d.getMonth() + 1)}/${d.getFullYear()} ${pad(d.getHours())}:${pad(d.getMinutes())}`
}

function extractDetail(err: unknown, fallback: string): string {
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  const anyErr = err as any
  if (anyErr?.response?.data?.detail) return String(anyErr.response.data.detail)
  if (anyErr?.message)                return String(anyErr.message)
  return fallback
}

// ── Generic modal ─────────────────────────────────────────────────────────────

function Modal({
  open, title, onClose, children,
}: { open: boolean; title: string; onClose: () => void; children: React.ReactNode }) {
  useEffect(() => {
    if (!open) return
    const onKey = (e: KeyboardEvent) => { if (e.key === 'Escape') onClose() }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [open, onClose])

  if (!open) return null
  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 p-4">
      <div className="w-full max-w-md rounded-lg bg-white shadow-xl" onClick={(e) => e.stopPropagation()}>
        <div className="flex items-start justify-between border-b border-gray-100 px-5 py-3">
          <h2 className="text-sm font-semibold text-gray-800">{title}</h2>
          <button onClick={onClose} className="text-gray-400 hover:text-gray-700" aria-label="Close">
            <X size={16} />
          </button>
        </div>
        <div className="px-5 py-4">{children}</div>
      </div>
    </div>
  )
}

// ── Toggle switch ─────────────────────────────────────────────────────────────

function Switch({ checked, onChange }: { checked: boolean; onChange: (v: boolean) => void }) {
  return (
    <button
      type="button" role="switch" aria-checked={checked}
      onClick={() => onChange(!checked)}
      className={`relative inline-flex h-5 w-9 shrink-0 cursor-pointer rounded-full transition-colors ${
        checked ? 'bg-certiva-primary' : 'bg-gray-300'
      }`}
    >
      <span
        className={`inline-block h-4 w-4 transform rounded-full bg-white shadow transition-transform ${
          checked ? 'translate-x-4' : 'translate-x-0.5'
        } self-center`}
      />
    </button>
  )
}

// ── Toast ─────────────────────────────────────────────────────────────────────

function Toast({ message }: { message: string }) {
  return (
    <div className="fixed bottom-6 right-6 z-50 rounded-lg bg-certiva-primary px-4 py-2 text-sm text-white shadow-lg">
      ✓ {message}
    </div>
  )
}


// ── Modal: create user ────────────────────────────────────────────────────────

function CreateUserModal({
  open, onClose, onSuccess,
}: { open: boolean; onClose: () => void; onSuccess: () => void }) {
  const [form, setForm] = useState<AdminUserCreatePayload>({
    full_name: '', username: '', email: '', password: '', role: 'planner',
  })
  const [err, setErr] = useState<string | null>(null)

  useEffect(() => {
    if (open) { setForm({ full_name: '', username: '', email: '', password: '', role: 'planner' }); setErr(null) }
  }, [open])

  const m = useMutation({
    mutationFn: (payload: AdminUserCreatePayload) =>
      api.post<AdminUser>('/admin/users/', payload).then((r) => r.data),
    onSuccess: () => { onSuccess(); onClose() },
    onError:   (e) => setErr(extractDetail(e, 'Failed to create user.')),
  })

  function handleSubmit(ev: React.FormEvent) {
    ev.preventDefault()
    setErr(null)
    if (!form.full_name.trim() || !form.email.trim() || !form.password || !form.username?.trim()) {
      setErr('All fields are required.')
      return
    }
    m.mutate({ ...form, full_name: form.full_name.trim(), email: form.email.trim(), username: form.username?.trim() })
  }

  return (
    <Modal open={open} title="Add user" onClose={onClose}>
      <form onSubmit={handleSubmit} className="space-y-3">
        <div>
          <label className={lblCls}>Full name *</label>
          <input type="text" value={form.full_name}
            onChange={(e) => setForm((f) => ({ ...f, full_name: e.target.value }))} className={inputCls} />
        </div>
        <div>
          <label className={lblCls}>Username * <span className="font-normal text-gray-400">(used to log in)</span></label>
          <input
            type="text"
            value={form.username ?? ''}
            onChange={(e) => setForm((f) => ({ ...f, username: e.target.value.trim() }))}
            className={inputCls}
            placeholder="e.g. john.smith"
          />
        </div>
        <div>
          <label className={lblCls}>Email *</label>
          <input type="email" value={form.email}
            onChange={(e) => setForm((f) => ({ ...f, email: e.target.value }))} className={inputCls} />
        </div>
        <div>
          <label className={lblCls}>Password *</label>
          <input type="password" value={form.password}
            onChange={(e) => setForm((f) => ({ ...f, password: e.target.value }))} className={inputCls} />
        </div>
        <div>
          <label className={lblCls}>Role *</label>
          <select value={form.role}
            onChange={(e) => setForm((f) => ({ ...f, role: e.target.value as UserRole }))} className={inputCls}>
            {ROLES.map((r) => <option key={r.value} value={r.value}>{r.label}</option>)}
          </select>
        </div>

        {err && <div className="rounded border border-red-200 bg-red-50 px-3 py-2 text-xs text-red-700">{err}</div>}

        <button type="submit" disabled={m.isPending}
          className="flex w-full items-center justify-center gap-2 rounded-lg bg-certiva-primary px-4 py-2 text-sm font-medium text-white hover:opacity-90 disabled:opacity-60">
          {m.isPending && <Loader2 size={14} className="animate-spin" />}
          {m.isPending ? 'Creating…' : 'Create'}
        </button>
      </form>
    </Modal>
  )
}

// ── Modal: edit user ──────────────────────────────────────────────────────────

function EditUserModal({
  user, onClose, onSuccess,
}: { user: AdminUser | null; onClose: () => void; onSuccess: () => void }) {
  const [form, setForm] = useState<AdminUserUpdatePayload>({})
  const [err, setErr]   = useState<string | null>(null)

  useEffect(() => {
    if (user) {
      setForm({ full_name: user.full_name, role: user.role, is_active: user.is_active })
      setErr(null)
    }
  }, [user])

  const m = useMutation({
    mutationFn: (payload: AdminUserUpdatePayload) =>
      api.put<AdminUser>(`/admin/users/${user!.id}`, payload).then((r) => r.data),
    onSuccess: () => { onSuccess(); onClose() },
    onError:   (e) => setErr(extractDetail(e, 'Failed to update user.')),
  })

  function handleSubmit(ev: React.FormEvent) {
    ev.preventDefault()
    setErr(null)
    if (form.full_name !== undefined && !form.full_name.trim()) {
      setErr('Full name cannot be empty.'); return
    }
    m.mutate({ ...form, full_name: form.full_name?.trim() })
  }

  return (
    <Modal open={!!user} title={`Edit user — ${user?.full_name ?? ''}`} onClose={onClose}>
      <form onSubmit={handleSubmit} className="space-y-3">
        <div>
          <label className={lblCls}>Full name</label>
          <input type="text" value={form.full_name ?? ''}
            onChange={(e) => setForm((f) => ({ ...f, full_name: e.target.value }))} className={inputCls} />
        </div>
        <div>
          <label className={lblCls}>Role</label>
          <select value={form.role ?? 'planner'}
            onChange={(e) => setForm((f) => ({ ...f, role: e.target.value as UserRole }))} className={inputCls}>
            {ROLES.map((r) => <option key={r.value} value={r.value}>{r.label}</option>)}
          </select>
        </div>
        <div className="flex items-center justify-between rounded-lg border border-gray-100 px-3 py-2">
          <span className="text-sm text-gray-700">Active</span>
          <Switch checked={!!form.is_active}
            onChange={(v) => setForm((f) => ({ ...f, is_active: v }))} />
        </div>

        {err && <div className="rounded border border-red-200 bg-red-50 px-3 py-2 text-xs text-red-700">{err}</div>}

        <button type="submit" disabled={m.isPending}
          className="flex w-full items-center justify-center gap-2 rounded-lg bg-certiva-primary px-4 py-2 text-sm font-medium text-white hover:opacity-90 disabled:opacity-60">
          {m.isPending && <Loader2 size={14} className="animate-spin" />}
          {m.isPending ? 'Saving…' : 'Save'}
        </button>
      </form>
    </Modal>
  )
}
// ── Modal: reset password ─────────────────────────────────────────────────────

function ResetPasswordModal({
  user, onClose, onSuccess,
}: { user: AdminUser | null; onClose: () => void; onSuccess: () => void }) {
  const [pw1, setPw1] = useState('')
  const [pw2, setPw2] = useState('')
  const [err, setErr] = useState<string | null>(null)

  useEffect(() => {
    if (user) { setPw1(''); setPw2(''); setErr(null) }
  }, [user])

  const m = useMutation({
    mutationFn: (payload: AdminResetPasswordPayload) =>
      api.post(`/admin/users/${user!.id}/reset-password`, payload).then((r) => r.data),
    onSuccess: () => { onSuccess(); onClose() },
    onError:   (e) => setErr(extractDetail(e, 'Failed to reset password.')),
  })

  function handleSubmit(ev: React.FormEvent) {
    ev.preventDefault()
    setErr(null)
    if (!pw1 || !pw2)   { setErr('Both fields are required.'); return }
    if (pw1 !== pw2)    { setErr('Passwords do not match.');   return }
    m.mutate({ new_password: pw1 })
  }

  return (
    <Modal open={!!user} title={`Reset password — ${user?.full_name ?? ''}`} onClose={onClose}>
      <form onSubmit={handleSubmit} className="space-y-3">
        <div>
          <label className={lblCls}>New password *</label>
          <input type="password" value={pw1} onChange={(e) => setPw1(e.target.value)} className={inputCls} />
        </div>
        <div>
          <label className={lblCls}>Confirm password *</label>
          <input type="password" value={pw2} onChange={(e) => setPw2(e.target.value)} className={inputCls} />
        </div>

        {err && <div className="rounded border border-red-200 bg-red-50 px-3 py-2 text-xs text-red-700">{err}</div>}

        <button type="submit" disabled={m.isPending}
          className="flex w-full items-center justify-center gap-2 rounded-lg bg-certiva-primary px-4 py-2 text-sm font-medium text-white hover:opacity-90 disabled:opacity-60">
          {m.isPending && <Loader2 size={14} className="animate-spin" />}
          {m.isPending ? 'Resetting…' : 'Reset'}
        </button>
      </form>
    </Modal>
  )
}

// ── Sub-components: stat card / row ───────────────────────────────────────────

function StatCard({ label, value }: { label: string; value: number }) {
  return (
    <div className="rounded-lg border border-gray-100 bg-white p-4">
      <p className="text-xs font-medium text-gray-500">{label}</p>
      <p className="mt-1 text-2xl font-medium text-gray-800">{value}</p>
    </div>
  )
}

function UserAvatar({ name }: { name: string }) {
  return (
    <div
      className="flex h-8 w-8 select-none items-center justify-center rounded-full text-white"
      style={{ background: '#1A4731', fontSize: 12 }}
      title={name}
    >
      {initialsOf(name)}
    </div>
  )
}

function RolePill({ role }: { role: UserRole }) {
  return (
    <span className={`rounded px-2 py-0.5 text-xs font-medium capitalize ${ROLE_PILL[role]}`}>
      {role}
    </span>
  )
}

function StatusBadge({ active }: { active: boolean }) {
  if (active) return (
    <span className="rounded px-2 py-0.5 text-xs font-medium" style={{ background: '#F0FAF4', color: '#1A4731' }}>
      Active
    </span>
  )
  return (
    <span className="rounded bg-gray-100 px-2 py-0.5 text-xs font-medium text-gray-500">
      Inactive
    </span>
  )
}

// ── Access-denied card ────────────────────────────────────────────────────────

function AccessDeniedCard() {
  return (
    <div className="flex min-h-[400px] flex-col items-center justify-center text-center">
      <ShieldOff size={48} className="text-gray-300" />
      <p className="mt-3 text-gray-800" style={{ fontSize: 16, fontWeight: 500 }}>Access restricted</p>
      <p className="mt-1 text-gray-400" style={{ fontSize: 13 }}>
        This page is only available to administrators.
      </p>
    </div>
  )
}


// ── Bulk import ───────────────────────────────────────────────────────────────

interface BulkImportResult {
  summary: { total_rows: number; created: number; skipped: number; errors: number }
  created: { row: number; username: string; full_name: string; role: string; user_id: string; auditor_id: string | null }[]
  skipped: { row: number; username: string; reason: string }[]
  errors:  { row: number; username: string; reason: string }[]
}

function BulkImportModal({
  open, onClose, onSuccess,
}: { open: boolean; onClose: () => void; onSuccess: () => void }) {
  const [file,    setFile]    = useState<File | null>(null)
  const [result,  setResult]  = useState<BulkImportResult | null>(null)
  const [loading, setLoading] = useState(false)
  const [error,   setError]   = useState<string | null>(null)
  const fileRef = useRef<HTMLInputElement>(null)

  useEffect(() => {
    if (open) { setFile(null); setResult(null); setError(null) }
  }, [open])

  async function handleImport() {
    if (!file) { setError('Please select a CSV file.'); return }
    setLoading(true)
    setError(null)
    setResult(null)
    try {
      const fd = new FormData()
      fd.append('file', file)
      const r = await api.post<BulkImportResult>('/admin/users/bulk-import', fd, {
        headers: { 'Content-Type': 'multipart/form-data' },
      })
      setResult(r.data)
      if (r.data.summary.created > 0) onSuccess()
    } catch (e) {
      setError(extractDetail(e, 'Import failed.'))
    } finally {
      setLoading(false)
    }
  }

  return (
    <Modal open={open} title="Bulk import users" onClose={onClose}>
      <div className="space-y-4">
        {/* Format guide */}
        <div className="rounded-lg bg-gray-50 p-3 text-xs text-gray-600">
          <p className="mb-1 font-medium text-gray-700">Expected CSV columns:</p>
          <code className="block leading-5 text-gray-500">
            full_name, username, email, password, role,<br />
            standards, ea_codes, accreditation_bodies, technical_depth
          </code>
          <p className="mt-2 text-gray-400">
            Pipe-separate multiple values: <code>ISO 9001|ISO 14001</code><br />
            Leave auditor columns blank for non-auditor rows.<br />
            Rows with existing usernames are skipped (safe to re-run).
          </p>
        </div>

        {/* File input */}
        <div>
          <label className={lblCls}>CSV file *</label>
          <input
            ref={fileRef}
            type="file"
            accept=".csv,text/csv"
            onChange={(e) => setFile(e.target.files?.[0] ?? null)}
            className="w-full rounded-lg border border-gray-200 px-3 py-2 text-sm
              text-gray-700 file:mr-2 file:rounded file:border-0 file:bg-gray-100
              file:px-2 file:py-0.5 file:text-xs focus:outline-none"
          />
        </div>

        {error && (
          <div className="rounded border border-red-200 bg-red-50 px-3 py-2 text-xs text-red-700">
            {error}
          </div>
        )}

        {/* Result summary */}
        {result && (
          <div className="space-y-2">
            <div className="grid grid-cols-3 gap-2 text-center text-xs">
              <div className="rounded-lg bg-green-50 p-2">
                <p className="text-lg font-semibold text-green-700">{result.summary.created}</p>
                <p className="text-green-600">Created</p>
              </div>
              <div className="rounded-lg bg-gray-50 p-2">
                <p className="text-lg font-semibold text-gray-600">{result.summary.skipped}</p>
                <p className="text-gray-500">Skipped</p>
              </div>
              <div className={`rounded-lg p-2 ${result.summary.errors > 0 ? 'bg-red-50' : 'bg-gray-50'}`}>
                <p className={`text-lg font-semibold ${result.summary.errors > 0 ? 'text-red-600' : 'text-gray-600'}`}>
                  {result.summary.errors}
                </p>
                <p className={result.summary.errors > 0 ? 'text-red-500' : 'text-gray-500'}>Errors</p>
              </div>
            </div>

            {result.errors.length > 0 && (
              <div className="max-h-32 overflow-y-auto rounded border border-red-100 bg-red-50 p-2">
                {result.errors.map((e, i) => (
                  <p key={i} className="text-xs text-red-600">
                    Row {e.row} ({e.username}): {e.reason}
                  </p>
                ))}
              </div>
            )}
          </div>
        )}

        <button
          type="button"
          onClick={handleImport}
          disabled={!file || loading}
          className="flex w-full items-center justify-center gap-2 rounded-lg bg-certiva-primary
            px-4 py-2 text-sm font-medium text-white hover:opacity-90 disabled:opacity-60"
        >
          {loading && <Loader2 size={14} className="animate-spin" />}
          {loading ? 'Importing…' : 'Import'}
        </button>
      </div>
    </Modal>
  )
}

// ── Main page ────────────────────────────────────────────────────────────────

export default function AdminUsersPage() {
  const { user: currentUser } = useAuth()
  const queryClient = useQueryClient()

  const [createOpen,    setCreateOpen]    = useState(false)
  const [bulkOpen,      setBulkOpen]      = useState(false)
  const [editTarget,    setEditTarget]    = useState<AdminUser | null>(null)
  const [resetTarget,   setResetTarget]   = useState<AdminUser | null>(null)
  const [toast,         setToast]         = useState<string | null>(null)

  const isAdmin = currentUser?.role === 'admin'

  const { data, isLoading, isError } = useQuery<AdminUser[]>({
    queryKey: ['admin-users'],
    queryFn:  () => api.get<AdminUser[]>('/admin/users/').then((r) => r.data),
    enabled:  isAdmin,
  })

  const deleteMutation = useMutation({
    mutationFn: (id: string) => api.delete(`/admin/users/${id}`),
    onSuccess:  () => queryClient.invalidateQueries({ queryKey: ['admin-users'] }),
  })

  function showToast(message: string) {
    setToast(message)
    window.setTimeout(() => setToast(null), 3000)
  }

  function invalidate() {
    queryClient.invalidateQueries({ queryKey: ['admin-users'] })
  }

  function handleDelete(u: AdminUser) {
    if (currentUser && u.id === currentUser.id) return
    if (!window.confirm(`Delete ${u.full_name}? This cannot be undone.`)) return
    deleteMutation.mutate(u.id)
  }

  if (!isAdmin) {
    return (
      <div className="mx-auto max-w-[1200px] py-4">
        <AccessDeniedCard />
      </div>
    )
  }

  const users   = data ?? []
  const total   = users.length
  const active  = users.filter((u) => u.is_active).length
  const admins  = users.filter((u) => u.role === 'admin').length

  return (
    <div className="mx-auto max-w-[1200px] space-y-5 py-4">
      {/* Header */}
      <div className="flex items-center justify-between">
        <h1 className="text-gray-800" style={{ fontSize: 22, fontWeight: 500 }}>User management</h1>
        <div className="flex items-center gap-2">
          <button
            type="button" onClick={() => setBulkOpen(true)}
            className="flex items-center gap-1 rounded-lg border border-certiva-primary px-3 py-2
              text-sm font-medium text-certiva-primary hover:bg-certiva-primary/5"
          >
            <Upload size={14} /> Bulk import
          </button>
          <button
            type="button" onClick={() => setCreateOpen(true)}
            className="flex items-center gap-1 rounded-lg bg-certiva-primary px-3 py-2 text-sm font-medium text-white hover:opacity-90"
          >
            <Plus size={14} /> Add user
          </button>
        </div>
      </div>

      {/* Summary stats */}
      <div className="grid grid-cols-3 gap-4">
        <StatCard label="Total users"  value={total} />
        <StatCard label="Active users" value={active} />
        <StatCard label="Admins"       value={admins} />
      </div>

      {/* Table */}
      <div className="overflow-hidden rounded-lg border border-gray-100 bg-white">
        <table className="w-full text-sm">
          <thead>
            <tr className="border-b border-gray-100 bg-gray-50 text-left text-xs font-medium text-gray-500">
              <th className="px-4 py-3">User</th>
              <th className="px-4 py-3">Username</th>
              <th className="px-4 py-3">Email</th>
              <th className="px-4 py-3">Role</th>
              <th className="px-4 py-3">Status</th>
              <th className="px-4 py-3">Last login</th>
              <th className="px-4 py-3 text-right">Actions</th>
            </tr>
          </thead>
          <tbody>
            {isLoading && (
              <tr><td colSpan={7} className="py-10 text-center text-sm text-gray-400">
                <Loader2 size={16} className="mx-auto animate-spin" />
              </td></tr>
            )}
            {isError && (
              <tr><td colSpan={7} className="py-10 text-center text-sm text-red-500">Failed to load users.</td></tr>
            )}
            {!isLoading && !isError && users.length === 0 && (
              <tr><td colSpan={7} className="py-10 text-center text-sm text-gray-400">No users yet.</td></tr>
            )}
            {users.map((u) => {
              const isSelf = currentUser?.id === u.id
              return (
                <tr key={u.id} className="border-b border-gray-50 last:border-0">
                  <td className="px-4 py-3">
                    <div className="flex items-center gap-2">
                      <UserAvatar name={u.full_name} />
                      <span className="text-gray-800" style={{ fontWeight: 500 }}>{u.full_name}</span>
                    </div>
                  </td>
                  <td className="px-4 py-3 font-mono text-xs text-gray-500">{u.username ?? '—'}</td>
                  <td className="px-4 py-3 text-gray-500" style={{ fontSize: 13 }}>{u.email}</td>
                  <td className="px-4 py-3"><RolePill role={u.role} /></td>
                  <td className="px-4 py-3"><StatusBadge active={u.is_active} /></td>
                  <td className="px-4 py-3 text-gray-500" style={{ fontSize: 13 }}>{formatDateTime(u.last_login)}</td>
                  <td className="px-4 py-3">
                    <div className="flex items-center justify-end gap-2">
                      <button
                        type="button" onClick={() => setEditTarget(u)}
                        className="text-gray-400 hover:text-gray-700" aria-label="Edit"
                      >
                        <Pencil size={16} />
                      </button>
                      <button
                        type="button" onClick={() => setResetTarget(u)}
                        className="text-gray-400 hover:text-gray-700" aria-label="Reset password"
                      >
                        <Key size={16} />
                      </button>
                      <button
                        type="button" onClick={() => handleDelete(u)}
                        disabled={isSelf}
                        title={isSelf ? 'Cannot delete yourself' : 'Delete'}
                        className="text-gray-400 hover:text-gray-700 disabled:cursor-not-allowed disabled:opacity-30 disabled:hover:text-gray-400"
                        aria-label="Delete"
                      >
                        <Trash2 size={16} />
                      </button>
                    </div>
                  </td>
                </tr>
              )
            })}
          </tbody>
        </table>
      </div>

      {/* Modals */}
      <BulkImportModal
        open={bulkOpen}
        onClose={() => setBulkOpen(false)}
        onSuccess={invalidate}
      />
      <CreateUserModal
        open={createOpen}
        onClose={() => setCreateOpen(false)}
        onSuccess={invalidate}
      />
      <EditUserModal
        user={editTarget}
        onClose={() => setEditTarget(null)}
        onSuccess={invalidate}
      />
      <ResetPasswordModal
        user={resetTarget}
        onClose={() => setResetTarget(null)}
        onSuccess={() => showToast('Password reset successfully.')}
      />

      {toast && <Toast message={toast} />}
    </div>
  )
}
