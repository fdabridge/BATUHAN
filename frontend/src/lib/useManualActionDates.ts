'use client'

import { useQuery } from '@tanstack/react-query'
import api from '@/lib/api'

export interface PlatformPolicy {
  client_email_verification: boolean
  employee_signature_email_verification: boolean
  retroactive_signing_dates: boolean
}

export function usePlatformPolicy() {
  return useQuery<PlatformPolicy>({
    queryKey: ['platform-policy'],
    queryFn: () => api.get<PlatformPolicy>('/config/policy').then((r) => r.data),
    staleTime: 30_000,
  })
}

export function useManualActionDates() {
  const query = usePlatformPolicy()
  return {
    ...query,
    // Keep the existing UI available until the policy is loaded.
    manualActionDatesEnabled: query.data?.retroactive_signing_dates ?? true,
  }
}
