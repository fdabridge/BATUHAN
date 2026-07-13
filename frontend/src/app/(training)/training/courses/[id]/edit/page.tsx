'use client'

import { useEffect, useState } from 'react'
import { useParams, useRouter } from 'next/navigation'
import api from '@/lib/api'

interface QuestionForm {
  question_number: number
  question_text: string
  option_a: string
  option_b: string
  option_c: string
  option_d: string
  correct_answer: string
}

function emptyQuestion(num: number): QuestionForm {
  return {
    question_number: num,
    question_text: '',
    option_a: '',
    option_b: '',
    option_c: '',
    option_d: '',
    correct_answer: 'A',
  }
}

export default function EditTrainingPage() {
  const params = useParams()
  const courseId = params.id as string
  const router = useRouter()

  const [loading, setLoading] = useState(true)
  const [saving, setSaving] = useState(false)
  const [error, setError] = useState('')

  const [title, setTitle] = useState('')
  const [description, setDescription] = useState('')
  const [passingGrade, setPassingGrade] = useState(70)
  const [isActive, setIsActive] = useState(true)
  const [materialFile, setMaterialFile] = useState<File | null>(null)
  const [examFile, setExamFile] = useState<File | null>(null)
  const [questions, setQuestions] = useState<QuestionForm[]>([emptyQuestion(1)])

  useEffect(() => {
    async function load() {
      try {
        const [courseRes, questionsRes] = await Promise.all([
          api.get(`/trainings/courses/${courseId}`),
          api.get(`/trainings/courses/${courseId}/questions`).catch(() => ({ data: [] })),
        ])
        const course = courseRes.data
        setTitle(course.title || '')
        setDescription(course.description || '')
        setPassingGrade(course.passing_grade ?? 70)
        setIsActive(course.is_active ?? true)

        const qs = questionsRes.data
        if (Array.isArray(qs) && qs.length > 0) {
          const LETTERS = ['A', 'B', 'C', 'D'] as const
          setQuestions(
            qs.map((q: any, i: number) => {
              const opts: string[] = Array.isArray(q.options) ? q.options : []
              return {
                question_number: q.question_number ?? i + 1,
                question_text: q.question_text || '',
                option_a: opts[0] || '',
                option_b: opts[1] || '',
                option_c: opts[2] || '',
                option_d: opts[3] || '',
                correct_answer: LETTERS[q.correct_option_index ?? 0] || 'A',
              }
            }),
          )
        }
      } catch {
        setError('Failed to load course data.')
      } finally {
        setLoading(false)
      }
    }
    load()
  }, [courseId])

  function addQuestion() {
    setQuestions((prev) => [...prev, emptyQuestion(prev.length + 1)])
  }

  function removeQuestion(idx: number) {
    setQuestions((prev) =>
      prev.filter((_, i) => i !== idx).map((q, i) => ({ ...q, question_number: i + 1 })),
    )
  }

  function updateQuestion(idx: number, field: keyof QuestionForm, value: string) {
    setQuestions((prev) =>
      prev.map((q, i) => (i === idx ? { ...q, [field]: value } : q)),
    )
  }

  async function handleSave() {
    if (!title.trim()) {
      setError('Title is required.')
      return
    }
    setSaving(true)
    setError('')

    try {
      // 1. Update the course
      await api.put(`/trainings/courses/${courseId}`, {
        title,
        description,
        passing_grade: passingGrade,
        is_active: isActive,
      })

      // 2. Upload material if selected
      if (materialFile) {
        const fd = new FormData()
        fd.append('file', materialFile)
        await api.post(`/trainings/courses/${courseId}/upload-material`, fd, {
          headers: { 'Content-Type': 'multipart/form-data' },
        })
      }

      // 3. Upload exam file if selected
      if (examFile) {
        const fd = new FormData()
        fd.append('file', examFile)
        await api.post(`/trainings/courses/${courseId}/upload-exam-file`, fd, {
          headers: { 'Content-Type': 'multipart/form-data' },
        })
      }

      // 4. Save questions
      const validQuestions = questions.filter((q) => q.question_text.trim())
      if (validQuestions.length > 0) {
        const mapped = validQuestions.map((q) => {
          const options = [q.option_a, q.option_b, q.option_c, q.option_d].filter(Boolean)
          const correctIndex = { A: 0, B: 1, C: 2, D: 3 }[q.correct_answer] ?? 0
          return {
            question_number: q.question_number,
            question_text: q.question_text,
            options,
            correct_option_index: correctIndex,
          }
        })
        await api.post(`/trainings/courses/${courseId}/questions`, { questions: mapped })
      }

      router.push('/training/dashboard')
    } catch (err: any) {
      setError(err?.response?.data?.detail || 'Failed to save training.')
    } finally {
      setSaving(false)
    }
  }

  if (loading) {
    return (
      <div className="flex items-center justify-center p-12">
        <span className="text-sm text-gray-400">Loading...</span>
      </div>
    )
  }

  return (
    <div className="mx-auto max-w-3xl p-6">
      <h1 className="mb-6 text-xl font-semibold" style={{ color: '#1A4731' }}>
        Edit Training
      </h1>

      {error && (
        <div className="mb-4 rounded-md bg-red-50 px-4 py-3 text-sm text-red-700">
          {error}
        </div>
      )}

      <div className="space-y-6">
        {/* Course Info */}
        <section className="rounded-lg border border-gray-100 bg-white p-5">
          <h2 className="mb-4 text-sm font-semibold text-gray-700">Course Info</h2>
          <div className="space-y-3">
            <div>
              <label className="mb-1 block text-xs font-medium text-gray-500">Title</label>
              <input
                type="text"
                value={title}
                onChange={(e) => setTitle(e.target.value)}
                className="w-full rounded-md border border-gray-200 px-3 py-2 text-sm focus:border-[#1A4731] focus:outline-none focus:ring-1 focus:ring-[#1A4731]"
              />
            </div>
            <div>
              <label className="mb-1 block text-xs font-medium text-gray-500">Description</label>
              <textarea
                value={description}
                onChange={(e) => setDescription(e.target.value)}
                rows={3}
                className="w-full rounded-md border border-gray-200 px-3 py-2 text-sm focus:border-[#1A4731] focus:outline-none focus:ring-1 focus:ring-[#1A4731]"
              />
            </div>
            <div className="flex items-center gap-3">
              <label className="relative inline-flex cursor-pointer items-center">
                <input
                  type="checkbox"
                  checked={isActive}
                  onChange={(e) => setIsActive(e.target.checked)}
                  className="peer sr-only"
                />
                <div className="h-5 w-9 rounded-full bg-gray-200 after:absolute after:left-[2px] after:top-[2px] after:h-4 after:w-4 after:rounded-full after:bg-white after:transition-all peer-checked:bg-[#1A4731] peer-checked:after:translate-x-full" />
              </label>
              <span className="text-sm text-gray-700">
                {isActive ? 'Active' : 'Inactive'}
                {!isActive && <span className="ml-1 text-xs text-gray-400">— new assignments blocked</span>}
              </span>
            </div>
          </div>
        </section>

        {/* Training Material */}
        <section className="rounded-lg border border-gray-100 bg-white p-5">
          <h2 className="mb-4 text-sm font-semibold text-gray-700">
            Training Material — upload to replace
          </h2>
          <input
            type="file"
            accept=".pdf,.mp4,.mov,.webm,.ppt,.pptx,.doc,.docx"
            onChange={(e) => setMaterialFile(e.target.files?.[0] ?? null)}
            className="text-sm text-gray-600"
          />
          <p className="mt-1 text-xs text-gray-400">
            {materialFile ? `Selected: ${materialFile.name}` : 'Accepted: PDF, MP4, MOV, WebM, PPT, PPTX, DOC, DOCX'}
          </p>
        </section>

        {/* Exam File */}
        <section className="rounded-lg border border-gray-100 bg-white p-5">
          <h2 className="mb-4 text-sm font-semibold text-gray-700">
            Exam File — upload to replace
          </h2>
          <input
            type="file"
            accept=".pdf,.doc,.docx"
            onChange={(e) => setExamFile(e.target.files?.[0] ?? null)}
            className="text-sm text-gray-600"
          />
          <p className="mt-1 text-xs text-gray-400">
            {examFile ? `Selected: ${examFile.name}` : 'Accepted: PDF, DOC, DOCX'}
          </p>
        </section>

        {/* Passing Grade */}
        <section className="rounded-lg border border-gray-100 bg-white p-5">
          <h2 className="mb-4 text-sm font-semibold text-gray-700">Passing Grade</h2>
          <div className="flex items-center gap-2">
            <input
              type="number"
              min={0}
              max={100}
              value={passingGrade}
              onChange={(e) => setPassingGrade(Number(e.target.value))}
              className="w-24 rounded-md border border-gray-200 px-3 py-2 text-sm focus:border-[#1A4731] focus:outline-none focus:ring-1 focus:ring-[#1A4731]"
            />
            <span className="text-sm text-gray-500">%</span>
          </div>
        </section>

        {/* Answer Key / Questions */}
        <section className="rounded-lg border border-gray-100 bg-white p-5">
          <div className="mb-4 flex items-center justify-between">
            <h2 className="text-sm font-semibold text-gray-700">Answer Key</h2>
            <button
              type="button"
              onClick={addQuestion}
              className="rounded-md px-3 py-1.5 text-xs text-white transition-opacity hover:opacity-90"
              style={{ background: '#1A4731' }}
            >
              + Add Question
            </button>
          </div>

          <div className="space-y-4">
            {questions.map((q, idx) => (
              <div key={idx} className="rounded-md border border-gray-100 bg-gray-50 p-4">
                <div className="mb-3 flex items-center justify-between">
                  <span className="text-xs font-semibold text-gray-500">
                    Question {q.question_number}
                  </span>
                  {questions.length > 1 && (
                    <button
                      type="button"
                      onClick={() => removeQuestion(idx)}
                      className="text-xs text-red-500 hover:underline"
                    >
                      Remove
                    </button>
                  )}
                </div>

                <input
                  type="text"
                  value={q.question_text}
                  onChange={(e) => updateQuestion(idx, 'question_text', e.target.value)}
                  placeholder="Question text"
                  className="mb-3 w-full rounded-md border border-gray-200 bg-white px-3 py-2 text-sm focus:border-[#1A4731] focus:outline-none focus:ring-1 focus:ring-[#1A4731]"
                />

                <div className="grid grid-cols-2 gap-2">
                  {(['A', 'B', 'C', 'D'] as const).map((letter) => {
                    const field = `option_${letter.toLowerCase()}` as keyof QuestionForm
                    return (
                      <div key={letter} className="flex items-center gap-2">
                        <input
                          type="radio"
                          name={`correct_${idx}`}
                          checked={q.correct_answer === letter}
                          onChange={() => updateQuestion(idx, 'correct_answer', letter)}
                          className="accent-[#1A4731]"
                        />
                        <span className="text-xs font-medium text-gray-500">{letter}.</span>
                        <input
                          type="text"
                          value={q[field] as string}
                          onChange={(e) => updateQuestion(idx, field, e.target.value)}
                          placeholder={`Option ${letter}`}
                          className="flex-1 rounded-md border border-gray-200 bg-white px-2 py-1.5 text-sm focus:border-[#1A4731] focus:outline-none focus:ring-1 focus:ring-[#1A4731]"
                        />
                      </div>
                    )
                  })}
                </div>
              </div>
            ))}
          </div>
        </section>

        {/* Save */}
        <div className="flex justify-end gap-3">
          <button
            type="button"
            onClick={() => router.push('/training/dashboard')}
            className="rounded-md border border-gray-200 px-4 py-2 text-sm text-gray-600 hover:bg-gray-50"
          >
            Cancel
          </button>
          <button
            type="button"
            onClick={handleSave}
            disabled={saving}
            className="rounded-md px-6 py-2 text-sm text-white transition-opacity hover:opacity-90 disabled:opacity-50"
            style={{ background: '#1A4731' }}
          >
            {saving ? 'Saving...' : 'Update Training'}
          </button>
        </div>
      </div>
    </div>
  )
}
