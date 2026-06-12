'use client'

import { useEffect, useState } from 'react'
import api from '@/lib/api'
import { NCFormClientSection } from '@/components/ui/NCFormClientSection'

type DocStatus = 'released' | 'signed'

interface DocSignature {
  id: string
  signer_role_label: string
  order_index: number
  required: boolean
  signed_at: string | null
  signer_name: string | null
}

interface SharedDoc {
  id: string
  label: string
  document_type: string
  status: DocStatus
  released_at: string | null
  signed_at: string | null
  signatures?: DocSignature[]
}

// True while an earlier (CB-side) signature slot is still pending — the client
// slot is order-gated server-side, so don't prompt "Open to Sign" yet.
function waitingOnCb(doc: SharedDoc): boolean {
  const sigs = doc.signatures ?? []
  const clientSlot = sigs.find((s) => s.signer_role_label === 'client' || s.signer_role_label === 'org_rep')
  if (!clientSlot) return false
  return sigs.some((s) => s.order_index < clientSlot.order_index && s.required && !s.signed_at)
}

function fmtDate(iso: string | null): string {
  if (!iso) return ''
  return new Date(iso).toLocaleDateString('en-GB', {
    day: 'numeric', month: 'long', year: 'numeric',
  })
}

export default function ClientDocumentsPage() {
  const [docs, setDocs]       = useState<SharedDoc[]>([])
  const [loading, setLoading] = useState(true)

  async function loadDocs() {
    try {
      const r = await api.get<SharedDoc[]>('/client/my-audit-set/documents')
      setDocs(r.data)
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => { loadDocs() }, [])

  // Bearer auth lives in localStorage; an <a href> can't send it. Fetch the
  // file as a blob via axios and trigger a download from an object URL.
  async function downloadDoc(docId: string, label: string) {
    try {
      const r = await api.get(`/client/my-audit-set/documents/${docId}/download`, {
        responseType: 'blob',
      })
      const url = window.URL.createObjectURL(r.data as Blob)
      const a = document.createElement('a')
      a.href = url
      a.download = `${label}.docx`
      document.body.appendChild(a)
      a.click()
      a.remove()
      window.URL.revokeObjectURL(url)
    } catch {
      alert('Could not download document.')
    }
  }

  if (loading) return <div className="p-8 text-gray-400">Loading documents…</div>

  return (
    <div className="mx-auto max-w-2xl p-6">
      <div className="mb-6">
        <h1 className="text-xl font-bold text-gray-900">Documents</h1>
        <p className="mt-0.5 text-sm text-gray-400">
          Documents shared with you by IFC Global
        </p>
      </div>

      {docs.length === 0 ? (
        <div className="py-16 text-center text-sm text-gray-400">
          No documents have been shared yet. You will be notified by email when
          documents are ready.
        </div>
      ) : (
        <div className="space-y-3">
          {docs.map((doc) => (
            <div key={doc.id} className="rounded-xl border bg-white p-5">
              <div className="flex items-center justify-between">
                <div>
                  <p className="text-sm font-semibold text-gray-900">{doc.label}</p>
                  <p className="mt-0.5 text-xs text-gray-400">
                    {doc.released_at ? `Received ${fmtDate(doc.released_at)}` : ''}
                  </p>
                </div>
                <span
                  className={`rounded-full px-2.5 py-1 text-xs font-semibold ${
                    doc.status === 'signed'
                      ? 'bg-green-100 text-green-700'
                      : waitingOnCb(doc)
                      ? 'bg-gray-100 text-gray-500'
                      : 'bg-amber-100 text-amber-700'
                  }`}
                >
                  {doc.status === 'signed'
                    ? '✓ Signed'
                    : waitingOnCb(doc)
                    ? 'Awaiting CB Signature'
                    : 'Awaiting Signature'}
                </span>
              </div>

              <div className="mt-4 flex items-center gap-2">
                <a
                  href={`/client/viewer/shared_doc/${doc.id}`}
                  className="inline-flex items-center gap-1.5 rounded-lg border border-[#1A4731] px-3 py-1.5
                    text-sm font-medium text-[#1A4731] hover:bg-[#1A4731]/5 transition-colors"
                >
                  {doc.status !== 'signed' && !waitingOnCb(doc) ? 'Open to Sign' : 'Open'}
                </a>
                <button
                  type="button"
                  onClick={() => downloadDoc(doc.id, doc.label)}
                  className="rounded-lg border border-[#1A4731] px-3 py-1.5 text-sm text-[#1A4731] transition-colors hover:bg-green-50"
                >
                  Download
                </button>
                {doc.status === 'signed' && doc.signed_at && (
                  <span className="text-xs text-gray-400">
                    Signed on {fmtDate(doc.signed_at)}
                  </span>
                )}
              </div>
            </div>
          ))}
        </div>
      )}

      <NCFormClientSection />
    </div>
  )
}
