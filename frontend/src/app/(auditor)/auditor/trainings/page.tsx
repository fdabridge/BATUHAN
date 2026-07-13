'use client'

import { useEffect, useState, useMemo } from 'react'
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

type Section = 'all' | 'pending' | 'exam_ready' | 'passed' | 'failed'

function TrainingCard({ t, linkBase }: { t: MyTraining; linkBase: string }) {
  const examReady = t.training_completed && !t.exam_completed

  return (
    <div className={`flex flex-col justify-between rounded-lg border bg-white p-5 ${examReady ? 'border-orange-200' : 'border-gray-100'}`}>
      <div>
        <h3 className="mb-2 font-medium" style={{ color: '#1A4731' }}>{t.course_title}</h3>
        <div className="mb-3 space-y-1 text-sm">
          <div className="flex items-center justify-between">
            <span className="text-gray-500">Training</span>
            <span className={`rounded px-2 py-0.5 text-xs font-medium ${t.training_completed ? 'bg-green-100 text-green-700' : 'bg-yellow-100 text-yellow-700'}`}>
              {t.training_completed ? 'Completed' : 'Pending'}
            </span>
          </div>
          <div className="flex items-center justify-between">
            <span className="text-gray-500">Exam</span>
            <span className={`rounded px-2 py-0.5 text-xs font-medium ${
              t.exam_passed === true ? 'bg-emerald-100 text-emerald-700'
                : t.exam_passed === false ? 'bg-red-100 text-red-700'
                : examReady ? 'bg-orange-100 text-orange-700'
                : 'bg-gray-100 text-gray-500'
            }`}>
              {t.exam_passed === true ? 'Passed' : t.exam_passed === false ? 'Failed' : examReady ? 'Ready' : 'Pending'}
            </span>
          </div>
          {t.exam_score !== null && (
            <div className="flex items-center justify-between">
              <span className="text-gray-500">Score</span>
              <span className="text-sm font-semibold tabular-nums">{t.exam_score}%</span>
            </div>
          )}
        </div>
      </div>
      <div className="flex gap-2 border-t border-gray-50 pt-3">
        <Link
          href={`${linkBase}/${t.course_id}/take`}
          className="flex-1 rounded-md border border-gray-200 px-3 py-1.5 text-center text-xs font-medium text-gray-600 hover:bg-gray-50"
        >
          View Training
        </Link>
        {examReady && (
          <Link
            href={`${linkBase}/${t.course_id}/exam`}
            className="flex-1 animate-pulse rounded-md px-3 py-1.5 text-center text-xs font-semibold text-white"
            style={{ background: '#D97706', animationDuration: '2s' }}
          >
            Take Exam
          </Link>
        )}
      </div>
    </div>
  )
}

export default function AuditorTrainingsPage() {
  const [trainings, setTrainings] = useState<MyTraining[]>([])
  const [loading, setLoading] = useState(true)
  const [section, setSection] = useState<Section>('all')

  useEffect(() => {
    api.get<MyTraining[]>('/trainings/my')
      .then((r) => setTrainings(r.data))
      .catch(() => {})
      .finally(() => setLoading(false))
  }, [])

  const filtered = useMemo(() => {
    if (section === 'all') return trainings
    return trainings.filter((t) => {
      if (section === 'pending') return !t.training_completed
      if (section === 'exam_ready') return t.training_completed && !t.exam_completed
      if (section === 'passed') return t.exam_passed === true
      if (section === 'failed') return t.exam_passed === false
      return true
    })
  }, [trainings, section])

  const counts = useMemo(() => ({
    all: trainings.length,
    pending: trainings.filter((t) => !t.training_completed).length,
    exam_ready: trainings.filter((t) => t.training_completed && !t.exam_completed).length,
    passed: trainings.filter((t) => t.exam_passed === true).length,
    failed: trainings.filter((t) => t.exam_passed === false).length,
  }), [trainings])

  const TABS: { key: Section; label: string }[] = [
    { key: 'all',        label: `All (${counts.all})` },
    { key: 'pending',    label: `Pending (${counts.pending})` },
    { key: 'exam_ready', label: `Exam Ready (${counts.exam_ready})` },
    { key: 'passed',     label: `Passed (${counts.passed})` },
    { key: 'failed',     label: `Failed (${counts.failed})` },
  ]

  return (
    <div className="p-6">
      <h1 className="mb-6 text-xl font-semibold" style={{ color: '#1A4731' }}>My Trainings</h1>

      {!loading && trainings.length > 0 && (
        <div className="mb-4 flex gap-1">
          {TABS.map((tab) => (
            <button
              key={tab.key}
              onClick={() => setSection(tab.key)}
              className={`rounded-md px-3 py-1.5 text-xs font-medium transition-colors ${
                section === tab.key ? 'bg-[#1A4731] text-white' : 'bg-gray-100 text-gray-600 hover:bg-gray-200'
              }`}
            >
              {tab.label}
            </button>
          ))}
        </div>
      )}

      {loading ? (
        <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
          {Array.from({ length: 3 }).map((_, i) => (
            <div key={i} className="h-44 animate-pulse rounded-lg border border-gray-100 bg-white" />
          ))}
        </div>
      ) : filtered.length === 0 ? (
        <div className="rounded-lg border border-gray-100 bg-white py-16 text-center text-sm text-gray-400">
          {trainings.length === 0 ? 'No trainings assigned to you yet.' : 'No trainings match this filter.'}
        </div>
      ) : (
        <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
          {filtered.map((t) => (
            <TrainingCard key={t.id} t={t} linkBase="/auditor/trainings" />
          ))}
        </div>
      )}
    </div>
  )
}
