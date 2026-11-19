'use client'

import Link from 'next/link'
import { useQuery } from '@tanstack/react-query'
import { ArrowRight, Briefcase, Plus } from 'lucide-react'
import api from '@/lib/api'
import { useAuth } from '@/lib/auth'

interface SalesCase {
  id: string
  company_name: string
  representative_name: string
  status: string
  quotation_revision: number
  created_at: string
  updated_at: string
}

const STATUS: Record<string, string> = {
  draft: 'Draft application',
  calculated: 'Duration calculated',
  quotation_ready: 'Ready to quote',
  quotation_generated: 'Quotation generated',
  quotation_rejected: 'Quotation rejected',
  agreed: 'Agreement generated',
}

export default function SalesQuotationWorkspacePage() {
  const { user } = useAuth()
  const { data = [], isLoading, error } = useQuery<SalesCase[]>({
    queryKey: ['sales-quotation-cases'],
    queryFn: () => api.get('/sales-quotations').then((response) => response.data),
    enabled: user?.role === 'sales_manager',
  })

  if (user && user.role !== 'sales_manager') {
    return <div className="rounded-xl border border-red-200 bg-red-50 p-5 text-sm text-red-700">This private workspace is available only to sales managers.</div>
  }

  const counts = data.reduce<Record<string, number>>((acc, item) => {
    acc[item.status] = (acc[item.status] || 0) + 1
    return acc
  }, {})

  return (
    <div className="mx-auto max-w-7xl space-y-6">
      <section className="overflow-hidden rounded-2xl bg-certiva-night p-7 text-white">
        <div className="flex flex-wrap items-end justify-between gap-5">
          <div>
            <p className="text-xs font-semibold uppercase tracking-[0.2em] text-certiva-signal">Private commercial workspace</p>
            <h1 className="mt-2 text-3xl font-semibold">Sales Quotation Workspace</h1>
            <p className="mt-2 max-w-3xl text-sm leading-6 text-white/65">
              Calculate audit duration, record the solicitation, prepare revision-controlled quotations, and generate an agreement. Nothing here creates a client, alerts a planner, or starts certification.
            </p>
          </div>
          <Link href="/apply?mode=sales" className="inline-flex items-center gap-2 rounded-lg bg-white px-4 py-2.5 text-sm font-semibold text-certiva-primary hover:bg-emerald-50">
            <Plus size={17} /> New sales calculation
          </Link>
        </div>
      </section>

      <div className="grid gap-3 sm:grid-cols-4">
        {[
          ['Open calculations', (counts.draft || 0) + (counts.calculated || 0)],
          ['Quoted', (counts.quotation_ready || 0) + (counts.quotation_generated || 0)],
          ['Rejected', counts.quotation_rejected || 0],
          ['Agreed', counts.agreed || 0],
        ].map(([label, value]) => (
          <div key={String(label)} className="rounded-xl border border-gray-100 bg-white p-5">
            <p className="text-xs uppercase tracking-wider text-gray-400">{label}</p>
            <p className="mt-2 text-3xl font-semibold text-certiva-primary">{value}</p>
          </div>
        ))}
      </div>

      <section className="overflow-hidden rounded-xl border border-gray-100 bg-white">
        <div className="flex items-center gap-3 border-b border-gray-100 px-5 py-4">
          <Briefcase size={19} className="text-certiva-primary" />
          <h2 className="font-semibold">My quotation cases</h2>
        </div>
        {isLoading ? (
          <div className="p-8 text-sm text-gray-500">Loading private cases…</div>
        ) : error ? (
          <div className="p-8 text-sm text-red-600">Could not load the private sales workspace.</div>
        ) : data.length === 0 ? (
          <div className="p-10 text-center">
            <p className="font-medium text-gray-700">No sales calculations yet</p>
            <p className="mt-1 text-sm text-gray-500">Start with the same information a client would enter in the application.</p>
          </div>
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead className="bg-gray-50 text-left text-xs uppercase tracking-wide text-gray-400">
                <tr><th className="px-5 py-3">Organization</th><th className="px-5 py-3">Contact</th><th className="px-5 py-3">Status</th><th className="px-5 py-3">Revision</th><th className="px-5 py-3">Updated</th><th /></tr>
              </thead>
              <tbody className="divide-y divide-gray-100">
                {data.map((item) => (
                  <tr key={item.id} className="hover:bg-gray-50/60">
                    <td className="px-5 py-4 font-medium text-gray-900">{item.company_name}</td>
                    <td className="px-5 py-4 text-gray-500">{item.representative_name || '—'}</td>
                    <td className="px-5 py-4"><span className="rounded-full bg-emerald-50 px-2.5 py-1 text-xs font-medium text-emerald-800">{STATUS[item.status] || item.status}</span></td>
                    <td className="px-5 py-4 text-gray-500">{item.quotation_revision ? `R${item.quotation_revision}` : '—'}</td>
                    <td className="px-5 py-4 text-gray-500">{new Date(item.updated_at).toLocaleDateString()}</td>
                    <td className="px-5 py-4 text-right"><Link href={`/sales/${item.id}`} className="inline-flex items-center gap-1 font-medium text-certiva-primary hover:underline">Open <ArrowRight size={14} /></Link></td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </section>
    </div>
  )
}
