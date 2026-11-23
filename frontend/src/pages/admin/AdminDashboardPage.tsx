import { Link } from 'react-router-dom'
import { adminApi } from '../../api/endpoints'
import { useApiResource } from '../../hooks/useApiResource'
import {
  EmptyState, ErrorState, PageHeader, Skeleton, StatCard,
} from '../../components/ui'
import { HealthBadge, InfoRow } from './shared'

const ROLE_LABEL: Record<string, string> = {
  admin: 'Platform Administrators',
  mine_manager: 'Mine Managers',
  safety_officer: 'Safety Officers',
  environmental_officer: 'Government Officers',
}

/** Administrator landing page: platform state only, never mine operations. */
export default function AdminDashboardPage() {
  const overview = useApiResource(() => adminApi.overview(), [])
  const health = useApiResource(() => adminApi.systemHealth(), [])

  if (overview.loading && !overview.data) {
    return <div className="page"><PageHeader title="Platform overview" /><Skeleton lines={5} /></div>
  }
  if (overview.error) {
    return (
      <div className="page">
        <PageHeader title="Platform overview" />
        <ErrorState message={overview.error} onRetry={overview.refetch} />
      </div>
    )
  }
  if (!overview.data) return null

  const d = overview.data
  const h = health.data

  return (
    <div className="page">
      <PageHeader
        title="Platform overview"
        subtitle={<>MineGuardAI platform administration · generated {new Date(d.generated_at).toLocaleString()}</>}
        actions={<button className="btn" onClick={() => { overview.refetch(); health.refetch() }}>Refresh</button>}
      />

      <div className="stat-grid stat-grid-4">
        <StatCard label="Registered mines" value={d.mines.total} hint={`${d.mines.active} active`} />
        <StatCard label="Active mines" value={d.mines.active} tone="ok" hint="status: operational" />
        <StatCard label="Inactive mines" value={d.mines.inactive}
          tone={d.mines.inactive ? 'warn' : 'ok'} hint="maintenance / suspended / closed" />
        <StatCard label="Registered users" value={d.users.total} hint={`${d.users.active} active`} />
        <StatCard label="Active users" value={d.users.active} tone="ok" />
        <StatCard label="Inactive users" value={d.users.inactive} tone={d.users.inactive ? 'warn' : 'ok'} />
        <StatCard label="Sensor devices" value={d.devices.total} hint={`${d.devices.active} active`} />
        <StatCard label="Pending invitations" value={d.invitations.pending}
          tone={d.invitations.pending ? 'warn' : 'ok'} hint="unused and not expired" />
      </div>

      <div className="two-col">
        <div className="card">
          <h3>System health</h3>
          {health.loading && !h
            ? <Skeleton lines={4} />
            : health.error
              ? <ErrorState message={health.error} onRetry={health.refetch} />
              : h && (
                <>
                  <InfoRow label="Backend API"><HealthBadge status={h.api.status} /></InfoRow>
                  <InfoRow label={`Database (${h.database.engine ?? 'unknown'})`}><HealthBadge status={h.database.status} /></InfoRow>
                  <InfoRow label="AI worker"><HealthBadge status={h.ai_worker.status} /></InfoRow>
                  <InfoRow label={`Storage (${h.storage.provider ?? '—'})`}><HealthBadge status={h.storage.status} /></InfoRow>
                  <InfoRow label="SMS / OTP">{<HealthBadge status={h.integrations?.sms_otp?.status ?? 'UNKNOWN'} />}</InfoRow>
                  <InfoRow label="System error log"><HealthBadge status={h.error_log.status} /></InfoRow>
                  <p className="card-sub" style={{ marginTop: '.6rem' }}>
                    <Link to="/admin/system-health">Open full system health →</Link>
                  </p>
                </>
              )}
        </div>

        <div className="card">
          <h3>Users by role</h3>
          <table className="table">
            <thead><tr><th>Role</th><th>Users</th></tr></thead>
            <tbody>
              {Object.entries(ROLE_LABEL).map(([role, label]) => (
                <tr key={role}>
                  <td>{label}</td>
                  <td className="num">{d.users.by_role[role] ?? 0}</td>
                </tr>
              ))}
            </tbody>
          </table>
          <p className="card-sub" style={{ marginTop: '.6rem' }}>
            <Link to="/admin/roles">Review role permissions →</Link>
          </p>
        </div>
      </div>

      <div className="card">
        <h3>Recent administrative activity</h3>
        {d.recent_activity.length === 0
          ? <EmptyState title="No recorded activity" message="No audit events have been recorded yet." />
          : (
            <div className="table-wrap">
              <table className="table">
                <thead>
                  <tr><th>#</th><th>When</th><th>Actor role</th><th>Action</th><th>Resource</th></tr>
                </thead>
                <tbody>
                  {d.recent_activity.map((event) => (
                    <tr key={event.id}>
                      <td className="num muted">{event.seq}</td>
                      <td><small>{new Date(event.created_at).toLocaleString()}</small></td>
                      <td>{event.actor_role ?? '—'}</td>
                      <td><code style={{ fontSize: '.78em' }}>{event.action}</code></td>
                      <td><small>{event.entity_type}{event.entity_id ? ` · ${event.entity_id.slice(0, 8)}…` : ''}</small></td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        <p className="card-sub" style={{ marginTop: '.6rem' }}>
          <Link to="/governance/audit">Open audit log →</Link>
        </p>
      </div>
    </div>
  )
}
