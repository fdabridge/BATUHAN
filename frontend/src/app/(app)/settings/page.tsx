'use client'

import axios from 'axios'
import { useEffect, useState } from 'react'
import { Loader2, Save, Settings } from 'lucide-react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import type { BrandingResponse } from '@/types'
import api from '@/lib/api'
import { useAuth } from '@/lib/auth'
import { PlatformPolicy, usePlatformPolicy } from '@/lib/useManualActionDates'

// Use a bare axios instance for /config/branding — endpoint is public, no auth needed.
const baseURL = process.env.NEXT_PUBLIC_API_URL ?? 'http://localhost:8000'

// ── Helpers ───────────────────────────────────────────────────────────────────

function fetchBranding(): Promise<BrandingResponse> {
  return axios.get<BrandingResponse>(`${baseURL}/config/branding`).then((r) => r.data)
}

// ── Sub-components ────────────────────────────────────────────────────────────

function InfoRow({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div className="flex items-start justify-between gap-4 border-b border-gray-100 py-2 last:border-0">
      <span className="text-xs font-medium text-gray-500">{label}</span>
      <span className="text-right text-gray-800" style={{ fontSize: 13 }}>{children}</span>
    </div>
  )
}

function ColorSwatch({ hex }: { hex: string }) {
  return (
    <span className="inline-flex items-center gap-2">
      <span
        className="inline-block h-4 w-4 rounded border border-gray-200"
        style={{ background: hex }}
      />
      <span className="font-mono text-gray-700" style={{ fontSize: 12 }}>{hex}</span>
    </span>
  )
}

// ── Main page ────────────────────────────────────────────────────────────────

export default function SettingsPage() {
  const { user } = useAuth()
  const { data, isLoading, isError } = useQuery<BrandingResponse>({
    queryKey: ['branding'],
    queryFn:  fetchBranding,
  })

  return (
    <div className="mx-auto max-w-[1200px] py-4">
      <h1 className="mb-5 text-gray-800" style={{ fontSize: 22, fontWeight: 500 }}>Settings</h1>

      <div className="mx-auto space-y-6" style={{ maxWidth: 620 }}>
        <div className="flex flex-col items-center text-center">
          <Settings size={48} className="text-certiva-accent" />
          <p className="mt-3 text-gray-800" style={{ fontSize: 18, fontWeight: 500 }}>Settings</p>
          <p className="mt-2 text-gray-500" style={{ fontSize: 13 }}>
            Review branding and control verification and real-time action-date policies.
          </p>
        </div>

        <div className="mt-6 rounded-lg bg-certiva-surface p-4">
          {isLoading && (
            <p className="text-center text-gray-400" style={{ fontSize: 13 }}>Loading configuration…</p>
          )}
          {isError && (
            <p className="text-center text-red-500" style={{ fontSize: 13 }}>Failed to load configuration.</p>
          )}
          {data && (
            <div className="space-y-0">
              <InfoRow label="CB name">{data.cb_name || '—'}</InfoRow>
              <InfoRow label="Short name">{data.cb_short_name || '—'}</InfoRow>
              <InfoRow label="Primary color">
                {data.cb_primary_color
                  ? <ColorSwatch hex={data.cb_primary_color} />
                  : '—'}
              </InfoRow>
              <InfoRow label="Website">
                {data.cb_website
                  ? <a href={data.cb_website} target="_blank" rel="noreferrer"
                       className="text-certiva-primary hover:underline">{data.cb_website}</a>
                  : '—'}
              </InfoRow>
              <InfoRow label="Email">
                {data.cb_email
                  ? <a href={`mailto:${data.cb_email}`} className="text-certiva-primary hover:underline">{data.cb_email}</a>
                  : '—'}
              </InfoRow>
              <InfoRow label="Accreditation bodies">
                {data.accreditation_bodies && data.accreditation_bodies.length > 0
                  ? data.accreditation_bodies.join(', ')
                  : '—'}
              </InfoRow>
              <InfoRow label="Supported standards">
                {data.supported_standards && data.supported_standards.length > 0
                  ? data.supported_standards.join(', ')
                  : '—'}
              </InfoRow>
            </div>
          )}
        </div>
        {user?.role === 'admin' && <PolicySettings />}
      </div>
    </div>
  )
}

const policyRows: { key: keyof PlatformPolicy; title: string; description: string }[] = [
  {
    key: 'client_email_verification',
    title: 'Client email verification',
    description: 'Require future client accounts to verify their email before accessing client portal records.',
  },
  {
    key: 'employee_signature_email_verification',
    title: 'Employee signature email verification',
    description: 'Require an emailed code before a new or updated organisation-employee signature becomes active.',
  },
  {
    key: 'retroactive_signing_dates',
    title: 'Manual action dates',
    description: 'Allow users to choose release, upload, signature, and workflow-action dates. Turn off to enforce server time.',
  },
]

function PolicySettings() {
  const queryClient = useQueryClient()
  const policy = usePlatformPolicy()
  const [draft, setDraft] = useState<PlatformPolicy | null>(null)

  useEffect(() => {
    if (policy.data) setDraft(policy.data)
  }, [policy.data])

  const save = useMutation({
    mutationFn: (values: PlatformPolicy) => api.put<PlatformPolicy>('/config/policy', values).then((r) => r.data),
    onSuccess: (values) => {
      setDraft(values)
      queryClient.setQueryData(['platform-policy'], values)
    },
  })

  return (
    <section className="rounded-lg border border-gray-100 bg-white p-5">
      <div className="mb-4">
        <h2 className="text-sm font-semibold text-gray-800">Runtime policy</h2>
        <p className="mt-1 text-xs leading-5 text-gray-500">
          Changes apply immediately to future actions. Turning off manual action dates forces document releases,
          uploads, signatures, and workflow transitions to use server time. Planning dates stay editable.
        </p>
      </div>
      {policy.isLoading || !draft ? (
        <Loader2 size={18} className="mx-auto animate-spin text-gray-400" />
      ) : (
        <div className="space-y-4">
          {policyRows.map((row) => (
            <label key={row.key} className="flex cursor-pointer items-start justify-between gap-5 rounded-lg bg-gray-50 p-3">
              <span>
                <span className="block text-sm font-medium text-gray-800">{row.title}</span>
                <span className="mt-0.5 block text-xs leading-5 text-gray-500">{row.description}</span>
              </span>
              <input
                type="checkbox"
                checked={draft[row.key]}
                onChange={(event) => setDraft({ ...draft, [row.key]: event.target.checked })}
                className="mt-1 h-4 w-4 accent-[#1A4731]"
              />
            </label>
          ))}
          {save.isError && <p className="text-xs text-red-600">Policy settings could not be saved.</p>}
          {save.isSuccess && <p className="text-xs text-emerald-700">Policy settings saved.</p>}
          <button
            onClick={() => save.mutate(draft)}
            disabled={save.isPending}
            className="flex items-center gap-2 rounded-lg bg-[#1A4731] px-4 py-2 text-sm font-medium text-white disabled:opacity-60"
          >
            {save.isPending ? <Loader2 size={14} className="animate-spin" /> : <Save size={14} />}
            Save policy
          </button>
        </div>
      )}
    </section>
  )
}
