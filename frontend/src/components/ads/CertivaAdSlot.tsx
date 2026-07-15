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
  image?: string
  tone?: 'emerald' | 'gold' | 'slate'
}

interface AdConfig {
  ads?: CertivaAd[]
}

const toneClass: Record<NonNullable<CertivaAd['tone']>, string> = {
  emerald: 'border-emerald-200 bg-emerald-50/95 text-emerald-950 from-emerald-50 to-white',
  gold:    'border-amber-200 bg-amber-50/95 text-amber-950 from-amber-50 to-white',
  slate:   'border-slate-200 bg-white/95 text-slate-900 from-slate-50 to-white',
}

export function CertivaAdSlot({ placement, className = '' }: { placement: Placement; className?: string }) {
  const [ads, setAds] = useState<CertivaAd[]>([])
  const [index, setIndex] = useState(0)

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

  const activeAds = useMemo(
    () => ads.filter((item) => item.active && item.placement === placement),
    [ads, placement],
  )

  useEffect(() => {
    setIndex(0)
  }, [placement, activeAds.length])

  useEffect(() => {
    if (activeAds.length < 2) return

    const timer = window.setInterval(() => {
      setIndex((current) => (current + 1) % activeAds.length)
    }, 7000)

    return () => window.clearInterval(timer)
  }, [activeAds.length])

  const ad = activeAds[index % Math.max(activeAds.length, 1)]

  if (!ad) return null

  const content = (
    <div
      className={`group relative overflow-hidden rounded-xl border bg-gradient-to-br p-4 shadow-sm transition duration-300 hover:-translate-y-0.5 hover:shadow-md ${toneClass[ad.tone ?? 'emerald']} ${className}`}
    >
      <div className="absolute -right-8 -top-8 h-24 w-24 rounded-full bg-white/40 blur-2xl" />
      <div className="relative flex gap-3">
        {ad.image && (
          <div className="flex h-12 w-16 shrink-0 items-center justify-center rounded-lg border border-white/70 bg-white p-1.5 shadow-sm">
            <img src={ad.image} alt="" className="max-h-full max-w-full object-contain" />
          </div>
        )}
        <div className="min-w-0 flex-1">
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
      </div>
      {activeAds.length > 1 && (
        <div className="relative mt-3 flex gap-1.5">
          {activeAds.map((item, itemIndex) => (
            <span
              key={item.id}
              className={`h-1 flex-1 rounded-full transition ${
                itemIndex === index % activeAds.length ? 'bg-current opacity-50' : 'bg-current opacity-15'
              }`}
            />
          ))}
        </div>
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
