import { useEffect, useState } from 'react'
import { Link, useParams } from 'react-router-dom'
import { invitationsApi } from '../api/endpoints'
import { ApiError, setStoredToken } from '../api/client'
import { useAuth } from '../context/AuthContext'
import type { InvitationPublic } from '../api/types'

const ROLE_LABEL: Record<string, string> = {
  admin: 'Administrator',
  mine_manager: 'Mine Manager',
  safety_officer: 'Safety Officer',
  environmental_officer: 'Government Officer',
}

/**
 * Public accept-invitation page (/accept-invitation/<token>).
 *
 * Validates the token first; expired/used/unknown tokens all show the same
 * generic message (the backend cannot distinguish them either). Acceptance
 * is OTP-gated and mirrors the public registration flow:
 *
 * Step 1: mobile number      -> MSG91 SMS OTP (POST .../mobile/start)
 * Step 2: enter the OTP      -> registration token (POST .../mobile/verify)
 * Step 3: create a password  -> account (POST .../accept/{token})
 *
 * The role comes from the server-side invitation and cannot be changed here.
 */
export default function AcceptInvitationPage() {
  const { token } = useParams<{ token: string }>()
  const { user } = useAuth()

  const [invitation, setInvitation] = useState<InvitationPublic | null>(null)
  const [loading, setLoading] = useState(true)
  const [invalid, setInvalid] = useState(false)

  const [step, setStep] = useState<'mobile' | 'otp' | 'password'>('mobile')
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

  useEffect(() => {
    if (!token) { setInvalid(true); setLoading(false); return }
    let cancelled = false
    invitationsApi.get(token)
      .then((inv) => { if (!cancelled) setInvitation(inv) })
      .catch(() => { if (!cancelled) setInvalid(true) })
      .finally(() => { if (!cancelled) setLoading(false) })
    return () => { cancelled = true }
  }, [token])

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
      const res = await invitationsApi.mobileStart(token!, mobile.trim())
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
      const res = await invitationsApi.mobileVerify(token!, mobile.trim(), otp.trim())
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
      const res = await invitationsApi.mobileStart(token!, mobile.trim())
      setMobileMasked(res.mobile_masked)
      startCooldown(res.cooldown_seconds)
      setNotice(`A new code was sent to ${res.mobile_masked}.`)
    } catch (err) {
      setError(err instanceof ApiError ? err.message : 'Could not resend the OTP.')
    } finally {
      setBusy(false)
    }
  }

  async function handleAccept(e: React.FormEvent) {
    e.preventDefault()
    setError(null)
    if (password.length < 8) { setError('Password must be at least 8 characters.'); return }
    if (password !== confirmPassword) { setError('Passwords do not match.'); return }
    setBusy(true)
    try {
      const res = await invitationsApi.accept(token!, {
        mobile: mobile.trim(),
        regToken,
        password,
        confirmPassword,
      })
      setStoredToken(res.access_token)
      // Full reload so AuthProvider re-resolves the session from the new
      // token (in-memory user state is only set by its mount effect).
      window.location.assign('/')
    } catch (err) {
      setError(err instanceof ApiError ? err.message : 'Could not accept the invitation.')
    } finally {
      setBusy(false)
    }
  }

  function goBack() {
    setError(null)
    setNotice(null)
    setStep(step === 'otp' ? 'mobile' : 'otp')
  }

  return (
    <div className="login-wrap">
      <div className="login-card">
        <div className="brand login-brand">
          <span className="brand-mark">⛏</span>
          <span className="brand-name">MineGuard<b>AI</b></span>
        </div>

        {loading && <p className="login-sub">Validating your invitation…</p>}

        {invalid && (
          <>
            <p className="form-error" role="alert">This invitation is expired or has already been used.</p>
            <p className="login-hint">Ask your Administrator for a new invitation link.</p>
            <Link to="/login" className="btn btn-ghost btn-block">Go to sign in</Link>
          </>
        )}

        {invitation && (
          <>
            <p className="login-sub">You've been invited to join MineGuardAI</p>
            <p>
              <strong>{invitation.full_name}</strong>
              <br />
              <code>{invitation.email}</code>
              <br />
              <span className="badge badge-info">{ROLE_LABEL[invitation.role] ?? invitation.role}</span>
            </p>
            <p className="login-hint">
              Verify your mobile number with the one-time SMS code we send you, then
              create your own password. Your role is fixed by the invitation.
            </p>

            {user && (
              <p className="login-hint">You are currently signed in as <code>{user.email}</code>; accepting will switch accounts.</p>
            )}

            <form onSubmit={step === 'mobile' ? handleMobile : step === 'otp' ? handleOtp : handleAccept}>
              {step === 'mobile' && (
                <>
                  <label htmlFor="acc-mobile">Mobile number</label>
                  <input id="acc-mobile" type="tel" value={mobile} autoFocus
                    onChange={(e) => setMobile(e.target.value)}
                    placeholder="+91 99999 99999" autoComplete="tel" />
                  <p className="login-hint">We'll verify it with a one-time SMS code.</p>
                </>
              )}

              {step === 'otp' && (
                <>
                  <p className="login-sub">
                    Code sent by SMS to <strong>{mobileMasked}</strong>
                  </p>
                  <label htmlFor="acc-otp">One-time code</label>
                  <input id="acc-otp" type="text" inputMode="numeric" maxLength={6} autoFocus
                    value={otp} autoComplete="one-time-code"
                    onChange={(e) => setOtp(e.target.value.replace(/\D/g, ''))}
                    placeholder="••••••" />
                  <button type="button" className="btn btn-ghost" onClick={handleResend} disabled={busy || cooldown > 0}>
                    {cooldown > 0 ? `Resend code in ${cooldown}s` : 'Resend code'}
                  </button>
                </>
              )}

              {step === 'password' && (
                <>
                  <label htmlFor="acc-password">Create password</label>
                  <input id="acc-password" type="password" value={password} autoFocus
                    autoComplete="new-password"
                    onChange={(e) => setPassword(e.target.value)}
                    placeholder="At least 8 characters" />

                  <label htmlFor="acc-confirm">Confirm password</label>
                  <input id="acc-confirm" type="password" value={confirmPassword}
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
                  : step === 'mobile'
                    ? 'Send OTP'
                    : step === 'otp'
                      ? 'Verify code'
                      : 'Create account'}
              </button>
            </form>

            {step !== 'mobile' && (
              <button type="button" className="btn btn-ghost btn-block" onClick={goBack}>
                ← Back
              </button>
            )}

            <p className="login-hint">
              Expires {new Date(invitation.expires_at).toLocaleString()} — single-use.
            </p>
          </>
        )}
      </div>
    </div>
  )
}
