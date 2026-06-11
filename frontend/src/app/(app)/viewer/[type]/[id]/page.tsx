'use client'

import { useParams, useRouter } from 'next/navigation'
import { ArrowLeft } from 'lucide-react'
import { CertivaDocumentViewer, type DocumentType } from '@/components/CertivaDocumentViewer'

export default function ViewerPage() {
  const params = useParams()
  const router = useRouter()
  const documentType = params.type as DocumentType
  const docId        = params.id   as string

  const validTypes: DocumentType[] = ['shared_doc', 'audit_report', 'nc_form']
  if (!validTypes.includes(documentType)) {
    return (
      <div className="p-8 text-sm text-red-600">
        Unknown document type: <code>{documentType}</code>
      </div>
    )
  }

  return (
    <div className="flex min-h-screen flex-col">
      {/* Header bar */}
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

      {/* Viewer */}
      <CertivaDocumentViewer
        documentType={documentType}
        docId={docId}
        onSignatureClick={(sigKey) => {
          // Prompt 25 will replace this with the signing modal
          alert(`Signing flow for [${sigKey}] — will be wired in Prompt 25.`)
        }}
      />
    </div>
  )
}
