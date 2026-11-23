import { adminApi, governanceApi, minesApi, usersApi } from '../../api/endpoints'
import { useApiResource } from '../../hooks/useApiResource'
import {
  EmptyState, ErrorState, PageHeader, Skeleton,
} from '../../components/ui'
import { downloadCsv } from './shared'

interface ReportDef {
  key: string
  title: string
  description: string
  build: () => Record<string, unknown>[]
  count: () => number
}

/** Administrative reports, generated from live platform data (CSV export). */
export default function AdminReportsPage() {
  const mines = useApiResource(() => minesApi.list({ limit: 200 }), [])
  const users = useApiResource(() => usersApi.list({ limit: 200 }), [])
  const devices = useApiResource(() => governanceApi.devices(), [])
  const invitations = useApiResource(() => usersApi.invitations({ limit: 200 }), [])
  const audit = useApiResource(() => governanceApi.audit({ limit: 200 }), [])
  const overview = useApiResource(() => adminApi.overview(), [])
  const health = useApiResource(() => adminApi.systemHealth(), [])

  const loading = mines.loading || users.loading || devices.loading || audit.loading
  const error = mines.error || users.error || devices.error || audit.error

  if (loading && !mines.data) {
    return <div className="page"><PageHeader title="Reports" /><Skeleton lines={5} /></div>
  }
  if (error) {
    return (
      <div className="page">
        <PageHeader title="Reports" />
        <ErrorState message={error} onRetry={() => { mines.refetch(); users.refetch(); devices.refetch(); audit.refetch() }} />
      </div>
    )
  }

  const mineRows = mines.data?.items ?? []
  const userRows = users.data?.items ?? []
  const deviceRows = devices.data ?? []
  const invitationRows = invitations.data?.items ?? []
  const auditRows = audit.data ?? []

  const reports: ReportDef[] = [
    {
      key: 'mine-registration',
      title: 'Mine registration report',
      description: 'Every registered mine with code, type, status, location and assigned manager.',
      count: () => mineRows.length,
      build: () => mineRows.map((mine) => ({
        mine_id: mine.id,
        name: mine.name,
        code: mine.code,
        type: mine.mine_type,
        status: mine.status,
        location: mine.location,
        manager_id: mine.manager_id ?? '',
        registered_at: mine.created_at,
      })),
    },
    {
      key: 'user-management',
      title: 'User management report',
      description: 'All accounts with role, status, assigned mines and creation date.',
      count: () => userRows.length,
      build: () => userRows.map((user) => ({
        user_id: user.id,
        full_name: user.full_name,
        email: user.email,
        role: user.role,
        active: user.is_active,
        permitted_mines: (user.permitted_mine_ids ?? []).length,
        created_at: user.created_at,
      })),
    },
    {
      key: 'invitations',
      title: 'Invitation report',
      description: 'Invitation codes with status, creator and expiry (codes omitted from the export).',
      count: () => invitationRows.length,
      build: () => invitationRows.map((inv) => ({
        invitation_id: inv.id,
        full_name: inv.full_name,
        email: inv.email,
        role: inv.role,
        status: inv.status,
        created_by: inv.created_by ?? '',
        created_at: inv.created_at,
        expires_at: inv.expires_at,
      })),
    },
    {
      key: 'sensor-devices',
      title: 'Sensor device report',
      description: 'Registered devices with mine, parameter, thresholds and last communication.',
      count: () => deviceRows.length,
      build: () => deviceRows.map((device) => ({
        device_id: device.id,
        device_code: device.device_code,
        mine_id: device.mine_id,
        parameter: device.parameter,
        unit: device.unit,
        source: device.source,
        active: device.is_active,
        warning_threshold: device.warning_threshold ?? '',
        critical_threshold: device.critical_threshold ?? '',
        last_seen_at: device.last_seen_at ?? 'never',
      })),
    },
    {
      key: 'administrative-actions',
      title: 'Administrative actions report',
      description: 'Audit-chain entries with actor role, action, resource and timestamp.',
      count: () => auditRows.length,
      build: () => auditRows.map((event) => ({
        seq: event.seq,
        created_at: event.created_at,
        actor_role: event.actor_role ?? '',
        action: event.action,
        entity_type: event.entity_type,
        entity_id: event.entity_id ?? '',
        mine_id: event.mine_id ?? '',
      })),
    },
    {
      key: 'platform-usage',
      title: 'Platform usage report',
      description: 'Headline platform counters for the current snapshot.',
      count: () => (overview.data ? 1 : 0),
      build: () => overview.data ? [{
        generated_at: overview.data.generated_at,
        mines_total: overview.data.mines.total,
        mines_active: overview.data.mines.active,
        users_total: overview.data.users.total,
        users_active: overview.data.users.active,
        devices_total: overview.data.devices.total,
        devices_online: overview.data.devices.online,
        invitations_pending: overview.data.invitations.pending,
        audit_entries: overview.data.audit.entries,
      }] : [],
    },
    {
      key: 'system-health',
      title: 'System health report',
      description: 'Status of each platform component at the last health check.',
      count: () => (health.data ? 1 : 0),
      build: () => {
        if (!health.data) return []
        const h = health.data
        return [
          { component: 'Backend API', status: h.api.status, detail: h.api.detail ?? '' },
          { component: 'Database', status: h.database.status, detail: h.database.detail ?? '' },
          { component: 'AI worker', status: h.ai_worker.status, detail: h.ai_worker.detail ?? '' },
          { component: 'Storage', status: h.storage.status, detail: h.storage.detail ?? '' },
          ...Object.entries(h.integrations ?? {}).map(([key, value]) => ({
            component: key, status: value.status, detail: value.provider ?? '',
          })),
          { component: 'Error log', status: h.error_log.status, detail: h.error_log.detail ?? '' },
        ]
      },
    },
  ]

  return (
    <div className="page">
      <PageHeader
        title="Reports"
        subtitle="Administrative reports generated from live platform data — exported as CSV"
      />

      <div className="report-grid">
        {reports.map((report) => {
          const count = report.count()
          return (
            <div className="card report-card" key={report.key}>
              <h3 style={{ marginTop: 0 }}>{report.title}</h3>
              <p className="card-sub">{report.description}</p>
              <div className="report-foot">
                <span className="muted">{count} row{count === 1 ? '' : 's'}</span>
                <button
                  className="btn btn-primary btn-sm"
                  disabled={count === 0}
                  onClick={() => downloadCsv(`${report.key}.csv`, report.build())}
                >
                  Download CSV
                </button>
              </div>
            </div>
          )
        })}
      </div>

      {reports.every((r) => r.count() === 0) && (
        <EmptyState title="No report data" message="The platform has no records to export yet." />
      )}

      <p className="unavailable-note">
        PDF report templates exist for inspections, compliance, safety and telemetry and remain
        available in the operational Reports area. These administrative exports are CSV because no
        administrative PDF template exists.
      </p>
    </div>
  )
}
