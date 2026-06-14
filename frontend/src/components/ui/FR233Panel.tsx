'use client'

import { useCallback, useEffect, useRef, useState } from 'react'
import Link from 'next/link'
import api from '@/lib/api'
import { useAuth } from '@/lib/auth'

interface FR233Member {
  id:        string
  user_id:   string
  user_name: string
  role:      'reviewer' | 'decision_maker'
  sig_key:   string | null
  ea_codes:  string[]
  signed:    boolean
}

interface FR233Status {
  status:                'pending' | 'signing' | 'complete'
  document_id:           string | null
  members:               FR233Member[]
  cert_manager_signed:   boolean
  all_committee_signed:  boolean
}

const SHOW_STAGES = new Set([
  'stage2_complete', 'committee_review', 'under_review',
  'stage2_in_progress', 'certified',
])

const ROLE_LABELS: Record<string, string> = {
  decision_maker: 'Chairperson',
  reviewer:       'Member',
}

export function FR233Panel({
  auditSetId, workflowStatus,
}: { auditSetId: string; workflowStatus: string | null }) {
  const { user } = useAuth()
  const [data,    setData]    = useState<FR233Status | null>(null)
  const [loading, setLoading] = useState(true)
  const [busy,    setBusy]    = useState(false)
  const [error,   setError]   = useState('')
  const [uploadFile, setUploadFile] = useState<File | null>(null)
  const fileInputRef = useRef<HTMLInputElement>(null)

  const load = useCallback(async () => {
    try {
      const r = await api.get<FR233Status>(`/audit-sets/${auditSetId}/fr233`)
      setData(r.data)
    } catch {
      setData(null)
    } finally {
      setLoading(false)
    }
  }, [auditSetId])

  useEffect(() => { load() }, [load])

  if (!workflowStatus || !SHOW_STAGES.has(workflowStatus)) return null
  if (loading) return null

  const canGenerate    = user && ['admin', 'planner', 'executive'].includes(user.role)
  const canCertManager = user && ['admin', 'executive'].includes(user.role)
  const status         = data?.status ?? 'pending'
  const documentId     = data?.document_id ?? null
  const members        = data?.members ?? []
  const cmSigned       = data?.cert_manager_signed ?? false
  const allSigned      = data?.all_committee_signed ?? false

  async function generate() {
    if (!confirm(
      status === 'pending'
        ? 'Generate the FR.233 Review & Decision Form from the template?'
        : 'Re-generate FR.233 from the template? The existing draft will be overwritten and any signatures collected on the old draft will need to be re-applied.',
    )) return
    setBusy(true); setError('')
    try {
      await api.post(`/audit-sets/${auditSetId}/fr233/generate`, {})
      await load()
    } catch (e: unknown) {
      const detail = (e as { response?: { data?: { detail?: string } } })?.response?.data?.detail
      setError(detail || 'Generation failed')
    } finally {
      setBusy(false)
    }
  }

  async function upload() {
    if (!uploadFile) return
    setBusy(true); setError('')
    try {
      const form = new FormData()
      form.append('file', uploadFile)
      await api.post(`/audit-sets/${auditSetId}/fr233/upload`, form, {
        headers: { 'Content-Type': 'multipart/form-data' },
      })
      setUploadFile(null)
      if (fileInputRef.current) fileInputRef.current.value = ''
      await load()
    } catch (e: unknown) {
      const detail = (e as { response?: { data?: { detail?: string } } })?.response?.data?.detail
      setError(detail || 'Upload failed')
    } finally {
      setBusy(false)
    }
  }

  const statusPill =
    status === 'complete' ? 'bg-green-100 text-green-700'
    : status === 'signing' ? 'bg-amber-100 text-amber-700'
    : 'bg-gray-100 text-gray-500'

  return (
    <div className="mt-6">
      <div className="mb-3 flex items-center justify-between">
        <div className="flex items-center gap-2">
          <h2 className="text-sm font-semibold uppercase tracking-wide text-gray-700">
            FR.233 Review &amp; Decision
          </h2>
          <span className={`rounded-full px-2 py-0.5 text-xs font-semibold ${statusPill}`}>
            {status}
          </span>
        </div>
        {canGenerate && status === 'pending' && (
          <div className="flex items-center gap-2">
            <input
              ref={fileInputRef}
              type="file"
              accept=".pdf,.docx"
              className="hidden"
              id={`fr233-upload-${auditSetId}`}
              onChange={e => setUploadFile(e.target.files?.[0] ?? null)}
            />
            <label
              htmlFor={`fr233-upload-${auditSetId}`}
              className="cursor-pointer rounded-lg border border-gray-300 px-3 py-1.5 text-xs font-medium text-gray-600 hover:bg-gray-50"
            >
              {uploadFile ? uploadFile.name : 'Choose FR.233 file…'}
            </label>
            {uploadFile && (
              <button
                type="button"
                onClick={upload}
                disabled={busy}
                className="rounded-lg bg-[#1A4731] px-3 py-1.5 text-xs font-medium text-white hover:bg-[#143b27] disabled:opacity-40"
              >
                {busy ? 'Uploading…' : 'Upload FR.233'}
              </button>
            )}
            <button
              type="button"
              onClick={generate}
              disabled={busy}
              className="rounded-lg border border-gray-300 px-2 py-1 text-[11px] font-medium text-gray-400 hover:bg-gray-50 disabled:opacity-40"
              title="Generate a pre-filled FR.233 from the template (admin/planner shortcut)"
            >
              Generate from template instead
            </button>
          </div>
        )}
        {canGenerate && status !== 'pending' && (
          <button
            type="button"
            onClick={generate}
            disabled={busy}
            className="rounded-lg border border-gray-300 px-3 py-1.5 text-xs font-medium text-gray-500 hover:bg-gray-50 disabled:opacity-40"
            title="Overwrite with a template-generated FR.233 (admin use)"
          >
            {busy ? 'Generating…' : 'Re-generate from template'}
          </button>
        )}
      </div>

      <div className="rounded-xl border bg-white">
        {status === 'pending' ? (
          <div className="px-4 py-6 text-center text-xs text-gray-400">
            Upload the completed FR.233 document above to begin committee signing.
          </div>
        ) : (
          <div className="divide-y divide-gray-100">
            {members.length === 0 && (
              <div className="px-4 py-3 text-xs text-gray-400">
                FR.233 uploaded — appoint committee members to enable signing.
              </div>
            )}
            {members.map(m => (
              <div key={m.id} className="flex items-center justify-between px-4 py-3">
                <div>
                  <p className="text-sm font-medium text-gray-800">{m.user_name}</p>
                  <p className="mt-0.5 text-xs text-gray-400">
                    {ROLE_LABELS[m.role] ?? m.role}
                    {m.sig_key ? ` · slot: ${m.sig_key}` : ' · no slot assigned'}
                    {m.ea_codes.length > 0 ? ` · EA: ${m.ea_codes.join(', ')}` : ''}
                  </p>
                </div>
                <span className={`rounded-full px-2 py-0.5 text-xs font-semibold ${m.signed ? 'bg-green-100 text-green-700' : 'bg-gray-100 text-gray-500'}`}>
                  {m.signed ? '✓ Signed' : 'Pending'}
                </span>
              </div>
            ))}
            <div className="flex items-center justify-between bg-gray-50 px-4 py-3">
              <div>
                <p className="text-sm font-medium text-gray-800">Certification Manager Approval</p>
                <p className="mt-0.5 text-xs text-gray-400">
                  slot: CERT_MANAGER_FR233 · advances workflow to <code>certified</code>
                </p>
              </div>
              <span className={`rounded-full px-2 py-0.5 text-xs font-semibold ${cmSigned ? 'bg-green-100 text-green-700' : allSigned ? 'bg-amber-100 text-amber-700' : 'bg-gray-100 text-gray-500'}`}>
                {cmSigned ? '✓ Signed' : allSigned ? 'Awaiting CM' : 'Locked'}
              </span>
            </div>
          </div>
        )}
      </div>

      {documentId && (
        <div className="mt-3 flex items-center gap-3">
          <Link
            href={`/viewer/shared_doc/${documentId}`}
            className="rounded-lg border px-3 py-1.5 text-xs font-medium text-gray-700 hover:bg-gray-50"
          >
            Open FR.233 in viewer
          </Link>
          {canCertManager && allSigned && !cmSigned && (
            <Link
              href={`/viewer/shared_doc/${documentId}?slot=CERT_MANAGER_FR233`}
              className="rounded-lg bg-[#1A4731] px-3 py-1.5 text-xs font-medium text-white hover:bg-[#143b27]"
            >
              Sign as Certification Manager
            </Link>
          )}
        </div>
      )}

      {error && <p className="mt-2 text-xs text-red-500">{error}</p>}
    </div>
  )
}
