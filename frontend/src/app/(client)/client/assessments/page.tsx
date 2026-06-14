'use client'

import { useEffect, useRef, useState, useCallback } from 'react'
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

// ── Portal 58 — FR.211 per-stage upload + ORG_REP sign via viewer ──────────

interface MyAuditSet {
  id: string
  workflow_status: string | null
}

interface SharedDocLite {
  id: string
  document_type: string
  status: string
  stage_type: string | null
}

// Mirrors backend STATUS_ORDER (documents_router.py) for "X or later" gates.
const STATUS_ORDER = [
  'pending_review', 'in_planning', 'quotation_sent', 'agreement_signed',
  'fr218_in_progress', 'fr218_complete', 'stage1_scheduled', 'stage1_in_progress',
  'stage1_complete', 'stage2_scheduled', 'stage2_in_progress', 'stage2_complete',
  'under_review', 'committee_review', 'certified',
]

function statusAtLeast(current: string | null, threshold: string): boolean {
  const a = STATUS_ORDER.indexOf(current ?? '')
  const b = STATUS_ORDER.indexOf(threshold)
  return a >= 0 && b >= 0 && a >= b
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

// Portal 58 — per-stage FR.211 auditor assessment.
// One upload per stage; signing happens in the viewer with the org-rep
// employee picker (Portal 56 flow). Re-uploads are blocked while a previous
// upload exists for the stage to keep the org-rep slot deterministic.
function Fr211StageRow({
  auditSetId, stageType, stageLabel, doc, onChanged,
}: {
  auditSetId: string
  stageType: string
  stageLabel: string
  doc: SharedDocLite | undefined
  onChanged: () => void
}) {
  const [file, setFile]   = useState<File | null>(null)
  const [busy, setBusy]   = useState(false)
  const [error, setError] = useState('')
  const fileRef = useRef<HTMLInputElement>(null)

  async function upload() {
    if (!file) { setError('Please choose a file first.'); return }
    setBusy(true); setError('')
    try {
      const fd = new FormData()
      fd.append('file', file)
      const today = new Date().toISOString().slice(0, 10)
      const label = `FR.211 Auditor Assessment — ${stageLabel}`
      await api.post(
        `/audit-sets/${auditSetId}/documents/upload`
          + `?label=${encodeURIComponent(label)}`
          + `&document_type=auditor_assessment`
          + `&stage_type=${encodeURIComponent(stageType)}`
          + `&upload_date=${today}`,
        fd,
        { headers: { 'Content-Type': 'multipart/form-data' } },
      )
      setFile(null)
      if (fileRef.current) fileRef.current.value = ''
      onChanged()
    } catch (err: unknown) {
      const detail = (err as { response?: { data?: { detail?: string } } })?.response?.data?.detail
      setError(detail || 'Upload failed.')
    } finally {
      setBusy(false)
    }
  }

  return (
    <li className="flex flex-wrap items-center justify-between gap-3 px-4 py-3">
      <div>
        <p className="text-sm font-medium text-gray-800">{stageLabel} Auditor Assessment</p>
        <p className="mt-0.5 text-xs text-gray-400">FR.211 — Lead Auditor / Auditor Assessment</p>
        {error && <p className="mt-1 text-xs text-red-500">{error}</p>}
      </div>
      <div className="flex items-center gap-2">
        {!doc && (
          <>
            <input
              ref={fileRef}
              type="file"
              accept=".docx,.pdf"
              onChange={(e) => setFile(e.target.files?.[0] ?? null)}
              className="w-48 text-xs text-gray-700 file:mr-2 file:rounded file:border-0 file:bg-gray-100 file:px-2 file:py-0.5 file:text-xs"
            />
            <button
              type="button"
              onClick={upload}
              disabled={busy || !file}
              className="rounded-lg bg-[#1A4731] px-3 py-1.5 text-xs font-medium text-white disabled:opacity-40 hover:bg-[#143828]"
            >
              {busy ? 'Uploading…' : 'Upload'}
            </button>
          </>
        )}
        {doc && doc.status !== 'signed' && (
          <a
            href={`/client/viewer/shared_doc/${doc.id}`}
            className="rounded-lg bg-[#1A4731] px-3 py-1.5 text-xs font-medium text-white hover:bg-[#143828]"
          >
            Open to Sign
          </a>
        )}
        {doc?.status === 'signed' && (
          <span className="rounded-full bg-green-100 px-2.5 py-1 text-xs font-semibold text-green-700">
            ✓ Submitted
          </span>
        )}
      </div>
    </li>
  )
}

function Fr211Section({
  auditSet, docs, onChanged,
}: {
  auditSet: MyAuditSet
  docs: SharedDocLite[]
  onChanged: () => void
}) {
  const rows: { stageType: string; label: string; threshold: string }[] = [
    { stageType: 'stage_1', label: 'Stage 1', threshold: 'stage1_complete' },
    { stageType: 'stage_2', label: 'Stage 2', threshold: 'stage2_complete' },
  ].filter(r => statusAtLeast(auditSet.workflow_status, r.threshold))
  if (rows.length === 0) return null

  return (
    <div>
      <h2 className="mb-3 text-sm font-semibold uppercase tracking-wide text-gray-500">
        FR.211 Auditor Assessment
      </h2>
      <p className="mb-3 text-xs text-gray-400">
        Download the blank FR.211 from your audit document set, complete the assessment of
        the lead auditor for the stage, then upload it here and open it to sign as the
        organisation representative.
      </p>
      <ul className="divide-y rounded-xl border bg-white">
        {rows.map((r) => (
          <Fr211StageRow
            key={r.stageType}
            auditSetId={auditSet.id}
            stageType={r.stageType}
            stageLabel={r.label}
            doc={docs.find(
              (d) => d.document_type === 'auditor_assessment' && d.stage_type === r.stageType,
            )}
            onChanged={onChanged}
          />
        ))}
      </ul>
    </div>
  )
}

export default function ClientAssessmentsPage() {
  const [assessments, setAssessments] = useState<Assessment[]>([])
  const [auditSet, setAuditSet] = useState<MyAuditSet | null>(null)
  const [docs, setDocs] = useState<SharedDocLite[]>([])
  const [loading, setLoading] = useState(true)

  const load = useCallback(async () => {
    try {
      const [a, s, d] = await Promise.all([
        api.get<Assessment[]>('/client/my-audit-set/assessments'),
        api.get<MyAuditSet>('/client/my-audit-set'),
        api.get<SharedDocLite[]>('/client/my-audit-set/documents'),
      ])
      setAssessments(a.data)
      setAuditSet(s.data)
      setDocs(d.data)
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

      {/* Portal 58 — FR.211 per-stage upload + ORG_REP sign via viewer */}
      {auditSet && (
        <div className="mt-10 space-y-8">
          <Fr211Section auditSet={auditSet} docs={docs} onChanged={load} />
        </div>
      )}
    </div>
  )
}
