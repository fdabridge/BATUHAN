'use client'

/**
 * SignatureConfirmDialog — Signs a [SIG:KEY] field directly (no OTP).
 *
 * Flow:
 *   1. For client-side slots (CLIENT / ORG_REP): fetch /org/employees and
 *      show an employee picker. The selected employee's saved signature is
 *      used for the document. (Portal 56)
 *   2. For all other slots: fetch the user's own saved signature from
 *      /me/signature and show the preview.
 *   3. User confirms → POST /viewer/sign/confirm (with employee_id when set).
 *   4. On success: calls onSigned(sigKey) and auto-closes.
 */

import { useEffect, useState } from 'react'
import { AlertCircle, CheckCircle2, Loader2, PenLine, X } from 'lucide-react'
import api from '@/lib/api'

type Stage = 'loading' | 'no_signature' | 'preview' | 'signing' | 'success'

interface Props {
  isOpen:       boolean
  sigKey:       string
  documentType: string
  docId:        string
  onClose:      () => void
  onSigned:     (sigKey: string) => void
}

interface OrgEmployee {
  id:             string
  full_name:      string
  role_title:     string
  has_signature:  boolean
}

const CLIENT_SIDE_SIG_KEYS = new Set(['CLIENT', 'ORG_REP'])

// Portal 73 — UUID-based org-employee slots embedded in sig_key (FR.225).
// Format: ORG_OPENING_ORG_EMP_<uuid> | ORG_CLOSING_ORG_EMP_<uuid>
// The employee is already determined by the key — no picker needed.
const ORG_EMP_RE = /^ORG_(OPENING|CLOSING)_ORG_EMP_([0-9a-fA-F-]{36})$/

function getSignatureSettingsUrl(): string {
  if (typeof window === 'undefined') return '/settings/signature'
  const p = window.location.pathname
  if (p.startsWith('/client/'))  return '/client/signature'
  if (p.startsWith('/auditor/')) return '/auditor/signature'
  return '/settings/signature'
}

const SIG_KEY_LABELS: Record<string, string> = {
  CB_PLANNER:      'Planning Officer',
  CB_CERT_MANAGER: 'Certification Manager',
  CB_REVIEWER:     'Committee Reviewer',
  LEAD_AUDITOR:    'Lead Auditor',
  CLIENT:          'Organisation Representative',
  ORG_REP:         'Organisation Representative',
  AUDITOR_MEMBER:  'Audit Team Member',
  GM:              'General Manager',
}

function todayIso() {
  return new Date().toISOString().slice(0, 10)
}

export function SignatureConfirmDialog({
  isOpen, sigKey, documentType, docId, onClose, onSigned,
}: Props) {
  const [stage,      setStage]      = useState<Stage>('loading')
  const [sigImage,   setSigImage]   = useState<string | null>(null)
  const [errorMsg,   setErrorMsg]   = useState('')
  const [signedDate, setSignedDate] = useState(todayIso)

  // Portal 56 — employee picker state, only used for generic CLIENT / ORG_REP slots.
  const needsEmployeePicker = CLIENT_SIDE_SIG_KEYS.has(sigKey)
  const [employees,     setEmployees]     = useState<OrgEmployee[]>([])
  const [selectedEmpId, setSelectedEmpId] = useState<string>('')
  const selectedEmp = employees.find((e) => e.id === selectedEmpId) ?? null

  // Portal 73 — UUID-embedded org-employee slots (FR.225 opening/closing rows).
  // The employee is already identified by the sig_key — no picker needed.
  const orgEmpMatch    = ORG_EMP_RE.exec(sigKey)
  const isOrgEmpSlot   = orgEmpMatch !== null
  const orgEmpUuid     = orgEmpMatch ? orgEmpMatch[2] : null
  const orgEmpPhase    = orgEmpMatch ? orgEmpMatch[1] : null   // 'OPENING' | 'CLOSING'
  const [orgEmployee,  setOrgEmployee]  = useState<OrgEmployee | null>(null)

  useEffect(() => {
    if (!isOpen) return
    setStage('loading')
    setErrorMsg('')
    setSigImage(null)
    setSelectedEmpId('')
    setOrgEmployee(null)

    // Portal 73 — UUID-embedded employee slot: fetch that specific employee.
    if (isOrgEmpSlot && orgEmpUuid) {
      api.get('/org/employees')
        .then((r) => {
          const list: OrgEmployee[] = Array.isArray(r.data) ? r.data : []
          const emp = list.find((e) => e.id === orgEmpUuid) ?? null
          setOrgEmployee(emp)
          if (!emp || !emp.has_signature) {
            setStage('no_signature')
          } else {
            return api.get(`/org/employees/${orgEmpUuid}/signature`).then((sr) => {
              setSigImage(sr.data?.image_data ?? null)
              setStage('preview')
            })
          }
        })
        .catch(() => {
          setOrgEmployee(null)
          setStage('no_signature')
        })
      return
    }

    if (needsEmployeePicker) {
      api.get('/org/employees')
        .then((r) => {
          const list = Array.isArray(r.data) ? (r.data as OrgEmployee[]) : []
          setEmployees(list)
          if (list.length === 0) {
            setStage('no_signature')
          } else {
            setStage('preview')
          }
        })
        .catch(() => {
          setEmployees([])
          setStage('no_signature')
        })
      return
    }

    api.get('/me/signature')
      .then((r) => {
        if (r.data?.image_data) {
          setSigImage(r.data.image_data)
          setStage('preview')
        } else {
          setStage('no_signature')
        }
      })
      .catch(() => {
        setStage('no_signature')
      })
  }, [isOpen, sigKey, needsEmployeePicker, isOrgEmpSlot, orgEmpUuid])

  // Portal 56 — when an employee is picked, fetch their signature image for preview.
  useEffect(() => {
    if (!needsEmployeePicker || !selectedEmpId) {
      if (needsEmployeePicker) setSigImage(null)
      return
    }
    api.get(`/org/employees/${selectedEmpId}/signature`)
      .then((r) => setSigImage(r.data?.image_data ?? null))
      .catch(() => setSigImage(null))
  }, [needsEmployeePicker, selectedEmpId])

  async function handleConfirm() {
    setStage('signing')
    setErrorMsg('')
    try {
      const body: Record<string, unknown> = {
        document_type: documentType,
        doc_id:        docId,
        sig_key:       sigKey,
        signed_date:   signedDate || todayIso(),
      }
      // Portal 56 — picker slots need employee_id; Portal 73 UUID slots do not
      // (backend reads the employee UUID directly from the sig_key).
      if (needsEmployeePicker) body.employee_id = selectedEmpId
      await api.post('/viewer/sign/confirm', body)
      setStage('success')
      setTimeout(() => onSigned(sigKey), 1400)
    } catch (e: unknown) {
      const err = e as { response?: { data?: { detail?: string } } }
      setErrorMsg(err.response?.data?.detail ?? 'Failed to sign. Please try again.')
      setStage('preview')
    }
  }

  if (!isOpen) return null

  // Resolve dynamic key labels (COMMITTEE_MEMBER_<id>, ORG_OPENING_*, ORG_CLOSING_*).
  function resolveSigLabel(key: string): string {
    if (SIG_KEY_LABELS[key]) return SIG_KEY_LABELS[key]
    if (key.startsWith('COMMITTEE_MEMBER_')) return 'Committee Member'
    if (key === 'ORG_OPENING_LEAD_AUDITOR') return 'Lead Auditor (Opening Meeting)'
    if (key === 'ORG_CLOSING_LEAD_AUDITOR') return 'Lead Auditor (Closing Meeting)'
    if (key.startsWith('ORG_OPENING_AUDITOR_')) return 'Auditor (Opening Meeting)'
    if (key.startsWith('ORG_CLOSING_AUDITOR_')) return 'Auditor (Closing Meeting)'
    if (key.startsWith('ORG_OPENING_TE_'))     return 'Technical Expert (Opening Meeting)'
    if (key.startsWith('ORG_CLOSING_TE_'))     return 'Technical Expert (Closing Meeting)'
    // Portal 73 — UUID-embedded slots: show employee name if available
    if (isOrgEmpSlot) {
      const phase = orgEmpPhase === 'OPENING' ? 'Opening' : 'Closing'
      return orgEmployee ? `${orgEmployee.full_name} (${phase} Meeting)` : `Organisation Attendee (${phase})`
    }
    if (key.startsWith('ORG_OPENING_'))        return 'Organisation Attendee (Opening)'
    if (key.startsWith('ORG_CLOSING_'))        return 'Organisation Attendee (Closing)'
    return key
  }
  const roleLabel = resolveSigLabel(sigKey)
  const busy      = stage === 'signing'

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/50 p-4">
      <div className="w-full max-w-md overflow-hidden rounded-xl bg-white shadow-2xl">
        {/* Header */}
        <div className="flex items-center justify-between border-b px-6 py-4">
          <div className="flex items-center gap-2.5">
            <PenLine size={17} className="text-[#1A4731]" />
            <h2 className="text-sm font-semibold text-gray-900">Sign as {roleLabel}</h2>
          </div>
          <button type="button" onClick={onClose} disabled={busy}
            className="rounded p-1 text-gray-400 hover:text-gray-600 disabled:opacity-40">
            <X size={17} />
          </button>
        </div>

        {/* Body */}
        <div className="px-6 py-5 space-y-4">

          {stage === 'loading' && (
            <div className="flex items-center justify-center gap-2 py-10 text-sm text-gray-400">
              <Loader2 size={18} className="animate-spin" /> Loading…
            </div>
          )}

          {/* Portal 73 — UUID org-employee slot: no signature on file */}
          {stage === 'no_signature' && isOrgEmpSlot && (
            <>
              <p className="text-sm text-gray-600">
                {orgEmployee
                  ? <><strong>{orgEmployee.full_name}</strong> does not have a saved signature yet.</>
                  : <>This employee is not found in your roster.</>}
                {' '}Go to <strong>Employees</strong> to upload their signature, then try again.
              </p>
              <a href="/client/employees" target="_blank" rel="noreferrer"
                className="block w-full rounded-lg border-2 border-dashed border-[#1A4731] py-3 text-center
                  text-sm font-medium text-[#1A4731] hover:bg-[#1A4731]/5 transition-colors">
                Open Employees →
              </a>
            </>
          )}

          {stage === 'no_signature' && !isOrgEmpSlot && needsEmployeePicker && (
            <>
              <p className="text-sm text-gray-600">
                No employees on file for your organisation. Add at least one employee
                with a signature in <strong>Employees</strong>, then come back here to sign.
              </p>
              <a href="/client/employees" target="_blank" rel="noreferrer"
                className="block w-full rounded-lg border-2 border-dashed border-[#1A4731] py-3 text-center
                  text-sm font-medium text-[#1A4731] hover:bg-[#1A4731]/5 transition-colors">
                Open Employees →
              </a>
              <p className="text-xs text-gray-400 text-center">
                Opens in a new tab. Add an employee + upload a transparent-background PNG signature, then retry.
              </p>
            </>
          )}

          {stage === 'no_signature' && !isOrgEmpSlot && !needsEmployeePicker && (
            <>
              <p className="text-sm text-gray-600">
                You don&apos;t have a saved signature yet. Go to{' '}
                <strong>Settings → My Signature</strong> to draw or upload your signature, then come back.
              </p>
              <a href={getSignatureSettingsUrl()} target="_blank" rel="noreferrer"
                className="block w-full rounded-lg border-2 border-dashed border-[#1A4731] py-3 text-center
                  text-sm font-medium text-[#1A4731] hover:bg-[#1A4731]/5 transition-colors">
                Set up my signature →
              </a>
              <p className="text-xs text-gray-400 text-center">
                Opens in a new tab. Save your signature, then close this dialog and try again.
              </p>
            </>
          )}

          {stage === 'preview' && (
            <>
              {/* Portal 73 — UUID org-employee slot: employee is determined by the key */}
              {isOrgEmpSlot && orgEmployee ? (
                <div className="rounded-lg bg-gray-50 border border-gray-200 px-4 py-3">
                  <p className="text-xs font-medium text-gray-500 uppercase tracking-wide mb-0.5">Signing as</p>
                  <p className="text-sm font-semibold text-gray-900">{orgEmployee.full_name}</p>
                  <p className="text-xs text-gray-500">{orgEmployee.role_title}</p>
                </div>
              ) : needsEmployeePicker ? (
                <>
                  <p className="text-sm text-gray-600">
                    Select which employee from your organisation is signing this document.
                    Their saved signature will be placed on the document.
                  </p>
                  <div>
                    <label className="mb-1 block text-xs font-medium text-gray-600">Signing on behalf of</label>
                    <select
                      value={selectedEmpId}
                      onChange={(e) => setSelectedEmpId(e.target.value)}
                      className="w-full rounded border border-gray-200 px-2 py-2 text-sm text-gray-700 focus:border-[#1A4731] focus:outline-none"
                    >
                      <option value="">— Pick an employee —</option>
                      {employees.map((e) => (
                        <option key={e.id} value={e.id} disabled={!e.has_signature}>
                          {e.full_name} — {e.role_title}{e.has_signature ? '' : '  (no signature)'}
                        </option>
                      ))}
                    </select>
                    {selectedEmp && !selectedEmp.has_signature && (
                      <p className="mt-1 text-xs text-amber-600">
                        {selectedEmp.full_name} has no signature on file. Pick someone else or
                        upload their signature in <a href="/client/employees" className="underline" target="_blank" rel="noreferrer">Employees</a>.
                      </p>
                    )}
                  </div>
                </>
              ) : (
                <p className="text-sm text-gray-600">
                  Your saved signature will be placed on the document. Click{' '}
                  <strong>Sign Document</strong> to proceed.
                </p>
              )}
              <div>
                <label className="mb-1 block text-xs font-medium text-gray-600">Signing date</label>
                <input
                  type="date"
                  value={signedDate}
                  onChange={(e) => setSignedDate(e.target.value)}
                  className="rounded border border-gray-200 px-2 py-1 text-sm text-gray-700 focus:border-[#1A4731] focus:outline-none"
                />
              </div>
              <div className="flex items-center justify-center rounded-lg p-4" style={{
                background: 'repeating-conic-gradient(#e5e7eb 0% 25%, #fff 0% 50%) 0 0 / 12px 12px',
                minHeight: 90,
              }}>
                {sigImage
                  ? <img src={sigImage} alt="Signature preview" className="max-h-20 max-w-full object-contain drop-shadow" />
                  : <span className="text-xs italic text-gray-400">
                      {needsEmployeePicker ? 'Pick an employee to preview their signature' : 'No image preview'}
                    </span>}
              </div>
              {errorMsg && (
                <div className="flex items-start gap-1.5 rounded-lg bg-red-50 p-3 text-sm text-red-600">
                  <AlertCircle size={15} className="mt-0.5 shrink-0" />{errorMsg}
                </div>
              )}
              <button type="button" onClick={handleConfirm}
                disabled={needsEmployeePicker && (!selectedEmp || !selectedEmp.has_signature || !sigImage)}
                className="w-full rounded-lg bg-[#1A4731] py-2.5 text-sm font-medium
                  text-white hover:bg-[#1A4731]/90 active:scale-[0.98] transition-all
                  disabled:opacity-40 disabled:cursor-not-allowed disabled:active:scale-100">
                Sign Document
              </button>
            </>
          )}

          {stage === 'signing' && (
            <div className="flex items-center justify-center gap-2 py-10 text-sm text-gray-500">
              <Loader2 size={18} className="animate-spin text-[#1A4731]" />
              Signing…
            </div>
          )}

          {stage === 'success' && (
            <div className="flex flex-col items-center gap-3 py-8 text-center">
              <CheckCircle2 size={44} className="text-[#1A4731]" />
              <p className="font-semibold text-gray-800">Signed successfully</p>
              <p className="text-sm text-gray-500">Your signature has been recorded on this document.</p>
            </div>
          )}

        </div>
      </div>
    </div>
  )
}
