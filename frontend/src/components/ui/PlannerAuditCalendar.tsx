'use client'

import { useEffect, useRef, useState } from 'react'
import Link from 'next/link'
import { useQueries } from '@tanstack/react-query'
import * as Popover from '@radix-ui/react-popover'
import { ArrowUpRight, CalendarDays, ChevronLeft, ChevronRight, X } from 'lucide-react'
import api from '@/lib/api'

type Booking = {
  id: string
  case_id: string
  plan_number: number
  company_name: string
  standards: string[]
  audit_type: string | null
  stage_type: string
  start: string
  end: string | null
  people: { name: string; role: string; standard: string | null }[]
}

const standardLabels: Record<string, string> = {
  QMS: 'ISO 9001:2015',
  EMS: 'ISO 14001:2015',
  OHSMS: 'ISO 45001:2018',
  FSMS: 'ISO 22000:2018',
  ISMS: 'ISO/IEC 27001:2022',
  MDQMS: 'ISO 13485:2016',
  ABMS: 'ISO 37001:2016',
  ENMS: 'ISO 50001:2018',
}

const weekdays = [
  ['Mon', 'Monday'], ['Tue', 'Tuesday'], ['Wed', 'Wednesday'], ['Thu', 'Thursday'],
  ['Fri', 'Friday'], ['Sat', 'Saturday'], ['Sun', 'Sunday'],
]
const monthLabel = new Intl.DateTimeFormat('en-US', { month: 'long', year: 'numeric', timeZone: 'UTC' })
const dayLabel = new Intl.DateTimeFormat('en-US', { dateStyle: 'full', timeZone: 'UTC' })
const shortDate = new Intl.DateTimeFormat('en-US', { day: 'numeric', month: 'short', timeZone: 'UTC' })
const iconButton = 'inline-flex h-8 w-8 shrink-0 items-center justify-center rounded-lg text-slate-600 hover:bg-certiva-mist hover:text-certiva-primary focus-visible:outline focus-visible:outline-2 focus-visible:outline-certiva-mid disabled:opacity-30'
const iso = (date: Date) => date.toISOString().slice(0, 10)
const firstDate = '0001-01-01'
const lastDate = '9999-12-31'

function todayLocal() {
  const date = new Date()
  const year = date.getFullYear()
  const month = String(date.getMonth() + 1).padStart(2, '0')
  const day = String(date.getDate()).padStart(2, '0')
  return `${year}-${month}-${day}`
}

function addDays(day: string, offset: number) {
  const date = new Date(`${day}T00:00:00Z`)
  date.setUTCDate(date.getUTCDate() + offset)
  if (date.getUTCFullYear() < 1) return firstDate
  if (date.getUTCFullYear() > 9999) return lastDate
  return iso(date)
}

function monthWeeks(month: string) {
  const first = new Date(`${month}-01T00:00:00Z`)
  const offset = (first.getUTCDay() + 6) % 7
  const last = new Date(first)
  last.setUTCMonth(last.getUTCMonth() + 1, 0)
  const days = Array.from({ length: last.getUTCDate() }, (_, i) => `${month}-${String(i + 1).padStart(2, '0')}`)
  const cells: (string | null)[] = [...Array<null>(offset).fill(null), ...days]
  while (cells.length % 7) cells.push(null)
  return Array.from({ length: cells.length / 7 }, (_, i) => cells.slice(i * 7, i * 7 + 7))
}

function formatStandard(value: string) {
  return standardLabels[value.toUpperCase()] ?? value
}

function dateRange({ start, end }: Booking) {
  if (!end || start === end) return shortDate.format(new Date(`${start}T00:00:00Z`))
  return `${shortDate.format(new Date(`${start}T00:00:00Z`))} – ${shortDate.format(new Date(`${end}T00:00:00Z`))}`
}

function stageLabel({ stage_type, audit_type }: Booking) {
  switch (stage_type) {
    case 'stage_1': return 'Stage 1'
    case 'stage_2': return 'Stage 2'
    case 'recertification': return 'Recertification'
    case 'surveillance':
      if (audit_type?.includes('surveillance_1')) return audit_type.includes('scope_extension') ? 'Surveillance 1 + Scope Extension' : 'Surveillance 1'
      if (audit_type?.includes('surveillance_2')) return audit_type.includes('scope_extension') ? 'Surveillance 2 + Scope Extension' : 'Surveillance 2'
      return 'Surveillance'
    default: return stage_type.replaceAll('_', ' ').replace(/\b\w/g, letter => letter.toUpperCase()) || 'Audit'
  }
}

function standardsLabel(booking: Booking) {
  return [...new Set(booking.standards.map(formatStandard))].join(' · ') || 'Standards not specified'
}

function BookingList({ bookings, ready }: { bookings: Booking[]; ready: boolean }) {
  if (bookings.length === 0) {
    return <p className="px-3 py-2.5 text-xs text-slate-600">{ready ? 'No audits are scheduled for this day.' : 'Audit details are still loading.'}</p>
  }
  return (
    <ul className="divide-y divide-slate-100">
      {bookings.map(booking => (
        <li key={booking.id} className="min-w-0 px-3 py-2 text-xs leading-[1.45]">
          <Link href={`/clients/${booking.case_id}`}
            aria-label={`Open ${booking.company_name}`}
            className="flex items-start justify-between gap-2 font-bold text-certiva-primary hover:underline">
            <span className="min-w-0 break-words">{booking.company_name}</span>
            <ArrowUpRight size={14} className="shrink-0" aria-hidden="true" />
          </Link>
          <p className="text-slate-600">{stageLabel(booking)} · {dateRange(booking)} · #{booking.plan_number}</p>
          <p className="break-words font-medium text-slate-700">{standardsLabel(booking)}</p>
          {!booking.end && <p className="text-amber-800">End date not entered</p>}
          {booking.people.length > 0 ? (
            <ul className="mt-0.5 space-y-0.5 text-slate-600">
              {booking.people.map((person, index) => (
                <li key={`${person.name}-${person.role}-${index}`} className="break-words">
                  <span className="font-medium text-slate-700">{person.name}</span> · {person.role}
                  {person.standard && ` · ${formatStandard(person.standard)}`}
                </li>
              ))}
            </ul>
          ) : <p className="text-amber-800">Audit team not assigned</p>}
        </li>
      ))}
    </ul>
  )
}

type DayMode = 'hover' | 'pinned'

function CalendarDay({ day, isToday, bookings, ready, mode, besideCalendar, onHover, onLeave, onStay, onPin, onDismiss }: {
  day: string
  isToday: boolean
  bookings: Booking[]
  ready: boolean
  mode: DayMode | undefined
  besideCalendar: boolean
  onHover: (day: string) => void
  onLeave: () => void
  onStay: () => void
  onPin: (day: string) => void
  onDismiss: (day: string) => void
}) {
  const trigger = useRef<HTMLButtonElement>(null)
  const content = useRef<HTMLDivElement>(null)
  const calendarEdge = useRef({
    get contextElement() { return trigger.current ?? undefined },
    getBoundingClientRect() {
      const dayRect = trigger.current?.getBoundingClientRect() ?? new DOMRect()
      const calendarRect = trigger.current?.closest('[aria-labelledby="planner-calendar-title"]')?.getBoundingClientRect()
      return new DOMRect(calendarRect?.right ?? dayRect.right, dayRect.top, 0, dayRect.height)
    },
  })
  const label = dayLabel.format(new Date(`${day}T00:00:00Z`))
  const countLabel = ready ? `${bookings.length} audit${bookings.length === 1 ? '' : 's'}` : 'Audit details'

  useEffect(() => {
    if (mode === 'pinned') content.current?.focus({ preventScroll: true })
  }, [mode])

  return (
    <Popover.Root open={Boolean(mode)} onOpenChange={open => { if (!open) onDismiss(day) }}>
      {besideCalendar && <Popover.Anchor virtualRef={calendarEdge} />}
      <Popover.Trigger asChild>
        <button type="button" ref={trigger} aria-current={isToday ? 'date' : undefined}
          aria-label={`${label}${isToday ? ', today' : ''}, ${countLabel}`}
          onPointerEnter={event => { if (event.pointerType === 'mouse' && bookings.length) onHover(day) }}
          onPointerLeave={event => { if (event.pointerType === 'mouse') onLeave() }}
          onClick={event => {
            event.preventDefault()
            if (mode === 'pinned') onDismiss(day)
            else onPin(day)
          }}
          className={`flex h-9 w-full items-center justify-center gap-0.5 rounded-md text-xs font-semibold hover:bg-certiva-mist focus-visible:outline focus-visible:outline-2 focus-visible:outline-certiva-mid sm:gap-1 ${mode ? 'bg-certiva-mist' : ''}`}>
          <span className={`grid h-6 min-w-5 place-items-center rounded-full sm:min-w-6 ${isToday ? 'bg-certiva-primary text-white' : 'text-slate-700'}`}>
            {Number(day.slice(-2))}
          </span>
          {bookings.length > 0 && (
            <span aria-hidden="true" className="min-w-3 rounded-full bg-certiva-pale px-0.5 text-[10px] leading-4 text-certiva-primary sm:min-w-4">
              {bookings.length}
            </span>
          )}
        </button>
      </Popover.Trigger>
      <Popover.Portal>
        <Popover.Content ref={content} aria-label={label} side={besideCalendar ? 'right' : 'bottom'}
          align={besideCalendar ? 'start' : 'center'} sideOffset={4} collisionPadding={8}
          onOpenAutoFocus={event => {
            event.preventDefault()
            if (mode === 'pinned') content.current?.focus({ preventScroll: true })
          }}
          onCloseAutoFocus={event => event.preventDefault()}
          onEscapeKeyDown={() => {
            if (content.current?.contains(document.activeElement)) trigger.current?.focus()
          }}
          onPointerEnter={onStay}
          onPointerLeave={event => { if (event.pointerType === 'mouse') onLeave() }}
          className="z-50 flex max-h-[min(19rem,var(--radix-popover-content-available-height))] w-80 max-w-[calc(100vw-16px)] flex-col overflow-hidden rounded-xl border border-slate-200 bg-white shadow-xl outline-none">
          <div className="flex shrink-0 items-center gap-1 border-b border-slate-100 bg-slate-50 px-2 py-1">
            <div className="min-w-0 flex-1 pl-1">
              <h3 className="text-xs font-bold text-certiva-primary">{label}</h3>
              <p className="text-[10px] text-slate-600">{countLabel}</p>
            </div>
            <button type="button" aria-label="Previous day" disabled={day === firstDate}
              className={iconButton} onClick={() => onPin(addDays(day, -1))}>
              <ChevronLeft size={15} aria-hidden="true" />
            </button>
            <button type="button" aria-label="Next day" disabled={day === lastDate}
              className={iconButton} onClick={() => onPin(addDays(day, 1))}>
              <ChevronRight size={15} aria-hidden="true" />
            </button>
            <Popover.Close asChild>
              <button type="button" aria-label="Close day details" className={iconButton}
                onClick={() => trigger.current?.focus({ preventScroll: true })}>
                <X size={15} aria-hidden="true" />
              </button>
            </Popover.Close>
          </div>
          <div className="min-h-0 overflow-y-auto overscroll-contain">
            <BookingList bookings={bookings} ready={ready} />
          </div>
        </Popover.Content>
      </Popover.Portal>
    </Popover.Root>
  )
}

export function PlannerAuditCalendar({ userId, onClose }: { userId: string; onClose: () => void }) {
  const [today, setToday] = useState(todayLocal)
  const [chosenMonth, setChosenMonth] = useState<string | null>(null)
  const [activeDay, setActiveDay] = useState<{ day: string; mode: DayMode } | null>(null)
  const [agendaStart, setAgendaStart] = useState<string | null>(null)
  const [wideLayout, setWideLayout] = useState(false)
  const hoverTimer = useRef<number | undefined>(undefined)
  const month = chosenMonth ?? today.slice(0, 7)
  const weeks = monthWeeks(month)
  const agendaDays = agendaStart ? [...new Set(Array.from({ length: 7 }, (_, i) => addDays(agendaStart, i)))] : []
  const months = agendaStart ? [...new Set(agendaDays.map(day => day.slice(0, 7)))] : [month]
  const queries = useQueries({
    queries: months.map(queryMonth => ({
      queryKey: ['planner-audit-calendar', userId, queryMonth],
      queryFn: ({ signal }: { signal: AbortSignal }) =>
        api.get<Booking[]>('/dashboard/audit-calendar', { params: { month: queryMonth }, signal }).then(response => response.data),
      staleTime: 0,
      refetchInterval: 60_000,
    })),
  })
  const bookings = [...new Map(queries.flatMap(query => query.data ?? []).map(booking => [booking.id, booking])).values()]
  const isLoading = queries.some(query => query.isLoading)
  const isError = queries.some(query => query.isError)
  const ready = !isLoading && !isError

  useEffect(() => {
    const refreshToday = () => setToday(todayLocal())
    const layout = window.matchMedia('(min-width: 1280px)')
    const refreshLayout = () => setWideLayout(layout.matches)
    refreshLayout()
    const timer = window.setInterval(refreshToday, 30_000)
    window.addEventListener('focus', refreshToday)
    layout.addEventListener('change', refreshLayout)
    return () => {
      window.clearInterval(timer)
      window.removeEventListener('focus', refreshToday)
      layout.removeEventListener('change', refreshLayout)
      window.clearTimeout(hoverTimer.current)
    }
  }, [])

  const bookingsOn = (day: string) => bookings.filter(booking => booking.start <= day && (booking.end ?? booking.start) >= day)

  function cancelHoverTimer() {
    window.clearTimeout(hoverTimer.current)
  }

  function hoverDay(day: string) {
    cancelHoverTimer()
    hoverTimer.current = window.setTimeout(() => {
      setActiveDay(current => current?.mode === 'pinned' ? current : { day, mode: 'hover' })
    }, 100)
  }

  function leaveDay() {
    cancelHoverTimer()
    hoverTimer.current = window.setTimeout(() => {
      setActiveDay(current => current?.mode === 'hover' ? null : current)
    }, 220)
  }

  function dismissDay(day: string) {
    cancelHoverTimer()
    setActiveDay(current => current?.day === day ? null : current)
  }

  function pinDay(day: string) {
    cancelHoverTimer()
    if (!day.startsWith(month)) setChosenMonth(day.slice(0, 7))
    setActiveDay({ day, mode: 'pinned' })
  }

  function movePeriod(delta: number) {
    cancelHoverTimer()
    setActiveDay(null)
    if (agendaStart) {
      setAgendaStart(addDays(agendaStart, delta * 7))
      return
    }
    const date = new Date(`${month}-01T00:00:00Z`)
    date.setUTCMonth(date.getUTCMonth() + delta)
    setChosenMonth(iso(date).slice(0, 7))
  }

  return (
    <section aria-labelledby="planner-calendar-title" className="min-w-0 rounded-2xl border border-emerald-950/10 bg-white shadow-sm">
      <div className="flex flex-wrap items-center gap-x-3 gap-y-1 border-b border-slate-100 px-3 py-2">
        <div className="flex min-w-0 flex-1 items-center gap-2">
          <span className="hidden rounded-lg bg-certiva-mist p-2 text-certiva-primary sm:inline-flex">
            <CalendarDays size={16} aria-hidden="true" />
          </span>
          <div>
            <h2 id="planner-calendar-title" className="text-[11px] font-semibold uppercase tracking-[0.12em] text-certiva-mid">Audit calendar</h2>
            <p aria-live="polite" className="text-sm font-bold text-certiva-primary sm:text-base">
              {agendaStart
                ? `${shortDate.format(new Date(`${agendaStart}T00:00:00Z`))} – ${shortDate.format(new Date(`${agendaDays[agendaDays.length - 1]}T00:00:00Z`))}`
                : monthLabel.format(new Date(`${month}-01T00:00:00Z`))}
            </p>
          </div>
        </div>
        <div className="flex items-center gap-0.5 sm:gap-1">
          <button type="button" onClick={() => {
            cancelHoverTimer()
            setAgendaStart(agendaStart ? null : today)
            setActiveDay(null)
          }}
            className="rounded-lg border border-slate-200 px-2.5 py-1.5 text-xs font-semibold text-certiva-primary hover:bg-certiva-mist focus-visible:outline focus-visible:outline-2 focus-visible:outline-certiva-mid">
            {agendaStart ? 'Month view' : '7-day agenda'}
          </button>
          <button type="button" onClick={() => {
            cancelHoverTimer()
            setChosenMonth(null)
            setActiveDay(null)
            if (agendaStart) setAgendaStart(today)
          }}
            className="rounded-lg border border-slate-200 px-2.5 py-1.5 text-xs font-semibold text-certiva-primary hover:bg-certiva-mist focus-visible:outline focus-visible:outline-2 focus-visible:outline-certiva-mid">
            Today
          </button>
          <button type="button" aria-label={agendaStart ? 'Previous 7 days' : 'Previous month'} className={iconButton} onClick={() => movePeriod(-1)} disabled={agendaStart ? agendaStart === firstDate : month === '0001-01'}>
            <ChevronLeft size={18} aria-hidden="true" />
          </button>
          <button type="button" aria-label={agendaStart ? 'Next 7 days' : 'Next month'} className={iconButton} onClick={() => movePeriod(1)} disabled={agendaStart ? agendaStart === lastDate : month === '9999-12'}>
            <ChevronRight size={18} aria-hidden="true" />
          </button>
          <button type="button" aria-label="Close calendar" title="Close calendar" className={iconButton} onClick={onClose}>
            <X size={18} aria-hidden="true" />
          </button>
        </div>
      </div>
      {isLoading && <p role="status" className="px-4 py-2 text-xs text-slate-600">Loading scheduled audits…</p>}
      {isError && (
        <div role="alert" className="flex flex-wrap items-center gap-2 bg-amber-50 px-4 py-2 text-sm text-amber-900">
          Scheduled audits could not be refreshed.
          <button type="button" onClick={() => queries.forEach(query => void query.refetch())} className="font-semibold underline">Try again</button>
        </div>
      )}
      {agendaStart ? (
        <div aria-label="Seven-day audit agenda" className="max-h-64 divide-y divide-slate-100 overflow-y-auto overscroll-contain">
          {agendaDays.map(day => (
            <section key={day} className={`grid grid-cols-[7rem_minmax(0,1fr)] ${day === today ? 'bg-certiva-mist' : ''}`}>
              <h3 aria-current={day === today ? 'date' : undefined} className="px-3 py-2 text-xs font-semibold text-certiva-primary">
                {dayLabel.format(new Date(`${day}T00:00:00Z`))}{day === today && ' · Today'}
              </h3>
              <BookingList bookings={bookingsOn(day)} ready={ready} />
            </section>
          ))}
        </div>
      ) : (
        <table aria-label="Monthly audit calendar" className="w-full table-fixed border-separate border-spacing-x-0.5 border-spacing-y-0.5 px-2 pb-2">
          <thead>
            <tr>
              {weekdays.map(([short, full]) => (
                <th key={short} scope="col" abbr={full} className="py-1.5 text-center text-[11px] font-semibold text-slate-500">
                  {short}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {weeks.map((week, index) => (
              <tr key={index}>
                {week.map((day, column) => (
                  <td key={day ?? column} className={`h-9 rounded-md p-0 ${day && column > 4 ? 'bg-slate-50' : ''}`}>
                    {day && (
                      <CalendarDay day={day} isToday={day === today} bookings={bookingsOn(day)} ready={ready}
                        mode={activeDay?.day === day ? activeDay.mode : undefined} besideCalendar={wideLayout}
                        onHover={hoverDay} onLeave={leaveDay} onStay={cancelHoverTimer}
                        onPin={pinDay} onDismiss={dismissDay} />
                    )}
                  </td>
                ))}
              </tr>
            ))}
          </tbody>
        </table>
      )}
      {!agendaStart && ready && bookings.length === 0 && (
        <p className="border-t border-slate-100 px-3 py-2 text-xs text-slate-600">No audits are scheduled for this month.</p>
      )}
    </section>
  )
}
