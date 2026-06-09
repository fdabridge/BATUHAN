'use client'

import { useEffect, useRef, useState } from 'react'
import api from '@/lib/api'

interface Message {
  id: string
  sender_name: string
  sender_role: string
  body: string
  created_at: string
  is_mine: boolean
}

interface Props {
  fetchUrl: string
  postUrl: string
  pollInterval?: number
}

// CB-side roles are flattened to "IFC Global" so clients never see internal
// titles; the client's own messages render as "You".
const ROLE_LABELS: Record<string, string> = {
  client:    'You',
  admin:     'IFC Global',
  planner:   'IFC Global',
  officer:   'IFC Global',
  executive: 'IFC Global',
  auditor:   'Auditor',
}

export function MessageThread({ fetchUrl, postUrl, pollInterval = 10000 }: Props) {
  const [messages, setMessages] = useState<Message[]>([])
  const [draft, setDraft]       = useState('')
  const [sending, setSending]   = useState(false)
  const bottomRef = useRef<HTMLDivElement>(null)

  async function load() {
    try {
      const r = await api.get<Message[]>(fetchUrl)
      setMessages(r.data)
    } catch {
      /* swallow — polling will retry */
    }
  }

  useEffect(() => {
    load()
    const interval = setInterval(load, pollInterval)
    return () => clearInterval(interval)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [fetchUrl, pollInterval])

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: 'smooth' })
  }, [messages.length])

  async function send() {
    if (!draft.trim() || sending) return
    setSending(true)
    try {
      await api.post(postUrl, { body: draft.trim() })
      setDraft('')
      await load()
    } finally {
      setSending(false)
    }
  }

  function handleKey(e: React.KeyboardEvent) {
    if (e.key === 'Enter' && (e.metaKey || e.ctrlKey)) send()
  }

  return (
    <div className="flex h-full min-h-[400px] flex-col">
      {/* Messages */}
      <div className="flex-1 space-y-3 overflow-y-auto p-4">
        {messages.length === 0 && (
          <p className="py-8 text-center text-sm text-gray-400">
            No messages yet. Start the conversation.
          </p>
        )}
        {messages.map((msg) => (
          <div
            key={msg.id}
            className={`flex ${msg.is_mine ? 'justify-end' : 'justify-start'}`}
          >
            <div
              className={`flex max-w-[75%] flex-col ${
                msg.is_mine ? 'items-end' : 'items-start'
              }`}
            >
              <span className="mb-1 px-1 text-xs text-gray-400">
                {msg.is_mine
                  ? 'You'
                  : (ROLE_LABELS[msg.sender_role] || msg.sender_name)}
                {' · '}
                {new Date(msg.created_at).toLocaleTimeString([], {
                  hour:   '2-digit',
                  minute: '2-digit',
                })}
              </span>
              <div
                className={`whitespace-pre-wrap break-words rounded-2xl px-4 py-2.5 text-sm ${
                  msg.is_mine
                    ? 'rounded-tr-sm bg-[#1A4731] text-white'
                    : 'rounded-tl-sm bg-gray-100 text-gray-800'
                }`}
              >
                {msg.body}
              </div>
            </div>
          </div>
        ))}
        <div ref={bottomRef} />
      </div>

      {/* Input */}
      <div className="flex items-end gap-2 border-t bg-white p-3">
        <textarea
          className="flex-1 resize-none rounded-xl border border-gray-200 px-3 py-2 text-sm focus:border-[#1A4731] focus:outline-none focus:ring-2 focus:ring-[#1A4731]/30"
          rows={2}
          placeholder="Type a message… (Ctrl+Enter to send)"
          value={draft}
          onChange={(e) => setDraft(e.target.value)}
          onKeyDown={handleKey}
        />
        <button
          type="button"
          onClick={send}
          disabled={!draft.trim() || sending}
          className="shrink-0 rounded-xl bg-[#1A4731] px-4 py-2 text-sm font-medium text-white transition-colors hover:bg-[#143828] disabled:opacity-40"
        >
          {sending ? '…' : 'Send'}
        </button>
      </div>
    </div>
  )
}
