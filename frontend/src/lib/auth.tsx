'use client'

import {
  createContext,
  useContext,
  useEffect,
  useState,
  ReactNode,
} from 'react'
import { useRouter } from 'next/navigation'
import api from '@/lib/api'

export interface User {
  id: string
  email: string
  full_name: string
  role: string
}

interface AuthContextValue {
  user: User | null
  token: string | null
  login: (token: string, user: User) => void
  logout: () => void
  isLoading: boolean
}

const AuthContext = createContext<AuthContextValue | null>(null)

const TOKEN_KEY = 'certiva_token'

export function AuthProvider({ children }: { children: ReactNode }) {
  const router = useRouter()
  const [user, setUser]       = useState<User | null>(null)
  const [token, setToken]     = useState<string | null>(null)
  const [isLoading, setLoading] = useState(true)

  // Hydrate from localStorage on mount
  useEffect(() => {
    const stored = typeof window !== 'undefined'
      ? localStorage.getItem(TOKEN_KEY)
      : null

    if (!stored) {
      setLoading(false)
      return
    }

    setToken(stored)
    api
      .get<User>('/auth/me')
      .then((res) => setUser(res.data))
      .catch(() => {
        localStorage.removeItem(TOKEN_KEY)
        setToken(null)
      })
      .finally(() => setLoading(false))
  }, [])

  function login(newToken: string, newUser: User) {
    localStorage.setItem(TOKEN_KEY, newToken)
    setToken(newToken)
    setUser(newUser)
  }

  function logout() {
    localStorage.removeItem(TOKEN_KEY)
    setToken(null)
    setUser(null)
    router.push('/login')
  }

  return (
    <AuthContext.Provider value={{ user, token, login, logout, isLoading }}>
      {children}
    </AuthContext.Provider>
  )
}

export function useAuth(): AuthContextValue {
  const ctx = useContext(AuthContext)
  if (!ctx) throw new Error('useAuth must be used within <AuthProvider>')
  return ctx
}
