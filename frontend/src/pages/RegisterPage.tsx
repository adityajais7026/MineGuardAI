import { useState } from 'react'
import { Link, useNavigate } from 'react-router-dom'
import { useAuth } from '../context/AuthContext'
import { authApi } from '../api/endpoints'
import { ApiError } from '../api/client'
import type { RegistrableRole } from '../api/types'

/**
 * Registration with MSG91 SMS OTP verification.
 *
 * Step 1: mobile -> real SMS OTP.                (POST /auth/register/otp/start)
 * Step 2: enter the OTP -> registration token.   (POST /auth/register/otp/verify)
 * Step 3: email + name + password + role.        (POST /auth/register/complete)
 *
 * Role policy (enforced server-side too):
 *  - Mine Manager / Inspector (safety_officer): immediate activation.
 *  - Government Officer / Administrator: invitation-only — never selectable
 *    here. A valid single-use invitation code (from an Administrator) is
 *    required and grants exactly the role it was minted for.
 */
export default function RegisterPage() {
  const { register } = useAuth()
  const navigate = useNavigate()

  const [step, setStep] = useState<'mobile' | 'otp' | 'details'>('mobile')
  const [mobile, setMobile] = useState('')
  const [otp, setOtp] = useState('')
  const [regToken, setRegToken] = useState('')
  const [mobileMasked, setMobileMasked] = useState('')

  const [fullName, setFullName] = useState('')
  const [email, setEmail] = useState('')
  const [password, setPassword] = useState('')
  const [role, setRole] = useState<RegistrableRole>('safety_officer')
  const [invitationCode, setInvitationCode] = useState('')

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
      setStep('details')
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

  async function handleDetails(e: React.FormEvent) {
    e.preventDefault()
    setError(null)
    if (password.length < 8) {
      setError('Password must be at least 8 characters.')
      return
    }
    setBusy(true)
    try {
      await register({
        token: regToken,
        email: email.trim(),
        full_name: fullName.trim(),
        password,
        role,
        invitation_code: invitationCode.trim() || null,
      })
      navigate('/', { replace: true })
    } catch (err) {
      setError(err instanceof ApiError ? err.message : 'Registration failed.')
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="login-wrap">
      <form
        className="login-card"
        onSubmit={step === 'mobile' ? handleMobile : step === 'otp' ? handleOtp : handleDetails}
      >
        <div className="brand login-brand">
          <span className="brand-mark">⛏</span>
          <span className="brand-name">MineGuard<b>AI</b></span>
        </div>
        <p className="login-sub">Create your MineGuardAI account</p>

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

        {step === 'details' && (
          <>
            <label htmlFor="full-name">Full name</label>
            <input id="full-name" type="text" value={fullName} autoFocus
              onChange={(e) => setFullName(e.target.value)} placeholder="Your name" />

            <label htmlFor="reg-email">Email</label>
            <input id="reg-email" type="email" value={email}
              onChange={(e) => setEmail(e.target.value)} placeholder="you@example.com" />

            <label htmlFor="reg-password">Password</label>
            <input id="reg-password" type="password" value={password} autoComplete="new-password"
              onChange={(e) => setPassword(e.target.value)} placeholder="At least 8 characters" />

            <label htmlFor="reg-role">Role</label>
            <select id="reg-role" value={role} onChange={(e) => setRole(e.target.value as RegistrableRole)}>
              <option value="safety_officer">Inspector (Safety Officer)</option>
              <option value="mine_manager">Mine Manager</option>
            </select>

            <label htmlFor="inv-code">Invitation code (optional)</label>
            <input id="inv-code" type="text" value={invitationCode}
              onChange={(e) => setInvitationCode(e.target.value)}
              placeholder="For Government Officer / Administrator invitations" />
            <p className="login-hint">
              Government Officer and Administrator accounts cannot self-register — an
              existing administrator must invite you (Profile → issue invitation). With a
              valid invitation code, your role is granted from the invitation.
            </p>
          </>
        )}

        {notice && <div className="login-hint" role="status">{notice}</div>}
        {error && <div className="form-error" role="alert">{error}</div>}

        <button className="btn btn-primary btn-block" type="submit" disabled={busy}>
          {busy
            ? 'Please wait…'
            : step === 'mobile'
              ? 'Send OTP'
              : step === 'otp'
                ? 'Verify code'
                : 'Create account'}
        </button>

        {step !== 'mobile' && (
          <button type="button" className="btn btn-ghost btn-block"
            onClick={() => {
              setError(null); setNotice(null)
              setStep(step === 'otp' ? 'mobile' : 'otp')
            }}>
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
