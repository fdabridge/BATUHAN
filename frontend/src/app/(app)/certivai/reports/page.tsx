'use client'

import Link from 'next/link'
import { ArrowLeft, ArrowRight, FileText, History, Plus, ScanLine } from 'lucide-react'

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
                  Convert audit evidence into structured report drafts with the existing AI report pipeline.
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

        <section className="mt-5 grid gap-4 md:grid-cols-2">
          <Link
            href="/reports/new"
            className="group border border-white/10 bg-white/[0.045] p-5 transition hover:-translate-y-1 hover:border-cyan-200/40 hover:bg-white/[0.07]"
            style={{ borderRadius: 8 }}
          >
            <FileText className="mb-5 text-cyan-200" size={28} />
            <h2 className="text-xl font-semibold">Generate Draft</h2>
            <p className="mt-3 text-sm leading-6 text-slate-300">
              Start a new AI report job from audit package files and context.
            </p>
            <span className="mt-8 inline-flex items-center gap-2 text-sm font-semibold text-cyan-200">
              Start <ArrowRight className="transition group-hover:translate-x-1" size={16} />
            </span>
          </Link>

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
      </div>
    </div>
  )
}
