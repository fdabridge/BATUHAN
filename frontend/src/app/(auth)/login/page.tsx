'use client'

import { useState, useEffect, type FormEvent } from 'react'
import { useRouter } from 'next/navigation'
import { ArrowRight, Loader2 } from 'lucide-react'
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
  activation_required?: boolean
}

// Role-based landing page after login or auto-rehydrate.
function roleHome(role: string | undefined): string {
  if (role === 'client')     return '/client/overview'
  if (role === 'auditor')    return '/auditor/dashboard'
  if (role === 'consultant') return '/consultant/clients'
  if (role === 'crm')        return '/crm'
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
        activation_required: data.activation_required,
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
    <div
      className="relative flex min-h-screen items-center justify-center overflow-hidden px-4 py-10"
      style={{
        backgroundColor: '#102A20',
        backgroundImage: `
          linear-gradient(135deg, rgba(16,42,32,0.94), rgba(22,70,49,0.78) 48%, rgba(231,242,236,0.72)),
          radial-gradient(circle at 16% 18%, rgba(197,226,211,0.35), transparent 28%),
          radial-gradient(circle at 82% 24%, rgba(255,255,255,0.55), transparent 23%),
          radial-gradient(circle at 62% 86%, rgba(209,167,87,0.22), transparent 30%)
        `,
      }}
    >
      <div className="absolute inset-0 opacity-[0.14]"
        style={{
          backgroundImage:
            'linear-gradient(rgba(255,255,255,.45) 1px, transparent 1px), linear-gradient(90deg, rgba(255,255,255,.45) 1px, transparent 1px)',
          backgroundSize: '44px 44px',
        }}
      />
      <div className="relative grid w-full max-w-5xl items-center gap-8 md:grid-cols-[1fr_400px]">
        <section className="hidden text-white md:block">
          <p className="mb-3 text-xs font-semibold uppercase tracking-[0.24em] text-white/65">
            Certiva Portal
          </p>
          <h1 className="max-w-xl text-5xl font-semibold leading-tight">
            Certiva: The Certification Body Super-App.
          </h1>
          <p className="mt-5 max-w-lg text-base leading-7 text-white/72">
            Run certification work from application to certificate maintenance: planning, document signing,
            auditor coordination, training, CRM follow-up, Certiv.AI audit plans, report writing, and report review.
          </p>
          <div className="mt-7 flex max-w-lg flex-wrap gap-2">
            {['Audit planning', 'Certiv.AI reports', 'Training records', 'Client CRM'].map((item) => (
              <span
                key={item}
                className="rounded-full border border-white/25 bg-white/10 px-3 py-1 text-xs font-medium text-white/82 backdrop-blur"
              >
                {item}
              </span>
            ))}
          </div>
        </section>

        <div className="w-full rounded-2xl border border-white/35 bg-white/95 px-10 py-10 shadow-2xl shadow-emerald-950/20 backdrop-blur">

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
              Username
            </label>
            <Input
              id="email"
              type="text"
              placeholder="username or email"
              value={email}
              onChange={(e) => setEmail(e.target.value)}
              required
              autoComplete="username"
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
            {!submitting && <ArrowRight size={15} />}
          </button>

          {/* 4 — Error state */}
          {error && (
            <p className="text-center text-red-600" style={{ fontSize: 13 }}>
              Invalid username or password.
            </p>
          )}

        </form>
        </div>
      </div>
    </div>
  )
}
