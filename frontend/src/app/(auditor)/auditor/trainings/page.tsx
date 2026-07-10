'use client'

import { useEffect, useState } from 'react'
import Link from 'next/link'
import api from '@/lib/api'

interface MyTraining {
  id: string
  course_id: string
  course_title: string
  training_completed: boolean
  exam_completed: boolean
  exam_score: number | null
  exam_passed: boolean | null
}

export default function AuditorTrainingsPage() {
  const [trainings, setTrainings] = useState<MyTraining[]>([])
  const [loading, setLoading] = useState(true)

  useEffect(() => {
    api
      .get<MyTraining[]>('/trainings/my')
      .then((r) => setTrainings(r.data))
      .catch(() => {})
      .finally(() => setLoading(false))
  }, [])

  return (
    <div className="p-6">
      <h1 className="mb-6 text-xl font-semibold" style={{ color: '#1A4731' }}>
        My Trainings
      </h1>

      {loading ? (
        <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
          {Array.from({ length: 3 }).map((_, i) => (
            <div key={i} className="h-44 animate-pulse rounded-lg border border-gray-100 bg-white" />
          ))}
        </div>
      ) : trainings.length === 0 ? (
        <div className="rounded-lg border border-gray-100 bg-white py-16 text-center text-sm text-gray-400">
          No trainings assigned to you yet.
        </div>
      ) : (
        <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
          {trainings.map((t) => (
            <div
              key={t.id}
              className="flex flex-col justify-between rounded-lg border border-gray-100 bg-white p-5"
            >
              <div>
                <h3 className="mb-2 font-medium" style={{ color: '#1A4731' }}>
                  {t.course_title}
                </h3>
                <div className="mb-3 space-y-1 text-sm">
                  <div className="flex items-center justify-between">
                    <span className="text-gray-500">Training</span>
                    <span
                      className={`rounded px-2 py-0.5 text-xs font-medium ${
                        t.training_completed
                          ? 'bg-green-100 text-green-700'
                          : 'bg-yellow-100 text-yellow-700'
                      }`}
                    >
                      {t.training_completed ? 'Completed' : 'Pending'}
                    </span>
                  </div>
                  <div className="flex items-center justify-between">
                    <span className="text-gray-500">Exam</span>
                    <span
                      className={`rounded px-2 py-0.5 text-xs font-medium ${
                        t.exam_completed
                          ? 'bg-green-100 text-green-700'
                          : 'bg-gray-100 text-gray-500'
                      }`}
                    >
                      {t.exam_completed ? 'Completed' : 'Not taken'}
                    </span>
                  </div>
                  {t.exam_score !== null && (
                    <div className="flex items-center justify-between">
                      <span className="text-gray-500">Score</span>
                      <span className="text-sm font-medium">
                        {t.exam_score}%{' '}
                        {t.exam_passed !== null && (
                          <span className={t.exam_passed ? 'text-green-700' : 'text-red-600'}>
                            ({t.exam_passed ? 'Passed' : 'Failed'})
                          </span>
                        )}
                      </span>
                    </div>
                  )}
                </div>
              </div>
              <div className="flex gap-2 border-t border-gray-50 pt-3">
                <Link
                  href={`/auditor/trainings/${t.course_id}/take`}
                  className="flex-1 rounded-md border border-gray-200 px-3 py-1.5 text-center text-xs font-medium text-gray-600 hover:bg-gray-50"
                >
                  View Training
                </Link>
                {t.training_completed && !t.exam_completed && (
                  <Link
                    href={`/auditor/trainings/${t.course_id}/exam`}
                    className="flex-1 rounded-md px-3 py-1.5 text-center text-xs font-medium text-white transition-opacity hover:opacity-90"
                    style={{ background: '#D97706' }}
                  >
                    Take Exam
                  </Link>
                )}
              </div>
            </div>
          ))}
        </div>
      )}
    </div>
  )
}
