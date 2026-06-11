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
  is_signed:    boolean
  signed_at:    string | null
}

const STAGE_TYPES = [
  { value: 'stage_1',         label: 'Stage 1' },
  { value: 'stage_2',         label: 'Stage 2' },
  { value: 'surveillance',    label: 'Surveillance' },
  { value: 'recertification', label: 'Recertification' },
]

function fmtDate(iso: string | null) {
  if (!iso) return ''
  return new Date(iso).toLocaleDateString('en-GB', { day: 'numeric', month: 'short', year: 'numeric' })
}

const STARS = [1, 2, 3, 4, 5]

export function AssessmentManagementSection({
  auditSetId,
  workflowStatus,
}: {
  auditSetId: string
  workflowStatus: string | null
}) {
  const [assessments, setAssessments] = useState<Assessment[]>([])
  const [loading, setLoading]         = useState(true)
  const [creating, setCreating]       = useState(false)
  const [stageToCreate, setStageToCreate] = useState('stage_1')
  const [createMsg, setCreateMsg]     = useState('')
  const [busy, setBusy]               = useState(false)

  const load = useCallback(async () => {
    try {
      const r = await api.get<Assessment[]>(`/audit-sets/${auditSetId}/assessments`)
      setAssessments(r.data)
    } finally {
      setLoading(false)
    }
  }, [auditSetId])

  useEffect(() => { load() }, [load])

  // Only show from audit_scheduled / stage1_scheduled onwards
  const relevantStatuses = new Set([
    'stage1_scheduled', 'stage1_in_progress', 'stage1_complete',
    'stage2_scheduled', 'stage2_in_progress',
    'audit_scheduled', 'audit_in_progress', 'under_review', 'certified',
  ])
  if (!workflowStatus || !relevantStatuses.has(workflowStatus)) return null

  async function createForStage() {
    setBusy(true)
    setCreateMsg('')
    try {
      const r = await api.post<{ created: number; skipped: number }>(
        `/audit-sets/${auditSetId}/assessments/create-for-stage?stage_type=${stageToCreate}`,
      )
      const { created, skipped } = r.data
      setCreateMsg(`Created ${created} new assessment form(s)${skipped ? `, ${skipped} already existed` : ''}.`)
      setCreating(false)
      await load()
    } catch (err: unknown) {
      const detail = (err as { response?: { data?: { detail?: string } } })?.response?.data?.detail
      setCreateMsg(detail || 'Failed to create assessments')
    } finally {
      setBusy(false)
    }
  }

  // Group by stage_type
  const grouped = assessments.reduce<Record<string, Assessment[]>>((acc, a) => {
    const key = a.stage_type + (a.stage_order ? `_${a.stage_order}` : '')
    acc[key] = acc[key] || []
    acc[key].push(a)
    return acc
  }, {})

  return (
    <div className="mt-6">
      <div className="mb-3 flex items-center justify-between">
        <h2 className="text-sm font-semibold uppercase tracking-wide text-gray-700">
          Auditor Assessments (FR.211)
        </h2>
        <button
          type="button"
          onClick={() => { setCreating(!creating); setCreateMsg('') }}
          className="rounded-lg border border-[#1A4731] px-3 py-1.5 text-xs font-medium text-[#1A4731] hover:bg-green-50"
        >
          {creating ? 'Cancel' : '+ Create Assessments'}
        </button>
      </div>

      {/* Create form */}
      {creating && (
        <div className="mb-4 flex items-end gap-3 rounded-xl border border-amber-200 bg-amber-50 p-4">
          <div>
            <label className="mb-1 block text-xs font-medium text-gray-600">Stage</label>
            <select
              value={stageToCreate}
              onChange={e => setStageToCreate(e.target.value)}
              className="rounded-lg border bg-white px-3 py-2 text-sm"
            >
              {STAGE_TYPES.map(s => (
                <option key={s.value} value={s.value}>{s.label}</option>
              ))}
            </select>
          </div>
          <button
            type="button"
            onClick={createForStage}
            disabled={busy}
            className="rounded-lg bg-[#1A4731] px-4 py-2 text-sm text-white disabled:opacity-40"
          >
            {busy ? 'Creating…' : 'Create Forms'}
          </button>
          {createMsg && <p className="text-xs text-gray-600">{createMsg}</p>}
        </div>
      )}

      {loading ? (
        <p className="text-xs text-gray-400">Loading…</p>
      ) : assessments.length === 0 ? (
        <div className="rounded-xl border bg-white px-4 py-6 text-center text-xs text-gray-400">
          No assessments yet. Click &quot;+ Create Assessments&quot; after an audit stage completes.
        </div>
      ) : (
        <AssessmentList grouped={grouped} />
      )}
    </div>
  )
}

function AssessmentList({ grouped }: { grouped: Record<string, Assessment[]> }) {
  return (
    <div className="space-y-3">
      {Object.entries(grouped).map(([key, list]) => {
        const stageLabel = STAGE_TYPES.find(s => list[0].stage_type.startsWith(s.value))?.label
          ?? list[0].stage_type
        const allSigned = list.every(a => a.is_signed)
        return (
          <div key={key} className="rounded-xl border bg-white">
            <div className="flex items-center justify-between border-b px-4 py-2.5">
              <p className="text-xs font-semibold uppercase tracking-wide text-gray-500">
                {stageLabel}
              </p>
              {allSigned && (
                <span className="rounded-full bg-green-100 px-2 py-0.5 text-xs font-semibold text-green-700">
                  All Signed ✓
                </span>
              )}
            </div>
            <div className="divide-y divide-gray-50">
              {list.map(a => (
                <div key={a.id} className="flex items-center justify-between px-4 py-3">
                  <div>
                    <p className="text-sm font-medium text-gray-800">{a.auditor_name}</p>
                    <p className="mt-0.5 text-xs text-gray-400">{a.auditor_role}</p>
                  </div>
                  <div className="flex items-center gap-3">
                    {a.is_signed ? (
                      <div className="text-right">
                        <div className="flex gap-0.5">
                          {STARS.map(n => (
                            <span key={n} className={`text-sm ${(a.rating ?? 0) >= n ? 'text-amber-400' : 'text-gray-200'}`}>★</span>
                          ))}
                        </div>
                        <p className="text-xs text-gray-400">Signed {fmtDate(a.signed_at)}</p>
                      </div>
                    ) : (
                      <span className="rounded-full bg-amber-100 px-2 py-0.5 text-xs text-amber-700">
                        Awaiting Client
                      </span>
                    )}
                  </div>
                </div>
              ))}
            </div>
          </div>
        )
      })}
    </div>
  )
}
