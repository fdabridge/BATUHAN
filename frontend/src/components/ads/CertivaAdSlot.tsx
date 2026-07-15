'use client'

import { useEffect, useMemo, useState } from 'react'

type Placement = 'apply_top' | 'apply_sidebar' | 'client_overview'

interface CertivaAd {
  id: string
  placement: Placement
  active: boolean
  label?: string
  title: string
  body: string
  cta?: string
  href?: string
  tone?: 'emerald' | 'gold' | 'slate'
}

interface AdConfig {
  ads?: CertivaAd[]
}

const toneClass: Record<NonNullable<CertivaAd['tone']>, string> = {
  emerald: 'border-emerald-200 bg-emerald-50/95 text-emerald-950',
  gold:    'border-amber-200 bg-amber-50/95 text-amber-950',
  slate:   'border-slate-200 bg-white/95 text-slate-900',
}

export function CertivaAdSlot({ placement, className = '' }: { placement: Placement; className?: string }) {
  const [ads, setAds] = useState<CertivaAd[]>([])

  useEffect(() => {
    let alive = true

    fetch('/certiva-ads.json', { cache: 'no-store' })
      .then((res) => (res.ok ? res.json() : null))
      .then((config: AdConfig | null) => {
        if (alive) setAds(Array.isArray(config?.ads) ? config.ads : [])
      })
      .catch(() => {
        if (alive) setAds([])
      })

    return () => {
      alive = false
    }
  }, [])

  const ad = useMemo(
    () => ads.find((item) => item.active && item.placement === placement),
    [ads, placement],
  )

  if (!ad) return null

  const content = (
    <div className={`rounded-xl border p-4 shadow-sm ${toneClass[ad.tone ?? 'emerald']} ${className}`}>
      {ad.label && (
        <p className="mb-1 text-[11px] font-semibold uppercase tracking-[0.18em] opacity-65">
          {ad.label}
        </p>
      )}
      <p className="text-sm font-semibold leading-5">{ad.title}</p>
      <p className="mt-1 text-xs leading-5 opacity-75">{ad.body}</p>
      {ad.href && ad.cta && (
        <span className="mt-3 inline-flex text-xs font-semibold underline underline-offset-4">
          {ad.cta}
        </span>
      )}
    </div>
  )

  if (ad.href && ad.cta) {
    return (
      <a href={ad.href} target="_blank" rel="noreferrer" className="block">
        {content}
      </a>
    )
  }

  return content
}
