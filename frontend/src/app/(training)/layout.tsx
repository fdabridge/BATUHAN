'use client'

import { useEffect } from 'react'
import { useRouter } from 'next/navigation'
import { useAuth } from '@/lib/auth'
import { RolePortalShell } from '@/components/layout/RolePortalShell'

const NAV = [
  { href: '/training/dashboard',  label: 'Training Dashboard' },
  { href: '/training/people',     label: 'People & Exam History' },
  { href: '/training/courses/new', label: 'Create Training'    },
]

export default function TrainingLayout({ children }: { children: React.ReactNode }) {
  const { user, isLoading } = useAuth()
  const router = useRouter()

  useEffect(() => {
    if (isLoading) return
    if (!user) {
      router.push('/login')
      return
    }
    if (!['training_officer', 'admin'].includes(user.role)) {
      router.push('/dashboard')
    }
  }, [user, isLoading, router])

  if (isLoading || !user || !['training_officer', 'admin'].includes(user.role)) return null

  return (
    <RolePortalShell roleLabel="Training officer" nav={NAV}>
      {children}
    </RolePortalShell>
  )
}
