import { useState } from 'react'
import { Link, useLocation, useNavigate } from 'react-router-dom'
import { OtpRequiredError, useAuth } from '../context/AuthContext'
import { ApiError } from '../api/client'

/**
 * Login with MSG91 SMS OTP.
 *
 * Step 1: email + password (validates credentials server-side, then an OTP is
 *         sent to the registered mobile).
 * Step 2: enter the SMS OTP -> same MineGuardAI JWT as the classic flow.
 *
 * Accounts without a registered mobile (seed/demo users) log in with the
 * classic password flow, exactly as before.
 */
export default function LoginPage() {
  const { login, loginVerifyOtp, user } = useAuth()
  const navigate = useNavigate()
  const location = useLocation()
  const initialNotice = (location.state as { notice?: string } | null)?.notice ?? null

  const [step, setStep] = useState<'credentials' | 'otp'>('credentials')
  const [email, setEmail] = useState('')
  const [password, setPassword] = useState('')
  const [otp, setOtp] = useState('')
  const [mobileMasked, setMobileMasked] = useState('')
  const [error, setError] = useState<string | null>(null)
  const [notice] = useState<string | null>(initialNotice)
  const [busy, setBusy] = useState(false)

  if (user) {
    navigate('/', { replace: true })
  }

  async function handleCredentials(e: React.FormEvent) {
    e.preventDefault()
    setError(null)
    if (!email.trim() || !password) {
      setError('Enter both email and password.')
      return
    }
    setBusy(true)
    try {
      await login(email.trim(), password)
      navigate('/', { replace: true })
    } catch (err) {
      if (err instanceof OtpRequiredError) {
        setMobileMasked(err.mobileMasked)
        setStep('otp')
      } else {
        setError(err instanceof ApiError ? err.message : 'Login failed. Please try again.')
      }
    } finally {
      setBusy(false)
    }
  }

  async function handleOtp(e: React.FormEvent) {
    e.preventDefault()
    setError(null)
    if (!otp.trim()) {
      setError('Enter the code sent to your phone.')
      return
    }
    setBusy(true)
    try {
      await loginVerifyOtp(email.trim(), otp.trim())
      navigate('/', { replace: true })
    } catch (err) {
      setError(err instanceof ApiError ? err.message : 'Verification failed. Please try again.')
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="login-wrap">
      <form className="login-card" onSubmit={step === 'credentials' ? handleCredentials : handleOtp}>
        <div className="brand login-brand">
          <span className="brand-mark">⛏</span>
          <span className="brand-name">MineGuard<b>AI</b></span>
        </div>
        <p className="login-sub">Mining safety, environmental monitoring &amp; compliance governance</p>

        {step === 'credentials' ? (
          <>
            <label htmlFor="email">Email</label>
            <input id="email" type="email" value={email} autoComplete="username"
              onChange={(e) => setEmail(e.target.value)} placeholder="admin@mineguard.ai" />

            <label htmlFor="password">Password</label>
            <input id="password" type="password" value={password} autoComplete="current-password"
              onChange={(e) => setPassword(e.target.value)} placeholder="••••••••" />
          </>
        ) : (
          <>
            <p className="login-sub">
              We sent a 6-digit code by SMS to <strong>{mobileMasked}</strong>. Enter it below.
            </p>
            <label htmlFor="otp">One-time code</label>
            <input id="otp" type="text" inputMode="numeric" autoComplete="one-time-code"
              value={otp} onChange={(e) => setOtp(e.target.value.replace(/\D/g, ''))}
              placeholder="••••••" maxLength={6} autoFocus />
          </>
        )}

        {notice && <div className="login-hint" role="status">{notice}</div>}
        {error && <div className="form-error" role="alert">{error}</div>}

        <button className="btn btn-primary btn-block" type="submit" disabled={busy}>
          {busy
            ? 'Please wait…'
            : step === 'credentials'
              ? 'Continue'
              : 'Verify & sign in'}
        </button>

        {step === 'otp' && (
          <button type="button" className="btn btn-ghost btn-block"
            onClick={() => { setStep('credentials'); setOtp(''); setError(null) }}>
            ← Back
          </button>
        )}

        {step === 'credentials' && (
          <p className="login-hint">
            New here? <Link to="/register">Create an account</Link>
          </p>
        )}

        <div className="login-hint">
          <strong>Demo accounts</strong> (no mobile registered — password sign-in):
          <code>admin@mineguard.ai / Admin@123</code><br />
          <code>manager@mineguard.ai / Manager@123</code> · <code>safety@mineguard.ai / Safety@123</code> ·
          <code> env@mineguard.ai / Env@123</code>
        </div>
      </form>
    </div>
  )
}
