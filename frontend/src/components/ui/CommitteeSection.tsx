'use client'

import { useEffect, useState, useCallback } from 'react'
import api from '@/lib/api'

interface CommitteeMember {
  id: string
  user_id: string
  user_name: string
  user_email: string
  role: 'reviewer' | 'decision_maker'
  appointed_by: string | null
  ea_codes_at_appointment: string[] | null
  appointed_at: string
  has_signed_fr218: boolean
}

interface EligibleUser {
  user_id: string
  full_name: string
  email: string
  role: string
  ea_codes: string[]
  ea_match: boolean
  has_auditor_profile: boolean
  eligible_as_reviewer: boolean
}

const ROLE_LABELS: Record<string, string> = {
  reviewer:       'Reviewer',
  decision_maker: 'Decision Maker',
}

function fmtDate(iso: string | null) {
  if (!iso) return ''
  return new Date(iso).toLocaleDateString('en-GB', { day: 'numeric', month: 'short', year: 'numeric' })
}

export function CommitteeSection({
  auditSetId,
  workflowStatus,
}: {
  auditSetId: string
  workflowStatus: string | null
}) {
  const [members, setMembers]                 = useState<CommitteeMember[]>([])
  const [showPicker, setShowPicker]           = useState(false)
  const [pickRole, setPickRole]               = useState<'reviewer' | 'decision_maker'>('reviewer')
  const [eligible, setEligible]               = useState<EligibleUser[]>([])
  const [loadingEligible, setLoadingEligible] = useState(false)
  const [busy, setBusy]                       = useState(false)
  const [error, setError]                     = useState('')

  const loadMembers = useCallback(async () => {
    try {
      const r = await api.get<CommitteeMember[]>(`/audit-sets/${auditSetId}/committee`)
      setMembers(r.data)
    } catch {
      // 403 for non-CB users — leave members empty
    }
  }, [auditSetId])

  useEffect(() => { loadMembers() }, [loadMembers])

  const COMMITTEE_STAGES = [
    'agreement_signed',
    'fr218_in_progress', 'fr218_complete',
    'stage1_scheduled', 'stage1_in_progress', 'stage1_complete',
    'stage2_scheduled', 'stage2_in_progress',
    'audit_scheduled', 'audit_in_progress',
    'under_review', 'certified',
  ]
  const showSection = workflowStatus != null && COMMITTEE_STAGES.includes(workflowStatus)
  if (!showSection) return null

  async function openPicker(role: 'reviewer' | 'decision_maker') {
    setPickRole(role)
    setShowPicker(true)
    setError('')
    setLoadingEligible(true)
    try {
      const r = await api.get<EligibleUser[]>(`/audit-sets/${auditSetId}/committee/eligible-users`)
      setEligible(r.data)
    } catch {
      setError('Failed to load eligible users')
    } finally {
      setLoadingEligible(false)
    }
  }

  async function appoint(userId: string) {
    setBusy(true)
    setError('')
    try {
      await api.post(`/audit-sets/${auditSetId}/committee/appoint`, {
        user_id: userId,
        role: pickRole,
      })
      setShowPicker(false)
      await loadMembers()
    } catch (e: unknown) {
      const detail = (e as { response?: { data?: { detail?: string } } })?.response?.data?.detail
      setError(detail || 'Appointment failed')
    } finally {
      setBusy(false)
    }
  }

  async function removeMember(memberId: string) {
    if (!confirm('Remove this committee member?')) return
    setBusy(true)
    try {
      await api.delete(`/audit-sets/${auditSetId}/committee/${memberId}`)
      await loadMembers()
    } catch (e: unknown) {
      const detail = (e as { response?: { data?: { detail?: string } } })?.response?.data?.detail
      alert(detail || 'Removal failed')
    } finally {
      setBusy(false)
    }
  }

  const hasReviewer = members.some(m => m.role === 'reviewer')

  return (
    <div className="mt-6">
      <div className="mb-3 flex items-center justify-between">
        <h2 className="text-sm font-semibold uppercase tracking-wide text-gray-700">
          Certification Committee
        </h2>
        <div className="flex gap-2">
          {!hasReviewer && (
            <button
              type="button"
              onClick={() => openPicker('reviewer')}
              disabled={busy}
              className="rounded-lg border border-[#1A4731] px-3 py-1.5 text-xs font-medium text-[#1A4731] hover:bg-green-50 disabled:opacity-40"
            >
              + Appoint Reviewer
            </button>
          )}
          <button
            type="button"
            onClick={() => openPicker('decision_maker')}
            disabled={busy}
            className="rounded-lg border border-gray-300 px-3 py-1.5 text-xs font-medium text-gray-600 hover:bg-gray-50 disabled:opacity-40"
          >
            + Add Decision Maker
          </button>
        </div>
      </div>

      <div className="rounded-xl border bg-white">
        {members.length === 0 ? (
          <div className="px-4 py-6 text-center text-xs text-gray-400">
            No committee members appointed yet.
          </div>
        ) : (
          <div className="divide-y divide-gray-100">
            {members.map(m => (
              <div key={m.id} className="flex items-center justify-between px-4 py-3">
                <div>
                  <p className="text-sm font-medium text-gray-800">{m.user_name}</p>
                  <p className="mt-0.5 text-xs text-gray-400">
                    {ROLE_LABELS[m.role]} · appointed {fmtDate(m.appointed_at)}
                    {m.ea_codes_at_appointment && m.ea_codes_at_appointment.length > 0
                      ? ` · EA: ${m.ea_codes_at_appointment.join(', ')}`
                      : ''}
                  </p>
                </div>
                <div className="flex items-center gap-2">
                  {m.has_signed_fr218 && (
                    <span className="rounded-full bg-green-100 px-2 py-0.5 text-xs font-semibold text-green-700">
                      FR.218 ✓
                    </span>
                  )}
                  {!m.has_signed_fr218 && (
                    <button
                      type="button"
                      onClick={() => removeMember(m.id)}
                      disabled={busy}
                      className="text-xs text-gray-400 hover:text-red-500 disabled:opacity-40"
                    >
                      Remove
                    </button>
                  )}
                </div>
              </div>
            ))}
          </div>
        )}
      </div>

      {showPicker && (
        <div className="mt-3 rounded-xl border border-amber-200 bg-amber-50 p-4">
          <div className="mb-3 flex items-center justify-between">
            <p className="text-sm font-semibold text-gray-700">
              Select {ROLE_LABELS[pickRole]}
            </p>
            <button
              type="button"
              onClick={() => { setShowPicker(false); setError('') }}
              className="text-xs text-gray-400 hover:text-gray-600"
            >
              Cancel
            </button>
          </div>

          {loadingEligible ? (
            <p className="text-xs text-gray-400">Loading eligible users…</p>
          ) : eligible.length === 0 ? (
            <p className="text-xs text-gray-400">No eligible users available.</p>
          ) : (
            <div className="space-y-1.5">
              {eligible.map(u => (
                <div
                  key={u.user_id}
                  className={`flex items-center justify-between rounded-lg border bg-white px-3 py-2.5 ${
                    pickRole === 'reviewer' && !u.eligible_as_reviewer ? 'opacity-50' : ''
                  }`}
                >
                  <div>
                    <p className="text-xs font-medium text-gray-800">{u.full_name}</p>
                    <p className="mt-0.5 text-xs text-gray-400">
                      {u.role}
                      {u.ea_codes.length > 0 ? ` · EA: ${u.ea_codes.join(', ')}` : ''}
                      {!u.has_auditor_profile ? ' · no auditor profile' : ''}
                      {u.has_auditor_profile && !u.ea_match ? ' · ⚠ EA codes may not match' : ''}
                    </p>
                  </div>
                  <button
                    type="button"
                    onClick={() => appoint(u.user_id)}
                    disabled={busy}
                    className="rounded bg-[#1A4731] px-2.5 py-1 text-xs text-white disabled:opacity-40"
                  >
                    {busy ? '…' : 'Appoint'}
                  </button>
                </div>
              ))}
            </div>
          )}
          {error && <p className="mt-2 text-xs text-red-500">{error}</p>}
        </div>
      )}
    </div>
  )
}
