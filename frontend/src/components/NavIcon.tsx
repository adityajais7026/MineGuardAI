/**
 * Sidebar icon set — single 16px stroke geometry, inheriting currentColor so
 * active/inactive states are driven by the nav link, never by separate colors.
 */
const PATHS: Record<string, string> = {
  dashboard: 'M2 8.5 8 3l6 5.5V14H2z M6 14v-4h4v4',
  mines: 'M2 13h12 M4 13l3-8 3 5 3-3 2 6 M7 13V9',
  users: 'M6 7a2.2 2.2 0 1 0 0-4.4A2.2 2.2 0 0 0 6 7z M1.5 13c0-2.2 2-3.6 4.5-3.6S10.5 10.8 10.5 13 M11 6.2a1.9 1.9 0 1 1 0-3.8 M12 9.6c1.4.3 2.5 1.4 2.5 3.4',
  roles: 'M8 2 3 4.2v3.9c0 3 2.1 5.2 5 6.4 2.9-1.2 5-3.4 5-6.4V4.2z M6 8l1.6 1.6L10.5 6.5',
  devices: 'M8 6.5a1.5 1.5 0 1 0 0 3 1.5 1.5 0 0 0 0-3z M2.6 5a5 5 0 0 0 0 6 M13.4 5a5 5 0 0 1 0 6 M4.6 3a8 8 0 0 0 0 10 M11.4 3a8 8 0 0 1 0 10',
  health: 'M1.5 8h3l1.6-3.6L8.4 12l1.6-4H14.5',
  config: 'M8 6a2 2 0 1 0 0 4 2 2 0 0 0 0-4z M8 1.5v1.8 M8 12.7v1.8 M1.5 8h1.8 M12.7 8h1.8 M3.4 3.4l1.3 1.3 M11.3 11.3l1.3 1.3 M12.6 3.4l-1.3 1.3 M4.7 11.3l-1.3 1.3',
  bell: 'M8 2a4 4 0 0 0-4 4v3l-1.2 2.4h10.4L12 9V6a4 4 0 0 0-4-4z M6.4 13a1.7 1.7 0 0 0 3.2 0',
  reports: 'M3 2h7l3 3v9H3z M10 2v3h3 M5.5 8.5h5 M5.5 11h5',
  audit: 'M3 2h10v12H3z M5.5 5.5h5 M5.5 8h5 M5.5 10.5h3',
  profile: 'M8 8a2.5 2.5 0 1 0 0-5 2.5 2.5 0 0 0 0 5z M3 14c0-2.8 2.2-4.2 5-4.2s5 1.4 5 4.2',
  live: 'M2 8s2.2-4 6-4 6 4 6 4-2.2 4-6 4-6-4-6-4z M8 9.6A1.6 1.6 0 1 0 8 6.4a1.6 1.6 0 0 0 0 3.2z',
  alerts: 'M8 2 1.6 13.5h12.8z M8 6.5v3.4 M8 11.4v.2',
  camera: 'M2 5h8v6H2z M10 7l4-2v6l-4-2',
  inspections: 'M4 2h8v12H4z M6 5.5h4 M6 8h4 M6 10.5h2.5 M2.5 4.5h1 M2.5 8h1 M2.5 11.5h1',
  offline: 'M3.5 13.5 12.5 2.5 M8 2.6A6 6 0 0 0 2 8.5 M14 8.5a6 6 0 0 0-4.6-5.8 M5 11.5a4 4 0 0 1 0-6 M11 5.5a4 4 0 0 1 0 6',
  compliance: 'M8 2 3 4.2v3.9c0 3 2.1 5.2 5 6.4 2.9-1.2 5-3.4 5-6.4V4.2z M6 8l1.6 1.6L10.5 6.5',
  rules: 'M6 3h8 M6 8h8 M6 13h8 M2 3h1.2 M2 8h1.2 M2 13h1.2',
  actions: 'M2.5 4.5h2v2h-2z M6.5 5.5h7 M2.5 11.5h2v2h-2z M6.5 12.5h7',
  workforce: 'M5.5 7a2 2 0 1 0 0-4 2 2 0 0 0 0 4z M1.5 13c0-2.2 1.8-3.4 4-3.4s4 1.2 4 3.4 M10.5 3.4a1.7 1.7 0 1 1 0 3.4 M12 9.8c1.3.2 2.3 1.3 2.3 3.2',
  emergency: 'M8 2.2 2 13.6h12z M8 6.4v3.6 M8 12v.2',
  incidents: 'M8 2.2 2 13.6h12z M8 6.4v3.6 M8 12v.2',
  zones: 'M2 2h5v5H2z M9 2h5v5H9z M2 9h5v5H2z M9 9h5v5H9z',
  risk: 'M2 13 6 7l3 3 5-6 M2 13h12',
  score: 'M2.5 13.5a7 7 0 1 1 11 0 M8 9.5 11 4.8 M8 9.5a1.3 1.3 0 1 0 0 .1z',
  environment: 'M8 14V6 M8 6C6 6 3.5 4.2 3.5 2c2.5 0 4.5 1.6 4.5 4z M8 8.5c2 0 4.5-1.8 4.5-4-2.5 0-4.5 1.6-4.5 4z',
  telemetry: 'M2 11.5h2.5l1.5-6 2.5 9 1.6-6H14',
  geofence: 'M8 14s4.5-4.2 4.5-7.2a4.5 4.5 0 1 0-9 0C3.5 9.8 8 14 8 14z M8 8.4a1.7 1.7 0 1 0 0-3.4 1.7 1.7 0 0 0 0 3.4z',
  ai: 'M5 5h6v6H5z M8 2v3 M8 11v3 M2 8h3 M11 8h3 M3.6 3.6 5.4 5.4 M10.6 10.6l1.8 1.8 M12.4 3.6 10.6 5.4 M5.4 10.6 3.6 12.4',
  tools: 'M10.5 2.5a3.2 3.2 0 0 0-3.3 4.6L2.5 11.8l1.7 1.7 4.7-4.7a3.2 3.2 0 0 0 4.6-3.3l-2 2-1.9-.5-.5-1.9z',
}

export function NavIcon({ name, size = 16 }: { name: string; size?: number }) {
  const d = PATHS[name] ?? PATHS.dashboard
  return (
    <svg
      className="nav-icon"
      width={size}
      height={size}
      viewBox="0 0 16 16"
      fill="none"
      stroke="currentColor"
      strokeWidth="1.4"
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden="true"
      focusable="false"
    >
      <path d={d} />
    </svg>
  )
}
