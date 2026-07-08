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

interface CommitteeReview {
  audit_set_id:   string
  plan_number:    number
  company_name:   string
  standards:      string[]
  committee_role: 'Chairperson' | 'Member'
  document_id:    string | null
  status:         'awaiting_release' | 'pending' | 'signing' | 'complete'
  signed:         boolean
}

export default function AuditorDashboard() {
  const router = useRouter()
  const [assignments, setAssignments] = useState<Assignment[]>([])
  const [committeeReviews, setCommitteeReviews] = useState<CommitteeReview[]>([])
  const [loading, setLoading] = useState(true)

  useEffect(() => {
    Promise.all([
      api.get<Assignment[]>('/auditor/my-assignments')
        .then(response => setAssignments(response.data)),
      api.get<CommitteeReview[]>('/auditor/my-committee-reviews')
        .then(response => setCommitteeReviews(response.data)),
    ])
      .catch(() => undefined)
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

      {committeeReviews.length > 0 && (
        <section className="mb-8">
          <h2 className="mb-3 text-sm font-semibold uppercase text-gray-600">
            Committee Reviews
          </h2>
          <div className="space-y-3">
            {committeeReviews.map(review => (
              <div
                key={review.audit_set_id}
                className="flex items-center justify-between rounded-lg border bg-white p-5"
              >
                <div className="min-w-0">
                  <div className="flex items-center gap-2">
                    <h3 className="truncate font-semibold text-gray-900">
                      {review.company_name}
                    </h3>
                    <span className="rounded bg-gray-100 px-2 py-0.5 text-xs text-gray-600">
                      {review.committee_role}
                    </span>
                  </div>
                  <p className="mt-1 text-xs text-gray-400">
                    FR.233 Review &amp; Decision
                    {review.plan_number ? ` · #${review.plan_number}` : ''}
                  </p>
                  <div className="mt-2 flex flex-wrap gap-1.5">
                    {(review.standards || []).map(standard => (
                      <span
                        key={standard}
                        className="rounded bg-blue-50 px-2 py-0.5 text-xs text-blue-700"
                      >
                        {STANDARD_NAMES[standard] || standard}
                      </span>
                    ))}
                  </div>
                </div>
                <div className="ml-4 flex shrink-0 items-center gap-3">
                  <span className={`text-xs font-medium ${
                    review.signed ? 'text-green-700' : 'text-amber-700'
                  }`}>
                    {review.signed
                      ? 'Signed'
                      : review.document_id
                        ? 'Signature required'
                        : 'Awaiting release'}
                  </span>
                  {review.document_id && (
                    <button
                      type="button"
                      onClick={() => router.push(
                        `/auditor/viewer/shared_doc/${review.document_id}`,
                      )}
                      className="rounded-lg bg-[#1A4731] px-3 py-2 text-xs font-medium text-white hover:bg-[#143828]"
                    >
                      {review.signed ? 'Open' : 'Open to Sign'}
                    </button>
                  )}
                </div>
              </div>
            ))}
          </div>
        </section>
      )}

      {assignments.length === 0 ? (
        <div className="py-16 text-center text-sm text-gray-400">
          No audit-team assignments yet.
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
