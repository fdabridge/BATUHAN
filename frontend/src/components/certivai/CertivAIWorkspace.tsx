'use client'

import type { ReactNode } from 'react'
import Link from 'next/link'
import {
  AlertCircle,
  ArrowLeft,
  Check,
  FileUp,
  Loader2,
  X,
} from 'lucide-react'

export function CertivAIToolShell({ children }: { children: ReactNode }) {
  return (
    <div className="min-h-[calc(100vh-52px)] bg-certiva-mist text-certiva-ink">
      <div className="mx-auto max-w-[1240px] px-4 py-6 sm:px-6 lg:py-8">
        <Link
          href="/certivai"
          className="mb-5 inline-flex items-center gap-2 text-sm font-semibold text-certiva-mid hover:text-certiva-green"
        >
          <ArrowLeft size={16} />
          Certiv.AI workspace
        </Link>
        {children}
      </div>
    </div>
  )
}

export function CertivAIToolHeader({
  eyebrow,
  title,
  description,
  icon,
  aside,
}: {
  eyebrow: string
  title: string
  description: string
  icon: ReactNode
  aside?: ReactNode
}) {
  return (
    <header className="overflow-hidden rounded-2xl border border-emerald-950/10 bg-certiva-night text-white shadow-sm">
      <div className="grid gap-6 px-5 py-6 sm:px-7 lg:grid-cols-[1fr_auto] lg:items-end">
        <div className="flex items-start gap-4">
          <span className="flex h-11 w-11 shrink-0 items-center justify-center rounded-xl bg-certiva-signal/15 text-certiva-signal ring-1 ring-certiva-signal/20">
            {icon}
          </span>
          <div>
            <p className="text-[11px] font-bold uppercase tracking-[0.18em] text-certiva-signal">{eyebrow}</p>
            <h1 className="mt-1 text-2xl font-semibold tracking-tight sm:text-3xl">{title}</h1>
            <p className="mt-2 max-w-3xl text-sm leading-6 text-white/65">{description}</p>
          </div>
        </div>
        {aside && <div className="rounded-xl border border-white/10 bg-white/[0.05] p-3">{aside}</div>}
      </div>
    </header>
  )
}

export function CertivAIStepBar({
  steps,
  current,
}: {
  steps: string[]
  current: number
}) {
  return (
    <div className="mt-4 grid gap-2 rounded-2xl border border-emerald-950/10 bg-white p-3 shadow-sm sm:grid-cols-3">
      {steps.map((step, index) => {
        const complete = index < current
        const active = index === current
        return (
          <div
            key={step}
            className={[
              'flex items-center gap-3 rounded-xl px-3 py-2.5 text-sm',
              active ? 'bg-certiva-mist font-semibold text-certiva-green' : 'text-slate-500',
            ].join(' ')}
          >
            <span className={[
              'flex h-7 w-7 shrink-0 items-center justify-center rounded-full border text-xs font-bold',
              complete
                ? 'border-certiva-green bg-certiva-green text-white'
                : active
                  ? 'border-certiva-green text-certiva-green'
                  : 'border-slate-200 text-slate-400',
            ].join(' ')}>
              {complete ? <Check size={14} /> : index + 1}
            </span>
            {step}
          </div>
        )
      })}
    </div>
  )
}

export function CertivAISection({
  title,
  description,
  children,
  action,
}: {
  title: string
  description?: string
  children: ReactNode
  action?: ReactNode
}) {
  return (
    <section className="rounded-2xl border border-emerald-950/10 bg-white p-5 shadow-sm sm:p-6">
      <div className="mb-5 flex items-start justify-between gap-4">
        <div>
          <h2 className="text-base font-semibold text-slate-900">{title}</h2>
          {description && <p className="mt-1 text-sm leading-5 text-slate-500">{description}</p>}
        </div>
        {action}
      </div>
      {children}
    </section>
  )
}

export function CertivAIFileDrop({
  id,
  title,
  description,
  accept,
  files,
  multiple = false,
  onAdd,
  onRemove,
}: {
  id: string
  title: string
  description: string
  accept: string
  files: File[]
  multiple?: boolean
  onAdd: (files: File[]) => void
  onRemove: (index: number) => void
}) {
  return (
    <div>
      <label
        htmlFor={id}
        className="flex min-h-36 cursor-pointer flex-col items-center justify-center rounded-xl border border-dashed border-certiva-leaf/35 bg-certiva-mist/60 px-5 py-6 text-center transition hover:border-certiva-leaf hover:bg-certiva-mist"
      >
        <span className="mb-3 flex h-10 w-10 items-center justify-center rounded-xl bg-white text-certiva-green shadow-sm ring-1 ring-emerald-950/10">
          <FileUp size={19} />
        </span>
        <span className="text-sm font-semibold text-slate-900">{title}</span>
        <span className="mt-1 max-w-md text-xs leading-5 text-slate-500">{description}</span>
        <input
          id={id}
          type="file"
          accept={accept}
          multiple={multiple}
          className="hidden"
          onChange={(event) => {
            const selected = Array.from(event.target.files ?? [])
            if (selected.length) onAdd(selected)
            event.target.value = ''
          }}
        />
      </label>
      {files.length > 0 && (
        <ul className="mt-3 space-y-2">
          {files.map((file, index) => (
            <li key={`${file.name}-${file.size}-${index}`} className="flex items-center gap-3 rounded-xl border border-slate-200 bg-white px-3 py-2.5 text-sm">
              <Check size={15} className="shrink-0 text-certiva-mid" />
              <span className="min-w-0 flex-1 truncate text-slate-700">{file.name}</span>
              <span className="shrink-0 text-xs text-slate-400">{formatBytes(file.size)}</span>
              <button
                type="button"
                onClick={() => onRemove(index)}
                className="rounded-lg p-1 text-slate-400 hover:bg-red-50 hover:text-red-600"
                aria-label={`Remove ${file.name}`}
              >
                <X size={14} />
              </button>
            </li>
          ))}
        </ul>
      )}
    </div>
  )
}

export function CertivAINotice({
  tone,
  children,
}: {
  tone: 'error' | 'success' | 'info'
  children: ReactNode
}) {
  const styles = {
    error: 'border-red-200 bg-red-50 text-red-800',
    success: 'border-emerald-200 bg-emerald-50 text-emerald-900',
    info: 'border-sky-200 bg-sky-50 text-sky-900',
  }[tone]
  return (
    <div className={`flex items-start gap-3 rounded-xl border px-4 py-3 text-sm leading-5 ${styles}`}>
      {tone === 'error' ? <AlertCircle size={18} className="mt-0.5 shrink-0" /> : tone === 'success' ? <Check size={18} className="mt-0.5 shrink-0" /> : <Loader2 size={18} className="mt-0.5 shrink-0" />}
      <div>{children}</div>
    </div>
  )
}

function formatBytes(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`
  if (bytes < 1024 * 1024) return `${Math.round(bytes / 1024)} KB`
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`
}
