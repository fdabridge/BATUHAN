'use client'

import { useEffect, useRef, useState } from 'react'
import api from '@/lib/api'
import { Download, Loader2 } from 'lucide-react'

interface CRMAuditorRow {
  id: string
  name: string
  email: string | null
  role: string | null
}

interface CRMCalendarEntry {
  audit_set_id: string
  plan_number: number
  company_name: string
  location: string
  standards: string[]
  audit_type: string
  stage_type: string
  date_start: string
  date_end: string
  audit_days: number
  auditor_role: string
}

const MONTH_NAMES = ['January','February','March','April','May','June',
                     'July','August','September','October','November','December']
const DAY_NAMES = ['Mon','Tue','Wed','Thu','Fri','Sat','Sun']

function toISO(d: Date): string {
  return `${d.getFullYear()}-${String(d.getMonth()+1).padStart(2,'0')}-${String(d.getDate()).padStart(2,'0')}`
}

function buildGrid(year: number, month: number): (Date | null)[] {
  const first = new Date(year, month, 1)
  const startPad = (first.getDay() + 6) % 7
  const daysInMonth = new Date(year, month + 1, 0).getDate()
  const cells: (Date | null)[] = Array(startPad).fill(null)
  for (let d = 1; d <= daysInMonth; d++) cells.push(new Date(year, month, d))
  while (cells.length % 7 !== 0) cells.push(null)
  return cells
}

export default function AuditorCalendar() {
  const [auditors, setAuditors]       = useState<CRMAuditorRow[]>([])
  const [selectedId, setSelectedId]   = useState<string>('')
  const [entries, setEntries]         = useState<CRMCalendarEntry[]>([])
  const [loadingA, setLoadingA]       = useState(true)
  const [loadingE, setLoadingE]       = useState(false)
  const [year, setYear]               = useState(() => new Date().getFullYear())
  const [month, setMonth]             = useState(() => new Date().getMonth())
  const [activeDay, setActiveDay]     = useState<string | null>(null)
  const [exporting, setExporting]     = useState(false)
  const [exportError, setExportError] = useState<string | null>(null)
  const popoverRef                    = useRef<HTMLDivElement>(null)

  useEffect(() => {
    api.get<CRMAuditorRow[]>('/crm/auditors')
      .then((r) => setAuditors(r.data))
      .catch(() => {})
      .finally(() => setLoadingA(false))
  }, [])

  useEffect(() => {
    if (!selectedId) { setEntries([]); return }
    setLoadingE(true)
    api.get<CRMCalendarEntry[]>(`/crm/auditors/${selectedId}/calendar`)
      .then((r) => setEntries(r.data))
      .catch(() => setEntries([]))
      .finally(() => setLoadingE(false))
  }, [selectedId])

  // Close popover on outside click
  useEffect(() => {
    function handler(e: MouseEvent) {
      if (popoverRef.current && !popoverRef.current.contains(e.target as Node)) {
        setActiveDay(null)
      }
    }
    document.addEventListener('mousedown', handler)
    return () => document.removeEventListener('mousedown', handler)
  }, [])

  function prevMonth() {
    if (month === 0) { setYear(y => y - 1); setMonth(11) } else setMonth(m => m - 1)
    setActiveDay(null)
  }
  function nextMonth() {
    if (month === 11) { setYear(y => y + 1); setMonth(0) } else setMonth(m => m + 1)
    setActiveDay(null)
  }

  function entriesForDay(day: string): CRMCalendarEntry[] {
    return entries.filter(e => e.date_start <= day && day <= e.date_end)
  }

  async function exportCalendar() {
    if (!selectedId) return
    setExporting(true)
    setExportError(null)
    try {
      const response = await api.get<Blob>(`/crm/auditors/${selectedId}/calendar/export`, {
        responseType: 'blob',
      })
      const auditor = auditors.find((item) => item.id === selectedId)
      const safeName = (auditor?.name || 'Auditor').replace(/[^A-Za-z0-9_-]+/g, '_')
      const url = URL.createObjectURL(response.data)
      const link = document.createElement('a')
      link.href = url
      link.download = `Auditor_Schedule_${safeName}.xlsx`
      document.body.appendChild(link)
      link.click()
      link.remove()
      URL.revokeObjectURL(url)
    } catch {
      setExportError('Could not export this auditor schedule. Please try again.')
    } finally {
      setExporting(false)
    }
  }

  const todayISO = toISO(new Date())
  const grid = buildGrid(year, month)

  return (
    <div className="space-y-6 max-w-3xl">
      <h1 className="text-xl font-semibold text-gray-900">Auditor Calendar</h1>

      {/* Auditor selector */}
      <div className="flex flex-wrap items-center gap-3">
        <label className="text-sm font-medium text-gray-600">Select auditor:</label>
        {loadingA ? (
          <span className="text-sm text-gray-400">Loading…</span>
        ) : (
          <select
            className="rounded-lg border border-gray-200 px-3 py-1.5 text-sm focus:outline-none focus:ring-2 focus:ring-emerald-500"
            value={selectedId}
            onChange={(e) => { setSelectedId(e.target.value); setActiveDay(null); setExportError(null) }}
          >
            <option value="">— choose an auditor —</option>
            {auditors.map((a) => (
              <option key={a.id} value={a.id}>{a.name}</option>
            ))}
          </select>
        )}
        {loadingE && <span className="text-xs text-gray-400">Loading calendar…</span>}
        <button
          type="button"
          onClick={exportCalendar}
          disabled={!selectedId || loadingE || exporting}
          className="inline-flex items-center gap-2 rounded-lg border border-[#1A4731] bg-[#1A4731] px-3 py-1.5 text-sm font-medium text-white hover:bg-[#123623] disabled:cursor-not-allowed disabled:opacity-45"
          title="Export occupied audit periods only"
        >
          {exporting ? <Loader2 size={15} className="animate-spin" /> : <Download size={15} />}
          {exporting ? 'Preparing Excel…' : 'Export Excel'}
        </button>
      </div>
      {selectedId && (
        <p className="-mt-4 text-xs text-gray-400">
          The export lists all scheduled audit periods for this auditor; empty calendar days are omitted.
        </p>
      )}
      {exportError && <p className="-mt-4 text-sm text-red-600">{exportError}</p>}

      {/* Calendar */}
      <div className="rounded-xl border border-gray-200 bg-white shadow-sm overflow-hidden">
        {/* Month header */}
        <div className="flex items-center justify-between px-6 py-4 border-b border-gray-100">
          <button onClick={prevMonth} className="rounded p-1 hover:bg-gray-100 text-gray-500">‹</button>
          <span className="font-semibold text-gray-800">{MONTH_NAMES[month]} {year}</span>
          <button onClick={nextMonth} className="rounded p-1 hover:bg-gray-100 text-gray-500">›</button>
        </div>

        {/* Day-of-week headers */}
        <div className="grid grid-cols-7 border-b border-gray-100">
          {DAY_NAMES.map(d => (
            <div key={d} className="py-2 text-center text-xs font-medium text-gray-400">{d}</div>
          ))}
        </div>

        {/* Calendar grid */}
        <div className="grid grid-cols-7 p-2 gap-1 relative">
          {grid.map((day, i) => {
            if (!day) return <div key={`empty-${i}`} />
            const iso = toISO(day)
            const dayEntries = entriesForDay(iso)
            const isBlocked = dayEntries.length > 0
            const isToday = iso === todayISO
            const isActive = activeDay === iso

            return (
              <div key={iso} className="relative">
                <button
                  onClick={() => isBlocked ? setActiveDay(isActive ? null : iso) : undefined}
                  className={[
                    'w-full aspect-square flex items-center justify-center text-sm rounded-lg transition-colors',
                    isBlocked
                      ? 'bg-[#1A4731] text-white cursor-pointer hover:bg-[#1A4731]/80 font-medium'
                      : 'text-gray-700 cursor-default hover:bg-gray-50',
                    isToday && !isBlocked ? 'ring-2 ring-emerald-400' : '',
                    isToday && isBlocked ? 'ring-2 ring-white/50' : '',
                  ].join(' ')}
                >
                  {day.getDate()}
                </button>
              </div>
            )
          })}
        </div>

        {/* Legend */}
        <div className="flex items-center gap-4 px-6 py-3 border-t border-gray-100 text-xs text-gray-400">
          <span className="flex items-center gap-1.5">
            <span className="inline-block w-3 h-3 rounded bg-[#1A4731]" /> Audit day
          </span>
          <span className="flex items-center gap-1.5">
            <span className="inline-block w-3 h-3 rounded ring-2 ring-emerald-400" /> Today
          </span>
        </div>
      </div>

      {/* Day detail popover */}
      {activeDay && entriesForDay(activeDay).length > 0 && (
        <div ref={popoverRef} className="rounded-xl border border-gray-200 bg-white shadow-lg p-5 space-y-3">
          <div className="flex items-center justify-between">
            <span className="text-sm font-semibold text-gray-700">
              {new Date(activeDay + 'T12:00:00').toLocaleDateString('en-GB', { weekday: 'long', day: 'numeric', month: 'long', year: 'numeric' })}
            </span>
            <button onClick={() => setActiveDay(null)} className="text-gray-400 hover:text-gray-600 text-lg leading-none">×</button>
          </div>
          {entriesForDay(activeDay).map((e) => (
            <div key={`${e.audit_set_id}-${e.stage_type}`} className="rounded-lg border border-gray-100 bg-gray-50 p-4">
              <p className="font-semibold text-gray-900">{e.company_name}</p>
              <p className="text-sm text-gray-500 mt-0.5">
                {e.audit_type} · {e.stage_type} · <span className={e.auditor_role === 'Lead Auditor' ? 'text-emerald-700 font-medium' : 'text-blue-600 font-medium'}>{e.auditor_role}</span>
              </p>
              <p className="text-xs text-gray-500 mt-1">{e.standards.join(' + ') || 'Standard not specified'}</p>
              {e.location && <p className="text-xs text-gray-400 mt-1">{e.location}</p>}
              <p className="text-xs text-gray-400 mt-1">
                #{e.plan_number} · {e.date_start === e.date_end ? e.date_start : `${e.date_start} → ${e.date_end}`}
              </p>
            </div>
          ))}
        </div>
      )}
    </div>
  )
}
