import { Navigate, useLocation } from 'react-router-dom'
import type { ReactNode } from 'react'
import { useAuth } from '../context/AuthContext'
import type { Role } from '../api/types'

export const PASSWORD_CHANGE_PATH = '/change-password'

/** Redirects unauthenticated users to /login; optionally enforces roles. */
export function RequireAuth({ children, roles }: { children: ReactNode; roles?: Role[] }) {
  const { user, loading } = useAuth()
  const location = useLocation()

  if (loading) return <div className="page-loading">Restoring session…</div>
  if (!user) return <Navigate to="/login" state={{ from: location }} replace />
  // An administrator-issued temporary password must be replaced before any
  // other screen is usable. The backend enforces the same rule (HTTP 403), so
  // this redirect is a convenience, not the security boundary.
  if (user.must_change_password && location.pathname !== PASSWORD_CHANGE_PATH) {
    return <Navigate to={PASSWORD_CHANGE_PATH} replace />
  }
  if (roles && !roles.includes(user.role) && user.role !== 'admin') {
    return (
      <div className="page">
        <div className="card error-card">
          <h2>403 — Forbidden</h2>
          <p>Your role ({user.role}) does not have access to this section.</p>
        </div>
      </div>
    )
  }
  return <>{children}</>
}
