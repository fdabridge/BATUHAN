'use client'

import { useEffect } from 'react'
import { useRouter } from 'next/navigation'
import { Sidebar } from '@/components/layout/Sidebar'
import { Topbar } from '@/components/layout/Topbar'
import { useAuth } from '@/lib/auth'

export default function AppLayout({
  children,
}: {
  children: React.ReactNode
}) {
  const { token, user, isLoading } = useAuth()
  const router = useRouter()

  useEffect(() => {
    if (isLoading) return
    if (!token) {
      router.replace('/login')
      return
    }
    // Client-role users belong in the (client) portal, not the internal app.
    if (user?.role === 'client') {
      router.replace('/client/overview')
    }
    // CRM-role users go to the CRM section.
    if (user?.role === 'crm') {
      router.replace('/crm')
    }
  }, [isLoading, token, user, router])

  // While hydrating auth state, show a minimal spinner
  if (isLoading) {
    return (
      <div className="flex h-screen items-center justify-center bg-certiva-surface">
        <span className="text-sm text-certiva-text/50">Loading…</span>
      </div>
    )
  }

  // Render nothing while redirect is in progress (avoids flash)
  if (!token) return null
  if (user?.role === 'client') return null
  if (user?.role === 'crm' && typeof window !== 'undefined' && !window.location.pathname.startsWith('/crm')) return null

  return (
    <div className="flex h-screen">
      <Sidebar />
      {/* ml-14 = 56px offset for the fixed sidebar */}
      <div className="ml-14 flex flex-1 flex-col overflow-hidden">
        <Topbar />
        <main className="flex-1 overflow-auto bg-certiva-surface p-6">
          {children}
        </main>
      </div>
    </div>
  )
}
