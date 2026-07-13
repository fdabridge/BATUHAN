'use client'

import { useEffect, useState } from 'react'
import Link from 'next/link'
import { usePathname, useRouter } from 'next/navigation'
import { useAuth } from '@/lib/auth'
import api from '@/lib/api'

const NAV = [
  { href: '/auditor/dashboard',  label: 'My Audits'    },
  { href: '/auditor/trainings',  label: 'Trainings'    },
  { href: '/auditor/signature',  label: 'My Signature' },
]

export default function AuditorLayout({ children }: { children: React.ReactNode }) {
  const { user, isLoading, logout } = useAuth()
  const router = useRouter()
  const pathname = usePathname()
  const [trainingCount, setTrainingCount] = useState(0)

  useEffect(() => {
    if (isLoading) return
    if (!user) {
      router.push('/login')
      return
    }
    if (!['auditor', 'admin'].includes(user.role)) {
      router.push('/dashboard')
    }
  }, [user, isLoading, router])

  useEffect(() => {
    if (!user || !['auditor', 'admin'].includes(user.role)) return
    let cancelled = false
    const fetch = () =>
      api.get<{ total: number }>('/trainings/my/counts')
        .then((r) => { if (!cancelled) setTrainingCount(r.data?.total ?? 0) })
        .catch(() => {})
    fetch()
    const id = setInterval(fetch, 60_000)
    return () => { cancelled = true; clearInterval(id) }
  }, [user])

  if (isLoading || !user || !['auditor', 'admin'].includes(user.role)) return null

  return (
    <div className="flex min-h-screen bg-gray-50">
      <aside className="flex w-56 shrink-0 flex-col border-r bg-white">
        <div className="border-b p-5">
          <p className="text-sm font-bold" style={{ color: '#1A4731' }}>IFC Global</p>
          <p className="mt-0.5 truncate text-xs text-gray-400">{user.full_name}</p>
          <span className="mt-1 inline-block rounded bg-orange-100 px-1.5 py-0.5 text-xs text-orange-700">
            Auditor
          </span>
        </div>
        <nav className="flex-1 space-y-1 p-4">
          {NAV.map((item) => {
            const active = pathname?.startsWith(item.href)
            const badge = item.href === '/auditor/trainings' ? trainingCount : 0
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
                {item.label}
                {badge > 0 && (
                  <span className="flex h-5 min-w-[20px] items-center justify-center rounded-full px-1 text-[10px] font-semibold text-white" style={{ background: '#D97706' }}>
                    {badge > 9 ? '9+' : badge}
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
            className="text-xs text-gray-400 hover:text-gray-600"
          >
            Sign out
          </button>
        </div>
      </aside>
      <main className="flex-1 overflow-auto">{children}</main>
    </div>
  )
}
