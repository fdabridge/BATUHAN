'use client'

import { FormEvent, useEffect, useMemo, useRef, useState } from 'react'
import { MessageCircle, Send, X } from 'lucide-react'
import { usePathname } from 'next/navigation'
import api from '@/lib/api'
import { useAuth } from '@/lib/auth'
import { VeraMark } from './VeraMark'

type Message = {
  role: 'user' | 'assistant'
  content: string
}

type VeraContext = {
  name: string
  description: string
  page: string
  has_case_context: boolean
  case_status: string | null
  suggestions: string[]
}

const WELCOME: Message = {
  role: 'assistant',
  content: "Hi, I’m Vera. I can explain this page, the certification workflow and what should happen next. I can read authorised information, but I can’t change any records.",
}

function auditSetIdFromPath(pathname: string): string | undefined {
  const patterns = [
    /^\/clients\/([^/]+)/,
    /^\/auditor\/audit\/([^/]+)/,
    /^\/consultant\/clients\/([^/]+)/,
    /^\/crm\/clients\/([^/]+)/,
    /^\/crm\/certificates\/([^/]+)/,
  ]
  for (const pattern of patterns) {
    const match = pathname.match(pattern)
    if (match?.[1] && match[1] !== 'new') return decodeURIComponent(match[1])
  }
  return undefined
}

function errorDetail(error: unknown): string {
  return (
    (error as { response?: { data?: { detail?: string } } })?.response?.data?.detail
    ?? 'Vera is temporarily unavailable. Please try again.'
  )
}

export function VeraAssistant() {
  const pathname = usePathname()
  const { user, isLoading } = useAuth()
  const [open, setOpen] = useState(false)
  const [context, setContext] = useState<VeraContext | null>(null)
  const [messages, setMessages] = useState<Message[]>([WELCOME])
  const [question, setQuestion] = useState('')
  const [asking, setAsking] = useState(false)
  const [contextLoading, setContextLoading] = useState(false)
  const scrollRef = useRef<HTMLDivElement>(null)
  const inputRef = useRef<HTMLTextAreaElement>(null)
  const auditSetId = useMemo(() => auditSetIdFromPath(pathname), [pathname])

  const contextKey = `${user?.id ?? ''}:${pathname}:${auditSetId ?? ''}`
  useEffect(() => {
    setContext(null)
    setMessages([WELCOME])
  }, [contextKey])

  useEffect(() => {
    if (!open || !user || user.activation_required) return
    let cancelled = false
    setContextLoading(true)
    api.get<VeraContext>('/vera/context', {
      params: { pathname, audit_set_id: auditSetId },
    })
      .then((response) => {
        if (!cancelled) setContext(response.data)
      })
      .catch(() => {
        if (!cancelled) setContext(null)
      })
      .finally(() => {
        if (!cancelled) setContextLoading(false)
      })
    return () => { cancelled = true }
  }, [open, user, pathname, auditSetId])

  useEffect(() => {
    if (!open) return
    scrollRef.current?.scrollTo({ top: scrollRef.current.scrollHeight, behavior: 'smooth' })
  }, [messages, asking, open])

  useEffect(() => {
    if (!open) return
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key === 'Escape') setOpen(false)
    }
    window.addEventListener('keydown', onKeyDown)
    return () => window.removeEventListener('keydown', onKeyDown)
  }, [open])

  if (isLoading || !user || user.activation_required || pathname === '/login' || pathname === '/apply') {
    return null
  }

  async function ask(value: string) {
    const clean = value.trim()
    if (!clean || asking) return

    const previous = messages
    setMessages([...previous, { role: 'user', content: clean }])
    setQuestion('')
    setAsking(true)
    try {
      const response = await api.post<{
        answer: string
        read_only: boolean
        remaining_today: number
      }>('/vera/ask', {
        question: clean,
        pathname,
        audit_set_id: auditSetId,
        history: previous.slice(-6),
      })
      setMessages((current) => [...current, { role: 'assistant', content: response.data.answer }])
    } catch (error) {
      setMessages((current) => [...current, { role: 'assistant', content: errorDetail(error) }])
    } finally {
      setAsking(false)
      requestAnimationFrame(() => inputRef.current?.focus())
    }
  }

  function submit(event: FormEvent) {
    event.preventDefault()
    void ask(question)
  }

  return (
    <>
      {open && (
        <section
          aria-label="Ask Vera"
          className="fixed inset-x-3 bottom-3 z-[80] flex max-h-[min(680px,calc(100vh-24px))] flex-col overflow-hidden rounded-2xl border border-certiva-green/15 bg-white shadow-[0_22px_70px_rgba(6,13,8,0.22)] sm:left-auto sm:right-5 sm:bottom-5 sm:w-[400px]"
        >
          <header className="flex items-center justify-between bg-certiva-night px-4 py-3.5 text-white">
            <div className="flex min-w-0 items-center gap-3">
              <VeraMark className="h-10 w-10 shrink-0" thinking={asking} />
              <div className="min-w-0">
                <div className="flex items-center gap-2">
                  <h2 className="text-sm font-bold">Vera</h2>
                  <span className="rounded-full border border-white/15 px-2 py-0.5 text-[9px] font-bold uppercase tracking-[0.12em] text-certiva-pale">
                    Read only
                  </span>
                </div>
                <p className="truncate text-[11px] text-white/60">
                  {context?.case_status ?? context?.page ?? "Certiva’s workflow guide"}
                </p>
              </div>
            </div>
            <button
              type="button"
              onClick={() => setOpen(false)}
              aria-label="Close Vera"
              className="flex h-9 w-9 items-center justify-center rounded-xl text-white/65 transition hover:bg-white/10 hover:text-white focus-visible:outline focus-visible:outline-2 focus-visible:outline-certiva-signal"
            >
              <X size={18} />
            </button>
          </header>

          <div ref={scrollRef} className="flex-1 space-y-3 overflow-y-auto bg-certiva-mist/60 px-4 py-4" aria-live="polite">
            {messages.map((message, index) => (
              <div
                key={`${message.role}-${index}`}
                className={message.role === 'user' ? 'flex justify-end' : 'flex justify-start'}
              >
                <div
                  className={[
                    'max-w-[88%] whitespace-pre-wrap rounded-2xl px-3.5 py-2.5 text-sm leading-5',
                    message.role === 'user'
                      ? 'rounded-br-md bg-certiva-green text-white'
                      : 'rounded-bl-md border border-slate-200/80 bg-white text-certiva-ink shadow-sm',
                  ].join(' ')}
                >
                  {message.content}
                </div>
              </div>
            ))}
            {asking && (
              <div className="flex justify-start">
                <div className="flex items-center gap-2 rounded-2xl rounded-bl-md border border-slate-200/80 bg-white px-3.5 py-2.5 text-xs text-slate-500 shadow-sm">
                  <span className="h-1.5 w-1.5 animate-pulse rounded-full bg-certiva-signal" />
                  Checking the authorised record…
                </div>
              </div>
            )}
          </div>

          {messages.length === 1 && (
            <div className="border-t border-slate-100 bg-white px-4 py-3">
              <p className="mb-2 text-[10px] font-bold uppercase tracking-[0.13em] text-certiva-mid">
                {contextLoading ? 'Reading this page' : 'Suggested questions'}
              </p>
              <div className="flex flex-wrap gap-2">
                {(context?.suggestions ?? []).map((suggestion) => (
                  <button
                    type="button"
                    key={suggestion}
                    onClick={() => void ask(suggestion)}
                    disabled={asking}
                    className="rounded-full border border-certiva-green/20 bg-certiva-mist px-3 py-1.5 text-left text-[11px] font-medium text-certiva-green transition hover:border-certiva-green/40 hover:bg-certiva-pale disabled:opacity-50"
                  >
                    {suggestion}
                  </button>
                ))}
              </div>
            </div>
          )}

          <form onSubmit={submit} className="border-t border-slate-200 bg-white p-3">
            <div className="flex items-end gap-2 rounded-2xl border border-slate-200 bg-white p-1.5 focus-within:border-certiva-mid focus-within:ring-2 focus-within:ring-certiva-pale">
              <textarea
                ref={inputRef}
                value={question}
                onChange={(event) => setQuestion(event.target.value.slice(0, 1200))}
                onKeyDown={(event) => {
                  if (event.key === 'Enter' && !event.shiftKey) {
                    event.preventDefault()
                    if (question.trim()) void ask(question)
                  }
                }}
                rows={1}
                aria-label="Question for Vera"
                placeholder="Ask about this page or workflow…"
                className="max-h-28 min-h-[38px] flex-1 resize-none border-0 bg-transparent px-2 py-2 text-sm text-certiva-ink outline-none placeholder:text-slate-400"
              />
              <button
                type="submit"
                disabled={asking || !question.trim()}
                aria-label="Send question"
                className="flex h-9 w-9 shrink-0 items-center justify-center rounded-xl bg-certiva-green text-white transition hover:bg-certiva-mid disabled:cursor-not-allowed disabled:opacity-40"
              >
                <Send size={16} />
              </button>
            </div>
            <p className="mt-2 px-1 text-[10px] leading-4 text-slate-400">
              Vera explains authorised records but cannot make certification decisions or change data.
            </p>
          </form>
        </section>
      )}

      {!open && (
        <button
          type="button"
          onClick={() => {
            setOpen(true)
            requestAnimationFrame(() => inputRef.current?.focus())
          }}
          aria-label="Ask Vera"
          className="fixed bottom-4 right-4 z-[79] flex items-center gap-2 rounded-full border border-white/10 bg-certiva-night py-2 pl-2 pr-4 text-white shadow-[0_12px_38px_rgba(6,13,8,0.28)] transition hover:-translate-y-0.5 hover:bg-certiva-dark focus-visible:outline focus-visible:outline-3 focus-visible:outline-offset-2 focus-visible:outline-certiva-signal sm:bottom-5 sm:right-5"
        >
          <VeraMark className="h-10 w-10" />
          <span className="text-sm font-semibold">Ask Vera</span>
          <MessageCircle size={15} className="text-certiva-signal" aria-hidden="true" />
        </button>
      )}
    </>
  )
}
