'use client'

import axios from 'axios'
import { Settings } from 'lucide-react'
import { useQuery } from '@tanstack/react-query'
import type { BrandingResponse } from '@/types'

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
  const { data, isLoading, isError } = useQuery<BrandingResponse>({
    queryKey: ['branding'],
    queryFn:  fetchBranding,
  })

  return (
    <div className="mx-auto max-w-[1200px] py-4">
      <h1 className="mb-5 text-gray-800" style={{ fontSize: 22, fontWeight: 500 }}>Settings</h1>

      <div className="mx-auto" style={{ maxWidth: 480 }}>
        <div className="flex flex-col items-center text-center">
          <Settings size={48} className="text-certiva-accent" />
          <p className="mt-3 text-gray-800" style={{ fontSize: 18, fontWeight: 500 }}>Settings</p>
          <p className="mt-2 text-gray-500" style={{ fontSize: 13 }}>
            Platform configuration is managed through environment variables on the server.
            Contact your administrator to update branding, supported standards, or accreditation bodies.
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
      </div>
    </div>
  )
}
