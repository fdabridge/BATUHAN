'use client'

import { useState, useEffect, type FormEvent } from 'react'
import { useRouter } from 'next/navigation'
import { ArrowRight, Loader2 } from 'lucide-react'
import { Input } from '@/components/ui/input'
import api from '@/lib/api'
import { useAuth } from '@/lib/auth'
import { CertivaLogo } from '@/components/brand/CertivaLogo'

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
  if (role === 'training_officer') return '/training/dashboard'
  return '/dashboard'
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
    <div className="relative flex min-h-screen items-center justify-center overflow-hidden bg-certiva-night px-4 py-10">
      <div className="absolute inset-0 opacity-[0.06]"
        style={{
          backgroundImage:
            'linear-gradient(rgba(216,243,220,.45) 1px, transparent 1px), linear-gradient(90deg, rgba(216,243,220,.45) 1px, transparent 1px)',
          backgroundSize: '64px 64px',
        }}
      />
      <div className="relative grid w-full max-w-5xl items-center gap-8 md:grid-cols-[1fr_400px]">
        <section className="hidden text-white md:block">
          <CertivaLogo variant="reversed" className="mb-10 h-11 w-auto" />
          <p className="mb-3 text-xs font-bold uppercase tracking-[0.2em] text-certiva-signal">
            Controlled certification operations
          </p>
          <h1 className="max-w-xl text-5xl font-bold leading-[1.08]">
            Certification work, connected from application to decision.
          </h1>
          <p className="mt-5 max-w-lg text-base leading-7 text-white/65">
            Each person sees the current handoff, the action assigned to them, and the records needed to complete it. Technical judgment and certification decisions remain with the certification body.
          </p>
          <div className="mt-8 max-w-lg border-l border-certiva-signal/60 pl-4 text-sm leading-6 text-certiva-pale">
            One next action. Clear ownership. The complete case record remains available.
          </div>
        </section>

        <div className="w-full rounded-2xl border border-white/35 bg-white/95 px-10 py-10 shadow-2xl shadow-emerald-950/20 backdrop-blur">

        {/* 1 — Logo block */}
        <div className="mb-6 flex flex-col items-center gap-2">
          <CertivaLogo className="h-11 w-auto" />
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
            className="certiva-button-primary mt-1 flex w-full items-center justify-center gap-2
              py-2.5 text-sm font-semibold disabled:opacity-60"
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
