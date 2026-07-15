'use client'

import { useEffect, useMemo, useState } from 'react'

type Placement = 'apply_top' | 'apply_sidebar' | 'client_overview'

interface CertivaAd {
  id: string
  placement: Placement
  active: boolean
  format?: 'compact' | 'vertical' | 'horizontal' | 'wide'
  visualTheme?: 'usa' | 'cosmetics' | 'marine'
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

function ServiceVisual({ theme, image, format }: { theme?: CertivaAd['visualTheme']; image?: string; format: NonNullable<CertivaAd['format']> }) {
  const isWide = format === 'wide' || format === 'horizontal'

  return (
    <div className={`relative overflow-hidden rounded-2xl border border-white/70 bg-white shadow-sm ${isWide ? 'h-32 w-40 shrink-0' : 'h-40 w-full'}`}>
      {theme === 'usa' && (
        <div className="absolute inset-0 bg-[linear-gradient(180deg,#ffffff_0_14%,#f1f5f9_14%_28%,#ffffff_28%_42%,#f1f5f9_42%_56%,#ffffff_56%_70%,#f1f5f9_70%_84%,#ffffff_84%)]">
          <div className="absolute left-0 top-0 h-20 w-24 bg-[#0b3b62]" />
          <div className="absolute left-4 top-4 grid grid-cols-3 gap-1">
            {Array.from({ length: 9 }).map((_, i) => (
              <span key={i} className="h-1 w-1 rounded-full bg-white/90" />
            ))}
          </div>
          <div className="absolute bottom-4 left-4 rounded-full border border-[#0b3b62]/20 bg-white/85 px-3 py-1 text-[10px] font-semibold uppercase tracking-[0.16em] text-[#0b3b62]">
            U.S. market
          </div>
        </div>
      )}
      {theme === 'cosmetics' && (
        <div className="absolute inset-0 bg-[radial-gradient(circle_at_80%_18%,rgba(214,174,74,.35),transparent_28%),linear-gradient(135deg,#eff6ff,#ffffff_50%,#fff7ed)]">
          <div className="absolute left-5 top-5 h-20 w-8 rounded-full border border-blue-200 bg-white shadow-sm" />
          <div className="absolute left-14 top-8 h-16 w-9 rounded-b-2xl rounded-t-md border border-amber-200 bg-amber-100/80 shadow-sm" />
          <div className="absolute bottom-5 right-5 flex h-16 w-16 items-center justify-center rounded-full border border-blue-200 bg-blue-700 text-[10px] font-semibold text-white shadow-sm">
            EU
          </div>
        </div>
      )}
      {theme === 'marine' && (
        <div className="absolute inset-0 bg-[linear-gradient(180deg,#eff6ff,#ffffff_46%,#dbeafe)]">
          <div className="absolute bottom-8 left-4 right-4 h-8 rounded-[50%] border-b-4 border-blue-500/45" />
          <div className="absolute bottom-14 left-10 h-0 w-0 border-b-[34px] border-l-[20px] border-r-[20px] border-b-slate-700 border-l-transparent border-r-transparent" />
          <div className="absolute bottom-11 left-7 h-4 w-24 rounded-b-full bg-[#0b3b62]" />
          <div className="absolute right-5 top-5 rounded-full border border-blue-200 bg-white/80 px-3 py-1 text-[10px] font-semibold uppercase tracking-[0.14em] text-blue-900">
            Marine
          </div>
        </div>
      )}
      {image && (
        <div className="absolute right-3 top-3 flex h-10 w-14 items-center justify-center rounded-lg border border-white/70 bg-white/90 p-1 shadow-sm">
          <img src={image} alt="" className="max-h-full max-w-full object-contain" />
        </div>
      )}
    </div>
  )
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

  const format = ad.format ?? 'compact'
  const isVertical = format === 'vertical'
  const isWide = format === 'wide'
  const isHorizontal = format === 'horizontal' || isWide
  const ctaClass = ad.tone === 'gold'
    ? 'bg-amber-500 text-white'
    : ad.tone === 'slate'
      ? 'bg-slate-900 text-white'
      : 'bg-emerald-800 text-white'

  const content = (
    <div
      className={`group relative overflow-hidden border bg-gradient-to-br shadow-sm transition duration-300 hover:-translate-y-0.5 hover:shadow-md ${
        isWide ? 'rounded-2xl p-5 md:p-6' : 'rounded-xl p-4'
      } ${toneClass[ad.tone ?? 'emerald']} ${className}`}
    >
      <div className="absolute -right-8 -top-8 h-28 w-28 rounded-full bg-white/45 blur-2xl" />
      <div className="absolute right-3 top-3 text-[10px] font-semibold uppercase tracking-[0.16em] opacity-45">
        AD
      </div>
      <div className={`relative ${isHorizontal ? 'flex items-center gap-5' : 'space-y-4'}`}>
        {(ad.visualTheme || ad.image) && (
          <ServiceVisual theme={ad.visualTheme} image={ad.image} format={format} />
        )}
        <div className={`min-w-0 flex-1 ${isVertical ? 'pt-1' : ''}`}>
          {ad.label && (
            <p className="mb-1 text-[11px] font-semibold uppercase tracking-[0.18em] opacity-65">
              {ad.label}
            </p>
          )}
          <p className={`${isWide ? 'text-2xl md:text-3xl' : isVertical ? 'text-2xl' : 'text-base'} font-semibold leading-tight`}>
            {ad.title}
          </p>
          <p className={`${isWide ? 'mt-2 max-w-xl text-sm' : 'mt-2 text-xs'} leading-5 opacity-75`}>
            {ad.body}
          </p>
          {ad.href && ad.cta && (
            <span className={`mt-4 inline-flex rounded-lg px-4 py-2 text-xs font-semibold shadow-sm ${ctaClass}`}>
              {ad.cta}
            </span>
          )}
        </div>
      </div>
      {activeAds.length > 1 && (
        <div className="relative mt-4 flex gap-1.5">
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
