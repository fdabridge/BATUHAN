'use client'

import { useEffect, useMemo, useState } from 'react'
import api from '@/lib/api'

interface PersonSummary {
  user_id: string
  full_name: string
  email: string | null
  role: string | null
  assignment_count: number
  exam_count: number
  passed_count: number
  failed_count: number
  last_exam_at: string | null
}

interface ExamHistoryItem {
  attempt_id: string | null
  assignment_id: string
  course_id: string
  course_title: string
  attempt_number: number
  exam_taken_at: string
  exam_score: number | null
  exam_passed: boolean | null
}

interface PersonExamHistory {
  person: Pick<PersonSummary, 'user_id' | 'full_name' | 'email' | 'role'>
  summary: {
    exam_count: number
    passed_count: number
    failed_count: number
    average_score: number | null
  }
  exams: ExamHistoryItem[]
}

function formatDate(value: string | null): string {
  if (!value) return '—'
  return new Intl.DateTimeFormat(undefined, {
    year: 'numeric', month: 'short', day: '2-digit',
    hour: '2-digit', minute: '2-digit',
  }).format(new Date(value))
}

export default function TrainingPeoplePage() {
  const [people, setPeople] = useState<PersonSummary[]>([])
  const [selectedUserId, setSelectedUserId] = useState<string | null>(null)
  const [history, setHistory] = useState<PersonExamHistory | null>(null)
  const [search, setSearch] = useState('')
  const [loadingPeople, setLoadingPeople] = useState(true)
  const [loadingHistory, setLoadingHistory] = useState(false)
  const [error, setError] = useState('')

  useEffect(() => {
    api.get<PersonSummary[]>('/trainings/people')
      .then((response) => {
        setPeople(response.data)
        if (response.data.length > 0) setSelectedUserId(response.data[0].user_id)
      })
      .catch(() => setError('Failed to load training participants.'))
      .finally(() => setLoadingPeople(false))
  }, [])

  useEffect(() => {
    if (!selectedUserId) {
      setHistory(null)
      return
    }
    setLoadingHistory(true)
    setError('')
    api.get<PersonExamHistory>(`/trainings/users/${selectedUserId}/exam-history`)
      .then((response) => setHistory(response.data))
      .catch(() => {
        setHistory(null)
        setError('Failed to load this participant’s exam history.')
      })
      .finally(() => setLoadingHistory(false))
  }, [selectedUserId])

  const filteredPeople = useMemo(() => {
    const query = search.trim().toLocaleLowerCase()
    if (!query) return people
    return people.filter((person) =>
      person.full_name.toLocaleLowerCase().includes(query)
      || (person.email ?? '').toLocaleLowerCase().includes(query)
      || (person.role ?? '').toLocaleLowerCase().includes(query),
    )
  }, [people, search])

  return (
    <div className="p-6">
      <div className="mb-6">
        <h1 className="text-xl font-semibold" style={{ color: '#1A4731' }}>People & Exam History</h1>
        <p className="mt-1 text-sm text-gray-500">Select a participant to review every recorded exam date, score, and result.</p>
      </div>

      {error && <div className="mb-4 rounded-md bg-red-50 px-4 py-3 text-sm text-red-700">{error}</div>}

      <div className="grid gap-5 lg:grid-cols-[320px_minmax(0,1fr)]">
        <section className="rounded-lg border border-gray-100 bg-white">
          <div className="border-b border-gray-100 p-4">
            <label htmlFor="person-search" className="mb-1 block text-xs font-medium uppercase tracking-wide text-gray-400">
              Find a person
            </label>
            <input
              id="person-search"
              type="search"
              value={search}
              onChange={(event) => setSearch(event.target.value)}
              placeholder="Name, email, or role"
              className="w-full rounded-md border border-gray-200 px-3 py-2 text-sm focus:border-[#1A4731] focus:outline-none focus:ring-1 focus:ring-[#1A4731]"
            />
          </div>

          <div className="max-h-[68vh] overflow-y-auto p-2">
            {loadingPeople ? (
              Array.from({ length: 5 }).map((_, index) => (
                <div key={index} className="mb-1 h-16 animate-pulse rounded-md bg-gray-50" />
              ))
            ) : filteredPeople.length === 0 ? (
              <p className="px-3 py-10 text-center text-sm text-gray-400">
                {people.length === 0 ? 'No training participants yet.' : 'No people match your search.'}
              </p>
            ) : filteredPeople.map((person) => {
              const selected = selectedUserId === person.user_id
              return (
                <button
                  key={person.user_id}
                  type="button"
                  onClick={() => setSelectedUserId(person.user_id)}
                  className={`mb-1 w-full rounded-md border px-3 py-2.5 text-left transition-colors ${
                    selected
                      ? 'border-[#B7D7C5] bg-[#F0FAF4]'
                      : 'border-transparent hover:bg-gray-50'
                  }`}
                >
                  <div className="flex items-start justify-between gap-2">
                    <div className="min-w-0">
                      <p className="truncate text-sm font-medium text-gray-800">{person.full_name}</p>
                      <p className="truncate text-xs text-gray-400">{person.email || person.role || '—'}</p>
                    </div>
                    <span className="shrink-0 rounded bg-gray-100 px-1.5 py-0.5 text-[10px] font-medium text-gray-600">
                      {person.exam_count} exam{person.exam_count === 1 ? '' : 's'}
                    </span>
                  </div>
                </button>
              )
            })}
          </div>
        </section>

        <section className="min-w-0 rounded-lg border border-gray-100 bg-white">
          {!selectedUserId ? (
            <div className="flex min-h-80 items-center justify-center p-8 text-sm text-gray-400">
              Select a participant to view exam history.
            </div>
          ) : loadingHistory ? (
            <div className="space-y-3 p-5">
              <div className="h-16 animate-pulse rounded bg-gray-50" />
              <div className="h-40 animate-pulse rounded bg-gray-50" />
            </div>
          ) : history ? (
            <>
              <div className="border-b border-gray-100 p-5">
                <div className="flex flex-wrap items-start justify-between gap-3">
                  <div>
                    <h2 className="font-semibold text-gray-800">{history.person.full_name}</h2>
                    <p className="mt-0.5 text-xs text-gray-400">
                      {[history.person.email, history.person.role].filter(Boolean).join(' · ') || 'Participant'}
                    </p>
                  </div>
                  <div className="grid grid-cols-2 gap-2 sm:grid-cols-4">
                    {[
                      ['Exams', history.summary.exam_count, 'text-blue-700 bg-blue-50'],
                      ['Passed', history.summary.passed_count, 'text-emerald-700 bg-emerald-50'],
                      ['Failed', history.summary.failed_count, 'text-red-700 bg-red-50'],
                      ['Average', history.summary.average_score == null ? '—' : `${history.summary.average_score}%`, 'text-purple-700 bg-purple-50'],
                    ].map(([label, value, color]) => (
                      <div key={String(label)} className={`rounded-md px-3 py-2 ${color}`}>
                        <p className="text-base font-bold tabular-nums">{value}</p>
                        <p className="text-[10px] font-medium uppercase tracking-wide opacity-75">{label}</p>
                      </div>
                    ))}
                  </div>
                </div>
              </div>

              <div className="overflow-x-auto">
                <table className="w-full text-sm">
                  <thead>
                    <tr className="border-b border-gray-100 text-left text-xs font-medium uppercase tracking-wide text-gray-400">
                      <th className="px-5 py-3">Exam / Training</th>
                      <th className="px-5 py-3">Attempt</th>
                      <th className="px-5 py-3">Date taken</th>
                      <th className="px-5 py-3">Score</th>
                      <th className="px-5 py-3">Result</th>
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-gray-50">
                    {history.exams.map((exam) => (
                      <tr key={exam.attempt_id ?? `${exam.assignment_id}-${exam.exam_taken_at}`} className="hover:bg-gray-50/40">
                        <td className="px-5 py-3 font-medium text-gray-800">{exam.course_title}</td>
                        <td className="px-5 py-3 text-gray-500">#{exam.attempt_number}</td>
                        <td className="whitespace-nowrap px-5 py-3 text-gray-500">{formatDate(exam.exam_taken_at)}</td>
                        <td className="px-5 py-3 font-semibold tabular-nums">
                          {exam.exam_score == null ? '—' : `${Number(exam.exam_score.toFixed(2))}%`}
                        </td>
                        <td className="px-5 py-3">
                          {exam.exam_passed === true ? (
                            <span className="rounded bg-emerald-100 px-2 py-0.5 text-xs font-semibold text-emerald-700">Passed</span>
                          ) : exam.exam_passed === false ? (
                            <span className="rounded bg-red-100 px-2 py-0.5 text-xs font-semibold text-red-700">Failed</span>
                          ) : (
                            <span className="text-gray-400">—</span>
                          )}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
                {history.exams.length === 0 && (
                  <div className="py-16 text-center text-sm text-gray-400">No completed exams recorded for this participant.</div>
                )}
              </div>
            </>
          ) : null}
        </section>
      </div>
    </div>
  )
}
