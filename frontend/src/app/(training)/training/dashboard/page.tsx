'use client'

import { useEffect, useState } from 'react'
import Link from 'next/link'
import api from '@/lib/api'

interface Course {
  id: string
  title: string
  description: string
  passing_grade: number
  is_active: boolean
  questions_count?: number
}

export default function TrainingDashboardPage() {
  const [courses, setCourses] = useState<Course[]>([])
  const [loading, setLoading] = useState(true)

  useEffect(() => {
    api
      .get<Course[]>('/trainings/courses')
      .then((r) => setCourses(r.data))
      .catch(() => {})
      .finally(() => setLoading(false))
  }, [])

  return (
    <div className="p-6">
      <div className="mb-6 flex items-center justify-between">
        <h1 className="text-xl font-semibold" style={{ color: '#1A4731' }}>
          Training Courses
        </h1>
        <Link
          href="/training/courses/new"
          className="rounded-md px-4 py-2 text-sm text-white transition-opacity hover:opacity-90"
          style={{ background: '#1A4731' }}
        >
          + Create New Training
        </Link>
      </div>

      <div className="rounded-lg border border-gray-100 bg-white">
        <div className="overflow-x-auto">
          <table className="w-full text-sm">
            <thead>
              <tr className="border-b border-gray-100 text-left text-xs font-medium uppercase tracking-wide text-gray-400">
                <th className="px-4 py-3">Title</th>
                <th className="px-4 py-3">Questions</th>
                <th className="px-4 py-3">Passing Grade</th>
                <th className="px-4 py-3">Status</th>
                <th className="px-4 py-3">Actions</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-gray-50">
              {loading
                ? Array.from({ length: 4 }).map((_, i) => (
                    <tr key={i}>
                      {Array.from({ length: 5 }).map((_, j) => (
                        <td key={j} className="px-4 py-3">
                          <div className="h-3 w-24 animate-pulse rounded bg-gray-100" />
                        </td>
                      ))}
                    </tr>
                  ))
                : courses.map((c) => (
                    <tr key={c.id} className="hover:bg-gray-50/40">
                      <td className="px-4 py-3 font-medium">{c.title}</td>
                      <td className="px-4 py-3 text-gray-500">
                        {(c as any).question_count ?? c.questions_count ?? '—'}
                      </td>
                      <td className="px-4 py-3 text-gray-500">{c.passing_grade}%</td>
                      <td className="px-4 py-3">
                        <span
                          className={`inline-block rounded px-2 py-0.5 text-xs font-medium ${
                            c.is_active
                              ? 'bg-green-100 text-green-700'
                              : 'bg-gray-100 text-gray-500'
                          }`}
                        >
                          {c.is_active ? 'Active' : 'Inactive'}
                        </span>
                      </td>
                      <td className="flex gap-3 px-4 py-3">
                        <Link
                          href={`/training/courses/${c.id}/assignments`}
                          className="text-sm text-blue-600 hover:underline"
                        >
                          Assignments
                        </Link>
                        <Link
                          href={`/training/courses/${c.id}/edit`}
                          className="text-sm hover:underline"
                          style={{ color: '#D97706' }}
                        >
                          Edit
                        </Link>
                      </td>
                    </tr>
                  ))}
            </tbody>
          </table>

          {!loading && courses.length === 0 && (
            <div className="py-16 text-center text-gray-400">
              <p>No training courses yet.</p>
              <Link
                href="/training/courses/new"
                className="mt-2 inline-block text-sm hover:underline"
                style={{ color: '#1A4731' }}
              >
                + Create your first training
              </Link>
            </div>
          )}
        </div>
      </div>
    </div>
  )
}
