'use client'

import { useState } from 'react'
import { useRouter } from 'next/navigation'
import api from '@/lib/api'

interface QuestionForm {
  question_number: number
  correct_answer: string
}

function emptyQuestion(num: number): QuestionForm {
  return {
    question_number: num,
    correct_answer: 'A',
  }
}

export default function CreateTrainingPage() {
  const router = useRouter()
  const [saving, setSaving] = useState(false)
  const [error, setError] = useState('')

  const [title, setTitle] = useState('')
  const [description, setDescription] = useState('')
  const [passingGrade, setPassingGrade] = useState(70)
  const [examDurationMinutes, setExamDurationMinutes] = useState(30)
  const [materialFile, setMaterialFile] = useState<File | null>(null)
  const [examFile, setExamFile] = useState<File | null>(null)
  const [questions, setQuestions] = useState<QuestionForm[]>([emptyQuestion(1)])

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

  function validateQuestions(): string | null {
    if (questions.length === 0) return 'Add at least one answer key row.'
    return null
  }

  async function handleSave() {
    if (!title.trim()) {
      setError('Title is required.')
      return
    }
    const qErr = validateQuestions()
    if (qErr) {
      setError(qErr)
      return
    }
    setSaving(true)
    setError('')

    try {
      // 1. Create the course
      const { data: course } = await api.post('/trainings/courses', {
        title,
        description,
        exam_duration_minutes: examDurationMinutes,
      })
      const courseId = course.id

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

      // 4. Save answer key. The uploaded exam file contains the actual question text.
      const mapped = questions.map((q) => ({
        question_number: q.question_number,
        question_text: `Question ${q.question_number}`,
        options: ['A', 'B', 'C', 'D'],
        correct_option_index: ({ A: 0, B: 1, C: 2, D: 3 } as Record<string, number>)[q.correct_answer] ?? 0,
      }))
      await api.post(`/trainings/courses/${courseId}/questions`, { questions: mapped })

      // 5. Update passing grade
      await api.put(`/trainings/courses/${courseId}`, {
        passing_grade: passingGrade,
        exam_duration_minutes: examDurationMinutes,
      })

      router.push('/training/dashboard')
    } catch (err: any) {
      setError(err?.response?.data?.detail || 'Failed to save training.')
    } finally {
      setSaving(false)
    }
  }

  return (
    <div className="mx-auto max-w-3xl p-6">
      <h1 className="mb-6 text-xl font-semibold" style={{ color: '#1A4731' }}>
        Create New Training
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
                placeholder="e.g. Food Safety Level 2"
              />
            </div>
            <div>
              <label className="mb-1 block text-xs font-medium text-gray-500">Description</label>
              <textarea
                value={description}
                onChange={(e) => setDescription(e.target.value)}
                rows={3}
                className="w-full rounded-md border border-gray-200 px-3 py-2 text-sm focus:border-[#1A4731] focus:outline-none focus:ring-1 focus:ring-[#1A4731]"
                placeholder="Brief description of the training course..."
              />
            </div>
          </div>
        </section>

        {/* Training Material */}
        <section className="rounded-lg border border-gray-100 bg-white p-5">
          <h2 className="mb-4 text-sm font-semibold text-gray-700">Training Material</h2>
          <input
            type="file"
            accept=".pdf,.mp4,.mov,.webm"
            onChange={(e) => setMaterialFile(e.target.files?.[0] ?? null)}
            className="text-sm text-gray-600"
          />
          <p className="mt-1 text-xs text-gray-400">
            {materialFile ? `Selected: ${materialFile.name}` : 'Accepted: PDF, MP4, MOV, WebM. For slide trainings, export PPT/PPTX to PDF first.'}
          </p>
        </section>

        {/* Exam File */}
        <section className="rounded-lg border border-gray-100 bg-white p-5">
          <h2 className="mb-4 text-sm font-semibold text-gray-700">Exam File</h2>
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

        {/* Exam Timer */}
        <section className="rounded-lg border border-gray-100 bg-white p-5">
          <h2 className="mb-4 text-sm font-semibold text-gray-700">Exam Timer</h2>
          <div className="flex items-center gap-2">
            <input
              type="number"
              min={1}
              value={examDurationMinutes}
              onChange={(e) => setExamDurationMinutes(Math.max(1, Number(e.target.value) || 1))}
              className="w-24 rounded-md border border-gray-200 px-3 py-2 text-sm focus:border-[#1A4731] focus:outline-none focus:ring-1 focus:ring-[#1A4731]"
            />
            <span className="text-sm text-gray-500">minutes</span>
          </div>
          <p className="mt-1 text-xs text-gray-400">
            Countdown starts when the user opens the exam and does not reset on refresh.
          </p>
        </section>

        {/* Answer Key / Questions */}
        <section className="rounded-lg border border-gray-100 bg-white p-5">
          <div className="mb-4 flex items-center justify-between">
            <div>
              <h2 className="text-sm font-semibold text-gray-700">Answer Key</h2>
              <p className="mt-1 text-xs text-gray-400">
                The exam file is the question paper. Add one row per question and mark the correct answer.
              </p>
            </div>
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

                <div className="grid grid-cols-4 gap-2">
                  {(['A', 'B', 'C', 'D'] as const).map((letter) => {
                    return (
                      <label
                        key={letter}
                        className={`flex cursor-pointer items-center justify-center gap-2 rounded-md border px-3 py-2 text-sm ${
                          q.correct_answer === letter
                            ? 'border-[#1A4731] bg-emerald-50 font-semibold text-[#1A4731]'
                            : 'border-gray-200 bg-white text-gray-600'
                        }`}
                      >
                        <input
                          type="radio"
                          name={`correct_${idx}`}
                          checked={q.correct_answer === letter}
                          onChange={() => updateQuestion(idx, 'correct_answer', letter)}
                          className="accent-[#1A4731]"
                        />
                        {letter}
                      </label>
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
            {saving ? 'Saving...' : 'Save Training'}
          </button>
        </div>
      </div>
    </div>
  )
}
