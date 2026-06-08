'use client'

import { useState, useEffect, type FormEvent } from 'react'
import { useRouter } from 'next/navigation'
import { Loader2 } from 'lucide-react'
import { Input } from '@/components/ui/input'
import api from '@/lib/api'
import { useAuth } from '@/lib/auth'

// Backend: POST /auth/login  body: { email, password }  (JSON, not form data)
// Response: { access_token, role, full_name, user_id }

interface LoginResponse {
  access_token: string
  role: string
  full_name: string
  user_id: string
}

// Role-based landing page after login or auto-rehydrate.
function roleHome(role: string | undefined): string {
  if (role === 'client')  return '/client/overview'
  if (role === 'auditor') return '/auditor/dashboard'
  return '/dashboard'
}

// ── Logo mark (44 × 44, same SVG as Sidebar) ─────────────────────────────────

function CertivaLogoMark() {
  return (
    <div
      className="flex h-11 w-11 items-center justify-center rounded-xl"
      style={{ background: '#1A4731' }}
    >
      <svg width="26" height="26" viewBox="0 0 20 20" fill="none">
        <path
          d="M4 2h9l3 3v13H4V2z"
          stroke="white"
          strokeWidth="1.5"
          strokeLinejoin="round"
        />
        <path
          d="M13 2v3h3"
          stroke="white"
          strokeWidth="1.5"
          strokeLinejoin="round"
        />
        <path
          d="M7 10.5l2 2 4-4"
          stroke="white"
          strokeWidth="1.5"
          strokeLinecap="round"
          strokeLinejoin="round"
        />
      </svg>
    </div>
  )
}

// ── Page ──────────────────────────────────────────────────────────────────────

export default function LoginPage() {
  const router = useRouter()
  const { user, isLoading, login } = useAuth()

  const [email,      setEmail]      = useState('')
  const [password,   setPassword]   = useState('')
  const [submitting, setSubmitting] = useState(false)
  const [error,      setError]      = useState(false)

  // Already authenticated → go straight to role-appropriate landing page
  useEffect(() => {
    if (!isLoading && user) {
      router.replace(roleHome(user.role))
    }
  }, [isLoading, user, router])

  async function handleSubmit(e: FormEvent) {
    e.preventDefault()
    setError(false)
    setSubmitting(true)
    try {
      const { data } = await api.post<LoginResponse>('/auth/login', {
        email,
        password,
      })
      login(data.access_token, {
        id:        data.user_id,
        email,
        full_name: data.full_name,
        role:      data.role,
      })
      router.push(roleHome(data.role))
    } catch {
      setError(true)
    } finally {
      setSubmitting(false)
    }
  }

  // Prevent flash of login form while auth context hydrates
  if (isLoading) return null

  return (
    <div className="flex min-h-screen items-center justify-center bg-certiva-surface">
      <div className="w-full max-w-[400px] rounded-xl bg-white px-10 py-10 shadow-sm">

        {/* 1 — Logo block */}
        <div className="mb-6 flex flex-col items-center gap-2">
          <CertivaLogoMark />
          <span
            className="text-certiva-primary"
            style={{ fontSize: 24, fontWeight: 400, letterSpacing: '-0.02em' }}
          >
            certiva
          </span>
        </div>

        {/* 2 — Heading */}
        <p
          className="mb-6 text-center text-gray-500"
          style={{ fontSize: 15, fontWeight: 400 }}
        >
          Sign in to your account
        </p>

        {/* 3 — Form */}
        <form onSubmit={handleSubmit} noValidate className="flex flex-col gap-4">

          <div className="flex flex-col gap-1">
            <label
              htmlFor="email"
              className="text-gray-700"
              style={{ fontSize: 12, fontWeight: 500, letterSpacing: '0.04em', textTransform: 'uppercase' }}
            >
              Email
            </label>
            <Input
              id="email"
              type="email"
              placeholder="you@example.com"
              value={email}
              onChange={(e) => setEmail(e.target.value)}
              required
              autoComplete="email"
            />
          </div>

          <div className="flex flex-col gap-1">
            <label
              htmlFor="password"
              className="text-gray-700"
              style={{ fontSize: 12, fontWeight: 500, letterSpacing: '0.04em', textTransform: 'uppercase' }}
            >
              Password
            </label>
            <Input
              id="password"
              type="password"
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              required
              autoComplete="current-password"
            />
          </div>

          <button
            type="submit"
            disabled={submitting}
            className="mt-1 flex w-full items-center justify-center gap-2 rounded-lg
              py-2.5 text-sm font-medium text-white transition-opacity
              hover:opacity-90 disabled:opacity-60"
            style={{ background: '#1A4731' }}
          >
            {submitting && <Loader2 size={15} className="animate-spin" />}
            Sign in
          </button>

          {/* 4 — Error state */}
          {error && (
            <p className="text-center text-red-600" style={{ fontSize: 13 }}>
              Invalid email or password.
            </p>
          )}

        </form>
      </div>
    </div>
  )
}
