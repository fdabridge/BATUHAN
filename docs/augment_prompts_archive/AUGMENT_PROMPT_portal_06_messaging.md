# Portal Build — Prompt 6 of 8: Messaging System

## ⚠️ CRITICAL: DO NOT BREAK THE EXISTING PORTAL
Purely additive. New API endpoints and new frontend pages only.
The `audit_set_messages` table was created in Prompt 1 — this prompt wires it up.

---

## Context

Every audit set has a message thread accessible from both the internal CB portal and the client
portal. All messages are stored with sender, role, and timestamp — creating a full audit trail
of communication that replaces WhatsApp/email/phone for traceability.

Messages are loaded by polling every 10 seconds (no WebSocket needed).

---

## Task

### Backend: Messaging API

#### Add to `backend/audit_set/client_router.py`

Append these endpoints to the existing client router:

```python
from audit_set.db_models import AuditSetMessage
from pydantic import BaseModel as PydanticBase

class MessageCreateSchema(PydanticBase):
    body: str

# ── Messages (both CB and client access via their respective routers) ────────

@router.get("/my-audit-set/messages")
def get_my_messages(
    db: Session = Depends(get_db),
    current_user: PlatformUser = Depends(get_current_user),
):
    audit_set = _get_client_audit_set(current_user, db)
    msgs = (
        db.query(AuditSetMessage)
        .filter_by(audit_set_id=audit_set.id)
        .order_by(AuditSetMessage.created_at)
        .all()
    )
    return [
        {
            "id": m.id,
            "sender_name": m.sender_name,
            "sender_role": m.sender_role,
            "body": m.body,
            "created_at": m.created_at.isoformat(),
            "is_mine": m.sender_user_id == current_user.id,
        }
        for m in msgs
    ]


@router.post("/my-audit-set/messages")
def post_my_message(
    payload: MessageCreateSchema,
    db: Session = Depends(get_db),
    current_user: PlatformUser = Depends(get_current_user),
):
    audit_set = _get_client_audit_set(current_user, db)
    if not payload.body.strip():
        raise HTTPException(400, "Message body cannot be empty")
    msg = AuditSetMessage(
        audit_set_id=audit_set.id,
        sender_user_id=current_user.id,
        sender_name=current_user.full_name,
        sender_role=current_user.role,
        body=payload.body.strip(),
    )
    db.add(msg)
    db.commit()
    db.refresh(msg)
    return {"id": msg.id, "created_at": msg.created_at.isoformat()}
```

#### New file: `backend/audit_set/messages_router.py`

CB-side message access (for any audit set, not just the current user's):

```python
"""
BATUHAN — Audit set messaging API (CB-side).
CB users (planner, admin, auditor role) can message on any audit set they have access to.
"""
from __future__ import annotations
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from audit_set.db_models import AuditSet, AuditSetMessage, get_db
from auth.db_models import PlatformUser, get_db as get_auth_db
from auth.router import get_current_user
from email_service import send_new_message_notification

router = APIRouter(prefix="/audit-sets", tags=["messages"])

CB_ROLES = {"admin", "planner", "officer", "executive", "auditor"}

class MessageCreateSchema(BaseModel):
    body: str


@router.get("/{audit_set_id}/messages")
def get_messages(
    audit_set_id: str,
    db: Session = Depends(get_db),
    current_user: PlatformUser = Depends(get_current_user),
):
    if current_user.role not in CB_ROLES:
        raise HTTPException(403, "Not authorized")
    msgs = (
        db.query(AuditSetMessage)
        .filter_by(audit_set_id=audit_set_id)
        .order_by(AuditSetMessage.created_at)
        .all()
    )
    return [
        {
            "id": m.id,
            "sender_name": m.sender_name,
            "sender_role": m.sender_role,
            "body": m.body,
            "created_at": m.created_at.isoformat(),
            "is_mine": m.sender_user_id == current_user.id,
        }
        for m in msgs
    ]


@router.post("/{audit_set_id}/messages")
def post_message(
    audit_set_id: str,
    payload: MessageCreateSchema,
    db: Session = Depends(get_db),
    auth_db: Session = Depends(get_auth_db),
    current_user: PlatformUser = Depends(get_current_user),
):
    if current_user.role not in CB_ROLES:
        raise HTTPException(403, "Not authorized")
    audit_set = db.query(AuditSet).filter_by(id=audit_set_id).first()
    if not audit_set:
        raise HTTPException(404, "Audit set not found")
    if not payload.body.strip():
        raise HTTPException(400, "Message body cannot be empty")

    msg = AuditSetMessage(
        audit_set_id=audit_set_id,
        sender_user_id=current_user.id,
        sender_name=current_user.full_name,
        sender_role=current_user.role,
        body=payload.body.strip(),
    )
    db.add(msg)
    db.commit()

    # Notify client if they have an account
    client_user = auth_db.query(PlatformUser).filter_by(
        audit_set_id=audit_set_id, role="client"
    ).first()
    if client_user:
        send_new_message_notification(
            to=client_user.email,
            full_name=client_user.full_name,
            sender_name=current_user.full_name,
        )

    return {"id": msg.id, "created_at": msg.created_at.isoformat()}
```

Register in `backend/main.py`:
```python
from audit_set.messages_router import router as messages_router
app.include_router(messages_router)
```

### Frontend: Shared MessageThread component

#### New file: `frontend/src/components/ui/MessageThread.tsx`

```tsx
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
  fetchUrl: string    // GET URL to load messages
  postUrl: string     // POST URL to send message
  pollInterval?: number
}

const ROLE_LABELS: Record<string, string> = {
  client: 'You',
  admin: 'IFC Global',
  planner: 'IFC Global',
  officer: 'IFC Global',
  auditor: 'Auditor',
  executive: 'IFC Global',
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
    } catch {}
  }

  useEffect(() => {
    load()
    const interval = setInterval(load, pollInterval)
    return () => clearInterval(interval)
  }, [fetchUrl])

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
    <div className="flex flex-col h-full min-h-[400px]">
      {/* Messages */}
      <div className="flex-1 overflow-y-auto p-4 space-y-3">
        {messages.length === 0 && (
          <p className="text-center text-sm text-gray-400 py-8">No messages yet. Start the conversation.</p>
        )}
        {messages.map(msg => (
          <div key={msg.id} className={`flex ${msg.is_mine ? 'justify-end' : 'justify-start'}`}>
            <div className={`max-w-[75%] ${msg.is_mine ? 'items-end' : 'items-start'} flex flex-col`}>
              <span className="text-xs text-gray-400 mb-1 px-1">
                {msg.is_mine ? 'You' : (ROLE_LABELS[msg.sender_role] || msg.sender_name)}
                {' · '}
                {new Date(msg.created_at).toLocaleTimeString([], {hour:'2-digit', minute:'2-digit'})}
              </span>
              <div className={`px-4 py-2.5 rounded-2xl text-sm whitespace-pre-wrap break-words
                ${msg.is_mine
                  ? 'bg-[#1A4731] text-white rounded-tr-sm'
                  : 'bg-gray-100 text-gray-800 rounded-tl-sm'
                }`}>
                {msg.body}
              </div>
            </div>
          </div>
        ))}
        <div ref={bottomRef} />
      </div>

      {/* Input */}
      <div className="border-t p-3 flex gap-2 items-end bg-white">
        <textarea
          className="flex-1 border border-gray-200 rounded-xl px-3 py-2 text-sm resize-none focus:outline-none focus:ring-2 focus:ring-[#1A4731]/30 focus:border-[#1A4731]"
          rows={2}
          placeholder="Type a message… (Ctrl+Enter to send)"
          value={draft}
          onChange={e => setDraft(e.target.value)}
          onKeyDown={handleKey}
        />
        <button
          onClick={send}
          disabled={!draft.trim() || sending}
          className="bg-[#1A4731] text-white px-4 py-2 rounded-xl text-sm font-medium disabled:opacity-40 hover:bg-[#143828] transition-colors shrink-0"
        >
          {sending ? '...' : 'Send'}
        </button>
      </div>
    </div>
  )
}
```

### Frontend: Client Messages page

Replace the placeholder `frontend/src/app/(client)/client/messages/page.tsx`:

```tsx
'use client'
import { MessageThread } from '@/components/ui/MessageThread'

export default function ClientMessagesPage() {
  return (
    <div className="p-6 max-w-2xl mx-auto h-full flex flex-col">
      <div className="mb-4">
        <h1 className="text-xl font-bold text-gray-900">Messages</h1>
        <p className="text-sm text-gray-400 mt-0.5">Communicate with the IFC Global team</p>
      </div>
      <div className="bg-white rounded-xl border flex-1 overflow-hidden">
        <MessageThread
          fetchUrl="/client/my-audit-set/messages"
          postUrl="/client/my-audit-set/messages"
        />
      </div>
    </div>
  )
}
```

### Frontend: Add Messages panel to CB audit set detail page

In `frontend/src/app/(app)/clients/[id]/page.tsx`, add a "Messages" tab or section
at the bottom of the page (below existing content — do NOT reorganize existing sections):

```tsx
// Add after all existing sections:
<div className="mt-8">
  <h2 className="text-sm font-semibold text-gray-700 uppercase tracking-wide mb-3">Client Messages</h2>
  <div className="bg-white rounded-xl border" style={{ height: 400 }}>
    <MessageThread
      fetchUrl={`/audit-sets/${id}/messages`}
      postUrl={`/audit-sets/${id}/messages`}
    />
  </div>
</div>
```

Import `MessageThread` at the top of the file.

### Verify

1. CB can send/receive messages in the audit set detail page
2. Client can send/receive messages in `/client/messages`
3. Messages from CB show as "IFC Global" to the client (not the planner's name)
4. Poll every 10s — new messages appear without page refresh
5. All existing audit set detail content is unchanged

### Commit and push

Commit: `feat(portal): messaging system — CB and client portal threads`
Push to main.

## Files to create/edit
- `backend/audit_set/client_router.py` — add message endpoints (additive)
- `backend/audit_set/messages_router.py` — new (CB-side)
- `backend/main.py` — register messages_router
- `frontend/src/components/ui/MessageThread.tsx` — new shared component
- `frontend/src/app/(client)/client/messages/page.tsx` — replace placeholder
- `frontend/src/app/(app)/clients/[id]/page.tsx` — add Messages section at bottom (additive)
