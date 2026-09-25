import { useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { useAuth } from '../context/AuthContext'
import { ApiError } from '../api/client'

export default function LoginPage() {
  const { login, user } = useAuth()
  const navigate = useNavigate()
  const [email, setEmail] = useState('')
  const [password, setPassword] = useState('')
  const [error, setError] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)

  if (user) {
    navigate('/', { replace: true })
  }

  async function handleSubmit(e: React.FormEvent) {
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
      setError(err instanceof ApiError ? err.message : 'Login failed. Please try again.')
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="login-wrap">
      <form className="login-card" onSubmit={handleSubmit}>
        <div className="brand login-brand">
          <span className="brand-mark">⛏</span>
          <span className="brand-name">MineGuard<b>AI</b></span>
        </div>
        <p className="login-sub">Mining safety, environmental monitoring &amp; compliance governance</p>

        <label htmlFor="email">Email</label>
        <input id="email" type="email" value={email} autoComplete="username"
          onChange={(e) => setEmail(e.target.value)} placeholder="admin@mineguard.ai" />

        <label htmlFor="password">Password</label>
        <input id="password" type="password" value={password} autoComplete="current-password"
          onChange={(e) => setPassword(e.target.value)} placeholder="••••••••" />

        {error && <div className="form-error" role="alert">{error}</div>}

        <button className="btn btn-primary btn-block" type="submit" disabled={busy}>
          {busy ? 'Signing in…' : 'Sign in'}
        </button>

        <div className="login-hint">
          <strong>Demo accounts</strong> (simulated data):
          <code>admin@mineguard.ai / Admin@123</code><br />
          <code>manager@mineguard.ai / Manager@123</code> · <code>safety@mineguard.ai / Safety@123</code> ·
          <code> env@mineguard.ai / Env@123</code>
        </div>
      </form>
    </div>
  )
}
