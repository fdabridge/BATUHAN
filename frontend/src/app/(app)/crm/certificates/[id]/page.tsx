'use client'

import { useEffect, useState } from 'react'
import { useParams, useRouter } from 'next/navigation'
import api from '@/lib/api'
import { useAuth } from '@/lib/auth'

const CRM_ROLES = new Set(['crm', 'admin'])

interface CertificateDetail {
  audit_set_id: string
  company_name: string
  standards: {
    standard: string
    lifecycle_status: string
    certificate_number: string | null
    cert_issued_date: string | null
    cert_expiry_date: string | null
    next_surveillance_due: string | null
    last_surveillance_completed: string | null
    assigned_auditor: string | null
    audit_history: { date: string; type: string; result: string }[]
    payment_status: string
    amount_due: number | null
    amount_received: number | null
    notes: string | null
  }[]
}

function fmtDate(iso: string | null | undefined) {
  if (!iso) return '\u2014'
  return new Date(iso).toLocaleDateString('en-GB', { day: 'numeric', month: 'short', year: 'numeric' })
}

const STATUS_COLORS: Record<string, string> = {
  active: 'bg-green-100 text-green-700',
  expiring_soon: 'bg-orange-100 text-orange-700',
  expired: 'bg-red-100 text-red-700',
  suspended: 'bg-gray-100 text-gray-500',
  withdrawn: 'bg-gray-100 text-gray-500',
  in_progress: 'bg-blue-100 text-blue-700',
}

export default function CertificateDetailPage() {
  const { user } = useAuth()
  const { id } = useParams<{ id: string }>()
  const router = useRouter()
  const [detail, setDetail] = useState<CertificateDetail | null>(null)
  const [loading, setLoading] = useState(true)
  const [activeTab, setActiveTab] = useState(0)
  const [saving, setSaving] = useState(false)
  const [saveSuccess, setSaveSuccess] = useState(false)

  // Commercial form state per standard
  const [commercialForms, setCommercialForms] = useState<Record<string, {
    payment_status: string
    amount_due: string
    amount_received: string
    notes: string
  }>>({})

  useEffect(() => {
    if (!id) return
    api.get<CertificateDetail>(`/crm/certificates/${id}`)
      .then((r) => {
        setDetail(r.data)
        // Initialize commercial forms
        const forms: typeof commercialForms = {}
        r.data.standards.forEach((s) => {
          forms[s.standard] = {
            payment_status: s.payment_status || 'unpaid',
            amount_due: s.amount_due != null ? String(s.amount_due) : '',
            amount_received: s.amount_received != null ? String(s.amount_received) : '',
            notes: s.notes || '',
          }
        })
        setCommercialForms(forms)
      })
      .catch(() => {})
      .finally(() => setLoading(false))
  }, [id])

  async function handleSave(standard: string) {
    const form = commercialForms[standard]
    if (!form) return
    setSaving(true)
    setSaveSuccess(false)
    try {
      await api.patch(`/crm/certificates/${id}/commercial`, {
        standard,
        payment_status: form.payment_status,
        amount_due: form.amount_due ? parseFloat(form.amount_due) : null,
        amount_received: form.amount_received ? parseFloat(form.amount_received) : null,
        notes: form.notes || null,
      })
      setSaveSuccess(true)
      setTimeout(() => setSaveSuccess(false), 3000)
    } catch {
      // silent
    } finally {
      setSaving(false)
    }
  }

  function updateForm(standard: string, field: string, value: string) {
    setCommercialForms((prev) => ({
      ...prev,
      [standard]: { ...prev[standard], [field]: value },
    }))
  }

  if (!user || !CRM_ROLES.has(user.role)) {
    return <div className="p-8 text-sm text-red-500">Access denied.</div>
  }

  if (loading) return <div className="p-8 text-sm text-gray-400">Loading...</div>
  if (!detail) return <div className="p-8 text-sm text-red-500">Certificate not found.</div>

  const currentStandard = detail.standards[activeTab]
  const currentForm = currentStandard ? commercialForms[currentStandard.standard] : null

  return (
    <div className="space-y-6 max-w-4xl">
      {/* Header */}
      <div className="flex items-center gap-4">
        <button onClick={() => router.back()} className="text-sm text-gray-400 hover:text-gray-700">&larr; Back</button>
        <h1 className="text-xl font-semibold text-gray-900">{detail.company_name}</h1>
      </div>

      {/* Standard Tabs (if multi-standard) */}
      {detail.standards.length > 1 && (
        <div className="flex gap-2">
          {detail.standards.map((s, i) => (
            <button
              key={s.standard}
              onClick={() => setActiveTab(i)}
              className={`rounded-lg px-3 py-1.5 text-sm font-medium transition-colors ${
                activeTab === i
                  ? 'bg-emerald-100 text-emerald-700'
                  : 'bg-gray-100 text-gray-500 hover:bg-gray-200'
              }`}
            >
              {s.standard}
            </button>
          ))}
        </div>
      )}

      {currentStandard && (
        <div className="grid grid-cols-1 gap-6 lg:grid-cols-2">
          {/* Certification Panel (Read-only) */}
          <div className="rounded-xl border border-gray-200 bg-white p-5 shadow-sm opacity-80">
            <h2 className="text-xs font-semibold uppercase tracking-wide text-gray-400 mb-4">Certification Details</h2>
            <div className="space-y-3 text-sm">
              <div className="flex justify-between">
                <span className="text-gray-500">Standard</span>
                <span className="text-gray-700 font-medium">{currentStandard.standard}</span>
              </div>
              <div className="flex justify-between">
                <span className="text-gray-500">Status</span>
                <span className={`rounded-full px-2 py-0.5 text-xs font-medium ${STATUS_COLORS[currentStandard.lifecycle_status] ?? 'bg-gray-100 text-gray-600'}`}>
                  {currentStandard.lifecycle_status.replace(/_/g, ' ')}
                </span>
              </div>
              <div className="flex justify-between">
                <span className="text-gray-500">Certificate #</span>
                <span className="text-gray-700">{currentStandard.certificate_number || '\u2014'}</span>
              </div>
              <div className="flex justify-between">
                <span className="text-gray-500">Issued</span>
                <span className="text-gray-700">{fmtDate(currentStandard.cert_issued_date)}</span>
              </div>
              <div className="flex justify-between">
                <span className="text-gray-500">Expires</span>
                <span className="text-gray-700">{fmtDate(currentStandard.cert_expiry_date)}</span>
              </div>
              <div className="flex justify-between">
                <span className="text-gray-500">Next Surveillance</span>
                <span className="text-gray-700">{fmtDate(currentStandard.next_surveillance_due)}</span>
              </div>
              <div className="flex justify-between">
                <span className="text-gray-500">Last Surveillance</span>
                <span className="text-gray-700">{fmtDate(currentStandard.last_surveillance_completed)}</span>
              </div>
              <div className="flex justify-between">
                <span className="text-gray-500">Auditor</span>
                <span className="text-gray-700">{currentStandard.assigned_auditor || '\u2014'}</span>
              </div>
            </div>

            {/* Audit History */}
            {currentStandard.audit_history && currentStandard.audit_history.length > 0 && (
              <div className="mt-5">
                <h3 className="text-xs font-semibold uppercase tracking-wide text-gray-400 mb-2">Audit History</h3>
                <div className="space-y-2">
                  {currentStandard.audit_history.map((h, i) => (
                    <div key={i} className="flex items-center justify-between text-xs border-b border-gray-50 pb-1">
                      <span className="text-gray-500">{fmtDate(h.date)}</span>
                      <span className="text-gray-600">{h.type}</span>
                      <span className="text-gray-700 font-medium">{h.result}</span>
                    </div>
                  ))}
                </div>
              </div>
            )}
          </div>

          {/* Commercial Panel (Editable) */}
          {currentForm && (
            <div className="rounded-xl border border-gray-200 bg-white p-5 shadow-sm">
              <h2 className="text-xs font-semibold uppercase tracking-wide text-gray-400 mb-4">Commercial</h2>
              <div className="space-y-4">
                <div>
                  <label className="block text-xs font-medium text-gray-600 mb-1">Payment Status</label>
                  <select
                    className="w-full rounded-lg border border-gray-200 px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-emerald-500"
                    value={currentForm.payment_status}
                    onChange={(e) => updateForm(currentStandard.standard, 'payment_status', e.target.value)}
                  >
                    <option value="unpaid">Unpaid</option>
                    <option value="partially_paid">Partially Paid</option>
                    <option value="paid">Paid</option>
                    <option value="overdue">Overdue</option>
                  </select>
                </div>
                <div>
                  <label className="block text-xs font-medium text-gray-600 mb-1">Amount Due ($)</label>
                  <input
                    type="number"
                    className="w-full rounded-lg border border-gray-200 px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-emerald-500"
                    value={currentForm.amount_due}
                    onChange={(e) => updateForm(currentStandard.standard, 'amount_due', e.target.value)}
                    placeholder="0.00"
                  />
                </div>
                <div>
                  <label className="block text-xs font-medium text-gray-600 mb-1">Amount Received ($)</label>
                  <input
                    type="number"
                    className="w-full rounded-lg border border-gray-200 px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-emerald-500"
                    value={currentForm.amount_received}
                    onChange={(e) => updateForm(currentStandard.standard, 'amount_received', e.target.value)}
                    placeholder="0.00"
                  />
                </div>
                <div>
                  <label className="block text-xs font-medium text-gray-600 mb-1">Notes</label>
                  <textarea
                    className="w-full rounded-lg border border-gray-200 px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-emerald-500"
                    rows={3}
                    value={currentForm.notes}
                    onChange={(e) => updateForm(currentStandard.standard, 'notes', e.target.value)}
                    placeholder="Add notes..."
                  />
                </div>
                <button
                  onClick={() => handleSave(currentStandard.standard)}
                  disabled={saving}
                  className="w-full rounded-lg bg-emerald-600 px-4 py-2 text-sm font-medium text-white hover:bg-emerald-700 transition-colors disabled:opacity-60"
                >
                  {saving ? 'Saving...' : 'Save Commercial Data'}
                </button>
                {saveSuccess && (
                  <p className="text-xs text-emerald-600 font-medium">Saved successfully.</p>
                )}
              </div>
            </div>
          )}
        </div>
      )}
    </div>
  )
}
