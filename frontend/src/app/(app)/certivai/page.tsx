'use client'

import Link from 'next/link'
import { ArrowRight, ClipboardCheck, FileSearch, ScanLine, Sparkles } from 'lucide-react'

const MODULES = [
  {
    title: 'Audit Plan Generator',
    description: 'Create a validated FR.223 schedule from controlled day windows and the authoritative FR.222 clause map.',
    href: '/certivai/audit-plan',
    icon: ClipboardCheck,
    step: 'Plan',
  },
  {
    title: 'Report Generation',
    description: 'Build a report draft from the exact audit cycle, controlled template, integrated standards, and uploaded evidence.',
    href: '/certivai/reports',
    icon: ScanLine,
    step: 'Draft',
  },
  {
    title: 'Report Review',
    description: 'Assess a completed report against accreditation profiles, evidence requirements, and standard-specific gaps.',
    href: '/certivai/review',
    icon: FileSearch,
    step: 'Review',
  },
]

export default function CertivAIPage() {
  return (
    <div className="min-h-[calc(100vh-52px)] bg-certiva-mist text-certiva-ink">
      <div className="mx-auto max-w-[1240px] px-4 py-7 sm:px-6 lg:py-10">
        <header className="overflow-hidden rounded-2xl bg-certiva-night text-white shadow-sm">
          <div className="grid gap-8 px-6 py-8 sm:px-8 lg:grid-cols-[1fr_360px] lg:items-end">
            <div>
              <span className="inline-flex items-center gap-2 rounded-full border border-certiva-signal/25 bg-certiva-signal/10 px-3 py-1 text-xs font-semibold text-certiva-signal"><Sparkles size={14} /> Controlled AI workspace</span>
              <h1 className="mt-5 text-4xl font-semibold tracking-tight sm:text-5xl">Certiv.AI</h1>
              <p className="mt-4 max-w-2xl text-base leading-7 text-white/65">One clear workspace for planning, report drafting, and review—using explicit inputs, protected background jobs, and visible validation.</p>
            </div>
            <div className="rounded-2xl border border-white/10 bg-white/[0.05] p-4">
              <p className="text-[11px] font-bold uppercase tracking-[0.16em] text-certiva-signal">How work moves</p>
              <div className="mt-3 flex items-center gap-2 text-sm font-semibold text-white"><span>Plan</span><ArrowRight size={14} className="text-white/35" /><span>Draft</span><ArrowRight size={14} className="text-white/35" /><span>Review</span></div>
              <p className="mt-2 text-xs leading-5 text-white/50">Each tool keeps its source documents and validation rules visible before generation begins.</p>
            </div>
          </div>
        </header>

        <section className="mt-6 grid gap-4 lg:grid-cols-3">
          {MODULES.map((module, index) => {
            const Icon = module.icon
            return (
              <Link key={module.title} href={module.href} className="group flex min-h-72 flex-col justify-between rounded-2xl border border-emerald-950/10 bg-white p-5 shadow-sm transition hover:-translate-y-0.5 hover:border-certiva-leaf/40 hover:shadow-md">
                <div>
                  <div className="flex items-start justify-between">
                    <span className="flex h-11 w-11 items-center justify-center rounded-xl bg-certiva-mist text-certiva-green"><Icon size={22} /></span>
                    <span className="rounded-full bg-slate-100 px-2.5 py-1 text-[11px] font-bold uppercase tracking-wider text-slate-500">0{index + 1} · {module.step}</span>
                  </div>
                  <h2 className="mt-6 text-xl font-semibold text-slate-900">{module.title}</h2>
                  <p className="mt-3 text-sm leading-6 text-slate-600">{module.description}</p>
                </div>
                <span className="mt-8 inline-flex items-center gap-2 text-sm font-semibold text-certiva-mid">Open tool <ArrowRight size={16} className="transition group-hover:translate-x-1" /></span>
              </Link>
            )
          })}
        </section>
      </div>
    </div>
  )
}
