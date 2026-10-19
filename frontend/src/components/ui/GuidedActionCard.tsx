import Link from 'next/link'
import { AlertCircle, ArrowRight, CheckCircle2, Clock3, Sparkles } from 'lucide-react'

export type GuidedActionTone = 'action' | 'waiting' | 'success' | 'neutral'

interface GuidedActionCardProps {
  eyebrow?: string
  title: string
  description: string
  tone?: GuidedActionTone
  href?: string
  actionLabel?: string
  onAction?: () => void
  secondaryHref?: string
  secondaryLabel?: string
  meta?: string
  compact?: boolean
}

const TONES: Record<GuidedActionTone, {
  shell: string
  accent: string
  eyebrow: string
  icon: typeof Sparkles
}> = {
  action: {
    shell: 'border-certiva-green/20 bg-white',
    accent: 'bg-certiva-green',
    eyebrow: 'text-certiva-green',
    icon: Sparkles,
  },
  waiting: {
    shell: 'border-amber-200 bg-amber-50/55',
    accent: 'bg-amber-500',
    eyebrow: 'text-amber-800',
    icon: Clock3,
  },
  success: {
    shell: 'border-emerald-200 bg-certiva-mist',
    accent: 'bg-certiva-leaf',
    eyebrow: 'text-certiva-green',
    icon: CheckCircle2,
  },
  neutral: {
    shell: 'border-slate-200 bg-white',
    accent: 'bg-slate-400',
    eyebrow: 'text-slate-600',
    icon: AlertCircle,
  },
}

export function GuidedActionCard({
  eyebrow = 'Next action',
  title,
  description,
  tone = 'action',
  href,
  actionLabel,
  onAction,
  secondaryHref,
  secondaryLabel,
  meta,
  compact = false,
}: GuidedActionCardProps) {
  const palette = TONES[tone]
  const Icon = palette.icon

  return (
    <section className={`relative overflow-hidden rounded-2xl border shadow-[0_12px_36px_rgba(6,13,8,0.04)] ${palette.shell}`}>
      <div className={`absolute inset-y-0 left-0 w-1 ${palette.accent}`} />
      <div className={`flex gap-4 ${compact ? 'p-4 pl-5' : 'p-5 pl-6 sm:p-6 sm:pl-7'}`}>
        <div className="mt-0.5 flex h-9 w-9 shrink-0 items-center justify-center rounded-xl bg-certiva-night text-certiva-signal">
          <Icon size={18} aria-hidden="true" />
        </div>
        <div className="min-w-0 flex-1">
          <div className="flex flex-wrap items-center justify-between gap-2">
            <p className={`text-[11px] font-bold uppercase tracking-[0.16em] ${palette.eyebrow}`}>
              {eyebrow}
            </p>
            {meta && <p className="text-xs text-slate-500">{meta}</p>}
          </div>
          <h2 className={`${compact ? 'mt-1 text-base' : 'mt-1.5 text-lg'} font-semibold leading-snug text-certiva-ink`}>
            {title}
          </h2>
          <p className="mt-1 max-w-3xl text-sm leading-6 text-slate-600">{description}</p>
          {((href || onAction) && actionLabel) || (secondaryHref && secondaryLabel) ? (
            <div className="mt-4 flex flex-wrap items-center gap-3">
              {href && actionLabel && (
                <Link href={href} className="certiva-button-primary inline-flex items-center gap-2 px-4 py-2 text-sm font-semibold">
                  {actionLabel}
                  <ArrowRight size={15} aria-hidden="true" />
                </Link>
              )}
              {!href && onAction && actionLabel && (
                <button type="button" onClick={onAction} className="certiva-button-primary inline-flex items-center gap-2 px-4 py-2 text-sm font-semibold">
                  {actionLabel}
                  <ArrowRight size={15} aria-hidden="true" />
                </button>
              )}
              {secondaryHref && secondaryLabel && (
                <Link href={secondaryHref} className="text-sm font-semibold text-certiva-green underline-offset-4 hover:underline">
                  {secondaryLabel}
                </Link>
              )}
            </div>
          ) : null}
        </div>
      </div>
    </section>
  )
}
