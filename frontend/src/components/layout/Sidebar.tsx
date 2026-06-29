'use client'

import { useEffect, useState } from 'react'
import Link from 'next/link'
import { usePathname } from 'next/navigation'
import {
  LayoutDashboard,
  Building2,
  Sparkles,
  Users,
  Calculator,
  Inbox,
  PenLine,
  UserCog,
  Settings,
  BarChart3,
  RefreshCw,
  type LucideIcon,
} from 'lucide-react'
import { useAuth } from '@/lib/auth'
import api from '@/lib/api'

// ── Logo mark ────────────────────────────────────────────────────────────────

function CertivaIcon() {
  return (
    <div
      className="flex h-8 w-8 items-center justify-center rounded-lg"
      style={{ background: 'rgba(255,255,255,0.15)' }}
    >
      <svg width="20" height="20" viewBox="0 0 20 20" fill="none">
        {/* Document frame */}
        <path
          d="M4 2h9l3 3v13H4V2z"
          stroke="white"
          strokeWidth="1.5"
          strokeLinejoin="round"
        />
        {/* Folded corner */}
        <path
          d="M13 2v3h3"
          stroke="white"
          strokeWidth="1.5"
          strokeLinejoin="round"
        />
        {/* Checkmark */}
        <path
          d="M7 10.5l2 2 4-4"
          stroke="white"
          strokeWidth="1.5"
          strokeLinecap="round"
          strokeLinejoin="round"
        />
      </svg>
    </div>
  )
}

// ── Nav item ─────────────────────────────────────────────────────────────────

interface NavItemProps {
  icon: LucideIcon
  label: string
  href: string
  active: boolean
  badgeCount?: number
}

function NavItem({ icon: Icon, label, href, active, badgeCount }: NavItemProps) {
  return (
    <div className="group/tip relative">
      <Link
        href={href}
        className={[
          'relative flex h-10 w-10 items-center justify-center rounded-lg transition-colors',
          active
            ? 'bg-white/15 text-white'
            : 'text-white/50 hover:bg-white/10 hover:text-white/80',
        ].join(' ')}
        aria-label={label}
      >
        <Icon size={20} />
        {badgeCount != null && badgeCount > 0 && (
          <span
            className="absolute -right-1 -top-1 flex h-4 min-w-[16px] items-center justify-center
              rounded-full px-1 text-[10px] font-semibold text-white"
            style={{ background: '#D97706' }}
          >
            {badgeCount > 9 ? '9+' : badgeCount}
          </span>
        )}
      </Link>

      {/* Tooltip — appears to the right on hover */}
      <div
        className="pointer-events-none absolute left-14 top-1/2 z-50 hidden -translate-y-1/2
          items-center whitespace-nowrap rounded px-2 py-1 text-xs text-white
          group-hover/tip:flex"
        style={{ background: '#1C2B22' }}
      >
        {label}
      </div>
    </div>
  )
}

// ── Nav definitions ──────────────────────────────────────────────────────────

const NAV_TOP: NavItemProps[] = [
  { icon: LayoutDashboard, label: 'Dashboard',    href: '/dashboard',    active: false },
  { icon: Inbox,           label: 'Applications', href: '/applications', active: false },
  { icon: Building2,       label: 'Clients',      href: '/clients',      active: false },
  { icon: Sparkles,        label: 'AI Reports',   href: '/reports',      active: false },
  { icon: Users,           label: 'Auditors',     href: '/auditors',     active: false },
  { icon: Calculator,      label: 'Calculator',   href: '/calculator',   active: false },
]

const CB_REVIEW_ROLES = new Set(['admin', 'planner', 'officer', 'executive'])

const CRM_NAV: NavItemProps[] = [
  { icon: BarChart3, label: 'CRM Dashboard', href: '/crm',         active: false },
  { icon: RefreshCw, label: 'Clients',        href: '/crm/clients', active: false },
]

const NAV_BOTTOM: NavItemProps[] = [
  { icon: UserCog,  label: 'Users',        href: '/admin/users',        active: false },
  { icon: PenLine,  label: 'My Signature', href: '/settings/signature', active: false },
  { icon: Settings, label: 'Settings',     href: '/settings',           active: false },
]

// ── Sidebar ──────────────────────────────────────────────────────────────────

export function Sidebar() {
  const pathname = usePathname()
  const { user } = useAuth()
  const [pendingCount, setPendingCount] = useState<number>(0)

  const isActive = (href: string) => pathname.startsWith(href)

  const bottomItems = NAV_BOTTOM.filter(
    (item) => item.href !== '/admin/users' || user?.role === 'admin',
  )

  // Poll pending applications count for the Applications badge (CB roles only)
  useEffect(() => {
    if (!user || !CB_REVIEW_ROLES.has(user.role)) return
    let cancelled = false
    const fetchCount = () =>
      api
        .get<unknown[]>('/audit-sets/pending-applications')
        .then((r) => { if (!cancelled) setPendingCount(Array.isArray(r.data) ? r.data.length : 0) })
        .catch(() => {})
    fetchCount()
    const id = setInterval(fetchCount, 60_000)
    return () => { cancelled = true; clearInterval(id) }
  }, [user])

  return (
    <aside
      className="fixed left-0 top-0 z-40 flex h-screen w-14 flex-col items-center gap-1 py-4"
      style={{ background: '#1A4731' }}
    >
      {/* Logo */}
      <div className="mb-4">
        <CertivaIcon />
      </div>

      {/* Primary nav — CRM role sees only CRM items */}
      {user?.role === 'crm' ? (
        CRM_NAV.map((item) => (
          <NavItem key={item.href} {...item} active={isActive(item.href)} />
        ))
      ) : (
        NAV_TOP.map((item) => (
          <NavItem
            key={item.href}
            {...item}
            active={isActive(item.href)}
            badgeCount={item.href === '/applications' ? pendingCount : undefined}
          />
        ))
      )}

      {/* Divider */}
      <div className="my-2 w-8 border-t border-white/15" />

      {/* Secondary nav (Users hidden for non-admins) */}
      {bottomItems.map((item) => (
        <NavItem key={item.href} {...item} active={isActive(item.href)} />
      ))}
    </aside>
  )
}
