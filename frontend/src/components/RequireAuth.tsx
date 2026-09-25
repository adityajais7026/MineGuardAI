import { Navigate, useLocation } from 'react-router-dom'
import type { ReactNode } from 'react'
import { useAuth } from '../context/AuthContext'
import type { Role } from '../api/types'

/** Redirects unauthenticated users to /login; optionally enforces roles. */
export function RequireAuth({ children, roles }: { children: ReactNode; roles?: Role[] }) {
  const { user, loading } = useAuth()
  const location = useLocation()

  if (loading) return <div className="page-loading">Restoring session…</div>
  if (!user) return <Navigate to="/login" state={{ from: location }} replace />
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
