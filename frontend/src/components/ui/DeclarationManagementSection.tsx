'use client'

import { useEffect, useState } from 'react'
import api from '@/lib/api'

interface Declaration {
  id:           string
  stage_type:   string
  stage_order:  number | null
  member_name:  string
  member_role:  string
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
  return new Date(iso).toLocaleDateString('en-GB', {
    day: 'numeric', month: 'short', year: 'numeric',
  })
}

const ROLE_COLOR: Record<string, string> = {
  'Lead Auditor':     'bg-purple-100 text-purple-700',
  'Team Auditor':     'bg-blue-100 text-blue-700',
  'Technical Expert': 'bg-teal-100 text-teal-700',
  'Observer':         'bg-gray-100 text-gray-500',
}

export function DeclarationManagementSection({
  auditSetId,
  workflowStatus,
}: {
  auditSetId: string
  workflowStatus: string | null
}) {
  const [declarations, setDeclarations] = useState<Declaration[]>([])
  const [loading, setLoading]     = useState(true)
  const [creating, setCreating]   = useState(false)
  const [stageToCreate, setStageToCreate] = useState('stage_1')
  const [createMsg, setCreateMsg] = useState('')
  const [busy, setBusy]           = useState(false)

  const relevantStatuses = new Set([
    'in_planning', 'quotation_sent', 'agreement_signed',
    'stage1_scheduled', 'stage1_in_progress', 'stage1_complete',
    'stage2_scheduled', 'stage2_in_progress',
    'audit_scheduled', 'audit_in_progress', 'under_review', 'certified',
  ])

  useEffect(() => {
    if (!workflowStatus || !relevantStatuses.has(workflowStatus)) {
      setLoading(false)
      return
    }
    api.get<Declaration[]>(`/audit-sets/${auditSetId}/declarations`)
      .then(r => setDeclarations(r.data))
      .finally(() => setLoading(false))
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [auditSetId, workflowStatus])

  if (!workflowStatus || !relevantStatuses.has(workflowStatus)) return null

  async function createForStage() {
    setBusy(true)
    setCreateMsg('')
    try {
      const r = await api.post<{ created: number; skipped: number }>(
        `/audit-sets/${auditSetId}/declarations/create-for-stage?stage_type=${stageToCreate}`,
      )
      const { created, skipped } = r.data
      setCreateMsg(
        `Created ${created} declaration form(s)${skipped ? `, ${skipped} already existed` : ''}.`,
      )
      setCreating(false)
      const reload = await api.get<Declaration[]>(`/audit-sets/${auditSetId}/declarations`)
      setDeclarations(reload.data)
    } catch (err: unknown) {
      const detail = (err as { response?: { data?: { detail?: string } } })?.response?.data?.detail
      setCreateMsg(detail || 'Failed to create declarations')
    } finally {
      setBusy(false)
    }
  }

  const grouped = declarations.reduce<Record<string, Declaration[]>>((acc, d) => {
    acc[d.stage_type] = acc[d.stage_type] || []
    acc[d.stage_type].push(d)
    return acc
  }, {})

  return (
    <div className="mt-6">
      <div className="mb-3 flex items-center justify-between">
        <h2 className="text-sm font-semibold uppercase tracking-wide text-gray-700">
          Impartiality Declarations (FR.224)
        </h2>
        <button
          type="button"
          onClick={() => { setCreating(!creating); setCreateMsg('') }}
          className="rounded-lg border border-[#1A4731] px-3 py-1.5 text-xs font-medium text-[#1A4731] hover:bg-green-50"
        >
          {creating ? 'Cancel' : '+ Create Declarations'}
        </button>
      </div>

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
            {busy ? 'Creating…' : 'Create & Notify Auditors'}
          </button>
          {createMsg && <p className="text-xs text-gray-600">{createMsg}</p>}
        </div>
      )}

      {loading ? (
        <p className="text-xs text-gray-400">Loading…</p>
      ) : declarations.length === 0 ? (
        <div className="rounded-xl border bg-white px-4 py-6 text-center text-xs text-gray-400">
          No declarations yet. Click &quot;+ Create Declarations&quot; after assigning the audit team.
        </div>
      ) : (
        <div className="space-y-3">
          {Object.entries(grouped).map(([stageType, list]) => {
            const stageLabel = STAGE_TYPES.find(s => s.value === stageType)?.label ?? stageType
            const allSigned  = list.every(d => d.is_signed)
            return (
              <div key={stageType} className="rounded-xl border bg-white">
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
                  {list.map(d => (
                    <div key={d.id} className="flex items-center justify-between px-4 py-3">
                      <div className="flex items-center gap-2">
                        <p className="text-sm font-medium text-gray-800">{d.member_name}</p>
                        <span className={`rounded-full px-2 py-0.5 text-xs font-medium ${ROLE_COLOR[d.member_role] ?? 'bg-gray-100 text-gray-500'}`}>
                          {d.member_role}
                        </span>
                      </div>
                      {d.is_signed ? (
                        <span className="text-xs text-gray-400">
                          Signed {fmtDate(d.signed_at)}
                        </span>
                      ) : (
                        <span className="rounded-full bg-amber-100 px-2 py-0.5 text-xs text-amber-700">
                          Pending
                        </span>
                      )}
                    </div>
                  ))}
                </div>
              </div>
            )
          })}
        </div>
      )}
    </div>
  )
}
