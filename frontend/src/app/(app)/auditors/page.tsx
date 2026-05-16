'use client'

import { useRef, useState } from 'react'
import Link from 'next/link'
import { useRouter } from 'next/navigation'
import {
  AlertTriangle, Loader2, Plus, Upload, X, FileText, Trash2,
} from 'lucide-react'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import api from '@/lib/api'
import type { AuditorDashboardEntry, AuditorIngestResult } from '@/types'

// ── Helpers ───────────────────────────────────────────────────────────────────

function hasWarnings(a: AuditorDashboardEntry): boolean {
  return a.qualifications.some((q) => q.training_expiry_warning || q.verification_warning)
}

function lastAuditLabel(a: AuditorDashboardEntry): string {
  if (a.total_audits === 0) return 'Never'
  if (a.days_since_last_audit == null) return '—'
  return `${a.days_since_last_audit} days ago`
}

function uniq(arr: (string | null | undefined)[]): string[] {
  return Array.from(new Set(arr.filter((x): x is string => !!x)))
}

// ── Stat card ─────────────────────────────────────────────────────────────────

function StatCard({ label, value }: { label: string; value: number }) {
  return (
    <div className="rounded-lg border border-gray-100 bg-white" style={{ padding: '0.875rem 1rem' }}>
      <p className="text-certiva-primary" style={{ fontSize: 24, fontWeight: 500 }}>{value}</p>
      <p className="mt-1 uppercase tracking-wide text-gray-400" style={{ fontSize: 11 }}>{label}</p>
    </div>
  )
}

// ── Status badge ──────────────────────────────────────────────────────────────

function StatusBadge({ a }: { a: AuditorDashboardEntry }) {
  if (!a.is_active) {
    return <span className="rounded px-2 py-0.5 text-xs" style={{ background: '#F3F4F6', color: '#6B7280' }}>Inactive</span>
  }
  if (hasWarnings(a)) {
    return (
      <span className="inline-flex items-center gap-1 rounded px-2 py-0.5 text-xs" style={{ background: '#FEF3C7', color: '#92400E' }}>
        <AlertTriangle size={12} /> Warnings
      </span>
    )
  }
  return <span className="rounded px-2 py-0.5 text-xs" style={{ background: '#F0FAF4', color: '#1A4731' }}>Active</span>
}

// ── Skeleton row ──────────────────────────────────────────────────────────────

function SkeletonRow() {
  return (
    <tr className="border-b border-gray-50">
      {Array.from({ length: 7 }).map((_, i) => (
        <td key={i} className="px-4 py-3">
          <div className="h-3 w-3/4 animate-pulse rounded bg-gray-100" />
        </td>
      ))}
    </tr>
  )
}

// ── Row ───────────────────────────────────────────────────────────────────────

function AuditorRow({ a, stds, overflow, onClick }: {
  a: AuditorDashboardEntry; stds: string[]; overflow: number; onClick: () => void
}) {
  return (
    <tr className="cursor-pointer hover:bg-gray-50" onClick={onClick}>
      <td className="px-4 py-3">
        <div className="font-medium text-gray-800">{a.name}</div>
        {a.role && <div className="text-gray-400" style={{ fontSize: 12 }}>{a.role}</div>}
      </td>
      <td className="px-4 py-3">
        <div className="flex flex-wrap gap-1">
          {stds.map((s) => (
            <span key={s} className="rounded px-1.5 py-0.5 font-medium" style={{ fontSize: 11, background: '#F0FAF4', color: '#1A4731' }}>
              {s}
            </span>
          ))}
          {overflow > 0 && (
            <span className="rounded px-1.5 py-0.5 text-gray-500" style={{ fontSize: 11, background: '#F3F4F6' }}>
              +{overflow}
            </span>
          )}
        </div>
      </td>
      <td className="px-4 py-3 text-gray-500" style={{ fontSize: 13 }}>{a.ea_codes.join(', ') || '—'}</td>
      <td className="px-4 py-3">
        <div className="flex flex-wrap gap-1">
          {a.accreditation_bodies.length === 0 && <span className="text-gray-400">—</span>}
          {a.accreditation_bodies.map((b) => (
            <span key={b} className="rounded px-1.5 py-0.5 text-gray-600" style={{ fontSize: 12, background: '#F3F4F6' }}>{b}</span>
          ))}
        </div>
      </td>
      <td className="px-4 py-3 text-gray-500" style={{ fontSize: 13 }}>{lastAuditLabel(a)}</td>
      <td className="px-4 py-3"><StatusBadge a={a} /></td>
      <td className="px-4 py-3">
        <Link
          href={`/auditors/${a.auditor_id}`}
          onClick={(e) => e.stopPropagation()}
          className="text-certiva-primary hover:underline"
          style={{ fontSize: 13 }}
        >
          View
        </Link>
      </td>
    </tr>
  )
}

// ── Add-auditor slide-over ────────────────────────────────────────────────────

const inputCls = 'w-full rounded-lg border border-gray-200 px-3 py-2 text-sm text-gray-800 placeholder-gray-400 outline-none focus:border-certiva-primary focus:ring-2 focus:ring-certiva-primary/20'
const lblCls   = 'mb-1 block text-xs font-medium text-gray-500'

interface QualRow { standard_code: string; accreditation_body: string; technical_depth: string }

function toQualRows(p: AuditorIngestResult): QualRow[] {
  return (p.standard_qualifications ?? []).map((q) => ({
    standard_code:      q.standard_code      ?? '',
    accreditation_body: (p.accreditation_bodies?.[0]) ?? '',
    technical_depth:    q.technical_depth    ?? '',
  }))
}

function AddAuditorPanel({ onClose, onCreated }: { onClose: () => void; onCreated: () => void }) {
  const fileRef = useRef<HTMLInputElement | null>(null)
  const [file,     setFile]     = useState<File | null>(null)
  const [preview,  setPreview]  = useState<AuditorIngestResult | null>(null)
  const [quals,    setQuals]    = useState<QualRow[]>([])
  const [eaText,   setEaText]   = useState('')
  const [ingestErr, setIngestErr] = useState<string | null>(null)
  const [saveErr,   setSaveErr]   = useState<string | null>(null)

  const ingest = useMutation({
    mutationFn: async (f: File) => {
      const fd = new FormData()
      fd.append('file', f)
      const res = await api.post<AuditorIngestResult>('/auditors/ingest', fd, {
        headers: { 'Content-Type': 'multipart/form-data' },
      })
      return res.data
    },
    onSuccess: (data) => {
      setPreview(data)
      setQuals(toQualRows(data))
      setEaText((data.ea_codes ?? []).join(', '))
      setIngestErr(null)
    },
    onError: (err) => {
      // eslint-disable-next-line @typescript-eslint/no-explicit-any
      const anyErr = err as any
      setIngestErr(String(anyErr?.response?.data?.detail ?? anyErr?.message ?? 'Failed to extract.'))
    },
  })

  const save = useMutation({
    mutationFn: async () => {
      if (!preview) throw new Error('No preview')
      const ea = eaText.split(',').map((s) => s.trim()).filter(Boolean)
      const accBodies = Array.from(new Set(quals.map((q) => q.accreditation_body.trim()).filter(Boolean)))
      const body = {
        name:                  (preview.name ?? '').trim(),
        email:                 preview.email  ?? null,
        phone:                 preview.phone  ?? null,
        mobile:                preview.mobile ?? null,
        role:                  preview.role   ?? null,
        field_of_expertise:    preview.field_of_expertise ?? null,
        ea_codes:              ea.length ? ea : null,
        accreditation_bodies:  accBodies.length ? accBodies : null,
        education:             preview.education       ?? [],
        languages:             preview.languages       ?? [],
        standard_qualifications: quals
          .filter((q) => q.standard_code.trim())
          .map((q) => ({
            standard_code:   q.standard_code.trim(),
            technical_depth: q.technical_depth || null,
            is_qualified:    true,
          })),
        work_experience:       preview.work_experience ?? [],
        training_records:      preview.training_records ?? [],
        audit_log:             [],
      }
      await api.post('/auditors/', body)
    },
    onSuccess: () => { onCreated(); onClose() },
    onError: (err) => {
      // eslint-disable-next-line @typescript-eslint/no-explicit-any
      const anyErr = err as any
      setSaveErr(String(anyErr?.response?.data?.detail ?? anyErr?.message ?? 'Failed to save.'))
    },
  })

  function patchPreview(p: Partial<AuditorIngestResult>) {
    setPreview((prev) => (prev ? { ...prev, ...p } : prev))
  }

  function pickFile(f: File | null) {
    setFile(f); setPreview(null); setIngestErr(null); setSaveErr(null)
  }

  return (
    <>
      <div className="fixed inset-0 z-40 bg-black/30" onClick={onClose} />
      <div className="fixed right-0 top-0 z-50 flex h-full w-full max-w-xl flex-col bg-white shadow-xl">
        <div className="flex items-center justify-between border-b border-gray-100 px-5 py-4">
          <h2 className="text-base font-semibold text-gray-800">Add auditor</h2>
          <button type="button" onClick={onClose} className="rounded p-1 text-gray-400 hover:bg-gray-50">
            <X size={18} />
          </button>
        </div>

        <div className="flex-1 overflow-y-auto px-5 py-5">
          {!preview ? (
            <>
              <p className="mb-3 text-sm text-gray-500">
                Upload a CV or FR.201 form (PDF or DOCX). Fields will be extracted for review before saving.
              </p>

              <div
                className="rounded-lg border border-dashed border-gray-200 p-6 text-center"
                style={{ background: '#F0FAF4' }}
              >
                <Upload size={20} className="mx-auto text-certiva-primary" />
                {file
                  ? <p className="mt-2 inline-flex items-center gap-1 text-sm text-gray-700"><FileText size={14} /> {file.name}</p>
                  : <p className="mt-2 text-sm text-gray-500">Drag a file here or click to choose</p>}
                <input
                  ref={fileRef} type="file" accept=".pdf,.docx" className="hidden"
                  onChange={(e) => pickFile(e.target.files?.[0] ?? null)}
                />
                <button
                  type="button" onClick={() => fileRef.current?.click()}
                  className="mt-3 rounded-lg border border-certiva-primary px-3 py-1.5 text-sm font-medium text-certiva-primary hover:bg-white"
                >
                  Choose file
                </button>
              </div>

              {ingestErr && <p className="mt-3 text-xs text-red-600">{ingestErr}</p>}

              <button
                type="button"
                disabled={!file || ingest.isPending}
                onClick={() => file && ingest.mutate(file)}
                className="mt-4 flex w-full items-center justify-center gap-2 rounded-lg bg-certiva-primary px-4 py-2.5 text-sm font-medium text-white hover:opacity-90 disabled:opacity-60"
              >
                {ingest.isPending && <Loader2 size={14} className="animate-spin" />}
                {ingest.isPending ? 'Extracting…' : 'Extract fields'}
              </button>
            </>
          ) : (
            <AuditorPreviewForm
              preview={preview} quals={quals} eaText={eaText}
              onPreviewChange={patchPreview}
              onQualsChange={setQuals}
              onEaChange={setEaText}
              saving={save.isPending}
              saveErr={saveErr}
              onBack={() => { setPreview(null); setSaveErr(null) }}
              onSave={() => { setSaveErr(null); save.mutate() }}
            />
          )}
        </div>
      </div>
    </>
  )
}

// ── Main page ─────────────────────────────────────────────────────────────────

export default function AuditorsPage() {
  const router       = useRouter()
  const queryClient  = useQueryClient()
  const [adding, setAdding] = useState(false)

  const { data, isLoading } = useQuery<AuditorDashboardEntry[]>({
    queryKey: ['auditors-dashboard'],
    queryFn: () => api.get<AuditorDashboardEntry[]>('/auditors/dashboard').then((r) => r.data),
  })

  const rows = data ?? []
  const totalCount   = rows.length
  const activeCount  = rows.filter((a) => a.is_active).length
  const warningCount = rows.filter((a) => a.is_active && hasWarnings(a)).length

  function refreshLists() {
    queryClient.invalidateQueries({ queryKey: ['auditors-dashboard'] })
    queryClient.invalidateQueries({ queryKey: ['auditors-active'] })
  }

  return (
    <>
      {/* Header */}
      <div className="mb-5 flex items-center justify-between">
        <h1 className="text-xl font-semibold text-gray-800">Auditors</h1>
        <button
          type="button"
          onClick={() => setAdding(true)}
          className="flex items-center gap-1.5 rounded-lg px-3 py-1.5 text-sm font-medium text-white hover:opacity-90"
          style={{ background: '#1A4731' }}
        >
          <Plus size={14} /> Add auditor
        </button>
      </div>

      {/* Stat row */}
      <div className="mb-5 grid grid-cols-3 gap-3">
        <StatCard label="Total auditors"   value={totalCount} />
        <StatCard label="Active"           value={activeCount} />
        <StatCard label="Expiry warnings"  value={warningCount} />
      </div>

      {/* Table */}
      <div className="rounded-lg border border-gray-100 bg-white">
        <div className="overflow-x-auto">
          <table className="w-full text-sm">
            <thead>
              <tr className="border-b border-gray-100 text-left text-xs font-medium uppercase tracking-wide text-gray-400">
                <th className="px-4 py-2.5">Auditor</th>
                <th className="px-4 py-2.5">Qualified standards</th>
                <th className="px-4 py-2.5">EA codes</th>
                <th className="px-4 py-2.5">Accreditation bodies</th>
                <th className="px-4 py-2.5">Last audit</th>
                <th className="px-4 py-2.5">Status</th>
                <th className="px-4 py-2.5">Actions</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-gray-50">
              {isLoading
                ? Array.from({ length: 6 }).map((_, i) => <SkeletonRow key={i} />)
                : rows.length === 0
                ? (
                  <tr>
                    <td colSpan={7} className="px-4 py-12 text-center text-sm text-gray-400">
                      No auditors yet.
                    </td>
                  </tr>
                )
                : rows.map((a) => {
                  const stds = uniq(a.qualifications.map((q) => q.standard_code))
                  const visible = stds.slice(0, 4)
                  const overflow = stds.length - visible.length
                  return (
                    <AuditorRow
                      key={a.auditor_id}
                      a={a}
                      stds={visible}
                      overflow={overflow}
                      onClick={() => router.push(`/auditors/${a.auditor_id}`)}
                    />
                  )
                })}
            </tbody>
          </table>
        </div>
      </div>

      {adding && <AddAuditorPanel onClose={() => setAdding(false)} onCreated={refreshLists} />}
    </>
  )
}

// ── Preview / edit form (Step 2 of add-auditor flow) ──────────────────────────

const ROLE_OPTIONS = ['Lead Auditor', 'Auditor', 'Technical Expert'] as const
const BODY_OPTIONS = ['UAF', 'TURKAK'] as const

function AuditorPreviewForm({
  preview, quals, eaText, onPreviewChange, onQualsChange, onEaChange,
  saving, saveErr, onBack, onSave,
}: {
  preview:         AuditorIngestResult
  quals:           QualRow[]
  eaText:          string
  onPreviewChange: (p: Partial<AuditorIngestResult>) => void
  onQualsChange:   (q: QualRow[]) => void
  onEaChange:      (v: string) => void
  saving:          boolean
  saveErr:         string | null
  onBack:          () => void
  onSave:          () => void
}) {
  function patchQual(i: number, p: Partial<QualRow>) {
    onQualsChange(quals.map((q, idx) => (idx === i ? { ...q, ...p } : q)))
  }
  function addQual()    { onQualsChange([...quals, { standard_code: '', accreditation_body: 'UAF', technical_depth: '' }]) }
  function removeQual(i: number) { onQualsChange(quals.filter((_, idx) => idx !== i)) }

  const nameMissing = !(preview.name ?? '').trim()

  return (
    <div className="space-y-4">
      <p className="text-sm text-gray-500">
        Review the extracted fields and correct anything before saving.
      </p>

      <div className="grid grid-cols-2 gap-3">
        <div className="col-span-2">
          <label className={lblCls}>Name *</label>
          <input
            type="text" className={inputCls}
            value={preview.name ?? ''}
            onChange={(e) => onPreviewChange({ name: e.target.value })}
          />
          {nameMissing && <p className="mt-1 text-xs text-red-500">Name is required.</p>}
        </div>

        <div>
          <label className={lblCls}>Role</label>
          <select
            className={inputCls} value={preview.role ?? ''}
            onChange={(e) => onPreviewChange({ role: e.target.value || null })}
          >
            <option value="">—</option>
            {ROLE_OPTIONS.map((r) => <option key={r} value={r}>{r}</option>)}
          </select>
        </div>

        <div>
          <label className={lblCls}>Email</label>
          <input
            type="email" className={inputCls} value={preview.email ?? ''}
            onChange={(e) => onPreviewChange({ email: e.target.value || null })}
          />
        </div>

        <div className="col-span-2">
          <label className={lblCls}>EA codes <span className="font-normal text-gray-300">(comma-separated)</span></label>
          <input
            type="text" className={inputCls} value={eaText}
            onChange={(e) => onEaChange(e.target.value)} placeholder="29, 30"
          />
        </div>
      </div>

      <div>
        <div className="mb-2 flex items-center justify-between">
          <label className="block text-sm font-medium text-gray-700">Qualifications</label>
          <button type="button" onClick={addQual} className="inline-flex items-center gap-1 text-xs font-medium text-certiva-primary hover:opacity-70">
            <Plus size={12} /> Add
          </button>
        </div>
        <div className="space-y-2">
          {quals.length === 0 && <p className="text-xs text-gray-400">No qualifications extracted.</p>}
          {quals.map((q, i) => (
            <div key={i} className="flex items-center gap-2">
              <input
                type="text" placeholder="Standard (QMS, EMS…)"
                className={`${inputCls} flex-1`} value={q.standard_code}
                onChange={(e) => patchQual(i, { standard_code: e.target.value })}
              />
              <select
                className={`${inputCls} w-28`} value={q.accreditation_body}
                onChange={(e) => patchQual(i, { accreditation_body: e.target.value })}
              >
                {BODY_OPTIONS.map((b) => <option key={b} value={b}>{b}</option>)}
              </select>
              <input
                type="text" placeholder="Depth" className={`${inputCls} w-32`}
                value={q.technical_depth}
                onChange={(e) => patchQual(i, { technical_depth: e.target.value })}
              />
              <button type="button" onClick={() => removeQual(i)} className="rounded p-2 text-gray-400 hover:bg-gray-50 hover:text-red-500" aria-label="Remove qualification">
                <Trash2 size={13} />
              </button>
            </div>
          ))}
        </div>
      </div>

      {saveErr && (
        <div className="rounded-lg border border-red-200 bg-red-50 p-3 text-sm text-red-700">{saveErr}</div>
      )}

      <div className="flex gap-2 pt-2">
        <button
          type="button" onClick={onBack} disabled={saving}
          className="flex-1 rounded-lg border border-gray-200 px-4 py-2 text-sm text-gray-700 hover:bg-gray-50 disabled:opacity-60"
        >
          Back
        </button>
        <button
          type="button" onClick={onSave}
          disabled={saving || nameMissing}
          className="flex flex-1 items-center justify-center gap-2 rounded-lg bg-certiva-primary px-4 py-2 text-sm font-medium text-white hover:opacity-90 disabled:opacity-60"
        >
          {saving && <Loader2 size={14} className="animate-spin" />}
          {saving ? 'Saving…' : 'Confirm & save'}
        </button>
      </div>
    </div>
  )
}
