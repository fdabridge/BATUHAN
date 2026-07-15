'use client'

import { useEffect, useState } from 'react'
import Link from 'next/link'
import { usePathname, useRouter } from 'next/navigation'
import { LogOut } from 'lucide-react'
import { useAuth } from '@/lib/auth'
import api from '@/lib/api'

function waitingOnCb(doc: { signatures?: { signer_role_label: string; order_index: number; required: boolean; signed_at: string | null }[] }): boolean {
  const sigs = doc.signatures ?? []
  const clientSlot = sigs.find((s) => s.signer_role_label === 'client' || s.signer_role_label === 'org_rep')
  if (!clientSlot) return false
  return sigs.some((s) => s.order_index < clientSlot.order_index && s.required && !s.signed_at)
}

export default function ClientLayout({ children }: { children: React.ReactNode }) {
  const { user, isLoading, logout } = useAuth()
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

  const NAV = [
    { href: '/client/overview',    label: 'Overview',      badge: 0 },
    { href: '/client/documents',   label: 'Documents',     badge: pendingDocCount },
    { href: '/client/assessments', label: 'Assessments',   badge: 0 },
    { href: '/client/ncs',         label: 'Nonconformities',  badge: 0 },
    { href: '/client/messages',    label: 'Messages',      badge: 0 },
    { href: '/client/employees',   label: 'Employees',     badge: 0 },
    { href: '/client/signature',   label: 'My Signature',  badge: 0 },
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
