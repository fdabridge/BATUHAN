'use client'

import { useEffect, useState } from 'react'
import { useParams } from 'next/navigation'
import Link from 'next/link'
import api from '@/lib/api'

interface Assignment {
  id: string
  user_id: string
  user_name: string
  training_completed: boolean
  exam_completed: boolean
  score: number | null
  passed: boolean | null
}

interface UserOption {
  id: string
  full_name: string
  email: string
}

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

  useEffect(() => {
    loadData()
  }, [courseId])

  async function loadData() {
    setLoading(true)
    try {
      const [assignRes, usersRes] = await Promise.all([
        api.get(`/trainings/courses/${courseId}/assignments`),
        api.get('/admin/users').catch(() => ({ data: [] })),
      ])
      setAssignments(assignRes.data)
      setUsers(Array.isArray(usersRes.data) ? usersRes.data : usersRes.data?.items || [])
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

  // Filter out already-assigned users
  const assignedIds = new Set(assignments.map((a) => a.user_id))
  const availableUsers = users.filter((u) => !assignedIds.has(u.id))

  return (
    <div className="p-6">
      <div className="mb-6 flex items-center gap-4">
        <Link
          href="/training/dashboard"
          className="text-sm text-gray-400 hover:text-gray-600"
        >
          &larr; Back
        </Link>
        <h1 className="text-xl font-semibold" style={{ color: '#1A4731' }}>
          Course Assignments
        </h1>
      </div>

      {error && (
        <div className="mb-4 rounded-md bg-red-50 px-4 py-3 text-sm text-red-700">{error}</div>
      )}
      {success && (
        <div className="mb-4 rounded-md bg-green-50 px-4 py-3 text-sm text-green-700">{success}</div>
      )}

      {/* Assign Users Section */}
      <section className="mb-6 rounded-lg border border-gray-100 bg-white p-5">
        <h2 className="mb-3 text-sm font-semibold text-gray-700">Assign Users</h2>

        {availableUsers.length === 0 ? (
          <p className="text-sm text-gray-400">No unassigned users available.</p>
        ) : (
          <>
            <div className="mb-3 max-h-48 overflow-y-auto rounded-md border border-gray-100 p-2">
              {availableUsers.map((u) => (
                <label
                  key={u.id}
                  className="flex cursor-pointer items-center gap-2 rounded px-2 py-1.5 text-sm hover:bg-gray-50"
                >
                  <input
                    type="checkbox"
                    checked={selectedUserIds.has(u.id)}
                    onChange={() => toggleUser(u.id)}
                    className="accent-[#1A4731]"
                  />
                  <span>{u.full_name}</span>
                  <span className="text-xs text-gray-400">{u.email}</span>
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

      {/* Assignments Table */}
      <div className="rounded-lg border border-gray-100 bg-white">
        <div className="px-5 py-4">
          <span className="text-sm font-medium">Current Assignments</span>
        </div>
        <div className="overflow-x-auto">
          <table className="w-full text-sm">
            <thead>
              <tr className="border-t border-gray-100 text-left text-xs font-medium uppercase tracking-wide text-gray-400">
                <th className="px-4 py-2.5">User Name</th>
                <th className="px-4 py-2.5">Training Completed</th>
                <th className="px-4 py-2.5">Exam Completed</th>
                <th className="px-4 py-2.5">Score</th>
                <th className="px-4 py-2.5">Passed</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-gray-50">
              {loading
                ? Array.from({ length: 3 }).map((_, i) => (
                    <tr key={i}>
                      {Array.from({ length: 5 }).map((_, j) => (
                        <td key={j} className="px-4 py-3">
                          <div className="h-3 w-20 animate-pulse rounded bg-gray-100" />
                        </td>
                      ))}
                    </tr>
                  ))
                : assignments.map((a) => (
                    <tr key={a.id} className="hover:bg-gray-50/40">
                      <td className="px-4 py-3 font-medium">{a.user_name}</td>
                      <td className="px-4 py-3">
                        <span
                          className={`inline-block rounded px-2 py-0.5 text-xs font-medium ${
                            a.training_completed
                              ? 'bg-green-100 text-green-700'
                              : 'bg-gray-100 text-gray-500'
                          }`}
                        >
                          {a.training_completed ? 'Yes' : 'No'}
                        </span>
                      </td>
                      <td className="px-4 py-3">
                        <span
                          className={`inline-block rounded px-2 py-0.5 text-xs font-medium ${
                            a.exam_completed
                              ? 'bg-green-100 text-green-700'
                              : 'bg-gray-100 text-gray-500'
                          }`}
                        >
                          {a.exam_completed ? 'Yes' : 'No'}
                        </span>
                      </td>
                      <td className="px-4 py-3 text-gray-500">
                        {a.score !== null ? `${a.score}%` : '—'}
                      </td>
                      <td className="px-4 py-3">
                        {a.passed === null ? (
                          <span className="text-gray-400">—</span>
                        ) : a.passed ? (
                          <span className="text-xs font-medium text-green-700">Passed</span>
                        ) : (
                          <span className="text-xs font-medium text-red-600">Failed</span>
                        )}
                      </td>
                    </tr>
                  ))}
            </tbody>
          </table>

          {!loading && assignments.length === 0 && (
            <div className="py-12 text-center text-sm text-gray-400">
              No users assigned to this course yet.
            </div>
          )}
        </div>
      </div>
    </div>
  )
}
