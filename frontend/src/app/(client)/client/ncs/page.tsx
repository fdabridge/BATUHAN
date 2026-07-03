'use client'

import { useEffect, useRef, useState } from 'react'
import api from '@/lib/api'
import { useAuth } from '@/lib/auth'

interface NCEvidence {
  id:          string
  file_name:   string | null
  upload_type: string
  uploaded_at: string
  round_number: number
}

interface NCReview {
  id:          string
  decision:    string
  notes:       string | null
  reviewed_at: string
  round_number: number
}

interface NCItem {
  id:          string
  nc_index:    number
  category:    string
  description: string
  status:      string
  due_date:    string | null
  evidence:    NCEvidence[]
  reviews:     NCReview[]
}

interface NCDecision {
  id:          string
  audit_set_id: string
  no_nc:       boolean
  notes:       string | null
  decided_at:  string
  items:       NCItem[]
}

const CAT_COLOR: Record<string, string> = {
  critical: 'text-red-600 bg-red-50',
  major:    'text-orange-700 bg-orange-50',
  minor:    'text-blue-700 bg-blue-50',
}

const STATUS_COLOR: Record<string, string> = {
  open:             'text-gray-600 bg-gray-100',
  client_responded: 'text-blue-700 bg-blue-100',
  rejected:         'text-red-600 bg-red-100',
  closed:           'text-green-700 bg-green-100',
}

export default function ClientNcsPage() {
  const { user } = useAuth()
  const [decision, setDecision] = useState<NCDecision | null | undefined>(undefined)
  const [loading, setLoading]   = useState(true)
  const [uploading, setUploading] = useState<string | null>(null)
  const [uploadType, setUploadType] = useState<Record<string, string>>({})
  const fileInputRef = useRef<HTMLInputElement>(null)
  const [activeNcId, setActiveNcId] = useState<string | null>(null)

  const load = () => {
    api.get<NCDecision | null>('/client/my-audit-set/ncs')
      .then((r) => setDecision(r.data))
      .catch(() => setDecision(null))
      .finally(() => setLoading(false))
  }

  useEffect(() => { load() }, [])

  const handleUpload = async (ncId: string, files: FileList | null) => {
    if (!files || files.length === 0) return
    const type = uploadType[ncId] || 'root_cause'
    setUploading(ncId)
    try {
      const formData = new FormData()
      formData.append('upload_type', type)
      Array.from(files).forEach((f) => formData.append('files', f))
      const auditSetId = decision?.audit_set_id
      await api.post(`/audit-sets/${auditSetId}/nc-items/${ncId}/evidence`, formData, {
        headers: { 'Content-Type': 'multipart/form-data' },
      })
      load()
    } catch (e: unknown) {
      const err = e as { response?: { data?: { detail?: string } } }
      alert(err.response?.data?.detail || 'Upload failed')
    } finally {
      setUploading(null)
    }
  }

  if (loading) return (
    <div className="p-8">
      <p className="text-sm text-gray-400">Loading nonconformities…</p>
    </div>
  )

  if (!decision) return (
    <div className="p-8 space-y-2">
      <h1 className="text-lg font-semibold text-gray-900">Nonconformities</h1>
      <p className="text-sm text-gray-500">
        No nonconformity decision has been submitted by the audit team yet.
        This page will update once the lead auditor completes their NC assessment.
      </p>
    </div>
  )

  if (decision.no_nc) return (
    <div className="p-8 space-y-4">
      <h1 className="text-lg font-semibold text-gray-900">Nonconformities</h1>
      <div className="rounded-lg bg-green-50 border border-green-200 p-4 flex items-center gap-3">
        <svg className="h-5 w-5 text-green-600" fill="none" viewBox="0 0 24 24" stroke="currentColor">
          <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M5 13l4 4L19 7" />
        </svg>
        <div>
          <p className="text-sm font-medium text-green-800">No nonconformities were identified</p>
          {decision.notes && <p className="text-xs text-green-600 mt-0.5">{decision.notes}</p>}
        </div>
      </div>
    </div>
  )

  const allClosed = decision.items.every((i) => i.status === 'closed')

  return (
    <div className="p-8 space-y-6 max-w-3xl">
      <div className="flex items-start justify-between">
        <div>
          <h1 className="text-lg font-semibold text-gray-900">Nonconformities</h1>
          <p className="text-sm text-gray-500 mt-1">
            Review each nonconformity below and upload your root cause analysis and corrective
            action plan. For each NC, upload both types of evidence separately.
          </p>
        </div>
        {allClosed && (
          <span className="rounded-full bg-green-50 border border-green-200 px-3 py-1 text-xs font-medium text-green-700">
            All NCs Closed
          </span>
        )}
      </div>

      {decision.items.map((item) => {
        const isOverdue = item.due_date && new Date(item.due_date) < new Date() && item.status !== 'closed'
        const latestReview = item.reviews[item.reviews.length - 1]
        const isRejected   = item.status === 'rejected'
        const canUpload    = item.status === 'open' || item.status === 'rejected'

        return (
          <div key={item.id} className={`rounded-lg border p-5 space-y-4 ${item.status === 'closed' ? 'border-green-200 bg-green-50/30' : 'border-gray-200 bg-white'}`}>
            {/* Header */}
            <div className="flex items-start justify-between gap-3">
              <div className="space-y-1">
                <div className="flex items-center gap-2 flex-wrap">
                  <span className="text-sm font-bold text-gray-800">NC-{item.nc_index}</span>
                  <span className={`rounded-full px-2 py-0.5 text-[11px] font-semibold uppercase ${CAT_COLOR[item.category] || 'bg-gray-100 text-gray-600'}`}>
                    {item.category}
                  </span>
                  <span className={`rounded-full px-2 py-0.5 text-[11px] font-medium ${STATUS_COLOR[item.status] || 'bg-gray-100 text-gray-600'}`}>
                    {item.status.replace(/_/g, ' ')}
                  </span>
                </div>
                <p className="text-sm text-gray-700 leading-relaxed">{item.description}</p>
              </div>
              {item.due_date && (
                <span className={`shrink-0 text-xs ${isOverdue ? 'text-red-600 font-semibold' : 'text-gray-400'}`}>
                  Due {new Date(item.due_date).toLocaleDateString()}{isOverdue ? ' ⚠' : ''}
                </span>
              )}
            </div>

            {/* Rejection feedback */}
            {isRejected && latestReview && (
              <div className="rounded bg-red-50 border border-red-200 p-3">
                <p className="text-xs font-medium text-red-700 mb-1">Auditor rejection notes:</p>
                <p className="text-sm text-red-600">{latestReview.notes || 'No notes provided'}</p>
                <p className="text-xs text-gray-400 mt-1">Please resubmit additional evidence addressing these concerns.</p>
              </div>
            )}

            {/* Previously uploaded evidence */}
            {item.evidence.length > 0 && (
              <div className="space-y-1">
                <p className="text-xs font-medium text-gray-500">Your uploads</p>
                {item.evidence.map((ev) => (
                  <div key={ev.id} className="flex items-center gap-2 text-xs">
                    <a
                      href={`${process.env.NEXT_PUBLIC_API_URL}/client/my-audit-set/ncs/${item.id}/evidence/${ev.id}/download`}
                      target="_blank"
                      rel="noreferrer"
                      className="text-green-700 hover:underline"
                    >
                      {ev.file_name || 'File'} ({ev.upload_type.replace(/_/g, ' ')})
                    </a>
                    <span className="text-gray-400">round {ev.round_number}</span>
                  </div>
                ))}
              </div>
            )}

            {/* Upload section */}
            {canUpload && (
              <div className="border-t pt-4 space-y-3">
                <p className="text-xs font-medium text-gray-500">
                  Upload evidence{isRejected ? ' (resubmission)' : ''}
                </p>
                <div className="flex items-center gap-3">
                  <select
                    value={uploadType[item.id] || 'root_cause'}
                    onChange={(e) => setUploadType((prev) => ({ ...prev, [item.id]: e.target.value }))}
                    className="rounded border border-gray-300 px-2 py-1.5 text-xs"
                  >
                    <option value="root_cause">Root Cause Analysis</option>
                    <option value="corrective_action">Corrective Action Plan</option>
                  </select>
                  <label className={`cursor-pointer rounded-lg border border-dashed border-gray-300 px-4 py-2 text-xs text-gray-600 hover:border-green-600 hover:text-green-700 transition-colors ${uploading === item.id ? 'opacity-50 pointer-events-none' : ''}`}>
                    {uploading === item.id ? 'Uploading…' : 'Choose files…'}
                    <input
                      type="file"
                      multiple
                      className="hidden"
                      onChange={(e) => handleUpload(item.id, e.target.files)}
                      disabled={uploading === item.id}
                    />
                  </label>
                </div>
                <p className="text-[11px] text-gray-400">
                  You can upload multiple files (PDF, DOCX, images). Upload root cause and corrective action separately.
                </p>
              </div>
            )}

            {/* Closed state */}
            {item.status === 'closed' && (
              <div className="flex items-center gap-2 text-sm text-green-700">
                <svg className="h-4 w-4" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M5 13l4 4L19 7" />
                </svg>
                NC closed — corrective action accepted by auditor
              </div>
            )}

            {/* Waiting state */}
            {item.status === 'client_responded' && (
              <p className="text-xs text-blue-600">
                Evidence submitted. Awaiting auditor review.
              </p>
            )}
          </div>
        )
      })}
    </div>
  )
}
