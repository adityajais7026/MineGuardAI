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
 * generic message (the backend cannot distinguish them either). On success
 * the invited person sets their own password; the role comes from the
 * server-side invitation and cannot be changed here. No MSG91/SMS involved.
 */
export default function AcceptInvitationPage() {
  const { token } = useParams<{ token: string }>()
  const { user } = useAuth()

  const [invitation, setInvitation] = useState<InvitationPublic | null>(null)
  const [loading, setLoading] = useState(true)
  const [invalid, setInvalid] = useState(false)

  const [password, setPassword] = useState('')
  const [confirmPassword, setConfirmPassword] = useState('')
  const [error, setError] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)

  useEffect(() => {
    if (!token) { setInvalid(true); setLoading(false); return }
    let cancelled = false
    invitationsApi.get(token)
      .then((inv) => { if (!cancelled) setInvitation(inv) })
      .catch(() => { if (!cancelled) setInvalid(true) })
      .finally(() => { if (!cancelled) setLoading(false) })
    return () => { cancelled = true }
  }, [token])

  async function handleAccept(e: React.FormEvent) {
    e.preventDefault()
    setError(null)
    if (password.length < 8) { setError('Password must be at least 8 characters.'); return }
    if (password !== confirmPassword) { setError('Passwords do not match.'); return }
    setBusy(true)
    try {
      const res = await invitationsApi.accept(token!, password, confirmPassword)
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
              Your role is fixed by the invitation. Create your own password below —
              no SMS verification is needed.
            </p>

            {user && (
              <p className="login-hint">You are currently signed in as <code>{user.email}</code>; accepting will switch accounts.</p>
            )}

            <form onSubmit={handleAccept}>
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

              {error && <div className="form-error" role="alert">{error}</div>}

              <button className="btn btn-primary btn-block" type="submit" disabled={busy}>
                {busy ? 'Creating your account…' : 'Create account'}
              </button>
            </form>

            <p className="login-hint">
              Expires {new Date(invitation.expires_at).toLocaleString()} — single-use.
            </p>
          </>
        )}
      </div>
    </div>
  )
}
