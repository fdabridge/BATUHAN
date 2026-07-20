'use client'

import Link from 'next/link'
import { ArrowLeft, ArrowRight, FileText, History, Layers3, Plus, ScanLine, ShieldCheck } from 'lucide-react'

export default function CertivAIReportsPage() {
  return (
    <div className="min-h-[calc(100vh-52px)] bg-[#07130E] px-6 py-6 text-white">
      <div className="mx-auto max-w-[1120px]">
        <Link href="/certivai" className="mb-6 inline-flex items-center gap-2 text-sm text-emerald-200 hover:text-white">
          <ArrowLeft size={16} />
          Certiv.AI
        </Link>

        <section className="border border-cyan-200/20 bg-white/[0.045] p-6" style={{ borderRadius: 8 }}>
          <div className="flex flex-col justify-between gap-6 md:flex-row md:items-center">
            <div className="flex items-center gap-4">
              <span className="flex h-14 w-14 items-center justify-center rounded bg-cyan-300/15 text-cyan-200">
                <ScanLine size={28} />
              </span>
              <div>
                <h1 className="text-3xl font-semibold">Report Generation</h1>
                <p className="mt-2 max-w-2xl text-sm leading-6 text-slate-300">
                  Generate audit reports with integrated standards, surveillance cycles, recertification context, and accreditation-aware review logic.
                </p>
              </div>
            </div>
            <Link
              href="/reports/new"
              className="inline-flex items-center justify-center gap-2 rounded bg-cyan-400 px-4 py-3 text-sm font-semibold text-slate-950 hover:bg-cyan-300"
            >
              <Plus size={16} />
              New report
            </Link>
          </div>
        </section>

        <section className="mt-5 grid gap-4 md:grid-cols-3">
          <Link
            href="/reports/new"
            className="group border border-white/10 bg-white/[0.045] p-5 transition hover:-translate-y-1 hover:border-cyan-200/40 hover:bg-white/[0.07]"
            style={{ borderRadius: 8 }}
          >
            <FileText className="mb-5 text-cyan-200" size={28} />
            <h2 className="text-xl font-semibold">Integrated Draft</h2>
            <p className="mt-3 text-sm leading-6 text-slate-300">
              Select one or more standards, choose Stage 1, Stage 2, Surveillance 1/2, or Recertification, then submit evidence and a template.
            </p>
            <span className="mt-8 inline-flex items-center gap-2 text-sm font-semibold text-cyan-200">
              Start <ArrowRight className="transition group-hover:translate-x-1" size={16} />
            </span>
          </Link>

          <div
            className="border border-white/10 bg-white/[0.045] p-5"
            style={{ borderRadius: 8 }}
          >
            <Layers3 className="mb-5 text-violet-200" size={28} />
            <h2 className="text-xl font-semibold">Context Matrix</h2>
            <p className="mt-3 text-sm leading-6 text-slate-300">
              The job setup now carries the audit cycle into the backend prompt so surveillance and recertification outputs are not written like initial audits.
            </p>
            <div className="mt-7 flex flex-wrap gap-2 text-xs text-slate-200">
              {['Stage 1', 'Stage 2', 'Surv 1', 'Surv 2', 'Recert'].map((label) => (
                <span key={label} className="rounded border border-white/10 bg-white/10 px-2 py-1">{label}</span>
              ))}
            </div>
          </div>

          <Link
            href="/reports"
            className="group border border-white/10 bg-white/[0.045] p-5 transition hover:-translate-y-1 hover:border-emerald-200/40 hover:bg-white/[0.07]"
            style={{ borderRadius: 8 }}
          >
            <History className="mb-5 text-emerald-200" size={28} />
            <h2 className="text-xl font-semibold">Report Jobs</h2>
            <p className="mt-3 text-sm leading-6 text-slate-300">
              Track completed, failed, and in-progress report generation jobs.
            </p>
            <span className="mt-8 inline-flex items-center gap-2 text-sm font-semibold text-emerald-200">
              Open history <ArrowRight className="transition group-hover:translate-x-1" size={16} />
            </span>
          </Link>
        </section>

        <section className="mt-4 border border-emerald-200/20 bg-emerald-300/[0.07] p-5" style={{ borderRadius: 8 }}>
          <div className="flex items-start gap-3">
            <ShieldCheck size={20} className="mt-0.5 text-emerald-200" />
            <p className="text-sm leading-6 text-emerald-50">
              Use the new setup page for every report job. The old single-standard Stage 1/Stage 2 assumptions are no longer enough for integrated, surveillance, and recertification work.
            </p>
          </div>
        </section>
      </div>
    </div>
  )
}
