'use client'

import { useEffect, useState } from 'react'
import { useParams, useRouter } from 'next/navigation'
import api from '@/lib/api'
import { TrainingMaterialViewer } from '@/components/training/TrainingMaterialViewer'

interface CourseInfo {
  id: string
  title: string
  description: string
  material_kind: string | null
  material_file_name: string | null
  material_page_count: number | null
}

interface MyAssignment {
  id: string
  course_id: string
  course_title: string
  training_completed: boolean
  training_last_page_seen?: number
}

export default function TakeTrainingPage() {
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
  const [canComplete, setCanComplete] = useState(false)

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
    <div className="flex flex-col gap-4">
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-4">
          <button
            onClick={() => router.push('/trainings')}
            className="text-sm text-gray-400 hover:text-gray-600"
          >
            &larr; Back
          </button>
          <h1 className="text-xl font-semibold" style={{ color: '#1A4731' }}>
            {course?.title || 'Training'}
          </h1>
        </div>
        <div className="flex items-center gap-3">
          {assignment && !assignment.training_completed && (
            <button
              onClick={handleComplete}
              disabled={completing || !canComplete}
              className="rounded-md px-4 py-2 text-sm text-white transition-opacity hover:opacity-90 disabled:opacity-50"
              style={{ background: '#1A4731' }}
            >
              {completing ? 'Marking...' : canComplete ? 'Mark as Completed' : 'Reach final page to complete'}
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

      {/* Material viewer */}
      <div className="flex-1 rounded-lg border border-gray-100 bg-white">
        <TrainingMaterialViewer
          blobUrl={blobUrl}
          kind={kind}
          fileName={course?.material_file_name}
          assignmentId={assignment?.id}
          materialPageCount={course?.material_page_count}
          initialLastPageSeen={assignment?.training_last_page_seen || 0}
          completed={assignment?.training_completed}
          onCanCompleteChange={setCanComplete}
        />
      </div>
    </div>
  )
}
