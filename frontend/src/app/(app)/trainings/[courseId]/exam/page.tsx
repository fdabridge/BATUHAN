'use client'

import { useEffect, useState } from 'react'
import { useParams, useRouter } from 'next/navigation'
import api from '@/lib/api'

interface Question {
  id: string
  question_number: number
  question_text: string
  options: string[]
}

interface MyAssignment {
  id: string
  course_id: string
  training_completed: boolean
  exam_completed: boolean
}

interface ExamResult {
  score: number
  passed: boolean
  passing_grade: number
  total_questions: number
  correct_count: number
}

export default function ExamPage() {
  const params = useParams()
  const courseId = params.courseId as string
  const router = useRouter()

  const [questions, setQuestions] = useState<Question[]>([])
  const [assignment, setAssignment] = useState<MyAssignment | null>(null)
  const [examPdfUrl, setExamPdfUrl] = useState<string | null>(null)
  const [answers, setAnswers] = useState<Record<number, number>>({}) // question_number -> selected_option_index
  const [loading, setLoading] = useState(true)
  const [submitting, setSubmitting] = useState(false)
  const [result, setResult] = useState<ExamResult | null>(null)
  const [error, setError] = useState('')

  useEffect(() => {
    async function load() {
      try {
        const myRes = await api.get<MyAssignment[]>('/trainings/my')
        const myAssignment = myRes.data.find((a: any) => a.course_id === courseId)
        if (myAssignment) setAssignment(myAssignment)

        const qRes = await api.get(`/trainings/courses/${courseId}/questions`)
        setQuestions(qRes.data)

        try {
          const pdfRes = await api.get(`/trainings/courses/${courseId}/exam-file`, {
            responseType: 'blob',
          })
          const url = URL.createObjectURL(pdfRes.data)
          setExamPdfUrl(url)
        } catch {
          // Exam file might not be uploaded
        }
      } catch {
        setError('Failed to load exam.')
      } finally {
        setLoading(false)
      }
    }
    load()

    return () => {
      if (examPdfUrl) URL.revokeObjectURL(examPdfUrl)
    }
  }, [courseId])

  function selectAnswer(questionNumber: number, optionIndex: number) {
    if (result || assignment?.exam_completed) return
    setAnswers((prev) => ({ ...prev, [questionNumber]: optionIndex }))
  }

  async function handleSubmit() {
    if (!assignment) return
    if (Object.keys(answers).length < questions.length) {
      setError('Please answer all questions before submitting.')
      return
    }

    setSubmitting(true)
    setError('')

    try {
      const payload = questions.map((q) => ({
        question_number: q.question_number,
        selected_option_index: answers[q.question_number] ?? -1,
      }))
      const res = await api.post(
        `/trainings/assignments/${assignment.id}/submit-exam`,
        { answers: payload },
      )
      setResult(res.data)
    } catch (err: any) {
      setError(err?.response?.data?.detail || 'Failed to submit exam.')
    } finally {
      setSubmitting(false)
    }
  }

  const isDisabled = !!result || !!assignment?.exam_completed
  const backPath = '/trainings'

  if (loading) {
    return (
      <div className="flex items-center justify-center p-12">
        <span className="text-sm text-gray-400">Loading exam...</span>
      </div>
    )
  }

  return (
    <div className="flex flex-col gap-4">
      <div className="flex items-center gap-4">
        <button
          onClick={() => router.push(backPath)}
          className="text-sm text-gray-400 hover:text-gray-600"
        >
          &larr; Back
        </button>
        <h1 className="text-xl font-semibold" style={{ color: '#1A4731' }}>
          Exam
        </h1>
      </div>

      {error && (
        <div className="rounded-md bg-red-50 px-4 py-3 text-sm text-red-700">{error}</div>
      )}

      {result && (
        <div
          className={`rounded-lg border p-5 ${
            result.passed
              ? 'border-green-200 bg-green-50'
              : 'border-red-200 bg-red-50'
          }`}
        >
          <h2 className={`text-lg font-semibold ${result.passed ? 'text-green-800' : 'text-red-800'}`}>
            {result.passed ? 'Congratulations! You passed!' : 'Unfortunately, you did not pass.'}
          </h2>
          <div className="mt-2 space-y-1 text-sm">
            <p>
              <span className="text-gray-600">Your Score: </span>
              <span className="font-semibold">{result.score}%</span>
            </p>
            <p>
              <span className="text-gray-600">Passing Grade: </span>
              <span className="font-semibold">{result.passing_grade}%</span>
            </p>
            <p>
              <span className="text-gray-600">Correct: </span>
              <span className="font-semibold">{result.correct_count}/{result.total_questions}</span>
            </p>
          </div>
          <button
            onClick={() => router.push(backPath)}
            className="mt-4 rounded-md px-4 py-2 text-sm text-white transition-opacity hover:opacity-90"
            style={{ background: '#1A4731' }}
          >
            Back to Trainings
          </button>
        </div>
      )}

      {/* Split-screen layout */}
      <div className="flex gap-4" style={{ height: '75vh' }}>
        {/* Left: Exam PDF */}
        <div className="flex-1 rounded-lg border border-gray-100 bg-white">
          {examPdfUrl ? (
            <object
              data={examPdfUrl}
              type="application/pdf"
              className="h-full w-full rounded-lg"
            >
              <div className="flex items-center justify-center p-12 text-sm text-gray-400">
                Unable to display PDF.{' '}
                <a href={examPdfUrl} target="_blank" rel="noreferrer" className="ml-1 text-blue-600 hover:underline">
                  Download instead
                </a>
              </div>
            </object>
          ) : (
            <div className="flex h-full items-center justify-center text-sm text-gray-400">
              No exam document uploaded.
            </div>
          )}
        </div>

        {/* Right: Answer form */}
        <div className="flex flex-1 flex-col rounded-lg border border-gray-100 bg-white">
          <div className="border-b border-gray-100 px-5 py-3">
            <span className="text-sm font-medium">Answer Sheet</span>
          </div>

          <div className="flex-1 space-y-4 overflow-y-auto p-5">
            {questions.length === 0 ? (
              <p className="text-sm text-gray-400">No questions available.</p>
            ) : (
              questions.map((q) => (
                <div key={q.id} className="rounded-md border border-gray-100 bg-gray-50 p-4">
                  <p className="mb-2 text-sm font-medium text-gray-700">
                    {q.question_number}. {q.question_text}
                  </p>
                  <div className="space-y-1.5">
                    {q.options.map((opt, idx) => {
                      const selected = answers[q.question_number] === idx
                      return (
                        <label
                          key={idx}
                          className={`flex cursor-pointer items-center gap-2 rounded-md px-3 py-2 text-sm transition-colors ${
                            selected
                              ? 'bg-[#F0FAF4] text-[#1A4731]'
                              : 'hover:bg-gray-100'
                          } ${isDisabled ? 'pointer-events-none opacity-60' : ''}`}
                        >
                          <input
                            type="radio"
                            name={`q_${q.question_number}`}
                            checked={selected}
                            onChange={() => selectAnswer(q.question_number, idx)}
                            disabled={isDisabled}
                            className="accent-[#1A4731]"
                          />
                          {opt}
                        </label>
                      )
                    })}
                  </div>
                </div>
              ))
            )}
          </div>

          {!isDisabled && questions.length > 0 && (
            <div className="border-t border-gray-100 p-4">
              <button
                onClick={handleSubmit}
                disabled={submitting}
                className="w-full rounded-md py-2.5 text-sm font-medium text-white transition-opacity hover:opacity-90 disabled:opacity-50"
                style={{ background: '#D97706' }}
              >
                {submitting ? 'Submitting...' : 'Submit Exam'}
              </button>
            </div>
          )}
        </div>
      </div>
    </div>
  )
}
