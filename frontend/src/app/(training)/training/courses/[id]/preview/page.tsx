'use client'

import { useEffect, useRef, useState } from 'react'
import { useParams } from 'next/navigation'
import Link from 'next/link'
import api from '@/lib/api'

interface CourseInfo {
  id: string
  title: string
  description: string | null
  material_kind: string | null
  material_file_name: string | null
  exam_kind: string | null
  exam_file_name: string | null
  passing_grade: number
  is_active: boolean
  is_ready: boolean
  missing_requirements: string[]
  question_count: number
}

interface Question {
  question_number: number
  question_text: string
  options: string[]
  correct_option_index: number
}

export default function CoursePreviewPage() {
  const params = useParams()
  const courseId = params.id as string

  const [course, setCourse] = useState<CourseInfo | null>(null)
  const [questions, setQuestions] = useState<Question[]>([])
  const [materialUrl, setMaterialUrl] = useState<string | null>(null)
  const [examUrl, setExamUrl] = useState<string | null>(null)
  const [loading, setLoading] = useState(true)
  const materialUrlRef = useRef<string | null>(null)
  const examUrlRef = useRef<string | null>(null)

  useEffect(() => {
    async function load() {
      try {
        const [cRes, qRes] = await Promise.all([
          api.get(`/trainings/courses/${courseId}`),
          api.get(`/trainings/courses/${courseId}/questions`).catch(() => ({ data: [] })),
        ])
        setCourse(cRes.data)
        setQuestions(Array.isArray(qRes.data) ? qRes.data : [])

        try {
          const mRes = await api.get(`/trainings/courses/${courseId}/material`, { responseType: 'blob' })
          const url = URL.createObjectURL(mRes.data)
          materialUrlRef.current = url
          setMaterialUrl(url)
        } catch { /* not uploaded */ }

        try {
          const eRes = await api.get(`/trainings/courses/${courseId}/exam-file`, { responseType: 'blob' })
          const url = URL.createObjectURL(eRes.data)
          examUrlRef.current = url
          setExamUrl(url)
        } catch { /* not uploaded */ }
      } catch { /* */ }
      finally { setLoading(false) }
    }
    load()

    return () => {
      if (materialUrlRef.current) URL.revokeObjectURL(materialUrlRef.current)
      if (examUrlRef.current) URL.revokeObjectURL(examUrlRef.current)
    }
  }, [courseId])

  if (loading) {
    return <div className="flex items-center justify-center p-12"><span className="text-sm text-gray-400">Loading preview...</span></div>
  }

  if (!course) {
    return <div className="p-6 text-sm text-red-600">Course not found.</div>
  }

  const mk = course.material_kind || 'pdf'
  const ek = course.exam_kind || 'pdf'

  return (
    <div className="space-y-6 p-6">
      {/* Header */}
      <div className="flex items-center gap-4">
        <Link href="/training/dashboard" className="text-sm text-gray-400 hover:text-gray-600">&larr; Dashboard</Link>
        <h1 className="text-xl font-semibold" style={{ color: '#1A4731' }}>Preview: {course.title}</h1>
      </div>

      {/* Course info + readiness */}
      <section className="rounded-lg border border-gray-100 bg-white p-5">
        <div className="flex items-start justify-between">
          <div>
            <h2 className="text-sm font-semibold text-gray-700">Course Info</h2>
            {course.description && <p className="mt-1 text-sm text-gray-500">{course.description}</p>}
            <p className="mt-2 text-xs text-gray-400">Passing grade: {course.passing_grade}%</p>
          </div>
          <div className="flex items-center gap-2">
            <span className={`rounded px-2 py-0.5 text-xs font-medium ${course.is_active ? 'bg-green-100 text-green-700' : 'bg-gray-100 text-gray-500'}`}>
              {course.is_active ? 'Active' : 'Inactive'}
            </span>
            {course.is_ready ? (
              <span className="rounded bg-emerald-100 px-2 py-0.5 text-xs font-medium text-emerald-700">Ready</span>
            ) : (
              <span className="rounded bg-orange-100 px-2 py-0.5 text-xs font-medium text-orange-700">Not Ready</span>
            )}
          </div>
        </div>
        {course.missing_requirements.length > 0 && (
          <div className="mt-3 rounded-md border border-orange-200 bg-orange-50 p-3">
            <p className="text-xs font-medium text-orange-800">Missing requirements:</p>
            <ul className="mt-1 list-inside list-disc text-xs text-orange-700">
              {course.missing_requirements.map((m) => <li key={m}>{m}</li>)}
            </ul>
          </div>
        )}
      </section>

      {/* Training Material */}
      <section className="rounded-lg border border-gray-100 bg-white p-5">
        <h2 className="mb-3 text-sm font-semibold text-gray-700">
          Training Material
          {course.material_file_name && <span className="ml-2 text-xs font-normal text-gray-400">{course.material_file_name}</span>}
        </h2>
        {!materialUrl ? (
          <p className="text-sm text-gray-400">No training material uploaded.</p>
        ) : mk === 'video' ? (
          <video src={materialUrl} controls className="max-h-[50vh] w-full rounded-lg bg-black">
            Your browser does not support video playback.
          </video>
        ) : mk === 'pdf' ? (
          <object data={materialUrl} type="application/pdf" className="h-[50vh] w-full rounded-lg">
            <p className="p-4 text-sm text-gray-400">
              Unable to display PDF. <a href={materialUrl} target="_blank" rel="noreferrer" className="text-blue-600 hover:underline">Open in new tab</a>
            </p>
          </object>
        ) : (
          <div className="flex items-center gap-3 rounded-md border border-gray-200 bg-gray-50 p-4">
            <span className="text-sm text-gray-600">{course.material_file_name || 'Training material'}</span>
            <a href={materialUrl} download={course.material_file_name || 'material'} className="rounded-md bg-[#1A4731] px-3 py-1 text-xs text-white hover:opacity-90">
              Download
            </a>
          </div>
        )}
      </section>

      {/* Exam File */}
      <section className="rounded-lg border border-gray-100 bg-white p-5">
        <h2 className="mb-3 text-sm font-semibold text-gray-700">
          Exam File
          {course.exam_file_name && <span className="ml-2 text-xs font-normal text-gray-400">{course.exam_file_name}</span>}
        </h2>
        {!examUrl ? (
          <p className="text-sm text-gray-400">No exam file uploaded.</p>
        ) : ek === 'pdf' ? (
          <object data={examUrl} type="application/pdf" className="h-[50vh] w-full rounded-lg">
            <p className="p-4 text-sm text-gray-400">
              Unable to display PDF. <a href={examUrl} target="_blank" rel="noreferrer" className="text-blue-600 hover:underline">Open in new tab</a>
            </p>
          </object>
        ) : (
          <div className="flex items-center gap-3 rounded-md border border-gray-200 bg-gray-50 p-4">
            <span className="text-sm text-gray-600">{course.exam_file_name || 'Exam file'}</span>
            <a href={examUrl} download={course.exam_file_name || 'exam'} className="rounded-md bg-[#1A4731] px-3 py-1 text-xs text-white hover:opacity-90">
              Download
            </a>
          </div>
        )}
      </section>

      {/* Answer Key */}
      <section className="rounded-lg border border-gray-100 bg-white p-5">
        <h2 className="mb-3 text-sm font-semibold text-gray-700">
          Answer Key ({questions.length} question{questions.length !== 1 ? 's' : ''})
        </h2>
        {questions.length === 0 ? (
          <p className="text-sm text-gray-400">No exam questions configured.</p>
        ) : (
          <div className="space-y-3">
            {questions.map((q) => (
              <div key={q.question_number} className="rounded-md border border-gray-100 bg-gray-50 p-4">
                <p className="mb-2 text-sm font-medium text-gray-700">
                  Question {q.question_number}
                </p>
                <div className="space-y-1">
                  {q.options.map((opt, idx) => {
                    const letter = ['A', 'B', 'C', 'D'][idx] ?? String(idx + 1)
                    return (
                      <div
                        key={idx}
                        className={`flex items-center gap-2 rounded-md px-3 py-1.5 text-sm ${
                          idx === q.correct_option_index
                            ? 'bg-emerald-50 font-medium text-emerald-800'
                            : 'text-gray-600'
                        }`}
                      >
                        {idx === q.correct_option_index ? (
                          <span className="flex h-4 w-4 items-center justify-center rounded-full bg-emerald-600 text-[10px] text-white">&#10003;</span>
                        ) : (
                          <span className="h-4 w-4 rounded-full border border-gray-300" />
                        )}
                        <span>{letter}</span>
                        {opt && opt !== letter && <span className="text-gray-500">- {opt}</span>}
                      </div>
                    )
                  })}
                </div>
              </div>
            ))}
          </div>
        )}
      </section>
    </div>
  )
}
