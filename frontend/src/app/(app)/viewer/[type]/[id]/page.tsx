'use client'

import { useCallback, useEffect, useState } from 'react'
import { useParams, useRouter } from 'next/navigation'
import { ArrowLeft } from 'lucide-react'
import api from '@/lib/api'
import {
  CertivaDocumentViewer,
  type DocumentType,
  type SignatureOverride,
} from '@/components/CertivaDocumentViewer'
import { SignatureConfirmDialog } from '@/components/SignatureConfirmDialog'

const VALID_TYPES: DocumentType[] = ['shared_doc', 'audit_report', 'nc_form']

export default function ViewerPage() {
  const params = useParams()
  const router = useRouter()
  const documentType = params.type as DocumentType
  const docId        = params.id   as string

  const [overrides,    setOverrides]    = useState<SignatureOverride[]>([])
  const [activeSigKey, setActiveSigKey] = useState<string | null>(null)
  const [docPrepared,  setDocPrepared]  = useState(false)

  const loadStatus = useCallback(async () => {
    try {
      const r = await api.get('/viewer/signing-status', {
        params: { document_type: documentType, doc_id: docId },
      })
      setOverrides(r.data.fields ?? [])
    } catch {
      // fail silently — boxes default to "pending"
    }
  }, [documentType, docId])

  useEffect(() => {
    if (docPrepared) loadStatus()
  }, [docPrepared, loadStatus])

  if (!VALID_TYPES.includes(documentType)) {
    return (
      <div className="p-8 text-sm text-red-600">
        Unknown document type: <code>{documentType}</code>
      </div>
    )
  }

  return (
    <div className="flex min-h-screen flex-col">
      {/* Header */}
      <div className="sticky top-0 z-10 flex items-center gap-3 border-b bg-white px-6 py-3 shadow-sm">
        <button
          type="button"
          onClick={() => router.back()}
          className="flex items-center gap-1.5 text-sm text-gray-500 hover:text-gray-800"
        >
          <ArrowLeft size={16} />
          Back
        </button>
        <span className="text-sm font-medium text-gray-700 capitalize">
          {documentType.replace(/_/g, ' ')}
        </span>
      </div>

      <CertivaDocumentViewer
        documentType={documentType}
        docId={docId}
        signatureOverrides={overrides}
        onSignatureClick={(sigKey) => setActiveSigKey(sigKey)}
        onPrepared={() => setDocPrepared(true)}
      />

      <SignatureConfirmDialog
        isOpen={activeSigKey !== null}
        sigKey={activeSigKey ?? ''}
        documentType={documentType}
        docId={docId}
        onClose={() => setActiveSigKey(null)}
        onSigned={(sk) => {
          setActiveSigKey(null)
          loadStatus()
        }}
      />
    </div>
  )
}
