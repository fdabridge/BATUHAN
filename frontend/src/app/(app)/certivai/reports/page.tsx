'use client'

import Link from 'next/link'
import { ArrowRight, FileText, History, Layers3, Plus, ScanLine, ShieldCheck } from 'lucide-react'
import {
  CertivAISection,
  CertivAIToolHeader,
  CertivAIToolShell,
} from '@/components/certivai/CertivAIWorkspace'

export default function CertivAIReportsPage() {
  return (
    <CertivAIToolShell>
      <CertivAIToolHeader
        eyebrow="Draft from verified evidence"
        title="Report Generation"
        description="Create a controlled audit-report draft from the approved template, selected audit cycle, integrated standards, and uploaded evidence."
        icon={<ScanLine size={22} />}
        aside={<Link href="/reports/new" className="inline-flex items-center gap-2 rounded-xl bg-certiva-signal px-4 py-2.5 text-sm font-semibold text-certiva-night hover:bg-certiva-pale"><Plus size={16} /> New report</Link>}
      />

      <div className="mt-5 grid gap-5 lg:grid-cols-[minmax(0,1fr)_340px]">
        <CertivAISection title="Choose what you need" description="The report engine keeps evidence, template structure, clause coverage, and accreditation context separate and explicit.">
          <div className="grid gap-4 md:grid-cols-2">
            <Link href="/reports/new" className="group rounded-2xl border border-slate-200 bg-slate-50 p-5 transition hover:border-certiva-leaf hover:bg-certiva-mist">
              <span className="flex h-10 w-10 items-center justify-center rounded-xl bg-white text-certiva-green shadow-sm"><FileText size={20} /></span>
              <h2 className="mt-5 text-lg font-semibold text-slate-900">Generate a new draft</h2>
              <p className="mt-2 text-sm leading-6 text-slate-600">Select every standard and the exact cycle, then provide the controlled template and evidence package.</p>
              <span className="mt-6 inline-flex items-center gap-2 text-sm font-semibold text-certiva-mid">Set up report <ArrowRight size={16} className="transition group-hover:translate-x-1" /></span>
            </Link>
            <Link href="/reports" className="group rounded-2xl border border-slate-200 bg-slate-50 p-5 transition hover:border-certiva-leaf hover:bg-certiva-mist">
              <span className="flex h-10 w-10 items-center justify-center rounded-xl bg-white text-certiva-green shadow-sm"><History size={20} /></span>
              <h2 className="mt-5 text-lg font-semibold text-slate-900">Open report jobs</h2>
              <p className="mt-2 text-sm leading-6 text-slate-600">Continue monitoring active work, understand failures, and download completed report documents.</p>
              <span className="mt-6 inline-flex items-center gap-2 text-sm font-semibold text-certiva-mid">View report history <ArrowRight size={16} className="transition group-hover:translate-x-1" /></span>
            </Link>
          </div>
        </CertivAISection>

        <div className="space-y-5">
          <CertivAISection title="Controlled inputs">
            <ul className="space-y-3 text-sm leading-5 text-slate-600">
              <li className="flex gap-3"><Layers3 size={17} className="mt-0.5 shrink-0 text-certiva-mid" /><span><strong className="text-slate-800">Audit context:</strong> Stage 1, Stage 2, surveillance, and recertification are handled separately.</span></li>
              <li className="flex gap-3"><FileText size={17} className="mt-0.5 shrink-0 text-certiva-mid" /><span><strong className="text-slate-800">Template:</strong> the uploaded DOCX controls structure and final layout.</span></li>
              <li className="flex gap-3"><ShieldCheck size={17} className="mt-0.5 shrink-0 text-certiva-mid" /><span><strong className="text-slate-800">Safety:</strong> cross-client leakage checks remain mandatory before delivery.</span></li>
            </ul>
          </CertivAISection>
        </div>
      </div>
    </CertivAIToolShell>
  )
}
