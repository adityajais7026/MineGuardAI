import { Link } from 'react-router-dom'
import { adminApi, governanceApi, usersApi } from '../../api/endpoints'
import { useApiResource } from '../../hooks/useApiResource'
import {
  Badge, EmptyState, ErrorState, PageHeader, Skeleton,
} from '../../components/ui'
import { HealthBadge, healthTone } from './shared'

const ROLE_LABEL: Record<string, string> = {
  admin: 'Administrator',
  mine_manager: 'Mine Manager',
  safety_officer: 'Safety Officer',
  environmental_officer: 'Government Officer',
}

/** Administrative notification centre — every item is derived from live data. */
export default function AdminNotificationsPage() {
  const health = useApiResource(() => adminApi.systemHealth(), [])
  const overview = useApiResource(() => adminApi.overview(), [])
  const invitations = useApiResource(() => usersApi.invitations({ limit: 50 }), [])
  const users = useApiResource(() => usersApi.list({ limit: 200 }), [])
  const notifications = useApiResource(() => governanceApi.notifications(false), [])

  if (health.loading && !health.data) {
    return <div className="page"><PageHeader title="Notifications" /><Skeleton lines={5} /></div>
  }
  if (health.error) {
    return (
      <div className="page">
        <PageHeader title="Notifications" />
        <ErrorState message={health.error} onRetry={health.refetch} />
      </div>
    )
  }

  const components = health.data
    ? [
      { label: 'Backend API', status: health.data.api.status, detail: health.data.api.detail },
      { label: 'Database', status: health.data.database.status, detail: health.data.database.detail },
      { label: 'AI worker', status: health.data.ai_worker.status, detail: health.data.ai_worker.detail },
      { label: 'Storage', status: health.data.storage.status, detail: health.data.storage.detail },
      ...Object.entries(health.data.integrations ?? {}).map(([key, value]) => ({
        label: key.replace(/_/g, ' '), status: value.status, detail: value.provider ? `Provider: ${value.provider}` : undefined,
      })),
    ]
    : []
  const issues = components.filter((c) => healthTone(c.status) !== 'ok')

  const pendingInvitations = (invitations.data?.items ?? []).filter((i) => i.status === 'Active')
  const recentUsers = [...(users.data?.items ?? [])]
    .sort((a, b) => new Date(b.created_at).getTime() - new Date(a.created_at).getTime())
    .slice(0, 8)

  return (
    <div className="page">
      <PageHeader
        title="Notifications"
        subtitle="Administrative alerts, registrations and invitations"
        actions={<button className="btn" onClick={() => { health.refetch(); overview.refetch(); invitations.refetch() }}>Refresh</button>}
      />

      <div className="card">
        <h3>Platform alerts</h3>
        {issues.length === 0 ? (
          <EmptyState title="No platform alerts" message="Every configured component is operational." />
        ) : (
          <ul className="notice-list">
            {issues.map((issue) => (
              <li key={issue.label}>
                <HealthBadge status={issue.status} />
                <strong>{issue.label}</strong>
                <span className="muted">{issue.detail}</span>
              </li>
            ))}
          </ul>
        )}
        <p className="card-sub" style={{ marginBottom: 0 }}>
          Unconfigured services report NOT CONFIGURED — they are not treated as failures of a
          service that was never deployed.
        </p>
      </div>

      <div className="two-col">
        <div className="card">
          <h3>Pending invitations <Badge text={String(pendingInvitations.length)} tone={pendingInvitations.length ? 'warn' : 'muted'} /></h3>
          {invitations.loading && !invitations.data
            ? <Skeleton lines={3} />
            : pendingInvitations.length === 0
              ? <EmptyState title="None pending" message="No unused, unexpired invitations." />
              : (
                <table className="table">
                  <thead><tr><th>Invitee</th><th>Role</th><th>Expires</th></tr></thead>
                  <tbody>
                    {pendingInvitations.slice(0, 8).map((inv) => (
                      <tr key={inv.id}>
                        <td>{inv.full_name}<br /><small className="muted">{inv.email}</small></td>
                        <td>{ROLE_LABEL[inv.role] ?? inv.role}</td>
                        <td><small>{new Date(inv.expires_at).toLocaleString()}</small></td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              )}
          <p className="card-sub" style={{ marginTop: '.6rem' }}>
            <Link to="/users">Manage users and invitations →</Link>
          </p>
        </div>

        <div className="card">
          <h3>Recent registrations</h3>
          {users.loading && !users.data
            ? <Skeleton lines={3} />
            : recentUsers.length === 0
              ? <EmptyState title="No users" message="No accounts are registered." />
              : (
                <table className="table">
                  <thead><tr><th>Name</th><th>Role</th><th>Created</th></tr></thead>
                  <tbody>
                    {recentUsers.map((user) => (
                      <tr key={user.id}>
                        <td>{user.full_name}<br /><small className="muted">{user.email}</small></td>
                        <td>{ROLE_LABEL[user.role] ?? user.role}</td>
                        <td><small>{new Date(user.created_at).toLocaleDateString()}</small></td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              )}
        </div>
      </div>

      <div className="two-col">
        <div className="card">
          <h3>Important administrative events</h3>
          {overview.loading && !overview.data
            ? <Skeleton lines={3} />
            : (overview.data?.recent_activity.length ?? 0) === 0
              ? <EmptyState title="No events" message="No administrative events have been recorded." />
              : (
                <ul className="notice-list">
                  {overview.data!.recent_activity.map((event) => (
                    <li key={event.id}>
                      <Badge text={event.actor_role ?? 'system'} tone="info" />
                      <code style={{ fontSize: '.78em' }}>{event.action}</code>
                      <span className="muted">{new Date(event.created_at).toLocaleString()}</span>
                    </li>
                  ))}
                </ul>
              )}
        </div>

        <div className="card">
          <h3>Platform notifications</h3>
          {notifications.loading && !notifications.data
            ? <Skeleton lines={3} />
            : (notifications.data?.length ?? 0) === 0
              ? <EmptyState title="No notifications" message="No platform notifications have been issued." />
              : (
                <ul className="notice-list">
                  {notifications.data!.slice(0, 8).map((n) => (
                    <li key={n.id}>
                      <Badge text={n.severity.toUpperCase()}
                        tone={n.severity === 'critical' ? 'danger' : n.severity === 'high' ? 'warn' : 'info'} />
                      <strong>{n.title}</strong>
                      <span className="muted">{new Date(n.created_at).toLocaleString()}</span>
                    </li>
                  ))}
                </ul>
              )}
        </div>
      </div>
    </div>
  )
}
