import type { Role } from '../api/types'

export interface NavItem {
  to: string
  label: string
  /** Icon key resolved by <NavIcon />. */
  icon: string
  roles?: Role[] // undefined -> all roles
  /** Show the "needs attention" dot from a live status query. */
  alertOf?: 'alerts' | 'emergencies'
}

export interface NavGroup {
  section: string
  items: NavItem[]
}

/**
 * Administrator navigation — platform administration only.
 *
 * Daily mine-safety operations (live detection, inspections, telemetry, risk,
 * workforce, emergencies…) deliberately live with the operational roles below;
 * their routes and backend endpoints are untouched, so nothing is lost.
 */
const ADMIN_NAV: NavGroup[] = [
  { section: 'Overview', items: [{ to: '/', label: 'Dashboard', icon: 'dashboard' }] },
  {
    section: 'Platform Management',
    items: [
      { to: '/admin/mines', label: 'Mines', icon: 'mines' },
      { to: '/users', label: 'Users', icon: 'users' },
      { to: '/admin/roles', label: 'Roles & Permissions', icon: 'roles' },
    ],
  },
  {
    section: 'Infrastructure',
    items: [
      { to: '/admin/devices', label: 'Sensor Devices', icon: 'devices' },
      { to: '/admin/system-health', label: 'System Health', icon: 'health' },
    ],
  },
  {
    section: 'Configuration',
    items: [{ to: '/admin/system-configuration', label: 'System Configuration', icon: 'config' }],
  },
  {
    section: 'Communication',
    items: [{ to: '/admin/notifications', label: 'Notifications', icon: 'bell' }],
  },
  {
    section: 'Governance',
    items: [
      { to: '/admin/reports', label: 'Reports', icon: 'reports' },
      { to: '/governance/audit', label: 'Audit Log', icon: 'audit' },
    ],
  },
  { section: 'Account', items: [{ to: '/profile', label: 'Profile', icon: 'profile' }] },
]

/**
 * Operational navigation (Mine Manager / Safety Officer / Government Officer).
 * Same grouping language as the admin shell, but for mine-safety work.
 */
const OPERATIONAL_NAV: NavGroup[] = [
  { section: 'Overview', items: [{ to: '/', label: 'Dashboard', icon: 'dashboard' }] },
  {
    section: 'Operations',
    items: [
      { to: '/live-detection', label: 'Live Detection', icon: 'live' },
      { to: '/alerts', label: 'Alerts', icon: 'alerts', alertOf: 'alerts' },
      { to: '/camera-events', label: 'Camera Events', icon: 'camera' },
      { to: '/incidents', label: 'Incidents', icon: 'incidents',
        roles: ['mine_manager', 'safety_officer'] },
      { to: '/governance/emergency', label: 'Emergency', icon: 'emergency',
        alertOf: 'emergencies' },
      { to: '/zones', label: 'Restricted Zones', icon: 'zones',
        roles: ['mine_manager', 'safety_officer'] },
      { to: '/governance/geofencing', label: 'Geofencing', icon: 'geofence',
        roles: ['mine_manager', 'safety_officer'] },
      { to: '/mines', label: 'Mines', icon: 'mines', roles: ['mine_manager'] },
    ],
  },
  {
    section: 'Inspections & Compliance',
    items: [
      { to: '/inspections', label: 'Inspections', icon: 'inspections' },
      { to: '/governance/offline-inspections', label: 'Field Inspections', icon: 'offline',
        roles: ['mine_manager', 'safety_officer'] },
      { to: '/governance/compliance', label: 'Compliance Status', icon: 'compliance' },
      { to: '/compliance', label: 'Compliance Rules', icon: 'rules' },
      { to: '/corrective-actions', label: 'Corrective Actions', icon: 'actions' },
    ],
  },
  {
    section: 'Risk & Environment',
    items: [
      { to: '/risk', label: 'Risk Overview', icon: 'risk' },
      { to: '/governance/risk', label: 'Risk Score', icon: 'score' },
      { to: '/environment', label: 'Environmental', icon: 'environment' },
      { to: '/governance/telemetry', label: 'Telemetry', icon: 'telemetry',
        roles: ['environmental_officer', 'safety_officer'] },
    ],
  },
  {
    section: 'Workforce',
    items: [
      { to: '/governance/workforce', label: 'Workforce', icon: 'workforce',
        roles: ['mine_manager', 'safety_officer'] },
    ],
  },
  {
    section: 'AI & Analysis',
    items: [
      { to: '/governance/ai', label: 'AI Workbench', icon: 'ai', roles: ['safety_officer'] },
      { to: '/governance/ai-tools', label: 'AI Tools (OCR/Voice)', icon: 'tools', roles: ['safety_officer'] },
    ],
  },
  {
    section: 'Governance',
    items: [
      { to: '/governance/notifications', label: 'Notifications', icon: 'bell' },
      { to: '/governance/reports', label: 'Reports', icon: 'reports' },
    ],
  },
  { section: 'Account', items: [{ to: '/profile', label: 'Profile', icon: 'profile' }] },
]

export function navForRole(role: Role | undefined): NavGroup[] {
  return role === 'admin' ? ADMIN_NAV : OPERATIONAL_NAV
}

/** Human-readable page titles for the topbar breadcrumb. */
export const ROUTE_TITLES: Record<string, string> = {
  '/': 'Dashboard',
  '/risk': 'Risk Overview',
  '/mines': 'Mines',
  '/environment': 'Environmental Monitoring',
  '/compliance': 'Compliance Rules',
  '/alerts': 'Alerts',
  '/incidents': 'Incidents',
  '/inspections': 'Inspections',
  '/governance/offline-inspections': 'Field Inspections (offline)',
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
  '/admin/mines': 'Mines',
  '/admin/roles': 'Roles & Permissions',
  '/admin/devices': 'Sensor Devices',
  '/admin/system-health': 'System Health',
  '/admin/system-configuration': 'System Configuration',
  '/admin/notifications': 'Notifications',
  '/admin/reports': 'Reports',
}
