'use client'

import { useEffect } from 'react'
import Link from 'next/link'
import { usePathname, useRouter } from 'next/navigation'
import { useAuth } from '@/lib/auth'

const NAV = [
  { href: '/client/overview',    label: 'Overview'      },
  { href: '/client/documents',   label: 'Documents'     },
  { href: '/client/assessments', label: 'Assessments'   },
  { href: '/client/messages',    label: 'Messages'      },
  { href: '/client/signature',   label: 'My Signature'  },
]

export default function ClientLayout({ children }: { children: React.ReactNode }) {
  const { user, isLoading, logout } = useAuth()
  const router = useRouter()
  const pathname = usePathname()

  useEffect(() => {
    if (isLoading) return
    if (!user) {
      router.push('/login')
      return
    }
    if (user.role !== 'client') {
      router.push('/dashboard')
    }
  }, [user, isLoading, router])

  // Avoid flash while hydrating or redirecting
  if (isLoading || !user || user.role !== 'client') return null

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
                  'block rounded-lg px-3 py-2 text-sm transition-colors',
                  active
                    ? 'bg-[#F0FAF4] font-medium text-[#1A4731]'
                    : 'text-gray-700 hover:bg-gray-100',
                ].join(' ')}
              >
                {item.label}
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

      {/* Main */}
      <main className="flex-1 overflow-auto">{children}</main>
    </div>
  )
}
