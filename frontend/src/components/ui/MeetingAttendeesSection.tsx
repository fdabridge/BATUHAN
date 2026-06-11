'use client'

import { useEffect, useState, useCallback } from 'react'
import api from '@/lib/api'

interface Attendee {
  id:                string
  stage_type:        string
  stage_label:       string
  full_name:         string
  title:             string | null
  email:             string
  opening_signed:    boolean
  opening_signed_at: string | null
  closing_signed:    boolean
  closing_signed_at: string | null
  created_at:        string
}

const STAGE_TYPES = [
  { value: 'stage_1',         label: 'Stage 1' },
  { value: 'stage_2',         label: 'Stage 2' },
  { value: 'surveillance',    label: 'Surveillance' },
  { value: 'recertification', label: 'Recertification' },
]

function SignBadge({ signed, label }: { signed: boolean; label: string }) {
  if (signed) {
    return (
      <span className="rounded-full bg-green-100 px-2 py-0.5 text-xs font-semibold text-green-700">
        {label} ✓
      </span>
    )
  }
  return (
    <span className="rounded-full bg-gray-100 px-2 py-0.5 text-xs text-gray-400">
      {label} Pending
    </span>
  )
}

export function MeetingAttendeesSection({
  auditSetId,
  workflowStatus,
}: {
  auditSetId: string
  workflowStatus: string | null
}) {
  const [attendees, setAttendees] = useState<Attendee[]>([])
  const [loading, setLoading]     = useState(true)
  const [showAdd, setShowAdd]     = useState(false)
  const [form, setForm]           = useState({
    stage_type: 'stage_1',
    full_name:  '',
    title:      '',
    email:      '',
  })
  const [busy, setBusy]   = useState(false)
  const [error, setError] = useState('')
  const [signing, setSigning] = useState<Record<string, boolean>>({})
  const [signErr, setSignErr] = useState<Record<string, string>>({})

  const load = useCallback(async () => {
    try {
      const r = await api.get<Attendee[]>(`/audit-sets/${auditSetId}/meeting-attendees`)
      setAttendees(r.data)
    } finally {
      setLoading(false)
    }
  }, [auditSetId])

  useEffect(() => { load() }, [load])

  const MEETING_STAGES = [
    'agreement_signed',
    'stage1_scheduled', 'stage1_in_progress', 'stage1_complete',
    'stage2_scheduled', 'stage2_in_progress',
    'audit_scheduled', 'audit_in_progress',
    'under_review', 'certified',
  ]
  const showSection = workflowStatus != null && MEETING_STAGES.includes(workflowStatus)
  if (!showSection) return null

  async function addAttendee(e: React.FormEvent) {
    e.preventDefault()
    if (!form.full_name.trim() || !form.email.trim()) return
    setBusy(true)
    setError('')
    try {
      await api.post(`/audit-sets/${auditSetId}/meeting-attendees`, {
        stage_type: form.stage_type,
        full_name:  form.full_name.trim(),
        title:      form.title.trim() || null,
        email:      form.email.trim(),
      })
      setForm({ stage_type: 'stage_1', full_name: '', title: '', email: '' })
      setShowAdd(false)
      await load()
    } catch (err: unknown) {
      const detail = (err as { response?: { data?: { detail?: string } } })?.response?.data?.detail
      setError(detail || 'Failed to add attendee')
    } finally {
      setBusy(false)
    }
  }

  async function removeAttendee(id: string) {
    if (!confirm('Remove this attendee?')) return
    try {
      await api.delete(`/audit-sets/${auditSetId}/meeting-attendees/${id}`)
      setAttendees(prev => prev.filter(a => a.id !== id))
    } catch (err: unknown) {
      const detail = (err as { response?: { data?: { detail?: string } } })?.response?.data?.detail
      alert(detail || 'Removal failed')
    }
  }

  async function handleDirectSign(attId: string, meetingType: 'opening' | 'closing') {
    const key = `${attId}-${meetingType}`
    setSigning(s => ({ ...s, [key]: true }))
    setSignErr(e => ({ ...e, [key]: '' }))
    try {
      const r = await api.post<Attendee>(
        `/audit-sets/${auditSetId}/meeting-attendees/${attId}/sign-direct`,
        { meeting_type: meetingType }
      )
      setAttendees(prev => prev.map(a => (a.id === attId ? r.data : a)))
    } catch (err: unknown) {
      const detail = (err as { response?: { data?: { detail?: string } } })?.response?.data?.detail
      setSignErr(e => ({ ...e, [key]: detail || 'Failed' }))
    } finally {
      setSigning(s => ({ ...s, [key]: false }))
    }
  }

  const grouped = attendees.reduce<Record<string, Attendee[]>>((acc, a) => {
    acc[a.stage_type] = acc[a.stage_type] || []
    acc[a.stage_type].push(a)
    return acc
  }, {})

  return (
    <div className="mt-6">
      <div className="mb-3 flex items-center justify-between">
        <h2 className="text-sm font-semibold uppercase tracking-wide text-gray-700">
          Meeting Attendees (FR.225)
        </h2>
        <button
          type="button"
          onClick={() => { setShowAdd(!showAdd); setError('') }}
          className="rounded-lg border border-[#1A4731] px-3 py-1.5 text-xs font-medium text-[#1A4731] hover:bg-green-50"
        >
          {showAdd ? 'Cancel' : '+ Add Attendee'}
        </button>
      </div>

      {showAdd && (
        <form
          onSubmit={addAttendee}
          className="mb-4 rounded-xl border border-amber-200 bg-amber-50 p-4"
        >
          <p className="mb-3 text-sm font-medium text-gray-700">New Meeting Attendee</p>
          <div className="grid grid-cols-2 gap-3">
            <div>
              <label className="mb-1 block text-xs font-medium text-gray-600">Stage</label>
              <select
                value={form.stage_type}
                onChange={e => setForm(f => ({ ...f, stage_type: e.target.value }))}
                className="w-full rounded-lg border px-3 py-2 text-sm"
              >
                {STAGE_TYPES.map(s => (
                  <option key={s.value} value={s.value}>{s.label}</option>
                ))}
              </select>
            </div>
            <div>
              <label className="mb-1 block text-xs font-medium text-gray-600">Full Name *</label>
              <input
                value={form.full_name}
                onChange={e => setForm(f => ({ ...f, full_name: e.target.value }))}
                required
                placeholder="Jane Smith"
                className="w-full rounded-lg border px-3 py-2 text-sm"
              />
            </div>
            <div>
              <label className="mb-1 block text-xs font-medium text-gray-600">Title / Role</label>
              <input
                value={form.title}
                onChange={e => setForm(f => ({ ...f, title: e.target.value }))}
                placeholder="General Manager"
                className="w-full rounded-lg border px-3 py-2 text-sm"
              />
            </div>
            <div>
              <label className="mb-1 block text-xs font-medium text-gray-600">Email *</label>
              <input
                type="email"
                value={form.email}
                onChange={e => setForm(f => ({ ...f, email: e.target.value }))}
                required
                placeholder="jane@company.com"
                className="w-full rounded-lg border px-3 py-2 text-sm"
              />
            </div>
          </div>
          <div className="mt-3 flex items-center gap-3">
            <button
              type="submit"
              disabled={busy}
              className="rounded-lg bg-[#1A4731] px-4 py-2 text-sm text-white disabled:opacity-40"
            >
              {busy ? 'Adding…' : 'Add & Send Invite'}
            </button>
            <p className="text-xs text-gray-400">
              Use "Mark Signed" next to each attendee to record their attendance directly.
            </p>
          </div>
          {error && <p className="mt-2 text-xs text-red-500">{error}</p>}
        </form>
      )}

      {loading ? (
        <p className="text-xs text-gray-400">Loading…</p>
      ) : attendees.length === 0 ? (
        <div className="rounded-xl border bg-white px-4 py-6 text-center text-xs text-gray-400">
          No attendees registered yet. Add them above and use "Mark Signed" to record attendance.
        </div>
      ) : (
        <div className="space-y-3">
          {Object.entries(grouped).map(([stageType, list]) => (
            <div key={stageType} className="rounded-xl border bg-white">
              <div className="border-b px-4 py-2.5">
                <p className="text-xs font-semibold uppercase tracking-wide text-gray-500">
                  {STAGE_TYPES.find(s => s.value === stageType)?.label ?? stageType}
                </p>
              </div>
              <div className="divide-y divide-gray-50">
                {list.map(a => (
                  <div key={a.id} className="flex items-center justify-between px-4 py-3">
                    <div>
                      <p className="text-sm font-medium text-gray-800">
                        {a.full_name}
                        {a.title && (
                          <span className="ml-1.5 text-xs text-gray-400">— {a.title}</span>
                        )}
                      </p>
                      <p className="mt-0.5 text-xs text-gray-400">{a.email}</p>
                    </div>
                    <div className="flex items-center gap-2 flex-wrap justify-end">
                      <SignBadge signed={a.opening_signed} label="Opening" />
                      {!a.opening_signed && (
                        <button
                          type="button"
                          onClick={() => handleDirectSign(a.id, 'opening')}
                          disabled={signing[`${a.id}-opening`]}
                          className="rounded px-2 py-0.5 text-xs text-certiva-primary border border-certiva-primary hover:bg-certiva-primary/5 disabled:opacity-50"
                        >
                          {signing[`${a.id}-opening`] ? '…' : 'Mark Signed'}
                        </button>
                      )}
                      {signErr[`${a.id}-opening`] && (
                        <span className="text-xs text-red-500">{signErr[`${a.id}-opening`]}</span>
                      )}
                      <SignBadge signed={a.closing_signed} label="Closing" />
                      {!a.closing_signed && (
                        <button
                          type="button"
                          onClick={() => handleDirectSign(a.id, 'closing')}
                          disabled={signing[`${a.id}-closing`]}
                          className="rounded px-2 py-0.5 text-xs text-certiva-primary border border-certiva-primary hover:bg-certiva-primary/5 disabled:opacity-50"
                        >
                          {signing[`${a.id}-closing`] ? '…' : 'Mark Signed'}
                        </button>
                      )}
                      {signErr[`${a.id}-closing`] && (
                        <span className="text-xs text-red-500">{signErr[`${a.id}-closing`]}</span>
                      )}
                      {!a.opening_signed && !a.closing_signed && (
                        <button
                          type="button"
                          onClick={() => removeAttendee(a.id)}
                          className="text-xs text-gray-400 hover:text-red-500"
                        >
                          Remove
                        </button>
                      )}
                    </div>
                  </div>
                ))}
              </div>
            </div>
          ))}
        </div>
      )}
    </div>
  )
}
