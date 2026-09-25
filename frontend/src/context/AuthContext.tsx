import { createContext, useCallback, useContext, useEffect, useMemo, useState } from 'react'
import type { ReactNode } from 'react'
import { authApi } from '../api/endpoints'
import { getStoredToken, setStoredToken } from '../api/client'
import type { User } from '../api/types'

interface AuthContextValue {
  user: User | null
  loading: boolean
  login: (email: string, password: string) => Promise<void>
  logout: () => void
}

const AuthContext = createContext<AuthContextValue | null>(null)

export function AuthProvider({ children }: { children: ReactNode }) {
  const [user, setUser] = useState<User | null>(null)
  const [loading, setLoading] = useState(true)

  // On mount: if a token exists, resolve the profile (validates the session).
  useEffect(() => {
    if (!getStoredToken()) {
      setLoading(false)
      return
    }
    authApi
      .me()
      .then(setUser)
      .catch(() => setStoredToken(null)) // expired/invalid token
      .finally(() => setLoading(false))
  }, [])

  const login = useCallback(async (email: string, password: string) => {
    const res = await authApi.login(email, password)
    setStoredToken(res.access_token)
    setUser(res.user)
  }, [])

  const logout = useCallback(() => {
    setStoredToken(null)
    setUser(null)
  }, [])

  // Any API call answered 401 -> the session died; clear it.
  useEffect(() => {
    const onUnauthorized = () => setUser(null)
    window.addEventListener('mineguardai:unauthorized', onUnauthorized)
    return () => window.removeEventListener('mineguardai:unauthorized', onUnauthorized)
  }, [])

  const value = useMemo(() => ({ user, loading, login, logout }), [user, loading, login, logout])
  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>
}

export function useAuth(): AuthContextValue {
  const ctx = useContext(AuthContext)
  if (!ctx) throw new Error('useAuth must be used inside AuthProvider')
  return ctx
}
