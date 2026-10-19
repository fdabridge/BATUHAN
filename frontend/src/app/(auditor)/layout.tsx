'use client'

import { useEffect, useState } from 'react'
import { useRouter } from 'next/navigation'
import { useAuth } from '@/lib/auth'
import api from '@/lib/api'
import { RolePortalShell } from '@/components/layout/RolePortalShell'

const NAV = [
  { href: '/auditor/dashboard',  label: 'My Audits'    },
  { href: '/auditor/trainings',  label: 'Trainings'    },
  { href: '/auditor/signature',  label: 'My Signature' },
]

export default function AuditorLayout({ children }: { children: React.ReactNode }) {
  const { user, isLoading } = useAuth()
  const router = useRouter()
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

  const nav = NAV.map((item) => ({
    ...item,
    badge: item.href === '/auditor/trainings' ? trainingCount : 0,
  }))

  return (
    <RolePortalShell roleLabel="Auditor" nav={nav}>
      {children}
    </RolePortalShell>
  )
}
