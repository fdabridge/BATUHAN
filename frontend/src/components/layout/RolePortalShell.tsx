'use client'

import type { ReactNode } from 'react'
import Link from 'next/link'
import { usePathname } from 'next/navigation'
import { LogOut } from 'lucide-react'
import { CertivaLogo } from '@/components/brand/CertivaLogo'
import { useAuth } from '@/lib/auth'

export interface RolePortalNavItem {
  href: string
  label: string
  badge?: number
}

interface RolePortalShellProps {
  roleLabel: string
  nav: RolePortalNavItem[]
  children: ReactNode
}

function initials(name: string): string {
  return name
    .split(' ')
    .filter(Boolean)
    .slice(0, 2)
    .map((part) => part[0]?.toUpperCase() ?? '')
    .join('')
}

export function RolePortalShell({ roleLabel, nav, children }: RolePortalShellProps) {
  const pathname = usePathname()
  const { user, logout } = useAuth()

  if (!user) return null

  return (
    <div className="min-h-screen bg-certiva-mist text-certiva-ink lg:flex">
      <aside className="border-b border-certiva-border-dark bg-certiva-night text-white lg:fixed lg:inset-y-0 lg:left-0 lg:flex lg:w-64 lg:flex-col lg:border-b-0 lg:border-r">
        <div className="flex items-center justify-between px-5 py-4 lg:block lg:px-6 lg:py-6">
          <CertivaLogo variant="reversed" className="h-9 w-auto" />
          <span className="rounded-full border border-white/10 bg-white/5 px-2.5 py-1 text-[10px] font-bold uppercase tracking-[0.14em] text-certiva-pale lg:mt-5 lg:inline-flex">
            {roleLabel}
          </span>
        </div>

        <nav className="flex gap-1 overflow-x-auto px-3 pb-3 lg:flex-1 lg:flex-col lg:overflow-visible lg:px-4 lg:pb-4">
          {nav.map((item) => {
            const active = pathname === item.href || pathname.startsWith(`${item.href}/`)
            return (
              <Link
                key={item.href}
                href={item.href}
                className={[
                  'flex shrink-0 items-center justify-between rounded-xl px-3 py-2.5 text-sm transition-colors',
                  active
                    ? 'bg-white/10 font-semibold text-white'
                    : 'text-white/65 hover:bg-white/[0.06] hover:text-white',
                ].join(' ')}
              >
                <span>{item.label}</span>
                {!!item.badge && item.badge > 0 && (
                  <span className="ml-3 flex h-5 min-w-[20px] items-center justify-center rounded-full bg-certiva-signal px-1.5 text-[10px] font-bold text-certiva-night">
                    {item.badge > 99 ? '99+' : item.badge}
                  </span>
                )}
              </Link>
            )
          })}
        </nav>

        <div className="hidden border-t border-white/10 p-4 lg:block">
          <div className="mb-3 flex items-center gap-3 px-2">
            <div className="flex h-9 w-9 items-center justify-center rounded-full bg-certiva-green text-xs font-bold text-white">
              {initials(user.full_name) || '?'}
            </div>
            <div className="min-w-0">
              <p className="truncate text-sm font-semibold text-white">{user.full_name}</p>
              <p className="truncate text-xs text-white/45">{user.email}</p>
            </div>
          </div>
          <button
            type="button"
            onClick={logout}
            className="flex w-full items-center justify-center gap-2 rounded-xl border border-white/10 px-3 py-2 text-sm font-medium text-white/65 transition-colors hover:bg-white/[0.06] hover:text-white"
          >
            <LogOut size={15} />
            Sign out
          </button>
        </div>
      </aside>

      <div className="min-w-0 flex-1 lg:ml-64">
        <header className="hidden h-16 items-center justify-between border-b border-slate-200/80 bg-white/90 px-7 backdrop-blur lg:flex">
          <div>
            <p className="text-[11px] font-bold uppercase tracking-[0.16em] text-certiva-mid">{roleLabel} workspace</p>
            <p className="mt-0.5 text-sm text-slate-500">One clear next step, with the complete record always available.</p>
          </div>
          <button onClick={logout} className="flex items-center gap-2 text-xs font-semibold text-slate-500 hover:text-certiva-green">
            <LogOut size={14} /> Sign out
          </button>
        </header>
        <main>{children}</main>
      </div>
    </div>
  )
}
