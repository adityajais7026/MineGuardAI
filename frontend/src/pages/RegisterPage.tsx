import { useState } from 'react'
import { Link, useNavigate } from 'react-router-dom'
import { useAuth } from '../context/AuthContext'
import { authApi } from '../api/endpoints'
import { ApiError } from '../api/client'
import type { InvitationValidate } from '../api/types'

const ROLE_LABEL: Record<string, string> = {
  admin: 'Administrator',
  mine_manager: 'Mine Manager',
  safety_officer: 'Safety Officer',
  environmental_officer: 'Government Officer',
}

/**
 * Registration — INVITATION CODE ONLY (no public/open registration).
 *
 * Step 1: invitation code + email -> server validates the pair; the
 *         invitation decides the role (never a dropdown).
 * Step 2: mobile number -> MSG91 SMS OTP.          (POST /auth/register/otp/start)
 * Step 3: enter the OTP -> registration token.     (POST /auth/register/otp/verify)
 * Step 4: create password -> account.              (POST /auth/register/complete)
 *
 * The backend re-validates the code+email pair and the invitation is the
 * source of truth for email/full name/role; the client cannot choose either.
 */
export default function RegisterPage() {
  const { register } = useAuth()
  const navigate = useNavigate()

  const [step, setStep] = useState<'code' | 'mobile' | 'otp' | 'password'>('code')
  const [code, setCode] = useState('')
  const [email, setEmail] = useState('')
  const [invitation, setInvitation] = useState<InvitationValidate | null>(null)

  const [mobile, setMobile] = useState('')
  const [otp, setOtp] = useState('')
  const [regToken, setRegToken] = useState('')
  const [mobileMasked, setMobileMasked] = useState('')

  const [password, setPassword] = useState('')
  const [confirmPassword, setConfirmPassword] = useState('')

  const [error, setError] = useState<string | null>(null)
  const [notice, setNotice] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)
  const [cooldown, setCooldown] = useState(0)

  function startCooldown(seconds: number) {
    setCooldown(seconds)
    const t = setInterval(() => {
      setCooldown((c) => {
        if (c <= 1) clearInterval(t)
        return c - 1
      })
    }, 1000)
  }

  async function handleCode(e: React.FormEvent) {
    e.preventDefault()
    setError(null)
    if (!code.trim()) { setError('Invitation code is required to create an account.'); return }
    if (!email.trim()) { setError('Enter the email address your invitation was issued for.'); return }
    setBusy(true)
    try {
      const inv = await authApi.validateInvitation(code.trim(), email.trim())
      setInvitation(inv)
      setStep('mobile')
    } catch (err) {
      setError(err instanceof ApiError ? err.message : 'Could not validate the invitation code.')
    } finally {
      setBusy(false)
    }
  }

  async function handleMobile(e: React.FormEvent) {
    e.preventDefault()
    setError(null)
    setBusy(true)
    try {
      const res = await authApi.registerOtpStart(mobile.trim())
      setMobileMasked(res.mobile_masked)
      startCooldown(res.cooldown_seconds)
      setStep('otp')
    } catch (err) {
      setError(err instanceof ApiError ? err.message : 'Could not send the OTP.')
    } finally {
      setBusy(false)
    }
  }

  async function handleOtp(e: React.FormEvent) {
    e.preventDefault()
    setError(null)
    setBusy(true)
    try {
      const res = await authApi.registerOtpVerify(mobile.trim(), otp.trim())
      setRegToken(res.token)
      setStep('password')
    } catch (err) {
      setError(err instanceof ApiError ? err.message : 'Verification failed.')
    } finally {
      setBusy(false)
    }
  }

  async function handleResend() {
    setError(null)
    setBusy(true)
    try {
      const res = await authApi.registerOtpStart(mobile.trim())
      setMobileMasked(res.mobile_masked)
      startCooldown(res.cooldown_seconds)
      setNotice(`A new code was sent to ${res.mobile_masked}.`)
    } catch (err) {
      setError(err instanceof ApiError ? err.message : 'Could not resend the OTP.')
    } finally {
      setBusy(false)
    }
  }

  async function handlePassword(e: React.FormEvent) {
    e.preventDefault()
    setError(null)
    if (password.length < 8) { setError('Password must be at least 8 characters.'); return }
    if (password !== confirmPassword) { setError('Passwords do not match.'); return }
    setBusy(true)
    try {
      await register({
        token: regToken,
        email: email.trim(),
        password,
        invitation_code: code.trim(),
      })
      navigate('/', { replace: true })
    } catch (err) {
      setError(err instanceof ApiError ? err.message : 'Registration failed.')
    } finally {
      setBusy(false)
    }
  }

  function goBack() {
    setError(null)
    setNotice(null)
    setStep(step === 'otp' ? 'mobile' : step === 'mobile' ? 'code' : 'otp')
  }

  const submitHandler =
    step === 'code' ? handleCode : step === 'mobile' ? handleMobile : step === 'otp' ? handleOtp : handlePassword

  return (
    <div className="login-wrap">
      <form className="login-card" onSubmit={submitHandler}>
        <div className="brand login-brand">
          <span className="brand-mark">⛏</span>
          <span className="brand-name">MineGuard<b>AI</b></span>
        </div>
        <p className="login-sub">Create your MineGuardAI account</p>

        {step === 'code' && (
          <>
            <label htmlFor="inv-code">Invitation code</label>
            <input
              id="inv-code" type="text" value={code} autoFocus
              onChange={(e) => setCode(e.target.value.toUpperCase())}
              placeholder="XXXX-XXXX-XXXX" autoComplete="off" spellCheck={false}
            />
            <label htmlFor="inv-email">Email</label>
            <input id="inv-email" type="email" value={email}
              onChange={(e) => setEmail(e.target.value)} placeholder="you@example.com" />
            <p className="login-hint">
              Registration is by invitation only. Enter the code and the email address
              it was issued for — the code is strictly tied to that email.
            </p>
          </>
        )}

        {step !== 'code' && invitation && (
          <p className="login-hint">
            Invited: <strong>{invitation.full_name}</strong> ·{' '}
            <span className="badge badge-info">{ROLE_LABEL[invitation.role] ?? invitation.role}</span>
            <br />
            <code>{email}</code> — your role and email come from the invitation and
            cannot be changed here.
          </p>
        )}

        {step === 'mobile' && (
          <>
            <label htmlFor="mobile">Mobile number</label>
            <input
              id="mobile" type="tel" value={mobile} autoFocus
              onChange={(e) => setMobile(e.target.value)}
              placeholder="+91 99999 99999" autoComplete="tel"
            />
            <p className="login-hint">We'll verify it with a one-time SMS code.</p>
          </>
        )}

        {step === 'otp' && (
          <>
            <p className="login-sub">
              Code sent by SMS to <strong>{mobileMasked}</strong>
            </p>
            <label htmlFor="reg-otp">One-time code</label>
            <input
              id="reg-otp" type="text" inputMode="numeric" maxLength={6} autoFocus
              value={otp} autoComplete="one-time-code"
              onChange={(e) => setOtp(e.target.value.replace(/\D/g, ''))}
              placeholder="••••••"
            />
            <button type="button" className="btn btn-ghost" onClick={handleResend} disabled={busy || cooldown > 0}>
              {cooldown > 0 ? `Resend code in ${cooldown}s` : 'Resend code'}
            </button>
          </>
        )}

        {step === 'password' && (
          <>
            <label htmlFor="reg-password">Password</label>
            <input id="reg-password" type="password" value={password} autoFocus
              autoComplete="new-password"
              onChange={(e) => setPassword(e.target.value)}
              placeholder="At least 8 characters" />

            <label htmlFor="reg-confirm">Confirm password</label>
            <input id="reg-confirm" type="password" value={confirmPassword}
              autoComplete="new-password"
              onChange={(e) => setConfirmPassword(e.target.value)}
              placeholder="Repeat the password" />
          </>
        )}

        {notice && <div className="login-hint" role="status">{notice}</div>}
        {error && <div className="form-error" role="alert">{error}</div>}

        <button className="btn btn-primary btn-block" type="submit" disabled={busy}>
          {busy
            ? 'Please wait…'
            : step === 'code'
              ? 'Validate invitation'
              : step === 'mobile'
                ? 'Send OTP'
                : step === 'otp'
                  ? 'Verify code'
                  : 'Create account'}
        </button>

        {step !== 'code' && (
          <button type="button" className="btn btn-ghost btn-block" onClick={goBack}>
            ← Back
          </button>
        )}

        <p className="login-hint">
          Already registered? <Link to="/login">Sign in</Link>
        </p>
      </form>
    </div>
  )
}
