'use client'

import Link from 'next/link'
import { ArrowLeft, FileSearch, ShieldCheck } from 'lucide-react'

export default function CertivAIReviewPage() {
  return (
    <div className="min-h-[calc(100vh-52px)] bg-[#07130E] px-6 py-6 text-white">
      <div className="mx-auto max-w-[980px]">
        <Link href="/certivai" className="mb-6 inline-flex items-center gap-2 text-sm text-emerald-200 hover:text-white">
          <ArrowLeft size={16} />
          Certiv.AI
        </Link>

        <section className="border border-amber-200/25 bg-white/[0.045] p-6" style={{ borderRadius: 8 }}>
          <div className="flex items-center gap-4">
            <span className="flex h-14 w-14 items-center justify-center rounded bg-amber-300/15 text-amber-200">
              <FileSearch size={28} />
            </span>
            <div>
              <h1 className="text-3xl font-semibold">Report Review</h1>
              <p className="mt-2 max-w-2xl text-sm leading-6 text-slate-300">
                This module is reserved for AI review of report consistency, missing clauses, evidence gaps, and formatting risk.
              </p>
            </div>
          </div>
        </section>

        <section className="mt-5 border border-white/10 bg-white/[0.045] p-5" style={{ borderRadius: 8 }}>
          <div className="flex items-start gap-4">
            <ShieldCheck className="mt-1 text-emerald-200" size={24} />
            <div>
              <h2 className="text-xl font-semibold">Reserved workflow</h2>
              <p className="mt-3 text-sm leading-6 text-slate-300">
                The entry point is ready, but review rules and acceptance criteria should be defined before enabling uploads.
              </p>
            </div>
          </div>
        </section>
      </div>
    </div>
  )
}
