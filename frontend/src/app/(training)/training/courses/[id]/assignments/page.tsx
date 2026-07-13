'use client'

import { useEffect, useState, useMemo } from 'react'
import { useParams } from 'next/navigation'
import Link from 'next/link'
import api from '@/lib/api'

interface Assignment {
  id: string
  user_id: string
  user_full_name: string
  user_email: string | null
  user_role: string | null
  training_completed: boolean
  training_completed_at: string | null
  exam_completed: boolean
  exam_completed_at: string | null
  exam_score: number | null
  exam_passed: boolean | null
  assigned_at: string | null
}

interface UserOption {
  id: string
  full_name: string
  email: string
  role: string
}

interface HistoryItem {
  course_title: string
  training_completed: boolean
  exam_score: number | null
  exam_passed: boolean | null
}

interface AnswerDetail {
  question_number: number
  question_text: string
  options: string[]
  correct_option_index: number
  selected_option_index: number | null
  is_correct: boolean
}

interface AnswersData {
  assignment_id: string
  exam_score: number
  exam_passed: boolean
  questions: AnswerDetail[]
}

type Filter = 'all' | 'pending' | 'training_done' | 'passed' | 'failed'

export default function AssignmentsPage() {
  const params = useParams()
  const courseId = params.id as string

  const [assignments, setAssignments] = useState<Assignment[]>([])
  const [loading, setLoading] = useState(true)
  const [users, setUsers] = useState<UserOption[]>([])
  const [selectedUserIds, setSelectedUserIds] = useState<Set<string>>(new Set())
  const [assigning, setAssigning] = useState(false)
  const [error, setError] = useState('')
  const [success, setSuccess] = useState('')
  const [filter, setFilter] = useState<Filter>('all')
  const [courseReady, setCourseReady] = useState(true)
  const [courseMissing, setCourseMissing] = useState<string[]>([])

  // History modal
  const [historyUserId, setHistoryUserId] = useState<string | null>(null)
  const [historyUserName, setHistoryUserName] = useState('')
  const [history, setHistory] = useState<HistoryItem[]>([])
  const [historyLoading, setHistoryLoading] = useState(false)

  // Answers modal
  const [answersData, setAnswersData] = useState<AnswersData | null>(null)
  const [answersUserName, setAnswersUserName] = useState('')
  const [answersLoading, setAnswersLoading] = useState(false)

  useEffect(() => { loadData() }, [courseId])

  async function loadData() {
    setLoading(true)
    try {
      const [assignRes, usersRes, courseRes] = await Promise.all([
        api.get(`/trainings/courses/${courseId}/assignments`),
        api.get('/trainings/assignable-users').catch(() => ({ data: [] })),
        api.get(`/trainings/courses/${courseId}`).catch(() => ({ data: {} })),
      ])
      setAssignments(assignRes.data)
      setUsers(Array.isArray(usersRes.data) ? usersRes.data : [])
      setCourseReady(courseRes.data.is_ready ?? true)
      setCourseMissing(courseRes.data.missing_requirements ?? [])
    } catch {
      setError('Failed to load assignments.')
    } finally {
      setLoading(false)
    }
  }

  function toggleUser(userId: string) {
    setSelectedUserIds((prev) => {
      const next = new Set(prev)
      if (next.has(userId)) next.delete(userId)
      else next.add(userId)
      return next
    })
  }

  async function handleAssign() {
    if (selectedUserIds.size === 0) return
    setAssigning(true)
    setError('')
    setSuccess('')
    try {
      await api.post(`/trainings/courses/${courseId}/assign`, {
        user_ids: Array.from(selectedUserIds),
      })
      setSuccess(`Assigned ${selectedUserIds.size} user(s) successfully.`)
      setSelectedUserIds(new Set())
      await loadData()
    } catch (err: any) {
      setError(err?.response?.data?.detail || 'Failed to assign users.')
    } finally {
      setAssigning(false)
    }
  }

  async function handleUnassign(a: Assignment) {
    if (!confirm(`Remove ${a.user_full_name} from this course?`)) return
    setError('')
    setSuccess('')
    try {
      await api.delete(`/trainings/assignments/${a.id}`)
      setSuccess(`${a.user_full_name} has been unassigned.`)
      await loadData()
    } catch (err: any) {
      setError(err?.response?.data?.detail || 'Failed to unassign user.')
    }
  }

  async function openHistory(userId: string, userName: string) {
    setHistoryUserId(userId)
    setHistoryUserName(userName)
    setHistoryLoading(true)
    setHistory([])
    try {
      const res = await api.get(`/trainings/users/${userId}/history`)
      setHistory(res.data)
    } catch { /* */ }
    finally { setHistoryLoading(false) }
  }

  async function openAnswers(assignmentId: string, userName: string) {
    setAnswersUserName(userName)
    setAnswersLoading(true)
    setAnswersData(null)
    try {
      const res = await api.get(`/trainings/assignments/${assignmentId}/answers`)
      setAnswersData(res.data)
    } catch { /* */ }
    finally { setAnswersLoading(false) }
  }

  async function handleExportCsv() {
    try {
      const res = await api.get(`/trainings/courses/${courseId}/assignments/export`, {
        responseType: 'blob',
      })
      const url = URL.createObjectURL(res.data)
      const a = document.createElement('a')
      a.href = url
      a.download = `training_results_${courseId}.csv`
      a.click()
      URL.revokeObjectURL(url)
    } catch {
      setError('Failed to export CSV.')
    }
  }

  const filtered = useMemo(() => {
    if (filter === 'all') return assignments
    return assignments.filter((a) => {
      if (filter === 'pending') return !a.training_completed
      if (filter === 'training_done') return a.training_completed && !a.exam_completed
      if (filter === 'passed') return a.exam_passed === true
      if (filter === 'failed') return a.exam_passed === false
      return true
    })
  }, [assignments, filter])

  const assignedIds = new Set(assignments.map((a) => a.user_id))
  const availableUsers = users.filter((u) => !assignedIds.has(u.id))

  const counts = useMemo(() => ({
    all: assignments.length,
    pending: assignments.filter((a) => !a.training_completed).length,
    training_done: assignments.filter((a) => a.training_completed && !a.exam_completed).length,
    passed: assignments.filter((a) => a.exam_passed === true).length,
    failed: assignments.filter((a) => a.exam_passed === false).length,
  }), [assignments])

  const FILTERS: { key: Filter; label: string }[] = [
    { key: 'all',           label: `All (${counts.all})` },
    { key: 'pending',       label: `Pending (${counts.pending})` },
    { key: 'training_done', label: `Exam Pending (${counts.training_done})` },
    { key: 'passed',        label: `Passed (${counts.passed})` },
    { key: 'failed',        label: `Failed (${counts.failed})` },
  ]

  return (
    <div className="p-6">
      <div className="mb-6 flex items-center justify-between">
        <div className="flex items-center gap-4">
          <Link href="/training/dashboard" className="text-sm text-gray-400 hover:text-gray-600">&larr; Back</Link>
          <h1 className="text-xl font-semibold" style={{ color: '#1A4731' }}>Course Assignments</h1>
        </div>
        {assignments.length > 0 && (
          <button
            onClick={handleExportCsv}
            className="rounded-md border border-gray-200 px-3 py-1.5 text-xs font-medium text-gray-600 hover:bg-gray-50"
          >
            Export CSV
          </button>
        )}
      </div>

      {error && <div className="mb-4 rounded-md bg-red-50 px-4 py-3 text-sm text-red-700">{error}</div>}
      {success && <div className="mb-4 rounded-md bg-green-50 px-4 py-3 text-sm text-green-700">{success}</div>}

      {/* Assign Users */}
      <section className="mb-6 rounded-lg border border-gray-100 bg-white p-5">
        <h2 className="mb-3 text-sm font-semibold text-gray-700">Assign Users</h2>
        {!courseReady ? (
          <div className="rounded-md border border-orange-200 bg-orange-50 p-3">
            <p className="text-sm font-medium text-orange-800">Course is not ready for assignment</p>
            <ul className="mt-1 list-inside list-disc text-xs text-orange-700">
              {courseMissing.map((m) => <li key={m}>{m}</li>)}
            </ul>
          </div>
        ) : availableUsers.length === 0 ? (
          <p className="text-sm text-gray-400">No unassigned users available.</p>
        ) : (
          <>
            <div className="mb-3 max-h-48 overflow-y-auto rounded-md border border-gray-100 p-2">
              {availableUsers.map((u) => (
                <label key={u.id} className="flex cursor-pointer items-center gap-2 rounded px-2 py-1.5 text-sm hover:bg-gray-50">
                  <input type="checkbox" checked={selectedUserIds.has(u.id)} onChange={() => toggleUser(u.id)} className="accent-[#1A4731]" />
                  <span>{u.full_name}</span>
                  <span className="text-xs text-gray-400">{u.email}</span>
                  <span className="ml-auto rounded bg-gray-100 px-1.5 py-0.5 text-[10px] text-gray-500">{u.role}</span>
                </label>
              ))}
            </div>
            <button
              type="button"
              onClick={handleAssign}
              disabled={assigning || selectedUserIds.size === 0}
              className="rounded-md px-4 py-2 text-sm text-white transition-opacity hover:opacity-90 disabled:opacity-50"
              style={{ background: '#1A4731' }}
            >
              {assigning ? 'Assigning...' : `Assign (${selectedUserIds.size})`}
            </button>
          </>
        )}
      </section>

      {/* Filter tabs */}
      <div className="mb-3 flex gap-1">
        {FILTERS.map((f) => (
          <button
            key={f.key}
            onClick={() => setFilter(f.key)}
            className={`rounded-md px-3 py-1.5 text-xs font-medium transition-colors ${
              filter === f.key ? 'bg-[#1A4731] text-white' : 'bg-gray-100 text-gray-600 hover:bg-gray-200'
            }`}
          >
            {f.label}
          </button>
        ))}
      </div>

      {/* Assignments Table */}
      <div className="rounded-lg border border-gray-100 bg-white">
        <div className="overflow-x-auto">
          <table className="w-full text-sm">
            <thead>
              <tr className="border-b border-gray-100 text-left text-xs font-medium uppercase tracking-wide text-gray-400">
                <th className="px-4 py-2.5">User</th>
                <th className="px-4 py-2.5">Role</th>
                <th className="px-4 py-2.5">Assigned</th>
                <th className="px-4 py-2.5">Training</th>
                <th className="px-4 py-2.5">Exam</th>
                <th className="px-4 py-2.5">Score</th>
                <th className="px-4 py-2.5">Result</th>
                <th className="px-4 py-2.5">Actions</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-gray-50">
              {loading
                ? Array.from({ length: 3 }).map((_, i) => (
                    <tr key={i}>
                      {Array.from({ length: 8 }).map((_, j) => (
                        <td key={j} className="px-4 py-3"><div className="h-3 w-16 animate-pulse rounded bg-gray-100" /></td>
                      ))}
                    </tr>
                  ))
                : filtered.map((a) => {
                    const daysPending = a.assigned_at && !a.training_completed
                      ? Math.floor((Date.now() - new Date(a.assigned_at).getTime()) / 86400000)
                      : null
                    const overdue = daysPending !== null && daysPending > 30
                    return (
                    <tr key={a.id} className={`hover:bg-gray-50/40 ${overdue ? 'bg-red-50/30' : ''}`}>
                      <td className="px-4 py-3">
                        <div className="font-medium">{a.user_full_name}</div>
                        {a.user_email && <div className="text-xs text-gray-400">{a.user_email}</div>}
                      </td>
                      <td className="px-4 py-3">
                        {a.user_role && <span className="rounded bg-gray-100 px-1.5 py-0.5 text-[10px] text-gray-500">{a.user_role}</span>}
                      </td>
                      <td className="px-4 py-3">
                        {a.assigned_at ? (
                          <div>
                            <div className="text-xs text-gray-500">{new Date(a.assigned_at).toLocaleDateString()}</div>
                            {daysPending !== null && (
                              <span className={`text-[10px] ${overdue ? 'font-semibold text-red-600' : 'text-gray-400'}`}>
                                {daysPending}d {overdue ? '— overdue' : 'ago'}
                              </span>
                            )}
                          </div>
                        ) : '—'}
                      </td>
                      <td className="px-4 py-3">
                        <span className={`inline-block rounded px-2 py-0.5 text-xs font-medium ${a.training_completed ? 'bg-green-100 text-green-700' : 'bg-yellow-100 text-yellow-700'}`}>
                          {a.training_completed ? 'Done' : 'Pending'}
                        </span>
                        {a.training_completed_at && (
                          <div className="mt-0.5 text-[10px] text-gray-400">{new Date(a.training_completed_at).toLocaleDateString()}</div>
                        )}
                      </td>
                      <td className="px-4 py-3">
                        <span className={`inline-block rounded px-2 py-0.5 text-xs font-medium ${a.exam_completed ? 'bg-green-100 text-green-700' : 'bg-gray-100 text-gray-500'}`}>
                          {a.exam_completed ? 'Done' : 'Pending'}
                        </span>
                        {a.exam_completed_at && (
                          <div className="mt-0.5 text-[10px] text-gray-400">{new Date(a.exam_completed_at).toLocaleDateString()}</div>
                        )}
                      </td>
                      <td className="px-4 py-3 font-medium tabular-nums">
                        {a.exam_score !== null ? `${a.exam_score}%` : '—'}
                      </td>
                      <td className="px-4 py-3">
                        {a.exam_passed === null ? (
                          <span className="text-gray-400">—</span>
                        ) : a.exam_passed ? (
                          <span className="rounded bg-emerald-100 px-2 py-0.5 text-xs font-semibold text-emerald-700">Passed</span>
                        ) : (
                          <span className="rounded bg-red-100 px-2 py-0.5 text-xs font-semibold text-red-700">Failed</span>
                        )}
                      </td>
                      <td className="px-4 py-3">
                        <div className="flex gap-2">
                          {a.exam_completed && (
                            <button onClick={() => openAnswers(a.id, a.user_full_name)} className="text-xs text-blue-600 hover:underline">
                              Answers
                            </button>
                          )}
                          <button onClick={() => openHistory(a.user_id, a.user_full_name)} className="text-xs text-blue-600 hover:underline">
                            History
                          </button>
                          {!a.training_completed && !a.exam_completed && (
                            <button onClick={() => handleUnassign(a)} className="text-xs text-red-500 hover:underline">
                              Remove
                            </button>
                          )}
                        </div>
                      </td>
                    </tr>
                    )
                  })}
            </tbody>
          </table>
          {!loading && filtered.length === 0 && (
            <div className="py-12 text-center text-sm text-gray-400">
              {assignments.length === 0 ? 'No users assigned to this course yet.' : 'No assignments match the selected filter.'}
            </div>
          )}
        </div>
      </div>

      {/* Answers Modal */}
      {(answersData || answersLoading) && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/30" onClick={() => { setAnswersData(null); setAnswersLoading(false) }}>
          <div className="w-full max-w-2xl rounded-xl bg-white p-6 shadow-xl" onClick={(e) => e.stopPropagation()}>
            <div className="mb-4 flex items-center justify-between">
              <h2 className="text-sm font-semibold" style={{ color: '#1A4731' }}>
                Exam Answers — {answersUserName}
                {answersData && (
                  <span className="ml-2 text-xs font-normal text-gray-400">
                    Score: {answersData.exam_score}% — {answersData.exam_passed ? 'Passed' : 'Failed'}
                  </span>
                )}
              </h2>
              <button onClick={() => { setAnswersData(null); setAnswersLoading(false) }} className="text-lg text-gray-400 hover:text-gray-600">&times;</button>
            </div>
            {answersLoading ? (
              <div className="py-8 text-center text-sm text-gray-400">Loading...</div>
            ) : answersData ? (
              <div className="max-h-[70vh] overflow-y-auto">
                <table className="w-full text-sm">
                  <thead>
                    <tr className="border-b text-left text-xs font-medium uppercase text-gray-400">
                      <th className="px-3 py-2">#</th>
                      <th className="px-3 py-2">Question</th>
                      <th className="px-3 py-2">Selected</th>
                      <th className="px-3 py-2">Correct</th>
                      <th className="px-3 py-2">Result</th>
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-gray-50">
                    {answersData.questions.map((q) => (
                      <tr key={q.question_number} className={q.is_correct ? '' : 'bg-red-50/40'}>
                        <td className="px-3 py-2 text-gray-400">{q.question_number}</td>
                        <td className="px-3 py-2 font-medium">{q.question_text}</td>
                        <td className="px-3 py-2">
                          {q.selected_option_index !== null ? q.options[q.selected_option_index] ?? '—' : '—'}
                        </td>
                        <td className="px-3 py-2 text-gray-500">
                          {q.options[q.correct_option_index] ?? '—'}
                        </td>
                        <td className="px-3 py-2">
                          {q.is_correct ? (
                            <span className="text-xs font-semibold text-emerald-700">Correct</span>
                          ) : (
                            <span className="text-xs font-semibold text-red-600">Wrong</span>
                          )}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            ) : null}
          </div>
        </div>
      )}

      {/* History Modal */}
      {historyUserId && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/30" onClick={() => setHistoryUserId(null)}>
          <div className="w-full max-w-xl rounded-xl bg-white p-6 shadow-xl" onClick={(e) => e.stopPropagation()}>
            <div className="mb-4 flex items-center justify-between">
              <h2 className="text-sm font-semibold" style={{ color: '#1A4731' }}>Training History — {historyUserName}</h2>
              <button onClick={() => setHistoryUserId(null)} className="text-lg text-gray-400 hover:text-gray-600">&times;</button>
            </div>
            {historyLoading ? (
              <div className="py-8 text-center text-sm text-gray-400">Loading...</div>
            ) : history.length === 0 ? (
              <div className="py-8 text-center text-sm text-gray-400">No training history found.</div>
            ) : (
              <div className="max-h-80 overflow-y-auto">
                <table className="w-full text-sm">
                  <thead>
                    <tr className="border-b text-left text-xs font-medium uppercase text-gray-400">
                      <th className="px-3 py-2">Course</th>
                      <th className="px-3 py-2">Training</th>
                      <th className="px-3 py-2">Score</th>
                      <th className="px-3 py-2">Result</th>
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-gray-50">
                    {history.map((h, i) => (
                      <tr key={i}>
                        <td className="px-3 py-2 font-medium">{h.course_title}</td>
                        <td className="px-3 py-2">
                          <span className={`rounded px-1.5 py-0.5 text-[10px] font-medium ${h.training_completed ? 'bg-green-100 text-green-700' : 'bg-yellow-100 text-yellow-700'}`}>
                            {h.training_completed ? 'Done' : 'Pending'}
                          </span>
                        </td>
                        <td className="px-3 py-2 tabular-nums">{h.exam_score !== null ? `${h.exam_score}%` : '—'}</td>
                        <td className="px-3 py-2">
                          {h.exam_passed === null ? '—' : h.exam_passed ? (
                            <span className="text-xs font-semibold text-emerald-700">Passed</span>
                          ) : (
                            <span className="text-xs font-semibold text-red-600">Failed</span>
                          )}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
          </div>
        </div>
      )}
    </div>
  )
}
