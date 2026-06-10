# Prompt 22 — User Signature Profile: Draw or Upload a Personal Signature

## Context

This is the Certiva platform. We are building a DocuSign-like visual signing layer across all portals.

Prompt 21 injected `[SIG:PARTY]` placeholder text into every DOCX template. The next three prompts build the full signing pipeline:

- **Prompt 22 (this one)**: Every user (CB staff, auditor, client) saves a personal visual signature — drawn on-screen with a mouse/touch, or uploaded as a scanned image with automatic white-background removal. Stored in the DB. A signature settings page is added to all three portals.
- Prompt 23: DOCX → PDF conversion pipeline + pdfplumber extracts `[SIG:...]` bounding boxes at upload time into a `document_signature_fields` table.
- Prompt 24: In-portal PDF viewer with clickable signature overlay boxes.
- Prompt 25: Visual signing + OTP commit, guest FR.225 inline signing.
- Prompt 26: PDF flattening + final document delivery.

---

## Confirmed existing state (verified by reading source files)

- `auth/db_models.py` defines `Base`, `engine`, `PlatformUser`, `create_tables()` which calls `Base.metadata.create_all(bind=engine)`. Adding a new `UserSignature` model to `auth/db_models.py` is all that's needed for the table to be created on next deploy — no migration script required.
- `auth/dependencies.py` exports `get_current_user` — returns `PlatformUser` from JWT. Available in all routers.
- `main.py` registers routers via `app.include_router(...)`. Pattern is already established for adding new routers.
- CB portal uses `components/layout/Sidebar.tsx` with `NAV_BOTTOM` array; Settings is already a nav item at `/settings`.
- CB portal already has `app/(app)/settings/page.tsx` (branding info page). The signature page goes at `/settings/signature` — a separate sub-route.
- Auditor portal sidebar is inline in `app/(auditor)/layout.tsx` with a simple `NAV` array.
- Client portal sidebar is inline in `app/(client)/layout.tsx` with a simple `NAV` array.
- `api` is the authenticated axios instance at `@/lib/api`. `useAuth` is at `@/lib/auth`.

---

## Change 1 of 6 — `backend/auth/db_models.py`

### 1a. Add `UserSignature` model

At the end of the file (after `PlatformUser`), add:

```python
class UserSignature(Base):
    __tablename__ = "user_signatures"

    id         = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    user_id    = Column(String, nullable=False, unique=True, index=True)  # soft FK → platform_users.id
    image_data = Column(String, nullable=False)  # base64 PNG data URL (data:image/png;base64,...)
    source     = Column(String, nullable=False)  # "drawn" | "uploaded"
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)
```

No changes to `create_tables()` are needed — `Base.metadata.create_all(bind=engine)` already handles new models.

---

## Change 2 of 6 — `backend/auth/user_signature_router.py` (new file)

Create this file:

```python
"""
Certiva — User Signature Profile (Prompt 22).

Every user (CB / auditor / client) may save one personal signature image.
The image is a base64 PNG data URL, captured via canvas draw or image upload
with white-background removal.

Routes:
  GET    /me/signature   → current user's signature or null
  POST   /me/signature   → upsert signature
  DELETE /me/signature   → remove signature
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from auth.db_models import UserSignature, get_db
from auth.dependencies import get_current_user
from auth.db_models import PlatformUser

router = APIRouter(prefix="/me", tags=["user_signature"])

# Max allowed base64 size ≈ 500 KB — generous for a signature PNG
_MAX_DATA_LEN = 700_000


class SignatureIn(BaseModel):
    image_data: str   # must be "data:image/png;base64,..."
    source: str       # "drawn" | "uploaded"


# ── GET ───────────────────────────────────────────────────────────────────────

@router.get("/signature")
def get_my_signature(
    db:           Session    = Depends(get_db),
    current_user: PlatformUser = Depends(get_current_user),
):
    sig = db.query(UserSignature).filter_by(user_id=current_user.id).first()
    if not sig:
        return None
    return {
        "image_data": sig.image_data,
        "source":     sig.source,
        "created_at": sig.created_at.isoformat(),
        "updated_at": sig.updated_at.isoformat(),
    }


# ── POST (upsert) ─────────────────────────────────────────────────────────────

@router.post("/signature")
def save_my_signature(
    body:         SignatureIn,
    db:           Session    = Depends(get_db),
    current_user: PlatformUser = Depends(get_current_user),
):
    if not body.image_data.startswith("data:image/png;base64,"):
        raise HTTPException(400, "image_data must be a PNG data URL (data:image/png;base64,...)")
    if len(body.image_data) > _MAX_DATA_LEN:
        raise HTTPException(400, "Signature image is too large. Maximum is ~500 KB.")
    if body.source not in ("drawn", "uploaded"):
        raise HTTPException(400, "source must be 'drawn' or 'uploaded'")

    sig = db.query(UserSignature).filter_by(user_id=current_user.id).first()
    if sig:
        sig.image_data = body.image_data
        sig.source     = body.source
    else:
        sig = UserSignature(
            user_id=current_user.id,
            image_data=body.image_data,
            source=body.source,
        )
        db.add(sig)

    db.commit()
    db.refresh(sig)
    return {"saved": True, "source": sig.source, "updated_at": sig.updated_at.isoformat()}


# ── DELETE ────────────────────────────────────────────────────────────────────

@router.delete("/signature")
def delete_my_signature(
    db:           Session    = Depends(get_db),
    current_user: PlatformUser = Depends(get_current_user),
):
    deleted = db.query(UserSignature).filter_by(user_id=current_user.id).delete()
    db.commit()
    return {"deleted": bool(deleted)}
```

---

## Change 3 of 6 — `backend/main.py`

### 3a. Add import (near the other auth/admin imports)

```python
from auth.user_signature_router import router as user_signature_router
```

### 3b. Register router

After the `app.include_router(auth_router, ...)` line, add:

```python
app.include_router(user_signature_router)
```

---

## Change 4 of 6 — `frontend/src/components/SignatureSettings.tsx` (new file)

This is the shared component used by all three portal signature pages. It renders identically in all three portals — just the surrounding chrome (sidebar) differs.

```tsx
'use client'

import { useCallback, useEffect, useRef, useState } from 'react'
import { PenLine, Upload, Trash2, Save, RotateCcw, CheckCircle } from 'lucide-react'
import api from '@/lib/api'

// ── Types ─────────────────────────────────────────────────────────────────────

interface ExistingSig {
  image_data: string
  source: 'drawn' | 'uploaded'
  updated_at: string
}

type Tab = 'draw' | 'upload'

// ── White background removal ──────────────────────────────────────────────────

function removeWhiteBackground(file: File): Promise<string> {
  return new Promise((resolve, reject) => {
    const reader = new FileReader()
    reader.onerror = reject
    reader.onload = (e) => {
      const src = e.target?.result as string
      const img = new Image()
      img.onerror = reject
      img.onload = () => {
        // Scale down to max 600 × 200 px (signature should be wide and thin)
        const MAX_W = 600
        const MAX_H = 200
        let w = img.naturalWidth
        let h = img.naturalHeight
        if (w > MAX_W) { h = Math.round(h * MAX_W / w); w = MAX_W }
        if (h > MAX_H) { w = Math.round(w * MAX_H / h); h = MAX_H }

        const canvas = document.createElement('canvas')
        canvas.width  = w
        canvas.height = h
        const ctx = canvas.getContext('2d')!

        // Draw on white background, then process
        ctx.fillStyle = '#ffffff'
        ctx.fillRect(0, 0, w, h)
        ctx.drawImage(img, 0, 0, w, h)

        const imageData = ctx.getImageData(0, 0, w, h)
        const d = imageData.data
        for (let i = 0; i < d.length; i += 4) {
          // If pixel is close to white, make transparent
          if (d[i] > 220 && d[i + 1] > 220 && d[i + 2] > 220) {
            d[i + 3] = 0
          }
        }
        ctx.clearRect(0, 0, w, h)
        ctx.putImageData(imageData, 0, 0)

        resolve(canvas.toDataURL('image/png'))
      }
      img.src = src
    }
    reader.readAsDataURL(file)
  })
}

// ── Draw pad ──────────────────────────────────────────────────────────────────

function DrawPad({ onReady }: { onReady: (getDataUrl: () => string | null) => void }) {
  const canvasRef   = useRef<HTMLCanvasElement>(null)
  const isDrawing   = useRef(false)
  const hasStrokes  = useRef(false)
  const lastPos     = useRef<{ x: number; y: number } | null>(null)

  const getCtx = () => canvasRef.current?.getContext('2d') ?? null

  const getPos = (e: MouseEvent | TouchEvent): { x: number; y: number } | null => {
    const canvas = canvasRef.current
    if (!canvas) return null
    const rect = canvas.getBoundingClientRect()
    const src  = 'touches' in e ? e.touches[0] : e
    return {
      x: (src.clientX - rect.left) * (canvas.width  / rect.width),
      y: (src.clientY - rect.top)  * (canvas.height / rect.height),
    }
  }

  // Initialise canvas (DPR-aware)
  useEffect(() => {
    const canvas = canvasRef.current
    if (!canvas) return
    const dpr  = window.devicePixelRatio || 1
    const rect = canvas.getBoundingClientRect()
    canvas.width  = rect.width  * dpr
    canvas.height = rect.height * dpr
    const ctx = canvas.getContext('2d')!
    ctx.scale(dpr, dpr)
    ctx.lineWidth   = 2.5
    ctx.lineCap     = 'round'
    ctx.lineJoin    = 'round'
    ctx.strokeStyle = '#1A4731'

    // Expose getter to parent
    onReady(() => {
      if (!hasStrokes.current) return null
      return canvas.toDataURL('image/png')
    })
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  const startDraw = useCallback((e: MouseEvent | TouchEvent) => {
    e.preventDefault()
    isDrawing.current = true
    lastPos.current   = getPos(e)
  }, [])

  const draw = useCallback((e: MouseEvent | TouchEvent) => {
    e.preventDefault()
    if (!isDrawing.current) return
    const ctx = getCtx()
    const pos = getPos(e)
    if (!ctx || !pos || !lastPos.current) return
    ctx.beginPath()
    ctx.moveTo(lastPos.current.x, lastPos.current.y)
    ctx.lineTo(pos.x, pos.y)
    ctx.stroke()
    lastPos.current = pos
    hasStrokes.current = true
  }, [])

  const stopDraw = useCallback(() => {
    isDrawing.current = false
    lastPos.current   = null
  }, [])

  const clearCanvas = () => {
    const canvas = canvasRef.current
    const ctx    = getCtx()
    if (!canvas || !ctx) return
    const dpr = window.devicePixelRatio || 1
    const rect = canvas.getBoundingClientRect()
    ctx.clearRect(0, 0, rect.width * dpr, rect.height * dpr)
    hasStrokes.current = false
  }

  useEffect(() => {
    const canvas = canvasRef.current
    if (!canvas) return
    canvas.addEventListener('mousedown',  startDraw as EventListener)
    canvas.addEventListener('mousemove',  draw      as EventListener)
    canvas.addEventListener('mouseup',    stopDraw)
    canvas.addEventListener('mouseleave', stopDraw)
    canvas.addEventListener('touchstart', startDraw as EventListener, { passive: false })
    canvas.addEventListener('touchmove',  draw      as EventListener, { passive: false })
    canvas.addEventListener('touchend',   stopDraw)
    return () => {
      canvas.removeEventListener('mousedown',  startDraw as EventListener)
      canvas.removeEventListener('mousemove',  draw      as EventListener)
      canvas.removeEventListener('mouseup',    stopDraw)
      canvas.removeEventListener('mouseleave', stopDraw)
      canvas.removeEventListener('touchstart', startDraw as EventListener)
      canvas.removeEventListener('touchmove',  draw      as EventListener)
      canvas.removeEventListener('touchend',   stopDraw)
    }
  }, [startDraw, draw, stopDraw])

  return (
    <div>
      <canvas
        ref={canvasRef}
        className="w-full cursor-crosshair rounded-lg border-2 border-dashed border-gray-300 bg-white"
        style={{ height: 150, touchAction: 'none' }}
      />
      <button
        type="button"
        onClick={clearCanvas}
        className="mt-2 flex items-center gap-1.5 text-sm text-gray-400 hover:text-gray-600"
      >
        <RotateCcw size={14} />
        Clear
      </button>
    </div>
  )
}

// ── Main component ────────────────────────────────────────────────────────────

export function SignatureSettings() {
  const [existing,       setExisting]       = useState<ExistingSig | null | 'loading'>('loading')
  const [activeTab,      setActiveTab]      = useState<Tab>('draw')
  const [uploadPreview,  setUploadPreview]  = useState<string | null>(null)
  const [isSaving,       setIsSaving]       = useState(false)
  const [isDeleting,     setIsDeleting]     = useState(false)
  const [statusMsg,      setStatusMsg]      = useState<{ type: 'ok' | 'err'; text: string } | null>(null)

  // Ref to the DrawPad's getDataUrl function
  const getDrawDataUrl = useRef<(() => string | null) | null>(null)

  // ── Load existing signature ─────────────────────────────────────────────────
  useEffect(() => {
    api.get('/me/signature')
      .then((r) => setExisting(r.data ?? null))
      .catch(() => setExisting(null))
  }, [])

  // ── Upload handler ──────────────────────────────────────────────────────────
  const handleFileChange = async (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0]
    if (!file) return
    if (file.size > 8 * 1024 * 1024) {
      setStatusMsg({ type: 'err', text: 'File too large. Maximum 8 MB.' })
      return
    }
    try {
      const processed = await removeWhiteBackground(file)
      setUploadPreview(processed)
      setStatusMsg(null)
    } catch {
      setStatusMsg({ type: 'err', text: 'Could not process the image. Please try a JPG or PNG file.' })
    }
  }

  // ── Save ────────────────────────────────────────────────────────────────────
  const handleSave = async () => {
    let imageData: string | null = null
    let source: 'drawn' | 'uploaded' = activeTab === 'draw' ? 'drawn' : 'uploaded'

    if (activeTab === 'draw') {
      imageData = getDrawDataUrl.current?.() ?? null
      if (!imageData) {
        setStatusMsg({ type: 'err', text: 'Please draw your signature before saving.' })
        return
      }
    } else {
      imageData = uploadPreview
      if (!imageData) {
        setStatusMsg({ type: 'err', text: 'Please upload an image first.' })
        return
      }
    }

    setIsSaving(true)
    setStatusMsg(null)
    try {
      await api.post('/me/signature', { image_data: imageData, source })
      // Refresh
      const r = await api.get('/me/signature')
      setExisting(r.data ?? null)
      setStatusMsg({ type: 'ok', text: 'Signature saved successfully.' })
    } catch (err: unknown) {
      const msg = (err as { response?: { data?: { detail?: string } } })?.response?.data?.detail ?? 'Failed to save signature.'
      setStatusMsg({ type: 'err', text: msg })
    } finally {
      setIsSaving(false)
    }
  }

  // ── Delete ──────────────────────────────────────────────────────────────────
  const handleDelete = async () => {
    if (!confirm('Remove your saved signature?')) return
    setIsDeleting(true)
    try {
      await api.delete('/me/signature')
      setExisting(null)
      setUploadPreview(null)
      setStatusMsg({ type: 'ok', text: 'Signature removed.' })
    } catch {
      setStatusMsg({ type: 'err', text: 'Failed to remove signature.' })
    } finally {
      setIsDeleting(false)
    }
  }

  // ── Render ──────────────────────────────────────────────────────────────────
  if (existing === 'loading') {
    return <p className="text-sm text-gray-400">Loading…</p>
  }

  return (
    <div className="mx-auto max-w-xl space-y-6">
      <div>
        <h2 className="text-lg font-semibold text-gray-900">My Signature</h2>
        <p className="mt-1 text-sm text-gray-500">
          This signature will be placed on documents you sign in the Certiva portal. Draw it
          with your mouse or trackpad, or upload a photo of your handwritten signature.
        </p>
      </div>

      {/* Current signature preview */}
      {existing && (
        <div className="rounded-xl border border-gray-200 bg-white p-4">
          <p className="mb-2 text-xs font-medium uppercase tracking-wide text-gray-400">
            Current saved signature
          </p>
          <div className="flex items-center justify-between gap-4">
            <img
              src={existing.image_data}
              alt="Your saved signature"
              className="h-16 max-w-[300px] object-contain"
              style={{ background: 'repeating-conic-gradient(#f0f0f0 0% 25%, #fff 0% 50%) 0 0 / 12px 12px' }}
            />
            <button
              type="button"
              onClick={handleDelete}
              disabled={isDeleting}
              className="flex items-center gap-1.5 rounded-lg border border-red-200 px-3 py-1.5
                text-sm text-red-500 hover:bg-red-50 disabled:opacity-50"
            >
              <Trash2 size={14} />
              {isDeleting ? 'Removing…' : 'Remove'}
            </button>
          </div>
          <p className="mt-2 text-xs text-gray-400">
            Saved {new Date(existing.updated_at).toLocaleDateString()} · source: {existing.source}
          </p>
        </div>
      )}

      {/* Tabs */}
      <div className="rounded-xl border border-gray-200 bg-white">
        {/* Tab bar */}
        <div className="flex border-b border-gray-100">
          {([['draw', 'Draw', PenLine], ['upload', 'Upload photo', Upload]] as const).map(([tab, label, Icon]) => (
            <button
              key={tab}
              type="button"
              onClick={() => { setActiveTab(tab); setStatusMsg(null) }}
              className={[
                'flex flex-1 items-center justify-center gap-2 py-3 text-sm font-medium transition-colors',
                activeTab === tab
                  ? 'border-b-2 border-[#1A4731] text-[#1A4731]'
                  : 'text-gray-400 hover:text-gray-600',
              ].join(' ')}
            >
              <Icon size={16} />
              {label}
            </button>
          ))}
        </div>

        <div className="p-5">
          {/* Draw tab */}
          {activeTab === 'draw' && (
            <div className="space-y-3">
              <p className="text-xs text-gray-400">
                Draw your signature in the box below using your mouse or finger.
              </p>
              <DrawPad
                onReady={(fn) => { getDrawDataUrl.current = fn }}
              />
            </div>
          )}

          {/* Upload tab */}
          {activeTab === 'upload' && (
            <div className="space-y-3">
              <p className="text-xs text-gray-400">
                Upload a JPG or PNG photo of your handwritten signature on white paper.
                The white background will be removed automatically.
              </p>
              <label className="flex cursor-pointer flex-col items-center justify-center rounded-lg
                border-2 border-dashed border-gray-300 bg-gray-50 p-6 transition-colors hover:border-gray-400">
                <Upload size={24} className="mb-2 text-gray-400" />
                <span className="text-sm text-gray-500">Click to select an image</span>
                <span className="mt-1 text-xs text-gray-400">JPG, PNG — max 8 MB</span>
                <input
                  type="file"
                  accept="image/jpeg,image/png"
                  className="sr-only"
                  onChange={handleFileChange}
                />
              </label>
              {uploadPreview && (
                <div className="rounded-lg border border-gray-200 p-3">
                  <p className="mb-2 text-xs font-medium text-gray-400">Preview (background removed)</p>
                  <img
                    src={uploadPreview}
                    alt="Processed signature preview"
                    className="h-20 max-w-full object-contain"
                    style={{ background: 'repeating-conic-gradient(#f0f0f0 0% 25%, #fff 0% 50%) 0 0 / 12px 12px' }}
                  />
                </div>
              )}
            </div>
          )}

          {/* Status message */}
          {statusMsg && (
            <div className={[
              'mt-3 flex items-center gap-2 rounded-lg px-3 py-2 text-sm',
              statusMsg.type === 'ok'
                ? 'bg-emerald-50 text-emerald-700'
                : 'bg-red-50 text-red-600',
            ].join(' ')}>
              {statusMsg.type === 'ok' && <CheckCircle size={15} />}
              {statusMsg.text}
            </div>
          )}

          {/* Save button */}
          <button
            type="button"
            onClick={handleSave}
            disabled={isSaving}
            className="mt-4 flex w-full items-center justify-center gap-2 rounded-lg py-2.5
              text-sm font-medium text-white transition-opacity disabled:opacity-60"
            style={{ background: '#1A4731' }}
          >
            <Save size={16} />
            {isSaving ? 'Saving…' : existing ? 'Update Signature' : 'Save Signature'}
          </button>
        </div>
      </div>
    </div>
  )
}
```

---

## Change 5 of 6 — Portal signature pages (3 new files)

### `frontend/src/app/(app)/settings/signature/page.tsx`

```tsx
import { SignatureSettings } from '@/components/SignatureSettings'

export default function CBSignaturePage() {
  return (
    <div className="mx-auto max-w-[1200px] py-4">
      <h1 className="mb-6 text-gray-800" style={{ fontSize: 22, fontWeight: 500 }}>
        My Signature
      </h1>
      <SignatureSettings />
    </div>
  )
}
```

### `frontend/src/app/(auditor)/auditor/signature/page.tsx`

```tsx
import { SignatureSettings } from '@/components/SignatureSettings'

export default function AuditorSignaturePage() {
  return (
    <div className="p-6">
      <h1 className="mb-6 text-xl font-semibold text-gray-900">My Signature</h1>
      <SignatureSettings />
    </div>
  )
}
```

### `frontend/src/app/(client)/client/signature/page.tsx`

```tsx
import { SignatureSettings } from '@/components/SignatureSettings'

export default function ClientSignaturePage() {
  return (
    <div className="p-6">
      <h1 className="mb-6 text-xl font-semibold text-gray-900">My Signature</h1>
      <SignatureSettings />
    </div>
  )
}
```

---

## Change 6 of 6 — Navigation (3 files)

### 6a. `frontend/src/components/layout/Sidebar.tsx` (CB portal)

Add `PenLine` to the lucide-react import at the top of the file:

```tsx
import {
  LayoutDashboard,
  Building2,
  Sparkles,
  Users,
  Calculator,
  Inbox,
  PenLine,     // ← add
  UserCog,
  Settings,
  type LucideIcon,
} from 'lucide-react'
```

Add the item to `NAV_BOTTOM` (before `Settings`, after `UserCog`):

```tsx
const NAV_BOTTOM: NavItemProps[] = [
  { icon: UserCog,  label: 'Users',        href: '/admin/users',        active: false },
  { icon: PenLine,  label: 'My Signature', href: '/settings/signature', active: false },
  { icon: Settings, label: 'Settings',     href: '/settings',           active: false },
]
```

### 6b. `frontend/src/app/(auditor)/layout.tsx` (Auditor portal)

Add `My Signature` to the `NAV` array:

```tsx
const NAV = [
  { href: '/auditor/dashboard',  label: 'My Audits'     },
  { href: '/auditor/signature',  label: 'My Signature'  },
]
```

### 6c. `frontend/src/app/(client)/layout.tsx` (Client portal)

Add `My Signature` to the `NAV` array:

```tsx
const NAV = [
  { href: '/client/overview',    label: 'Overview'      },
  { href: '/client/documents',   label: 'Documents'     },
  { href: '/client/assessments', label: 'Assessments'   },
  { href: '/client/messages',    label: 'Messages'      },
  { href: '/client/signature',   label: 'My Signature'  },
]
```

---

## What is NOT changing

- No existing routes or components are modified other than the three nav changes above.
- No changes to any existing DB models (only adding a new `UserSignature` model).
- No changes to the signing flow (OTP system) — that remains untouched until Prompt 25.
- No changes to any of the three portal layouts beyond the `NAV` array additions.
- `FR.225`, `FR.234`, or any template files are not touched.
- No new npm packages — the drawing pad uses native Canvas API only, no `signature_pad` library.

---

## Verification checklist

1. `npx tsc --noEmit` passes with no new errors.
2. `GET /me/signature` returns `null` for a new user, `{ image_data, source, created_at, updated_at }` after saving.
3. `POST /me/signature` with a valid PNG data URL returns `{ saved: true, source, updated_at }`.
4. `POST /me/signature` with an oversized or non-PNG payload returns HTTP 400.
5. Navigate to `/settings/signature` in the CB portal → page renders with draw pad and upload tab.
6. Navigate to `/auditor/signature` → same component renders.
7. Navigate to `/client/signature` → same component renders.
8. Draw a signature, click Save → preview appears in the "Current saved signature" box.
9. Upload a JPG scan → white background removed in preview → Save → preview appears.
10. Click Remove → confirmation, then preview disappears.
11. `PenLine` icon appears in the CB sidebar between "Users" and "Settings".
12. "My Signature" link appears in the Auditor and Client sidebars.

---

## Commit message

```
feat(portal): user signature profile — draw or upload personal signature (Prompt 22)

Backend:
- auth/db_models.py: add UserSignature model (user_id unique, image_data TEXT, source)
- auth/user_signature_router.py: GET/POST/DELETE /me/signature with 500KB size guard
- main.py: register user_signature_router

Frontend:
- components/SignatureSettings.tsx: shared component with DrawPad (canvas, DPR-aware,
  mouse+touch), Upload tab (white background removal via Canvas API), current sig preview,
  delete button, save/update flow
- app/(app)/settings/signature/page.tsx: CB portal signature page
- app/(auditor)/auditor/signature/page.tsx: Auditor portal signature page
- app/(client)/client/signature/page.tsx: Client portal signature page
- Sidebar.tsx: add PenLine "My Signature" nav item → /settings/signature
- (auditor)/layout.tsx: add My Signature to NAV
- (client)/layout.tsx: add My Signature to NAV
```
