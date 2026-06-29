'use client'

import { useEffect, useState } from 'react'
import { useParams, useRouter } from 'next/navigation'
import api from '@/lib/api'

interface CRMClient {
  id: string
  company_name: string
  city: string
  standards: string[]
  audit_type: string
  accreditation_body: string
  simple_status: string
  cert_issued_date: string | null
  cert_expiry_date: string | null
  surv1_due: string | null
  surv2_due: string | null
  recert_due: string | null
  certification_fee: number | null
  surveillance_fee: number | null
  currency: string
  contact_name: string
  contact_email: string
  contact_phone: string
}

function fmtDate(iso: string | null | undefined) {
  if (!iso) return '—'
  return new Date(iso).toLocaleDateString('en-GB', { day: 'numeric', month: 'short', year: 'numeric' })
}

function fmtFee(val: number | null, currency: string) {
  if (val == null) return '—'
  const sym = currency === 'EUR' ? '€' : currency === 'TRY' ? '₺' : '$'
  return `${sym}${val.toLocaleString()}`
}

function MilestoneRow({ label, due }: { label: string; due: string | null }) {
  if (!due) return (
    <div className="flex items-center justify-between py-3 border-b border-gray-100 last:border-0">
      <span className="text-sm text-gray-600">{label}</span>
      <span className="text-sm text-gray-400">Not yet scheduled</span>
    </div>
  )
  const days = Math.round((new Date(due).getTime() - Date.now()) / 86_400_000)
  let badge = { label: 'On track', cls: 'bg-green-100 text-green-700' }
  if (days < 0)  badge = { label: `${Math.abs(days)} days overdue`, cls: 'bg-red-100 text-red-700' }
  else if (days < 30) badge = { label: `${days} days`, cls: 'bg-orange-100 text-orange-700' }
  else if (days < 90) badge = { label: `${days} days`, cls: 'bg-yellow-100 text-yellow-700' }
  return (
    <div className="flex items-center justify-between py-3 border-b border-gray-100 last:border-0">
      <span className="text-sm text-gray-700">{label}</span>
      <div className="flex items-center gap-3">
        <span className="text-sm text-gray-600">{fmtDate(due)}</span>
        <span className={`rounded-full px-2 py-0.5 text-xs font-medium ${badge.cls}`}>{badge.label}</span>
      </div>
    </div>
  )
}

export default function CRMClientDetail() {
  const { id } = useParams<{ id: string }>()
  const router  = useRouter()
  const [client, setClient]   = useState<CRMClient | null>(null)
  const [loading, setLoading] = useState(true)

  useEffect(() => {
    if (!id) return
    api.get<CRMClient>(`/crm/clients/${id}`)
      .then((r) => setClient(r.data))
      .catch(() => {})
      .finally(() => setLoading(false))
  }, [id])

  if (loading) return <div className="p-8 text-sm text-gray-400">Loading…</div>
  if (!client)  return <div className="p-8 text-sm text-red-500">Client not found.</div>

  return (
    <div className="space-y-6 max-w-3xl">
      {/* Header */}
      <div className="flex items-center gap-4">
        <button onClick={() => router.back()} className="text-sm text-gray-400 hover:text-gray-700">← Back</button>
        <h1 className="text-xl font-semibold text-gray-900">{client.company_name}</h1>
        {client.city && <span className="text-sm text-gray-400">{client.city}</span>}
        <span className="rounded-full bg-emerald-100 px-3 py-0.5 text-xs font-medium text-emerald-700">{client.simple_status}</span>
      </div>

      <div className="grid grid-cols-1 gap-5 sm:grid-cols-2">
        {/* Contact Info */}
        <div className="rounded-xl border border-gray-200 bg-white p-5 shadow-sm">
          <h2 className="text-xs font-semibold uppercase tracking-wide text-gray-400 mb-3">Contact</h2>
          <div className="space-y-2 text-sm">
            <div><span className="text-gray-500">Name: </span><span className="text-gray-800">{client.contact_name || '—'}</span></div>
            <div><span className="text-gray-500">Email: </span>
              {client.contact_email
                ? <a href={`mailto:${client.contact_email}`} className="text-emerald-700 hover:underline">{client.contact_email}</a>
                : <span className="text-gray-400">—</span>}
            </div>
            <div><span className="text-gray-500">Phone: </span><span className="text-gray-800">{client.contact_phone || '—'}</span></div>
          </div>
        </div>

        {/* Certification Info */}
        <div className="rounded-xl border border-gray-200 bg-white p-5 shadow-sm">
          <h2 className="text-xs font-semibold uppercase tracking-wide text-gray-400 mb-3">Certification</h2>
          <div className="space-y-2 text-sm">
            <div><span className="text-gray-500">Standards: </span><span className="text-gray-800">{(client.standards || []).join(', ') || '—'}</span></div>
            <div><span className="text-gray-500">Type: </span><span className="text-gray-800 capitalize">{client.audit_type}</span></div>
            <div><span className="text-gray-500">Accreditation: </span><span className="text-gray-800">{client.accreditation_body || '—'}</span></div>
            <div><span className="text-gray-500">Cert Fee: </span><span className="text-gray-800">{fmtFee(client.certification_fee, client.currency)}</span></div>
            <div><span className="text-gray-500">Surv Fee: </span><span className="text-gray-800">{fmtFee(client.surveillance_fee, client.currency)}</span></div>
          </div>
        </div>
      </div>

      {/* Certification Cycle Timeline */}
      <div className="rounded-xl border border-gray-200 bg-white p-5 shadow-sm">
        <h2 className="text-xs font-semibold uppercase tracking-wide text-gray-400 mb-1">Certification Cycle</h2>
        {!client.cert_issued_date ? (
          <p className="text-sm text-gray-400 py-4">No certificate issued yet — cycle dates will appear here once certification is complete.</p>
        ) : (
          <div>
            <MilestoneRow label="✓ Certified"          due={client.cert_issued_date} />
            <MilestoneRow label="Surveillance 1"       due={client.surv1_due} />
            <MilestoneRow label="Surveillance 2"       due={client.surv2_due} />
            <MilestoneRow label="Recertification"      due={client.recert_due} />
            {client.cert_expiry_date && (
              <MilestoneRow label="Certificate Expires" due={client.cert_expiry_date} />
            )}
          </div>
        )}
      </div>
    </div>
  )
}
