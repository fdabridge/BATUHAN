'use client'

import { useEffect, useState } from 'react'
import { Download, ExternalLink, FileText, Loader2, RefreshCw } from 'lucide-react'
import api from '@/lib/api'

interface CompanyDocument {
  id: string
  file_name: string
  file_type: string
  file_size: number
  uploaded_at: string | null
  uploader_name: string
  uploader_role: string
}

function formatSize(bytes: number): string {
  if (bytes < 1024 * 1024) return `${Math.max(1, Math.round(bytes / 1024))} KB`
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`
}

function formatDate(value: string | null): string {
  if (!value) return '—'
  return new Date(value).toLocaleString()
}

export function CompanyDocumentsSection({ auditSetId }: { auditSetId: string }) {
  const [documents, setDocuments] = useState<CompanyDocument[]>([])
  const [loading, setLoading] = useState(true)
  const [loadError, setLoadError] = useState('')
  const [actionError, setActionError] = useState('')
  const [activeDocument, setActiveDocument] = useState<string | null>(null)
  const [reloadToken, setReloadToken] = useState(0)

  useEffect(() => {
    let cancelled = false
    setLoading(true)
    setLoadError('')
    setActionError('')
    api.get<CompanyDocument[]>(`/audit-sets/${auditSetId}/company-documents`)
      .then(response => {
        if (!cancelled) setDocuments(response.data)
      })
      .catch((error: { response?: { data?: { detail?: string } } }) => {
        if (!cancelled) {
          setLoadError(
            error.response?.data?.detail || 'Company documents could not be loaded.',
          )
        }
      })
      .finally(() => {
        if (!cancelled) setLoading(false)
      })
    return () => { cancelled = true }
  }, [auditSetId, reloadToken])

  async function openDocument(document: CompanyDocument, download: boolean) {
    const previewWindow = download ? null : window.open('', '_blank')
    setActionError('')
    setActiveDocument(document.id)
    try {
      const response = await api.get(
        `/audit-sets/${auditSetId}/company-documents/${document.id}/file`,
        { params: { download }, responseType: 'blob' },
      )
      const url = window.URL.createObjectURL(response.data as Blob)
      if (download) {
        const anchor = window.document.createElement('a')
        anchor.href = url
        anchor.download = document.file_name
        window.document.body.appendChild(anchor)
        anchor.click()
        anchor.remove()
      } else if (previewWindow) {
        previewWindow.location.href = url
      } else {
        window.open(url, '_blank')
      }
      window.setTimeout(() => window.URL.revokeObjectURL(url), 60_000)
    } catch {
      previewWindow?.close()
      setActionError(`Could not open ${document.file_name}.`)
    } finally {
      setActiveDocument(null)
    }
  }

  return (
    <section className="rounded-xl border border-slate-200 bg-white p-5">
      <div className="flex items-start justify-between gap-4">
        <div>
          <h2 className="text-sm font-semibold text-slate-800">Company Documents</h2>
          <p className="mt-1 text-xs text-slate-500">
            Supporting documents supplied by the client with this application.
          </p>
        </div>
        {!loading && !loadError && (
          <span className="rounded-full bg-slate-100 px-2.5 py-1 text-xs font-semibold text-slate-600">
            {documents.length} {documents.length === 1 ? 'file' : 'files'}
          </span>
        )}
      </div>

      {loading && (
        <div className="flex items-center gap-2 py-6 text-sm text-slate-400">
          <Loader2 size={15} className="animate-spin" />
          Loading company documents…
        </div>
      )}

      {loadError && (
        <div className="mt-4 flex items-center justify-between gap-3 rounded-lg bg-red-50 px-3 py-2 text-sm text-red-700">
          <span>{loadError}</span>
          <button
            type="button"
            onClick={() => setReloadToken(value => value + 1)}
            className="flex shrink-0 items-center gap-1 rounded-md border border-red-200 bg-white px-2.5 py-1.5 text-xs font-semibold text-red-700 hover:bg-red-100"
          >
            <RefreshCw size={12} /> Retry
          </button>
        </div>
      )}

      {actionError && (
        <p className="mt-4 rounded-lg bg-red-50 px-3 py-2 text-sm text-red-700">{actionError}</p>
      )}

      {!loading && !loadError && documents.length === 0 && (
        <p className="mt-4 rounded-lg bg-slate-50 px-3 py-3 text-sm text-slate-500">
          No company documents were uploaded with this application.
        </p>
      )}

      {!loading && !loadError && documents.length > 0 && (
        <div className="mt-4 divide-y divide-slate-100 overflow-hidden rounded-lg border border-slate-200">
          {documents.map(document => (
            <div key={document.id} className="flex items-center gap-3 px-3.5 py-3">
              <FileText size={18} className="shrink-0 text-[#1A4731]" />
              <div className="min-w-0 flex-1">
                <p className="truncate text-sm font-medium text-slate-700">{document.file_name}</p>
                <p className="mt-0.5 text-xs text-slate-400">
                  {document.file_type || 'Document'} · {formatSize(document.file_size)}
                  {' · '}Uploaded {formatDate(document.uploaded_at)} by {document.uploader_name}
                </p>
              </div>
              <button
                type="button"
                disabled={activeDocument === document.id}
                onClick={() => openDocument(document, false)}
                className="flex items-center gap-1 rounded-md border border-slate-200 px-2.5 py-1.5 text-xs font-medium text-slate-600 hover:bg-slate-50 disabled:opacity-50"
              >
                {activeDocument === document.id
                  ? <Loader2 size={13} className="animate-spin" />
                  : <ExternalLink size={13} />}
                Preview
              </button>
              <button
                type="button"
                disabled={activeDocument === document.id}
                onClick={() => openDocument(document, true)}
                className="flex items-center gap-1 rounded-md bg-[#1A4731] px-2.5 py-1.5 text-xs font-medium text-white hover:opacity-90 disabled:opacity-50"
              >
                <Download size={13} />
                Download
              </button>
            </div>
          ))}
        </div>
      )}
    </section>
  )
}
