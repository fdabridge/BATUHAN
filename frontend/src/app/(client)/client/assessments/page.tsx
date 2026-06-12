'use client'

import { useEffect, useState, useCallback } from 'react'
import api from '@/lib/api'

interface Assessment {
  id:           string
  stage_type:   string
  stage_order:  number | null
  auditor_name: string
  auditor_role: string | null
  rating:       number | null
  comments:     string | null
  is_signed:    boolean
  signed_at:    string | null
}

const STAGE_LABELS: Record<string, string> = {
  stage_1:        'Stage 1',
  stage_2:        'Stage 2',
  surveillance:   'Surveillance',
  recertification:'Recertification',
}

function fmtDate(iso: string | null) {
  if (!iso) return ''
  return new Date(iso).toLocaleDateString('en-GB', { day: 'numeric', month: 'long', year: 'numeric' })
}

function StarPicker({ value, onChange }: { value: number; onChange: (n: number) => void }) {
  const [hovered, setHovered] = useState(0)
  return (
    <div className="flex gap-1">
      {[1, 2, 3, 4, 5].map(n => (
        <button
          key={n}
          type="button"
          onClick={() => onChange(n)}
          onMouseEnter={() => setHovered(n)}
          onMouseLeave={() => setHovered(0)}
          className="text-2xl leading-none transition-transform hover:scale-110 focus:outline-none"
          aria-label={`Rate ${n} star${n !== 1 ? 's' : ''}`}
        >
          <span className={(hovered || value) >= n ? 'text-amber-400' : 'text-gray-200'}>★</span>
        </button>
      ))}
    </div>
  )
}

function SignedCard({ assessment }: { assessment: Assessment }) {
  return (
    <div className="rounded-xl border border-green-200 bg-green-50 p-5">
      <div className="flex items-start justify-between">
        <div>
          <p className="font-semibold text-gray-800">{assessment.auditor_name}</p>
          <p className="mt-0.5 text-xs text-gray-500">{assessment.auditor_role}</p>
        </div>
        <span className="rounded-full bg-green-100 px-2.5 py-1 text-xs font-semibold text-green-700">
          ✓ Submitted {fmtDate(assessment.signed_at)}
        </span>
      </div>
      <div className="mt-3 flex gap-0.5">
        {[1, 2, 3, 4, 5].map(n => (
          <span key={n} className={`text-xl ${(assessment.rating ?? 0) >= n ? 'text-amber-400' : 'text-gray-200'}`}>★</span>
        ))}
      </div>
      {assessment.comments && (
        <p className="mt-2 text-sm text-gray-600 italic">&quot;{assessment.comments}&quot;</p>
      )}
    </div>
  )
}

function AssessmentCard({ assessment, onSigned }: { assessment: Assessment; onSigned: () => void }) {
  const [rating, setRating]     = useState(assessment.rating ?? 0)
  const [comments, setComments] = useState(assessment.comments ?? '')
  const [error, setError]       = useState('')
  const [busy, setBusy]         = useState(false)
  const [signedDate, setSignedDate] = useState(() => new Date().toISOString().slice(0, 10))

  if (assessment.is_signed) return <SignedCard assessment={assessment} />

  async function saveDraft() {
    if (!rating) return
    try {
      await api.patch(`/client/my-audit-set/assessments/${assessment.id}/draft`, {
        rating,
        comments: comments || null,
      })
    } catch {
      // ignore — saving draft silently
    }
  }

  async function handleSign() {
    if (!rating) { setError('Please select a rating before signing'); return }
    setBusy(true)
    setError('')
    try {
      await api.patch(`/client/my-audit-set/assessments/${assessment.id}/draft`, {
        rating,
        comments: comments || null,
      })
      await api.post(`/client/my-audit-set/assessments/${assessment.id}/sign/direct`, { signed_date: signedDate })
      onSigned()
    } catch (err: unknown) {
      const detail = (err as { response?: { data?: { detail?: string } } })?.response?.data?.detail
      setError(detail || 'Signing failed')
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="rounded-xl border bg-white p-5">
      <div className="mb-4">
        <p className="font-semibold text-gray-800">{assessment.auditor_name}</p>
        <p className="mt-0.5 text-xs text-gray-400">
          {assessment.auditor_role} · {STAGE_LABELS[assessment.stage_type] ?? assessment.stage_type}
        </p>
      </div>

      <div className="space-y-3">
        <div>
          <p className="mb-1.5 text-sm font-medium text-gray-700">Overall Rating</p>
          <StarPicker value={rating} onChange={setRating} />
          {rating > 0 && (
            <p className="mt-1 text-xs text-gray-400">
              {['', 'Poor', 'Fair', 'Good', 'Very Good', 'Excellent'][rating]}
            </p>
          )}
        </div>
        <div>
          <label className="mb-1 block text-sm font-medium text-gray-700">
            Comments <span className="font-normal text-gray-400">(optional)</span>
          </label>
          <textarea
            rows={3}
            value={comments}
            onChange={e => setComments(e.target.value)}
            onBlur={saveDraft}
            placeholder="Your feedback about this auditor's conduct and professionalism…"
            className="w-full rounded-lg border px-3 py-2 text-sm resize-none focus:outline-none focus:ring-2 focus:ring-[#1A4731]/30"
          />
        </div>
        <div className="flex items-end gap-3">
          <div>
            <label className="block text-xs text-gray-500 mb-1">Signing date</label>
            <input
              type="date"
              value={signedDate}
              onChange={e => setSignedDate(e.target.value)}
              className="rounded-lg border px-2 py-1.5 text-sm"
            />
          </div>
          <button
            type="button"
            onClick={handleSign}
            disabled={!rating || busy}
            className="rounded-lg bg-[#1A4731] px-5 py-2.5 text-sm font-medium text-white disabled:opacity-40 hover:bg-[#143828]"
          >
            {busy ? 'Signing…' : 'Submit & Sign'}
          </button>
        </div>
        {error && <p className="text-xs text-red-500">{error}</p>}
      </div>
    </div>
  )
}

export default function ClientAssessmentsPage() {
  const [assessments, setAssessments] = useState<Assessment[]>([])
  const [loading, setLoading] = useState(true)

  const load = useCallback(async () => {
    try {
      const r = await api.get<Assessment[]>('/client/my-audit-set/assessments')
      setAssessments(r.data)
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => { load() }, [load])

  if (loading) return <div className="p-8 text-sm text-gray-400">Loading assessments…</div>

  const grouped = assessments.reduce<Record<string, Assessment[]>>((acc, a) => {
    acc[a.stage_type] = acc[a.stage_type] || []
    acc[a.stage_type].push(a)
    return acc
  }, {})

  return (
    <div className="mx-auto max-w-2xl p-6">
      <div className="mb-6">
        <h1 className="text-xl font-bold text-gray-900">Auditor Assessments</h1>
        <p className="mt-1 text-sm text-gray-400">
          Please rate each auditor who conducted your audit. Your feedback helps IFC Global
          maintain quality and is required for ISO 17021-1 compliance.
        </p>
      </div>

      {assessments.length === 0 ? (
        <div className="py-16 text-center text-sm text-gray-400">
          No assessments available yet. These will appear after each audit stage is complete.
        </div>
      ) : (
        <div className="space-y-6">
          {Object.entries(grouped).map(([stageType, list]) => (
            <div key={stageType}>
              <h2 className="mb-3 text-sm font-semibold uppercase tracking-wide text-gray-500">
                {STAGE_LABELS[stageType] ?? stageType}
              </h2>
              <div className="space-y-3">
                {list.map(a => (
                  <AssessmentCard key={a.id} assessment={a} onSigned={load} />
                ))}
              </div>
            </div>
          ))}
        </div>
      )}
    </div>
  )
}
