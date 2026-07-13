'use client'

import Link from 'next/link'
import { ArrowRight, ClipboardCheck, FileSearch, ScanLine, Sparkles } from 'lucide-react'

const MODULES = [
  {
    title: 'Audit Plan Generator',
    description: 'Build FR.223 day maps from a template, scope details, standards, categories, and exact audit windows.',
    href: '/certivai/audit-plan',
    icon: ClipboardCheck,
    accent: '#22C55E',
    status: 'Live',
  },
  {
    title: 'Report Generation',
    description: 'Generate audit report drafts from uploaded evidence, findings, and certification context.',
    href: '/certivai/reports',
    icon: ScanLine,
    accent: '#38BDF8',
    status: 'Live',
  },
  {
    title: 'Report Review',
    description: 'AI-assisted review for consistency, missing clauses, evidence gaps, and document quality.',
    href: '/certivai/review',
    icon: FileSearch,
    accent: '#F59E0B',
    status: 'Next',
  },
]

export default function CertivAIPage() {
  return (
    <div className="min-h-[calc(100vh-52px)] bg-[#07130E] text-white">
      <div
        className="mx-auto max-w-[1280px] px-6 py-8"
        style={{
          backgroundImage:
            'linear-gradient(rgba(255,255,255,0.055) 1px, transparent 1px), linear-gradient(90deg, rgba(255,255,255,0.055) 1px, transparent 1px)',
          backgroundSize: '36px 36px',
        }}
      >
        <div className="flex flex-col gap-8">
          <section className="grid gap-6 lg:grid-cols-[1.2fr_0.8fr]">
            <div className="space-y-5 py-5">
              <div className="inline-flex items-center gap-2 rounded px-3 py-1 text-xs font-semibold text-emerald-100 ring-1 ring-emerald-400/40">
                <Sparkles size={14} />
                Certiv.AI operating layer
              </div>
              <div>
                <h1 className="text-5xl font-semibold leading-tight text-white">
                  Certiv.AI
                </h1>
                <p className="mt-4 max-w-2xl text-base leading-7 text-slate-300">
                  Audit intelligence tools for planning, report drafting, and document review.
                </p>
              </div>
            </div>

            <div className="border border-white/10 bg-white/[0.04] p-5 shadow-2xl shadow-black/20" style={{ borderRadius: 8 }}>
              <div className="mb-5 flex items-center justify-between">
                <span className="text-sm font-medium text-slate-300">System modules</span>
                <span className="rounded bg-emerald-400/15 px-2 py-1 text-xs font-semibold text-emerald-200">
                  2 active
                </span>
              </div>
              <div className="space-y-3">
                {MODULES.map((module, index) => (
                  <div key={module.title} className="flex items-center gap-3 border border-white/10 bg-black/20 px-3 py-3" style={{ borderRadius: 8 }}>
                    <span className="flex h-8 w-8 items-center justify-center rounded bg-white/5 text-sm font-semibold text-slate-200">
                      0{index + 1}
                    </span>
                    <div className="min-w-0 flex-1">
                      <p className="truncate text-sm font-semibold text-white">{module.title}</p>
                      <p className="text-xs text-slate-400">{module.status}</p>
                    </div>
                    <span className="h-2 w-2 rounded-full" style={{ background: module.accent }} />
                  </div>
                ))}
              </div>
            </div>
          </section>

          <section className="grid gap-4 lg:grid-cols-3">
            {MODULES.map((module) => {
              const Icon = module.icon
              const isDisabled = module.status === 'Next'
              const content = (
                <div
                  className={[
                    'group flex min-h-[260px] flex-col justify-between border border-white/10 bg-white/[0.045] p-5 transition',
                    isDisabled ? 'opacity-75' : 'hover:-translate-y-1 hover:border-white/25 hover:bg-white/[0.07]',
                  ].join(' ')}
                  style={{ borderRadius: 8 }}
                >
                  <div className="space-y-5">
                    <div className="flex items-start justify-between">
                      <span
                        className="flex h-12 w-12 items-center justify-center rounded ring-1 ring-white/10"
                        style={{ color: module.accent, background: `${module.accent}18` }}
                      >
                        <Icon size={24} />
                      </span>
                      <span className="rounded px-2 py-1 text-xs font-semibold" style={{ color: module.accent, background: `${module.accent}1F` }}>
                        {module.status}
                      </span>
                    </div>
                    <div>
                      <h2 className="text-xl font-semibold text-white">{module.title}</h2>
                      <p className="mt-3 text-sm leading-6 text-slate-300">{module.description}</p>
                    </div>
                  </div>
                  <div className="mt-8 flex items-center justify-between text-sm font-semibold" style={{ color: module.accent }}>
                    <span>{isDisabled ? 'Reserved' : 'Open module'}</span>
                    {!isDisabled && <ArrowRight className="transition group-hover:translate-x-1" size={18} />}
                  </div>
                </div>
              )

              return isDisabled ? (
                <div key={module.title}>{content}</div>
              ) : (
                <Link key={module.title} href={module.href}>
                  {content}
                </Link>
              )
            })}
          </section>
        </div>
      </div>
    </div>
  )
}
