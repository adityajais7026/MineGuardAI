import { createContext, useCallback, useContext, useEffect, useMemo, useState } from 'react'
import type { ReactNode } from 'react'
import { authApi } from '../api/endpoints'
import { getStoredToken, setStoredToken } from '../api/client'
import type { LoginResponse, RegisterCompleteRequest, RegisterCompleteResponse, User } from '../api/types'

interface AuthContextValue {
  user: User | null
  loading: boolean
  login: (email: string, password: string) => Promise<void>
  /** OTP step 2 of login: verify the SMS code -> stores the same JWT. */
  loginVerifyOtp: (email: string, otp: string) => Promise<void>
  /** Full OTP registration (invitation-code only; every successful
   *  registration issues a JWT). */
  register: (payload: RegisterCompleteRequest) => Promise<RegisterCompleteResponse>
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
    // If the account has a registered mobile, the backend requires the SMS
    // OTP step; otherwise this resolves exactly like the classic login.
    try {
      const start = await authApi.loginOtpStart(email, password)
      if (start.otp_required) {
        throw new OtpRequiredError(start.mobile_masked ?? '')
      }
      const res = await authApi.login(email, password)
      setStoredToken(res.access_token)
      setUser(res.user)
    } catch (err) {
      if (err instanceof OtpRequiredError) throw err
      // OTP flow unavailable (older backend?) -> fall back to classic login.
      const res = await authApi.login(email, password)
      setStoredToken(res.access_token)
      setUser(res.user)
    }
  }, [])

  const loginVerifyOtp = useCallback(async (email: string, otp: string) => {
    const res: LoginResponse = await authApi.loginOtpVerify(email, otp)
    setStoredToken(res.access_token)
    setUser(res.user)
  }, [])

  const register = useCallback(async (payload: RegisterCompleteRequest) => {
    const res = await authApi.registerComplete(payload)
    setStoredToken(res.access_token)
    setUser(res.user)
    return res
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

  const value = useMemo(
    () => ({ user, loading, login, loginVerifyOtp, register, logout }),
    [user, loading, login, loginVerifyOtp, register, logout],
  )
  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>
}

/** Thrown by `login` when the backend demands the SMS OTP step. */
export class OtpRequiredError extends Error {
  mobileMasked: string
  constructor(mobileMasked: string) {
    super('OTP required')
    this.name = 'OtpRequiredError'
    this.mobileMasked = mobileMasked
  }
}

export function useAuth(): AuthContextValue {
  const ctx = useContext(AuthContext)
  if (!ctx) throw new Error('useAuth must be used inside AuthProvider')
  return ctx
}
