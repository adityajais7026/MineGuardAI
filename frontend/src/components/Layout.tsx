import { NavLink, Outlet, useNavigate } from 'react-router-dom'
import { useAuth } from '../context/AuthContext'
import type { Role } from '../api/types'

interface NavItem {
  to: string
  label: string
  roles?: Role[] // undefined -> all roles
}

const NAV: { section: string; items: NavItem[] }[] = [
  {
    section: 'Overview',
    items: [
      { to: '/', label: 'Dashboard' },
      { to: '/risk', label: 'Risk Overview' },
    ],
  },
  {
    section: 'Monitoring',
    items: [
      { to: '/environment', label: 'Environmental' },
      { to: '/camera-events', label: 'Camera Events' },
      { to: '/zones', label: 'Restricted Zones' },
    ],
  },
  {
    section: 'Response',
    items: [
      { to: '/alerts', label: 'Alerts' },
      { to: '/incidents', label: 'Incidents' },
      { to: '/inspections', label: 'Inspections' },
      { to: '/corrective-actions', label: 'Corrective Actions' },
    ],
  },
  {
    section: 'Governance',
    items: [
      { to: '/compliance', label: 'Compliance Rules' },
      { to: '/mines', label: 'Mines' },
      { to: '/users', label: 'Users', roles: ['admin'] },
    ],
  },
]

export default function Layout() {
  const { user, logout } = useAuth()
  const navigate = useNavigate()

  return (
    <div className="app-shell">
      <aside className="sidebar">
        <div className="brand">
          <span className="brand-mark">⛏</span>
          <span className="brand-name">MineGuard<b>AI</b></span>
        </div>
        <nav>
          {NAV.map((group) => {
            const items = group.items.filter(
              (i) => !i.roles || (user && (i.roles as string[]).includes(user.role)),
            )
            if (items.length === 0) return null
            return (
              <div key={group.section} className="nav-section">
                <div className="nav-heading">{group.section}</div>
                {items.map((item) => (
                  <NavLink key={item.to} to={item.to} end={item.to === '/'}
                    className={({ isActive }) => `nav-link${isActive ? ' active' : ''}`}>
                    {item.label}
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
      <main className="content">
        <Outlet />
      </main>
    </div>
  )
}
