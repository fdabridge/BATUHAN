'use client'

import { useEffect, useState } from 'react'
import { useRouter } from 'next/navigation'
import api from '@/lib/api'

const STANDARD_NAMES: Record<string, string> = {
  QMS:   'ISO 9001',
  EMS:   'ISO 14001',
  OHSMS: 'ISO 45001',
  FSMS:  'ISO 22000',
  ISMS:  'ISO 27001',
  ENMS:  'ISO 50001',
  MDQMS: 'ISO 13485',
  ABMS:  'ISO 37001',
}

interface MyStage {
  stage_type:       string
  audit_date_start: string | null
  audit_date_end:   string | null
  is_lead:          boolean
  status:           string
}

interface Assignment {
  id:              string
  plan_number:     number
  company_name:    string
  company_address: string
  standards:       string[]
  audit_type:      string
  scope_en:        string | null
  workflow_status: string | null
  my_stages:       MyStage[]
}

export default function AuditorDashboard() {
  const router = useRouter()
  const [assignments, setAssignments] = useState<Assignment[]>([])
  const [loading, setLoading] = useState(true)

  useEffect(() => {
    api.get<Assignment[]>('/auditor/my-assignments')
      .then(r => setAssignments(r.data))
      .finally(() => setLoading(false))
  }, [])

  if (loading) {
    return <div className="p-8 text-sm text-gray-400">Loading your assignments…</div>
  }

  return (
    <div className="mx-auto max-w-4xl p-6">
      <div className="mb-6">
        <h1 className="text-xl font-bold text-gray-900">My Audit Assignments</h1>
        <p className="mt-0.5 text-sm text-gray-400">
          {assignments.length} audit{assignments.length !== 1 ? 's' : ''} assigned
        </p>
      </div>

      {assignments.length === 0 ? (
        <div className="py-16 text-center text-sm text-gray-400">
          No assignments yet.
        </div>
      ) : (
        <div className="space-y-3">
          {assignments.map((a) => {
            const nextStage =
              a.my_stages.find((s) => s.status !== 'complete') ?? a.my_stages[0]
            return (
              <div
                key={a.id}
                className="cursor-pointer rounded-xl border bg-white p-5 transition-shadow hover:shadow-sm"
                onClick={() => router.push(`/auditor/audit/${a.id}`)}
              >
                <div className="flex items-start justify-between">
                  <div className="min-w-0 flex-1">
                    <h3 className="font-semibold text-gray-900">{a.company_name}</h3>
                    <p className="mt-0.5 truncate text-xs text-gray-400">{a.company_address}</p>
                    <div className="mt-2 flex flex-wrap gap-1.5">
                      {(a.standards || []).map((s) => (
                        <span
                          key={s}
                          className="rounded bg-blue-50 px-2 py-0.5 text-xs text-blue-700"
                        >
                          {STANDARD_NAMES[s] || s}
                        </span>
                      ))}
                    </div>
                    {a.scope_en && (
                      <p className="mt-1 truncate text-xs italic text-gray-400">
                        “{a.scope_en}”
                      </p>
                    )}
                  </div>
                  <div className="ml-4 shrink-0 text-right">
                    {nextStage?.audit_date_start && (
                      <p className="text-sm font-semibold text-gray-800">
                        {new Date(nextStage.audit_date_start).toLocaleDateString('en-GB', {
                          day: 'numeric', month: 'short', year: 'numeric',
                        })}
                      </p>
                    )}
                    {nextStage && (
                      <p className="mt-0.5 text-xs text-gray-400">
                        {nextStage.stage_type?.replace('_', ' ')}
                        {nextStage.is_lead ? ' · Lead' : ''}
                      </p>
                    )}
                  </div>
                </div>
              </div>
            )
          })}
        </div>
      )}
    </div>
  )
}
