'use client'

import { useEffect, useState } from 'react'
import Link from 'next/link'
import { usePathname, useRouter } from 'next/navigation'
import { Loader2, LogOut, MailCheck } from 'lucide-react'
import { useAuth } from '@/lib/auth'
import api from '@/lib/api'

function waitingOnCb(doc: { signatures?: { signer_role_label: string; order_index: number; required: boolean; signed_at: string | null }[] }): boolean {
  const sigs = doc.signatures ?? []
  const clientSlot = sigs.find((s) => s.signer_role_label === 'client' || s.signer_role_label === 'org_rep')
  if (!clientSlot) return false
  return sigs.some((s) => s.order_index < clientSlot.order_index && s.required && !s.signed_at)
}

export default function ClientLayout({ children }: { children: React.ReactNode }) {
  const { user, isLoading, logout, refreshUser } = useAuth()
  const router   = useRouter()
  const pathname = usePathname()
  const [pendingDocCount, setPendingDocCount] = useState(0)

  useEffect(() => {
    if (isLoading) return
    if (!user) { router.push('/login'); return }
    if (user.role !== 'client') { router.push('/dashboard'); return }
  }, [user, isLoading, router])

  // Fetch pending docs count for nav badge — silent, non-blocking
  useEffect(() => {
    if (!user || user.role !== 'client') return
    api.get('/client/my-audit-set/documents')
      .then((r) => {
        const docs = r.data as { status: string; signatures?: unknown[] }[]
        const pending = docs.filter(
          (d) => d.status !== 'signed' && !waitingOnCb(d as Parameters<typeof waitingOnCb>[0])
        ).length
        setPendingDocCount(pending)
      })
      .catch(() => {/* silent */})
  }, [user])

  if (isLoading || !user || user.role !== 'client') return null
  if (user.activation_required) {
    return <ClientActivationGate email={user.email} logout={logout} onVerified={refreshUser} />
  }

  const NAV = [
    { href: '/client/overview',    label: 'Overview',      badge: 0 },
    { href: '/client/documents',   label: 'Documents',     badge: pendingDocCount },
    { href: '/client/assessments', label: 'Assessments',   badge: 0 },
    { href: '/client/ncs',         label: 'Nonconformities',  badge: 0 },
    { href: '/client/messages',    label: 'Messages',      badge: 0 },
    { href: '/client/employees',   label: 'Employees',     badge: 0 },
  ]

  return (
    <div className="flex min-h-screen bg-gray-50">
      {/* Sidebar */}
      <aside className="flex w-56 shrink-0 flex-col border-r bg-white">
        <div className="border-b p-5">
          <p className="text-sm font-bold" style={{ color: '#1A4731' }}>IFC Global</p>
          <p className="mt-0.5 truncate text-xs text-gray-400">{user.full_name}</p>
        </div>
        <nav className="flex-1 space-y-1 p-4">
          {NAV.map((item) => {
            const active = pathname?.startsWith(item.href)
            return (
              <Link
                key={item.href}
                href={item.href}
                className={[
                  'flex items-center justify-between rounded-lg px-3 py-2 text-sm transition-colors',
                  active
                    ? 'bg-[#F0FAF4] font-medium text-[#1A4731]'
                    : 'text-gray-700 hover:bg-gray-100',
                ].join(' ')}
              >
                <span>{item.label}</span>
                {item.badge > 0 && (
                  <span className="flex h-4 min-w-[16px] items-center justify-center rounded-full bg-red-500 px-1 text-[10px] font-bold text-white">
                    {item.badge}
                  </span>
                )}
              </Link>
            )
          })}
        </nav>
        <div className="border-t p-4">
          <button
            type="button"
            onClick={logout}
            className="flex w-full items-center justify-center gap-2 rounded-lg border border-gray-200 px-3 py-2 text-sm font-medium text-gray-600 transition-colors hover:border-[#1A4731]/30 hover:bg-[#F0FAF4] hover:text-[#1A4731]"
          >
            <LogOut size={15} />
            Sign out
          </button>
        </div>
      </aside>

      {/* Main */}
      <main className="flex-1 overflow-auto">{children}</main>
    </div>
  )
}

function ClientActivationGate({
  email,
  logout,
  onVerified,
}: {
  email: string
  logout: () => void
  onVerified: () => Promise<void>
}) {
  const [code, setCode] = useState('')
  const [sent, setSent] = useState(false)
  const [busy, setBusy] = useState(false)
  const [message, setMessage] = useState<string | null>(null)

  async function requestCode() {
    setBusy(true); setMessage(null)
    try {
      await api.post('/auth/client-activation/request')
      setSent(true)
      setMessage(`A verification code was sent to ${email}.`)
    } catch (error) {
      const detail = (error as { response?: { data?: { detail?: string } } }).response?.data?.detail
      setMessage(detail || 'The verification email could not be sent.')
    } finally {
      setBusy(false)
    }
  }

  async function verify() {
    setBusy(true); setMessage(null)
    try {
      await api.post('/auth/client-activation/verify', { code })
      await onVerified()
    } catch (error) {
      const detail = (error as { response?: { data?: { detail?: string } } }).response?.data?.detail
      setMessage(detail || 'The verification code is not valid.')
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="flex min-h-screen items-center justify-center bg-gray-50 p-6">
      <div className="w-full max-w-md rounded-xl border border-gray-100 bg-white p-7 shadow-sm">
        <MailCheck className="mb-4 text-[#1A4731]" size={36} />
        <h1 className="text-xl font-semibold text-gray-900">Verify your email</h1>
        <p className="mt-2 text-sm text-gray-600">
          Verify the account email before accessing certification records and documents.
        </p>
        {!sent ? (
          <button onClick={requestCode} disabled={busy}
            className="mt-5 flex w-full items-center justify-center gap-2 rounded-lg bg-[#1A4731] px-4 py-2.5 text-sm font-medium text-white disabled:opacity-60">
            {busy && <Loader2 size={15} className="animate-spin" />} Send verification code
          </button>
        ) : (
          <div className="mt-5 space-y-3">
            <input
              value={code}
              onChange={(event) => setCode(event.target.value.replace(/\D/g, '').slice(0, 6))}
              inputMode="numeric"
              autoComplete="one-time-code"
              placeholder="6-digit code"
              className="w-full rounded-lg border border-gray-200 px-3 py-2.5 text-center text-lg tracking-[0.3em] outline-none focus:border-[#1A4731]"
            />
            <button onClick={verify} disabled={busy || code.length !== 6}
              className="flex w-full items-center justify-center gap-2 rounded-lg bg-[#1A4731] px-4 py-2.5 text-sm font-medium text-white disabled:opacity-60">
              {busy && <Loader2 size={15} className="animate-spin" />} Verify and continue
            </button>
            <button onClick={requestCode} disabled={busy} className="w-full text-xs text-gray-500 hover:text-[#1A4731]">
              Send a new code
            </button>
          </div>
        )}
        {message && <p className="mt-3 rounded-lg bg-gray-50 px-3 py-2 text-xs text-gray-600">{message}</p>}
        <button onClick={logout} className="mt-5 text-xs text-gray-400 hover:text-gray-700">Sign out</button>
      </div>
    </div>
  )
}
