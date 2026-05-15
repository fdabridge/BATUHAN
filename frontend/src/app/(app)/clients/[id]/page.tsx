'use client'

import { useState } from 'react'
import Link from 'next/link'
import { ArrowLeft, ChevronDown, ChevronRight, Download, Loader2, Pencil, Check } from 'lucide-react'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import api from '@/lib/api'
import { CertBadge } from '@/components/ui/CertBadge'
import type { AuditSetResponse, StageResponse, ManDayEntry } from '@/types'

// ── Helpers ───────────────────────────────────────────────────────────────────

function formatDate(iso: string | null | undefined): string {
  if (!iso) return '—'
  const [y, m, d] = iso.split('-')
  return `${d}/${m}/${y}`
}

function auditTypeLabel(t: string): string {
  if (t === 'initial')         return 'Initial certification'
  if (t === 'surveillance')    return 'Surveillance'
  if (t === 'recertification') return 'Recertification'
  return t
}

function nameList(arr: unknown[] | null | undefined): string {
  if (!arr || !arr.length) return ''
  return (arr as { name?: string }[]).map((a) => a.name ?? '').filter(Boolean).join(', ')
}

function textToAuditors(text: string) {
  return text.split(',').map((n) => n.trim()).filter(Boolean).map((name) => ({ name }))
}

// ── Local stage-edit state ────────────────────────────────────────────────────

interface StageEdit {
  lead_auditor_name: string
  audit_date_start:  string
  audit_date_end:    string
  auditors_text:     string
  tech_experts_text: string
}

function buildStageEdit(s: StageResponse): StageEdit {
  return {
    lead_auditor_name: s.lead_auditor_name ?? '',
    audit_date_start:  s.audit_date_start  ?? '',
    audit_date_end:    s.audit_date_end    ?? '',
    auditors_text:     nameList(s.auditors),
    tech_experts_text: nameList(s.technical_experts),
  }
}

// ── Shared styles ─────────────────────────────────────────────────────────────

const inputCls = 'w-full rounded-lg border border-gray-200 px-3 py-2 text-sm text-gray-800 placeholder-gray-400 outline-none focus:border-certiva-primary focus:ring-2 focus:ring-certiva-primary/20'
const lblCls   = 'mb-1 block text-xs font-medium text-gray-500'

function LabeledField({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div>
      <p className="mb-0.5 font-medium uppercase tracking-wide text-gray-400" style={{ fontSize: 11 }}>{label}</p>
      <div className="text-sm text-gray-800">{children}</div>
    </div>
  )
}

// ── Plan overview ─────────────────────────────────────────────────────────────

function PlanOverview({ data }: { data: AuditSetResponse }) {
  const p = data.personnel
  const personnelStr = p
    ? `${p.full_time} FT · ${p.part_time} PT · ${p.subcontractors} contractor`
    : data.effective_employees != null
    ? `${data.effective_employees} effective employees`
    : '—'

  return (
    <div className="rounded-lg border border-gray-100 bg-white p-5">
      <p className="mb-4 text-sm font-medium text-gray-700">Plan overview</p>
      <div className="grid grid-cols-3 gap-x-6 gap-y-5">
        <LabeledField label="Standards">
          <div className="mt-0.5 flex flex-wrap gap-1.5">
            {(data.standards ?? []).map((s) => (
              <span key={s} className="rounded px-2 py-0.5 text-xs font-medium" style={{ background: '#F0FAF4', color: '#1A4731' }}>
                {s}
              </span>
            ))}
          </div>
        </LabeledField>
        <LabeledField label="Audit type">{auditTypeLabel(data.audit_type)}</LabeledField>
        <LabeledField label="Accreditation body">{data.accreditation_body ?? '—'}</LabeledField>
        <LabeledField label="Scope (TR)">
          <span className="text-gray-500">{data.scope_tr || '—'}</span>
        </LabeledField>
        <LabeledField label="Scope (EN)">
          <span className="text-gray-500">{data.scope_en || '—'}</span>
        </LabeledField>
        <LabeledField label="Personnel">{personnelStr}</LabeledField>
      </div>
    </div>
  )
}


// ── Certification status section ──────────────────────────────────────────────

function CertSection({
  data, id, onInvalidate,
}: {
  data: AuditSetResponse
  id: string
  onInvalidate: () => void
}) {
  const [editing, setEditing]       = useState(false)
  const [issuedDate, setIssuedDate] = useState(data.cert_issued_date ?? '')
  const [expiryDate, setExpiryDate] = useState(data.cert_expiry_date ?? '')

  const { mutate, isPending } = useMutation({
    mutationFn: () =>
      api.patch(`/dashboard/clients/${id}/cert-dates`, {
        cert_issued_date: issuedDate || null,
        cert_expiry_date: expiryDate || null,
      }),
    onSuccess: () => {
      onInvalidate()
      setEditing(false)
    },
  })

  return (
    <div className="rounded-lg border border-gray-100 bg-white p-5">
      <div className="mb-4 flex items-center justify-between">
        <p className="text-sm font-medium text-gray-700">Certification status</p>
        <button
          type="button"
          onClick={() => setEditing((v) => !v)}
          className="flex items-center gap-1 text-certiva-primary hover:opacity-70"
          style={{ fontSize: 13 }}
        >
          <Pencil size={13} /> Edit dates
        </button>
      </div>

      <div className="grid grid-cols-4 gap-6">
        <LabeledField label="Cert status">
          <div className="mt-0.5"><CertBadge status={data.cert_status ?? null} /></div>
        </LabeledField>
        <LabeledField label="Issued date">{formatDate(data.cert_issued_date)}</LabeledField>
        <LabeledField label="Expiry date">{formatDate(data.cert_expiry_date)}</LabeledField>
        <div />
      </div>

      {editing && (
        <div className="mt-5 border-t border-gray-100 pt-4">
          <div className="grid grid-cols-2 gap-4">
            <div>
              <label className={lblCls}>Issued date</label>
              <input type="date" className={inputCls} value={issuedDate} onChange={(e) => setIssuedDate(e.target.value)} />
            </div>
            <div>
              <label className={lblCls}>Expiry date</label>
              <input type="date" className={inputCls} value={expiryDate} onChange={(e) => setExpiryDate(e.target.value)} />
            </div>
          </div>
          <div className="mt-3 flex gap-2">
            <button
              type="button" disabled={isPending}
              onClick={() => mutate()}
              className="flex items-center gap-1.5 rounded-lg px-4 py-1.5 text-sm font-medium text-white disabled:opacity-60 hover:opacity-90"
              style={{ background: '#1A4731' }}
            >
              {isPending && <Loader2 size={14} className="animate-spin" />}
              Save
            </button>
            <button type="button" onClick={() => setEditing(false)} className="rounded-lg border border-gray-200 px-4 py-1.5 text-sm text-gray-500 hover:bg-gray-50">
              Cancel
            </button>
          </div>
        </div>
      )}
    </div>
  )
}


// ── Stage card ────────────────────────────────────────────────────────────────

function StageCard({
  stage, label, allStages, auditSetId, onSuccess,
}: {
  stage: StageResponse
  label: string
  allStages: StageResponse[]
  auditSetId: string
  onSuccess: () => void
}) {
  const [edit, setEdit] = useState<StageEdit>(() => buildStageEdit(stage))
  const [saved, setSaved] = useState(false)

  const { mutate, isPending } = useMutation({
    mutationFn: () => {
      const stages = allStages.map((s) => {
        const isThis = s.id === stage.id
        return {
          stage_type:        s.stage_type,
          stage_order:       s.stage_order,
          status:            s.status,
          lead_auditor_name: isThis ? (edit.lead_auditor_name || null) : s.lead_auditor_name,
          audit_date_start:  isThis ? (edit.audit_date_start  || null) : s.audit_date_start,
          audit_date_end:    isThis ? (edit.audit_date_end    || null) : s.audit_date_end,
          auditors:          isThis ? textToAuditors(edit.auditors_text)     : ((s.auditors as { name: string }[]) ?? []),
          technical_experts: isThis ? textToAuditors(edit.tech_experts_text) : ((s.technical_experts as { name: string }[]) ?? []),
          observers:         (s.observers as { name: string }[]) ?? [],
          ik_experts:        [],
          evaluators:        [],
        }
      })
      return api.put<AuditSetResponse>(`/audit-sets/${auditSetId}/planning`, { stages })
    },
    onSuccess: (res) => {
      const updated = res.data.stages.find((s) => s.id === stage.id)
      if (updated) setEdit(buildStageEdit(updated))
      onSuccess()
      setSaved(true)
      setTimeout(() => setSaved(false), 2000)
    },
  })

  function patch(p: Partial<StageEdit>) { setEdit((prev) => ({ ...prev, ...p })) }

  return (
    <div className="rounded-lg border border-gray-100 p-4">
      {/* Header */}
      <div className="mb-4 flex items-center justify-between">
        <span className="text-sm font-medium text-gray-700">{label}</span>
        {stage.audit_days != null && (
          <span className="rounded px-2 py-0.5 text-xs font-medium" style={{ background: '#F0FAF4', color: '#1A4731' }}>
            {stage.audit_days} days
          </span>
        )}
      </div>

      {/* 2-col grid of fields */}
      <div className="grid grid-cols-2 gap-4">
        <div>
          <label className={lblCls}>Lead auditor</label>
          <input className={inputCls} value={edit.lead_auditor_name} onChange={(e) => patch({ lead_auditor_name: e.target.value })} placeholder="Name" />
        </div>
        <div className="grid grid-cols-2 gap-2">
          <div>
            <label className={lblCls}>Start date</label>
            <input type="date" className={inputCls} value={edit.audit_date_start} onChange={(e) => patch({ audit_date_start: e.target.value })} />
          </div>
          <div>
            <label className={lblCls}>End date</label>
            <input type="date" className={inputCls} value={edit.audit_date_end} onChange={(e) => patch({ audit_date_end: e.target.value })} />
          </div>
        </div>
        <div>
          <label className={lblCls}>Auditors <span className="font-normal text-gray-300">(comma-separated)</span></label>
          <input className={inputCls} value={edit.auditors_text} onChange={(e) => patch({ auditors_text: e.target.value })} placeholder="Name A, Name B" />
        </div>
        <div>
          <label className={lblCls}>Technical experts <span className="font-normal text-gray-300">(comma-separated)</span></label>
          <input className={inputCls} value={edit.tech_experts_text} onChange={(e) => patch({ tech_experts_text: e.target.value })} placeholder="Name A, Name B" />
        </div>
      </div>

      {/* Save row */}
      <div className="mt-4 flex items-center gap-2">
        <button
          type="button" disabled={isPending}
          onClick={() => mutate()}
          className="flex items-center gap-1.5 rounded-lg px-4 py-1.5 text-sm font-medium text-white disabled:opacity-60 hover:opacity-90"
          style={{ background: '#1A4731' }}
        >
          {isPending && <Loader2 size={13} className="animate-spin" />}
          Save stage
        </button>
        {saved && (
          <span className="flex items-center gap-1 text-xs text-green-600">
            <Check size={13} /> Saved
          </span>
        )}
      </div>
    </div>
  )
}


// ── Man-day section (collapsible) ─────────────────────────────────────────────

function ManDaySection({ result }: { result: Record<string, ManDayEntry> | null }) {
  const [open, setOpen] = useState(false)
  return (
    <div className="rounded-lg border border-gray-100 bg-white">
      <button
        type="button"
        className="flex w-full items-center justify-between px-5 py-4 text-left"
        onClick={() => setOpen((v) => !v)}
      >
        <span className="text-sm font-medium text-gray-700">Man-day calculation</span>
        {open
          ? <ChevronDown size={16} className="text-gray-400" />
          : <ChevronRight size={16} className="text-gray-400" />}
      </button>

      {open && (
        <div className="border-t border-gray-100 px-5 pb-5 pt-4">
          {!result ? (
            <p className="text-sm text-gray-400">Calculation not available.</p>
          ) : (
            <table className="w-full text-sm">
              <thead>
                <tr className="text-left text-xs font-medium uppercase tracking-wide text-gray-400">
                  <th className="pb-2 pr-4">Standard</th>
                  <th className="pb-2 pr-4">Base days</th>
                  <th className="pb-2 pr-4">After integration</th>
                  <th className="pb-2 pr-4">After reporting reduction</th>
                  <th className="pb-2">Final</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-gray-50">
                {Object.entries(result).map(([std, e]) => (
                  <tr key={std}>
                    <td className="py-2 pr-4 font-medium">{std}</td>
                    <td className="py-2 pr-4 text-gray-600">{e.base_days ?? '—'}</td>
                    <td className="py-2 pr-4 text-gray-600">{e.after_integration ?? '—'}</td>
                    <td className="py-2 pr-4 text-gray-600">{e.after_reporting_reduction ?? '—'}</td>
                    <td className="py-2 font-medium text-certiva-primary">{e.final ?? '—'}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </div>
      )}
    </div>
  )
}

// ── Main page ─────────────────────────────────────────────────────────────────

export default function ClientDetailPage({ params }: { params: { id: string } }) {
  const { id } = params
  const queryClient = useQueryClient()
  const [downloading, setDownloading] = useState(false)

  const { data, isLoading, isError } = useQuery<AuditSetResponse>({
    queryKey: ['client', id],
    queryFn: () => api.get<AuditSetResponse>(`/audit-sets/${id}`).then((r) => r.data),
  })

  async function handleDownload() {
    if (!data) return
    setDownloading(true)
    try {
      const res = await api.get(`/audit-sets/${id}/download`, { responseType: 'blob' })
      const url = URL.createObjectURL(res.data as Blob)
      const a   = document.createElement('a')
      a.href     = url
      a.download = `Set_${data.plan_number}_${data.company_name}.zip`
      a.click()
      URL.revokeObjectURL(url)
    } finally {
      setDownloading(false)
    }
  }

  function invalidate() {
    queryClient.invalidateQueries({ queryKey: ['client', id] })
  }

  if (isLoading) return (
    <div className="flex items-center justify-center py-24">
      <Loader2 size={24} className="animate-spin text-certiva-primary" />
    </div>
  )
  if (isError || !data) return (
    <div className="py-12 text-center text-sm text-red-500">Client not found.</div>
  )

  // Compute surveillance sequence number for labels
  let survCount = 0

  return (
    <div className="mx-auto max-w-[900px] space-y-5 py-4">
      {/* Back link */}
      <Link href="/clients" className="flex items-center gap-1 text-certiva-primary hover:opacity-70" style={{ fontSize: 13 }}>
        <ArrowLeft size={13} /> Clients
      </Link>

      {/* Header */}
      <div className="flex items-start justify-between">
        <div className="flex items-center gap-3">
          <h1 className="text-gray-800" style={{ fontSize: 22, fontWeight: 500 }}>{data.company_name}</h1>
          <span className="rounded px-2 py-0.5 font-mono text-xs" style={{ background: '#F0FAF4', color: '#1A4731' }}>
            #{data.plan_number}
          </span>
        </div>
        <div className="flex gap-2">
          <button
            type="button" disabled={downloading}
            onClick={handleDownload}
            className="flex items-center gap-1.5 rounded-lg border border-gray-200 px-3 py-1.5 text-sm text-gray-700 hover:bg-gray-50 disabled:opacity-60"
          >
            {downloading ? <Loader2 size={14} className="animate-spin" /> : <Download size={14} />}
            Download audit package
          </button>
          <Link
            href={`/reports/new?client_id=${id}`}
            className="flex items-center rounded-lg px-3 py-1.5 text-sm font-medium text-white hover:opacity-90"
            style={{ background: '#1A4731' }}
          >
            Generate AI report
          </Link>
        </div>
      </div>

      <PlanOverview data={data} />
      <CertSection data={data} id={id} onInvalidate={invalidate} />

      {/* Audit stages */}
      {data.stages.length > 0 && (
        <div className="rounded-lg border border-gray-100 bg-white p-5">
          <p className="mb-4 text-sm font-medium text-gray-700">Audit stages</p>
          <div className="space-y-3">
            {data.stages.map((stage) => {
              let stageLabel: string
              if (stage.stage_type === 'stage_1')      stageLabel = 'Stage 1 — Documentation review'
              else if (stage.stage_type === 'stage_2') stageLabel = 'Stage 2 — On-site audit'
              else { survCount += 1; stageLabel = `Surveillance ${survCount}` }
              return (
                <StageCard
                  key={stage.id}
                  stage={stage}
                  label={stageLabel}
                  allStages={data.stages}
                  auditSetId={id}
                  onSuccess={invalidate}
                />
              )
            })}
          </div>
        </div>
      )}

      <ManDaySection result={data.man_day_result} />
    </div>
  )
}
