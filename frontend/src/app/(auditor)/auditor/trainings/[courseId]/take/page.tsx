'use client'

import { useEffect, useState } from 'react'
import { useParams, useRouter } from 'next/navigation'
import api from '@/lib/api'

interface CourseInfo {
  id: string
  title: string
  description: string
  material_kind: string | null
  material_file_name: string | null
}

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

  const [course, setCourse] = useState<CourseInfo | null>(null)
  const [assignment, setAssignment] = useState<MyAssignment | null>(null)
  const [blobUrl, setBlobUrl] = useState<string | null>(null)
  const [loading, setLoading] = useState(true)
  const [completing, setCompleting] = useState(false)
  const [error, setError] = useState('')
  const [success, setSuccess] = useState('')

  useEffect(() => {
    async function load() {
      try {
        const [courseRes, myRes] = await Promise.all([
          api.get(`/trainings/courses/${courseId}`),
          api.get<MyAssignment[]>('/trainings/my'),
        ])
        setCourse(courseRes.data)
        const myAssignment = myRes.data.find((a: any) => a.course_id === courseId)
        if (myAssignment) setAssignment(myAssignment)

        try {
          const matRes = await api.get(`/trainings/courses/${courseId}/material`, {
            responseType: 'blob',
          })
          setBlobUrl(URL.createObjectURL(matRes.data))
        } catch {
          // No material uploaded
        }
      } catch {
        setError('Failed to load training.')
      } finally {
        setLoading(false)
      }
    }
    load()

    return () => {
      if (blobUrl) URL.revokeObjectURL(blobUrl)
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

  const kind = course?.material_kind || 'pdf'

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
            {course?.title || assignment?.course_title || 'Training'}
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

      {course?.description && (
        <p className="text-sm text-gray-500">{course.description}</p>
      )}

      <div className="flex-1 rounded-lg border border-gray-100 bg-white">
        {!blobUrl ? (
          <div className="flex items-center justify-center p-12 text-sm text-gray-400">
            No training material uploaded for this course.
          </div>
        ) : kind === 'video' ? (
          <video src={blobUrl} controls className="h-[75vh] w-full rounded-lg bg-black">
            Your browser does not support video playback.
          </video>
        ) : kind === 'pdf' ? (
          <object data={blobUrl} type="application/pdf" className="h-[75vh] w-full rounded-lg">
            <div className="flex items-center justify-center p-12 text-sm text-gray-400">
              Unable to display PDF.{' '}
              <a href={blobUrl} target="_blank" rel="noreferrer" className="ml-1 text-blue-600 hover:underline">
                Download instead
              </a>
            </div>
          </object>
        ) : (
          <div className="flex h-[75vh] flex-col items-center justify-center gap-4 text-center">
            <div className="rounded-full bg-gray-100 p-4">
              <svg width="32" height="32" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5" className="text-gray-400">
                <path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z" />
                <path d="M14 2v6h6" />
                <path d="M12 18v-6" />
                <path d="M9 15l3 3 3-3" />
              </svg>
            </div>
            <div>
              <p className="text-sm font-medium text-gray-700">
                {course?.material_file_name || 'Training material'}
              </p>
              <p className="mt-1 text-xs text-gray-400">
                This file type cannot be previewed in the browser.
              </p>
            </div>
            <a
              href={blobUrl}
              download={course?.material_file_name || 'training_material'}
              className="rounded-md px-5 py-2 text-sm font-medium text-white transition-opacity hover:opacity-90"
              style={{ background: '#1A4731' }}
            >
              Download File
            </a>
          </div>
        )}
      </div>
    </div>
  )
}
