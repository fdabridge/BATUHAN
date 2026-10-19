'use client'

import { usePathname } from 'next/navigation'
import { Bell, LogOut } from 'lucide-react'
import { useAuth } from '@/lib/auth'

// ── Helpers ───────────────────────────────────────────────────────────────────

const TITLES: Record<string, string> = {
  dashboard:  'Dashboard',
  clients:    'Clients',
  certivai:   'Certiv.AI',
  reports:    'AI Reports',
  auditors:   'Auditors',
  calculator: 'Calculator',
  admin:      'Administration',
  settings:   'Settings',
}

function getPageTitle(pathname: string): string {
  const segment = pathname.split('/').filter(Boolean)[0] ?? ''
  return TITLES[segment] ?? 'Certiva'
}

// ── User avatar (initials) ────────────────────────────────────────────────────

function UserAvatar({ fullName }: { fullName: string }) {
  const initials = fullName
    .split(' ')
    .filter(Boolean)
    .slice(0, 2)
    .map((w) => w[0]?.toUpperCase() ?? '')
    .join('')

  return (
    <div
      className="flex h-8 w-8 select-none items-center justify-center rounded-full
        text-sm font-semibold text-white"
      style={{ background: '#1A4731' }}
      title={fullName}
    >
      {initials || '?'}
    </div>
  )
}

// ── Topbar ────────────────────────────────────────────────────────────────────

export function Topbar() {
  const pathname = usePathname()
  const { user, logout } = useAuth()
  const title = getPageTitle(pathname)

  return (
    <header
      className="flex shrink-0 items-center justify-between border-b border-slate-200/80
        bg-white/95 px-6 backdrop-blur"
      style={{ height: 60 }}
    >
      <div>
        <p className="text-[10px] font-bold uppercase tracking-[0.16em] text-certiva-mid">Workspace</p>
        <h1 className="text-base font-semibold text-certiva-ink">{title}</h1>
      </div>

      <div className="flex items-center gap-3">
        {/* Notification bell */}
        <button
          className="text-gray-400 transition-colors hover:text-gray-700"
          aria-label="Notifications"
        >
          <Bell size={20} />
        </button>

        {user && (
          <div className="flex items-center gap-2">
            <UserAvatar fullName={user.full_name} />
            <button
              type="button"
              onClick={logout}
              className="flex items-center gap-1.5 rounded-lg border border-gray-200 px-2.5 py-1.5 text-xs font-medium text-gray-600 transition-colors hover:border-[#1A4731]/30 hover:bg-[#F0FAF4] hover:text-[#1A4731]"
            >
              <LogOut size={14} />
              Log out
            </button>
          </div>
        )}
      </div>
    </header>
  )
}
