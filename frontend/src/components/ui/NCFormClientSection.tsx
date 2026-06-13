'use client'

import { useEffect, useState } from 'react'
import api from '@/lib/api'

interface NCForm {
  id:               string
  stage_type:       string
  label:            string
  file_name:        string | null
  status:           string
  la_signed_at:     string | null
  client_signed_at: string | null
}

const STAGE_LABELS: Record<string, string> = {
  stage_1: 'Stage 1', stage_2: 'Stage 2',
  surveillance: 'Surveillance', recertification: 'Recertification',
}

function fmtDate(iso: string | null) {
  if (!iso) return ''
  return new Date(iso).toLocaleDateString('en-GB', {
    day: 'numeric', month: 'short', year: 'numeric',
  })
}

export function NCFormClientSection() {
  const [forms, setForms]     = useState<NCForm[]>([])
  const [loading, setLoading] = useState(true)

  useEffect(() => {
    api.get<NCForm[]>('/client/my-audit-set/nc-forms')
      .then(r => setForms(r.data))
      .finally(() => setLoading(false))
  }, [])

  if (loading) return null
  if (forms.length === 0) return null

  return (
    <div className="mt-8">
      <h2 className="mb-3 text-base font-semibold text-gray-900">
        Nonconformity Forms (FR.230)
      </h2>
      <div className="space-y-3">
        {forms.map(f => (
          <NCFormRow key={f.id} f={f} />
        ))}
      </div>
    </div>
  )
}

interface NCFormRowProps {
  f: NCForm
}

function NCFormRow({ f }: NCFormRowProps) {
  const isSigned = f.status === 'complete'

  if (isSigned) {
    return (
      <div className="flex items-center justify-between rounded-xl border border-green-200 bg-green-50 px-4 py-3">
        <div>
          <p className="font-medium text-gray-800">{f.label}</p>
          <p className="mt-0.5 text-xs text-gray-400">
            {STAGE_LABELS[f.stage_type] ?? f.stage_type} · Signed {fmtDate(f.client_signed_at)}
          </p>
        </div>
        <div className="flex items-center gap-3">
          <span className="rounded-full bg-green-100 px-2.5 py-0.5 text-xs font-semibold text-green-700">
            ✓ Signed
          </span>
          <a
            href={`/client/viewer/nc_form/${f.id}`}
            className="text-xs text-[#1A4731] underline"
          >
            Open
          </a>
        </div>
      </div>
    )
  }

  return (
    <div className="flex items-center justify-between rounded-xl border bg-white p-4">
      <div>
        <p className="font-medium text-gray-800">{f.label}</p>
        <p className="mt-0.5 text-xs text-gray-500">
          {STAGE_LABELS[f.stage_type] ?? f.stage_type}
          {f.la_signed_at && ` · Auditor signed ${fmtDate(f.la_signed_at)}`}
        </p>
      </div>
      <a
        href={`/client/viewer/nc_form/${f.id}`}
        className="inline-flex items-center rounded-lg bg-[#1A4731] px-3 py-1.5
          text-xs font-medium text-white hover:bg-[#143828] transition-colors"
      >
        Open to Sign
      </a>
    </div>
  )
}
