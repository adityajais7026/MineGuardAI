import { useState } from 'react'
import { Navigate, useNavigate } from 'react-router-dom'
import { useAuth } from '../context/AuthContext'
import { ApiError } from '../api/client'

/**
 * Self-service password change.
 *
 * Reached directly (Profile → Change password) and forced automatically when
 * the signed-in account holds an administrator-issued temporary password: the
 * backend refuses every other endpoint until the password is replaced.
 */
export default function ChangePasswordPage() {
  const { user, changePassword, logout } = useAuth()
  const navigate = useNavigate()
  const [currentPassword, setCurrentPassword] = useState('')
  const [newPassword, setNewPassword] = useState('')
  const [confirmPassword, setConfirmPassword] = useState('')
  const [error, setError] = useState<string | null>(null)
  const [notice, setNotice] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)

  if (!user) return <Navigate to="/login" replace />

  const forced = Boolean(user.must_change_password)

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault()
    setError(null)
    setNotice(null)
    if (newPassword.length < 8) {
      setError('The new password must be at least 8 characters.')
      return
    }
    if (newPassword !== confirmPassword) {
      setError('The two new passwords do not match.')
      return
    }
    if (newPassword === currentPassword) {
      setError('The new password must be different from the current one.')
      return
    }
    setBusy(true)
    try {
      await changePassword(currentPassword, newPassword)
      setNotice('Password changed. Opening the dashboard…')
      navigate('/', { replace: true })
    } catch (err) {
      setError(err instanceof ApiError ? err.message : 'Could not change the password.')
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="login-wrap">
      <form className="login-card password-form" onSubmit={handleSubmit}>
        <div className="brand login-brand">
          <span className="brand-mark">MG</span>
          <span className="brand-text">MineGuard<em>AI</em></span>
        </div>
        <h2 style={{ margin: '0 0 .25rem' }}>
          {forced ? 'Set a new password' : 'Change password'}
        </h2>
        <p className="login-sub">
          {forced
            ? 'This account is using a temporary password issued by an administrator. Set your own password to continue.'
            : `Signed in as ${user.email}`}
        </p>

        <label>Current password
          <input
            type="password"
            autoComplete="current-password"
            value={currentPassword}
            onChange={(e) => setCurrentPassword(e.target.value)}
            autoFocus
            required
          />
        </label>
        <label>New password (minimum 8 characters)
          <input
            type="password"
            autoComplete="new-password"
            value={newPassword}
            onChange={(e) => setNewPassword(e.target.value)}
            required
          />
        </label>
        <label>Confirm new password
          <input
            type="password"
            autoComplete="new-password"
            value={confirmPassword}
            onChange={(e) => setConfirmPassword(e.target.value)}
            required
          />
        </label>

        {error && <div className="form-error" role="alert">{error}</div>}
        {notice && <div className="login-hint" role="status">{notice}</div>}

        <button className="btn btn-primary" type="submit" disabled={busy}>
          {busy ? 'Saving…' : 'Save new password'}
        </button>
        <p className="login-hint">
          All other active sessions for this account are signed out when the password changes.{' '}
          <button type="button" className="btn btn-sm" onClick={logout}>Sign out</button>
        </p>
      </form>
    </div>
  )
}
