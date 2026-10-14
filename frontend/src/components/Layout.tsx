import { useEffect, useState } from 'react'
import { NavLink, Outlet, useLocation, useNavigate } from 'react-router-dom'
import { useAuth } from '../context/AuthContext'
import { useMineSelection } from '../context/MineSelectionContext'
import { governanceApi } from '../api/endpoints'
import type { Mine, Role } from '../api/types'

interface NavItem {
  to: string
  label: string
  roles?: Role[] // undefined -> all roles
  /** Show the "needs attention" dot on this link from a live status query. */
  alertOf?: 'alerts' | 'emergencies'
}

/**
 * Sidebar organization follows the command-center grouping (existing routes
 * only — no new routes were invented):
 *
 *   COMMAND CENTER      Dashboard
 *   SAFETY & AI         Live Detection · AI Workbench · AI Tools · Alerts · Camera Events
 *   INSPECTIONS &       Inspections · Field Inspections (Offline) · Compliance
 *     COMPLIANCE        · Corrective Actions · Compliance Rules
 *   OPERATIONS          Mines · Workforce · Emergency · Restricted Zones
 *   RISK & ENVIRONMENT  Risk Overview · Risk Score · Environmental · Telemetry · Geofencing
 *   GOVERNANCE          Notifications · Reports · Audit Log (admin)
 *   ADMINISTRATION      Users (admin) · Profile
 */
const NAV: { section: string; items: NavItem[] }[] = [
  {
    section: 'Command Center',
    items: [{ to: '/', label: 'Dashboard' }],
  },
  {
    section: 'Safety & AI',
    items: [
      // Matrix section 5: Live Safety/PPE — gov (VIEW) visible, ops roles MANAGE.
      { to: '/live-detection', label: 'Live Detection' },
      { to: '/governance/ai', label: 'AI Workbench', roles: ['admin', 'safety_officer'] },
      { to: '/governance/ai-tools', label: 'AI Tools (OCR/Voice)', roles: ['admin', 'safety_officer'] },
      { to: '/alerts', label: 'Alerts', alertOf: 'alerts' },
      { to: '/camera-events', label: 'Camera Events' },
    ],
  },
  {
    section: 'Inspections & Compliance',
    items: [
      { to: '/inspections', label: 'Inspections' },
      { to: '/governance/offline-inspections', label: 'Field Inspections (Offline)', roles: ['admin', 'mine_manager', 'safety_officer'] },
      { to: '/governance/compliance', label: 'Compliance Status' },
      { to: '/compliance', label: 'Compliance Rules' },
      { to: '/corrective-actions', label: 'Corrective Actions' },
    ],
  },
  {
    section: 'Operations',
    items: [
      { to: '/mines', label: 'Mines' },
      { to: '/governance/workforce', label: 'Workforce' },
      { to: '/governance/emergency', label: 'Emergency', alertOf: 'emergencies' },
      { to: '/incidents', label: 'Incidents', roles: ['admin', 'mine_manager', 'safety_officer'] },
      { to: '/zones', label: 'Restricted Zones', roles: ['admin', 'mine_manager', 'safety_officer'] },
    ],
  },
  {
    section: 'Risk & Environment',
    items: [
      { to: '/risk', label: 'Risk Overview' },
      { to: '/governance/risk', label: 'Risk Score' },
      { to: '/environment', label: 'Environmental' },
      { to: '/governance/telemetry', label: 'Telemetry', roles: ['admin', 'environmental_officer', 'safety_officer'] },
      { to: '/governance/geofencing', label: 'Geofencing', roles: ['admin', 'mine_manager', 'safety_officer'] },
    ],
  },
  {
    section: 'Governance',
    items: [
      { to: '/governance/notifications', label: 'Notifications' },
      { to: '/governance/reports', label: 'Reports' },
      { to: '/governance/audit', label: 'Audit Log', roles: ['admin'] },
    ],
  },
  {
    section: 'Administration',
    items: [
      { to: '/users', label: 'Users', roles: ['admin'] },
      { to: '/profile', label: 'Profile' },
    ],
  },
]

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
        <nav className="sidebar-scroll">
          {NAV.map((group) => {
            const items = group.items.filter(
              (i) => !i.roles || (user && (i.roles as string[]).includes(user.role)),
            )
            if (items.length === 0) return null
            return (
              <div key={group.section} className="nav-section">
                <div className="nav-heading">{group.section}</div>
                {items.map((item) => (
                  <NavLink key={item.to} to={item.to}
                    className={({ isActive }) => `nav-link${isActive ? ' active' : ''}`}>
                    {item.label}
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
              <NavLink to="/profile" className="nav-link profile-link">
                <span className="avatar">{user.full_name.charAt(0)}</span>
                <span>{user.full_name}<br /><small>{user.role.replace(/_/g, ' ')}</small></span>
              </NavLink>
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
          <div className="topbar-title">
            <span className="crumb">MineGuardAI</span>
            <span aria-hidden="true">›</span>
            <span>{label}</span>
          </div>
          <div className="topbar-right">
            {user && (mineSel.mines.length > 0 || user.role === 'admin') && (
              <div className="filter-bar" style={{ margin: 0 }} title="Active coal mine">
                <select
                  aria-label="Selected mine"
                  value={mineSel.mineId ?? ''}
                  onChange={(e) => mineSel.setMineId(e.target.value || null)}
                >
                  {user.role === 'admin' && <option value="">All mines</option>}
                  {mineSel.mines.map((m: Mine) => (
                    <option key={m.id} value={m.id}>{m.name}</option>
                  ))}
                </select>
              </div>
            )}
            {user && (
              <>
                <span className="topbar-chip" title="Signed-in user">
                  <b>{user.full_name.split(' ')[0]}</b>
                  <span className="topbar-chip">{user.role.replace(/_/g, ' ')}</span>
                </span>
                <NavLink to="/governance/notifications" className="topbar-bell"
                  data-unread={hasUnread} aria-label={`Notifications${hasUnread ? ' — unread items' : ''}`} title="Notifications">
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

const ROUTE_TITLES: Record<string, string> = {
  '/': 'Dashboard',
  '/risk': 'Risk Overview',
  '/mines': 'Mines',
  '/environment': 'Environmental Monitoring',
  '/compliance': 'Compliance Rules',
  '/alerts': 'Alerts',
  '/incidents': 'Incidents',
  '/inspections': 'Inspections',
  '/governance/offline-inspections': 'Field Inspections (Offline)',
  '/governance/ai-tools': 'AI Tools',
  '/corrective-actions': 'Corrective Actions',
  '/zones': 'Restricted Zones',
  '/camera-events': 'Camera Events & Detection',
  '/live-detection': 'Live Detection',
  '/governance/compliance': 'Compliance Status',
  '/governance/workforce': 'Workforce',
  '/governance/emergency': 'Emergency',
  '/governance/telemetry': 'Telemetry',
  '/governance/geofencing': 'Geofencing',
  '/governance/risk': 'Risk Score',
  '/governance/audit': 'Audit Log',
  '/governance/reports': 'Reports',
  '/governance/notifications': 'Notifications',
  '/governance/ai': 'AI Workbench',
  '/users': 'User Management',
  '/profile': 'Profile',
}

/** Mine detail routes (/mines/:mineId) — derive a readable title. */
function pageTitleFromRoutes(pathname: string): string {
  const m = pathname.match(/^\/mines\/([^/]+)$/)
  return m ? 'Mine detail' : 'MineGuardAI'
}
