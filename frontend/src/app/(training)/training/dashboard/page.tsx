'use client'

import { useEffect, useState, useMemo } from 'react'
import Link from 'next/link'
import api from '@/lib/api'
import { GuidedActionCard } from '@/components/ui/GuidedActionCard'

interface Summary {
  total_courses: number
  active_courses: number
  total_assignments: number
  pending_training: number
  training_completed_exam_pending: number
  passed_count: number
  failed_count: number
}

interface Course {
  id: string
  title: string
  description: string | null
  question_count: number
  passing_grade: number
  is_active: boolean
  is_ready: boolean
  missing_requirements: string[]
  assignment_count: number
  passed_count: number
  failed_count: number
}

type CourseFilter = 'all' | 'ready' | 'not_ready' | 'active' | 'inactive'

export default function TrainingDashboardPage() {
  const [summary, setSummary] = useState<Summary | null>(null)
  const [courses, setCourses] = useState<Course[]>([])
  const [loading, setLoading] = useState(true)
  const [search, setSearch] = useState('')
  const [courseFilter, setCourseFilter] = useState<CourseFilter>('all')

  useEffect(() => {
    Promise.all([
      api.get<Summary>('/trainings/summary'),
      api.get<Course[]>('/trainings/courses'),
    ])
      .then(([sRes, cRes]) => {
        setSummary(sRes.data)
        setCourses(cRes.data)
      })
      .catch(() => {})
      .finally(() => setLoading(false))
  }, [])

  const filtered = useMemo(() => {
    let list = courses
    if (search.trim()) {
      const q = search.toLowerCase()
      list = list.filter(
        (c) =>
          c.title.toLowerCase().includes(q) ||
          (c.description ?? '').toLowerCase().includes(q),
      )
    }
    if (courseFilter === 'ready') list = list.filter((c) => c.is_ready)
    else if (courseFilter === 'not_ready') list = list.filter((c) => !c.is_ready)
    else if (courseFilter === 'active') list = list.filter((c) => c.is_active)
    else if (courseFilter === 'inactive') list = list.filter((c) => !c.is_active)
    return list
  }, [courses, search, courseFilter])

  const cards: { label: string; value: number | string; color: string }[] = summary
    ? [
        { label: 'Courses',       value: summary.total_courses,                   color: 'bg-blue-50 text-blue-700' },
        { label: 'Active',        value: summary.active_courses,                  color: 'bg-green-50 text-green-700' },
        { label: 'Assignments',   value: summary.total_assignments,               color: 'bg-purple-50 text-purple-700' },
        { label: 'Pending',       value: summary.pending_training,                color: 'bg-yellow-50 text-yellow-700' },
        { label: 'Exam Pending',  value: summary.training_completed_exam_pending, color: 'bg-orange-50 text-orange-700' },
        { label: 'Passed',        value: summary.passed_count,                    color: 'bg-emerald-50 text-emerald-700' },
        { label: 'Failed',        value: summary.failed_count,                    color: 'bg-red-50 text-red-700' },
      ]
    : []

  const FILTERS: { key: CourseFilter; label: string }[] = [
    { key: 'all',       label: 'All' },
    { key: 'ready',     label: 'Ready' },
    { key: 'not_ready', label: 'Not Ready' },
    { key: 'active',    label: 'Active' },
    { key: 'inactive',  label: 'Inactive' },
  ]

  const incompleteCourse = courses.find((course) => !course.is_ready)
  const failedCourse = courses.find((course) => course.failed_count > 0)
  const guidedAction = incompleteCourse
    ? {
        eyebrow: 'Course setup incomplete',
        title: `Finish ${incompleteCourse.title}`,
        description: incompleteCourse.missing_requirements.length > 0
          ? `Complete ${incompleteCourse.missing_requirements.join(', ')} before assigning this training.`
          : 'Complete the remaining course requirements before assigning this training.',
        href: `/training/courses/${incompleteCourse.id}/edit`,
        actionLabel: 'Continue course setup',
        tone: 'action' as const,
      }
    : failedCourse
      ? {
          eyebrow: 'Follow-up required',
          title: `${failedCourse.failed_count} failed attempt${failedCourse.failed_count === 1 ? '' : 's'} in ${failedCourse.title}`,
          description: 'Open the assignment list to review the affected participants and reassign eligible failed attempts safely.',
          href: `/training/courses/${failedCourse.id}/assignments`,
          actionLabel: 'Review participants',
          tone: 'action' as const,
        }
      : summary && summary.training_completed_exam_pending > 0
        ? {
            eyebrow: 'Exam queue',
            title: `${summary.training_completed_exam_pending} participant${summary.training_completed_exam_pending === 1 ? '' : 's'} ready for an exam`,
            description: 'Review participant progress and follow up on training that is complete but still awaiting an exam attempt.',
            href: '/training/people',
            actionLabel: 'Open people view',
            tone: 'waiting' as const,
          }
        : {
            eyebrow: 'Training workspace',
            title: courses.length > 0 ? 'Training programme is up to date' : 'Create the first training',
            description: courses.length > 0
              ? 'No course setup or failed-exam follow-up is currently blocking the queue.'
              : 'Build the course material and exam before assigning participants.',
            href: courses.length > 0 ? '/training/people' : '/training/courses/new',
            actionLabel: courses.length > 0 ? 'Review people' : 'Create training',
            tone: courses.length > 0 ? 'success' as const : 'neutral' as const,
          }

  return (
    <div className="p-6">
      <div className="mb-6 flex items-center justify-between">
        <h1 className="text-xl font-semibold" style={{ color: '#1A4731' }}>
          Training Dashboard
        </h1>
        <Link
          href="/training/courses/new"
          className="rounded-md px-4 py-2 text-sm text-white transition-opacity hover:opacity-90"
          style={{ background: '#1A4731' }}
        >
          + Create New Training
        </Link>
      </div>

      {!loading && (
        <div className="mb-6">
          <GuidedActionCard {...guidedAction} />
        </div>
      )}

      {/* Summary cards */}
      {loading ? (
        <div className="mb-6 grid grid-cols-2 gap-3 sm:grid-cols-4 lg:grid-cols-7">
          {Array.from({ length: 7 }).map((_, i) => (
            <div key={i} className="h-20 animate-pulse rounded-lg border border-gray-100 bg-white" />
          ))}
        </div>
      ) : (
        <div className="mb-6 grid grid-cols-2 gap-3 sm:grid-cols-4 lg:grid-cols-7">
          {cards.map((c) => (
            <div key={c.label} className={`rounded-lg border border-gray-100 p-4 ${c.color}`}>
              <p className="text-2xl font-bold">{c.value}</p>
              <p className="mt-0.5 text-xs font-medium opacity-80">{c.label}</p>
            </div>
          ))}
        </div>
      )}

      {/* Search + filter */}
      <div className="mb-3 flex flex-wrap items-center gap-3">
        <input
          type="text"
          value={search}
          onChange={(e) => setSearch(e.target.value)}
          placeholder="Search courses..."
          className="w-56 rounded-md border border-gray-200 px-3 py-1.5 text-sm focus:border-[#1A4731] focus:outline-none focus:ring-1 focus:ring-[#1A4731]"
        />
        <div className="flex gap-1">
          {FILTERS.map((f) => (
            <button
              key={f.key}
              onClick={() => setCourseFilter(f.key)}
              className={`rounded-md px-3 py-1.5 text-xs font-medium transition-colors ${
                courseFilter === f.key
                  ? 'bg-[#1A4731] text-white'
                  : 'bg-gray-100 text-gray-600 hover:bg-gray-200'
              }`}
            >
              {f.label}
            </button>
          ))}
        </div>
      </div>

      {/* Courses table */}
      <div className="rounded-lg border border-gray-100 bg-white">
        <div className="overflow-x-auto">
          <table className="w-full text-sm">
            <thead>
              <tr className="border-b border-gray-100 text-left text-xs font-medium uppercase tracking-wide text-gray-400">
                <th className="px-4 py-3">Title</th>
                <th className="px-4 py-3">Questions</th>
                <th className="px-4 py-3">Grade</th>
                <th className="px-4 py-3">Assigned</th>
                <th className="px-4 py-3">Passed/Failed</th>
                <th className="px-4 py-3">Status</th>
                <th className="px-4 py-3">Actions</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-gray-50">
              {loading
                ? Array.from({ length: 4 }).map((_, i) => (
                    <tr key={i}>
                      {Array.from({ length: 7 }).map((_, j) => (
                        <td key={j} className="px-4 py-3">
                          <div className="h-3 w-16 animate-pulse rounded bg-gray-100" />
                        </td>
                      ))}
                    </tr>
                  ))
                : filtered.map((c) => (
                    <tr key={c.id} className="hover:bg-gray-50/40">
                      <td className="px-4 py-3 font-medium">{c.title}</td>
                      <td className="px-4 py-3 text-gray-500">{c.question_count ?? '—'}</td>
                      <td className="px-4 py-3 text-gray-500">{c.passing_grade}%</td>
                      <td className="px-4 py-3 tabular-nums text-gray-500">{c.assignment_count}</td>
                      <td className="px-4 py-3 tabular-nums">
                        <span className="text-emerald-700">{c.passed_count}</span>
                        <span className="text-gray-300"> / </span>
                        <span className="text-red-600">{c.failed_count}</span>
                      </td>
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
                        {!c.is_active && (
                          <span className="ml-1 text-[10px] text-gray-400">no new assigns</span>
                        )}
                        {c.is_ready ? (
                          <span className="ml-1.5 inline-block rounded bg-emerald-100 px-1.5 py-0.5 text-[10px] font-medium text-emerald-700">
                            Ready
                          </span>
                        ) : (
                          <span className="ml-1.5 inline-block rounded bg-orange-100 px-1.5 py-0.5 text-[10px] font-medium text-orange-700" title={c.missing_requirements.join(', ')}>
                            Not Ready
                          </span>
                        )}
                      </td>
                      <td className="flex gap-3 px-4 py-3">
                        <Link href={`/training/courses/${c.id}/preview`} className="text-sm hover:underline" style={{ color: '#1A4731' }}>
                          Preview
                        </Link>
                        <Link href={`/training/courses/${c.id}/assignments`} className="text-sm text-blue-600 hover:underline">
                          Assignments
                        </Link>
                        <Link href={`/training/courses/${c.id}/edit`} className="text-sm hover:underline" style={{ color: '#D97706' }}>
                          Edit
                        </Link>
                      </td>
                    </tr>
                  ))}
            </tbody>
          </table>

          {!loading && filtered.length === 0 && (
            <div className="py-16 text-center text-gray-400">
              {courses.length === 0 ? (
                <>
                  <p>No training courses yet.</p>
                  <Link href="/training/courses/new" className="mt-2 inline-block text-sm hover:underline" style={{ color: '#1A4731' }}>
                    + Create your first training
                  </Link>
                </>
              ) : (
                <p>No courses match your search or filter.</p>
              )}
            </div>
          )}
        </div>
      </div>
    </div>
  )
}
