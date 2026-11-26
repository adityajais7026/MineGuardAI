import { useEffect, useMemo, useState } from 'react'
import { NavLink, Outlet, useLocation, useNavigate } from 'react-router-dom'
import { useAuth } from '../context/AuthContext'
import { useMineSelection } from '../context/MineSelectionContext'
import { governanceApi } from '../api/endpoints'
import type { Mine } from '../api/types'
import { NavIcon } from './NavIcon'
import { ROUTE_TITLES, navForRole } from './nav'

export default function Layout() {
  const { user, logout } = useAuth()
  const mineSel = useMineSelection()
  const navigate = useNavigate()
  const location = useLocation()
  const [open, setOpen] = useState(false)

  // Live counts for the attention dots (only when signed in).
  const [hasActiveAlerts, setHasActiveAlerts] = useState(false)
  const [hasOpenEmergencies, setHasOpenEmergencies] = useState(false)
  const [hasUnread, setHasUnread] = useState(false)

  const nav = useMemo(() => navForRole(user?.role), [user?.role])

  useEffect(() => {
    if (!user) return
    let cancelled = false
    Promise.all([
      governanceApi.alertsStatus().catch(() => null),
      governanceApi.emergencyStatus().catch(() => null),
      governanceApi.unreadStatus().catch(() => null),
    ]).then(([alerts, emergencies, unread]) => {
      if (cancelled) return
      setHasActiveAlerts(!!alerts?.has_active)
      setHasOpenEmergencies(!!emergencies?.has_open)
      setHasUnread(!!unread?.has_unread)
    })
    const t = window.setInterval(() => {
      governanceApi.alertsStatus().then((a) => setHasActiveAlerts(!!a?.has_active)).catch(() => {})
    }, 60_000)
    return () => { cancelled = true; window.clearInterval(t) }
  }, [user])

  useEffect(() => { setOpen(false) }, [location.pathname])

  const label = ROUTE_TITLES[location.pathname] ?? pageTitleFromRoutes(location.pathname)
  const roleLabel = user ? (user.role === 'admin' ? 'Platform Administrator' : user.role.replace(/_/g, ' ')) : ''

  return (
    <div className="app-shell">
      <aside className={`sidebar${open ? ' open' : ''}`} aria-label="Primary">
        <div className="brand">
          <span className="brand-mark" aria-hidden="true">⛏</span>
          <span>
            <span className="brand-name">MineGuard<b>AI</b></span>
            <span className="brand-sub">Safety &amp; Compliance</span>
          </span>
        </div>
        {user && <div className="nav-role" title="Signed-in role">{roleLabel}</div>}
        <nav className="sidebar-scroll">
          {nav.map((group) => {
            const items = group.items.filter(
              (i) => !i.roles || (user && (i.roles as string[]).includes(user.role)),
            )
            if (items.length === 0) return null
            return (
              <div key={group.section} className="nav-section">
                <div className="nav-heading">{group.section}</div>
                {items.map((item) => (
                  <NavLink key={item.to} to={item.to} end={item.to === '/'}
                    title={item.label}
                    className={({ isActive }) => `nav-link${isActive ? ' active' : ''}`}>
                    <NavIcon name={item.icon} />
                    <span className="nav-label">{item.label}</span>
                    {item.alertOf === 'alerts' && hasActiveAlerts && <span className="nav-dot" title="Active alerts" />}
                    {item.alertOf === 'emergencies' && hasOpenEmergencies && <span className="nav-dot" title="Open emergencies" />}
                  </NavLink>
                ))}
              </div>
            )
          })}
        </nav>
        <div className="sidebar-footer">
          {user && (
            <>
              <div className="nav-link profile-link" style={{ cursor: 'default' }}>
                <span className="avatar">{user.full_name.charAt(0)}</span>
                <span>
                  {user.full_name}
                  <br />
                  <small>{roleLabel}</small>
                </span>
              </div>
              <button className="btn btn-block" onClick={() => { logout(); navigate('/login') }}>
                Log out
              </button>
            </>
          )}
        </div>
      </aside>
      {open && <div className="sidebar-backdrop" onClick={() => setOpen(false)} />}

      <div style={{ flex: 1, minWidth: 0, display: 'flex', flexDirection: 'column' }}>
        <header className="topbar">
          <button className="menu-btn" aria-label="Toggle navigation" aria-expanded={open} onClick={() => setOpen((v) => !v)}>
            ☰
          </button>
          <div className="topbar-title" title={label}>
            <span className="crumb">MineGuardAI</span>
            <span aria-hidden="true" className="crumb-sep">›</span>
            <span className="topbar-current">{label}</span>
          </div>
          <div className="topbar-right">
            {user && user.role !== 'admin' && mineSel.mines.length > 0 && (
              <div className="filter-bar" style={{ margin: 0 }} title="Active coal mine">
                <select
                  aria-label="Selected mine"
                  value={mineSel.mineId ?? ''}
                  onChange={(e) => mineSel.setMineId(e.target.value || null)}
                >
                  {mineSel.mines.map((m: Mine) => (
                    <option key={m.id} value={m.id}>{m.name}</option>
                  ))}
                </select>
              </div>
            )}
            {user && (
              <>
                <span className="topbar-chip topbar-user" title={`${user.full_name} — ${roleLabel}`}>
                  <b>{user.full_name.split(' ')[0]}</b>
                  <span className="topbar-role">{roleLabel}</span>
                </span>
                <NavLink
                  to={user.role === 'admin' ? '/admin/notifications' : '/governance/notifications'}
                  className="topbar-bell"
                  data-unread={hasUnread}
                  aria-label={`Notifications${hasUnread ? ' — unread items' : ''}`}
                  title="Notifications"
                >
                  🔔
                </NavLink>
              </>
            )}
          </div>
        </header>
        <main className="content" id="main-content">
          <Outlet />
        </main>
      </div>
    </div>
  )
}

/** Mine detail routes (/mines/:mineId) — derive a readable title. */
function pageTitleFromRoutes(pathname: string): string {
  const m = pathname.match(/^\/mines\/([^/]+)$/)
  return m ? 'Mine detail' : 'MineGuardAI'
}
