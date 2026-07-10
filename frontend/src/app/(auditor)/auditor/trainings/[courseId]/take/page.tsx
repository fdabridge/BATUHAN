'use client'

import { useEffect, useState } from 'react'
import { useParams, useRouter } from 'next/navigation'
import api from '@/lib/api'

interface MyAssignment {
  id: string
  course_id: string
  course_title: string
  training_completed: boolean
}

export default function AuditorTakeTrainingPage() {
  const params = useParams()
  const courseId = params.courseId as string
  const router = useRouter()

  const [assignment, setAssignment] = useState<MyAssignment | null>(null)
  const [pdfUrl, setPdfUrl] = useState<string | null>(null)
  const [loading, setLoading] = useState(true)
  const [completing, setCompleting] = useState(false)
  const [error, setError] = useState('')
  const [success, setSuccess] = useState('')

  useEffect(() => {
    async function load() {
      try {
        const myRes = await api.get<MyAssignment[]>('/trainings/my')
        const myAssignment = myRes.data.find((a: any) => a.course_id === courseId)
        if (myAssignment) setAssignment(myAssignment)

        try {
          const pdfRes = await api.get(`/trainings/courses/${courseId}/material`, {
            responseType: 'blob',
          })
          setPdfUrl(URL.createObjectURL(pdfRes.data))
        } catch {
          // Material might not be uploaded
        }
      } catch {
        setError('Failed to load training.')
      } finally {
        setLoading(false)
      }
    }
    load()

    return () => {
      if (pdfUrl) URL.revokeObjectURL(pdfUrl)
    }
  }, [courseId])

  async function handleComplete() {
    if (!assignment) return
    setCompleting(true)
    setError('')
    try {
      await api.post(`/trainings/assignments/${assignment.id}/complete-training`)
      setSuccess('Training marked as completed!')
      setAssignment({ ...assignment, training_completed: true })
    } catch (err: any) {
      setError(err?.response?.data?.detail || 'Failed to complete training.')
    } finally {
      setCompleting(false)
    }
  }

  if (loading) {
    return (
      <div className="flex items-center justify-center p-12">
        <span className="text-sm text-gray-400">Loading training...</span>
      </div>
    )
  }

  return (
    <div className="flex flex-col gap-4 p-6">
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-4">
          <button
            onClick={() => router.push('/auditor/trainings')}
            className="text-sm text-gray-400 hover:text-gray-600"
          >
            &larr; Back
          </button>
          <h1 className="text-xl font-semibold" style={{ color: '#1A4731' }}>
            {assignment?.course_title || 'Training'}
          </h1>
        </div>
        <div className="flex items-center gap-3">
          {assignment && !assignment.training_completed && (
            <button
              onClick={handleComplete}
              disabled={completing}
              className="rounded-md px-4 py-2 text-sm text-white transition-opacity hover:opacity-90 disabled:opacity-50"
              style={{ background: '#1A4731' }}
            >
              {completing ? 'Marking...' : 'Mark as Completed'}
            </button>
          )}
          {assignment?.training_completed && (
            <span className="rounded bg-green-100 px-3 py-1 text-xs font-medium text-green-700">
              Completed
            </span>
          )}
        </div>
      </div>

      {error && <div className="rounded-md bg-red-50 px-4 py-3 text-sm text-red-700">{error}</div>}
      {success && <div className="rounded-md bg-green-50 px-4 py-3 text-sm text-green-700">{success}</div>}

      <div className="flex-1 rounded-lg border border-gray-100 bg-white">
        {pdfUrl ? (
          <object data={pdfUrl} type="application/pdf" className="h-[75vh] w-full rounded-lg">
            <div className="flex items-center justify-center p-12 text-sm text-gray-400">
              Unable to display PDF.{' '}
              <a href={pdfUrl} target="_blank" rel="noreferrer" className="ml-1 text-blue-600 hover:underline">
                Download instead
              </a>
            </div>
          </object>
        ) : (
          <div className="flex items-center justify-center p-12 text-sm text-gray-400">
            No training material uploaded for this course.
          </div>
        )}
      </div>
    </div>
  )
}
