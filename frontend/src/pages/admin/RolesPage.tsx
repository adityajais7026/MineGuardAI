import { adminApi } from '../../api/endpoints'
import { useApiResource } from '../../hooks/useApiResource'
import {
  Badge, EmptyState, ErrorState, PageHeader, Skeleton,
} from '../../components/ui'

const ROLE_TONE: Record<string, 'ok' | 'warn' | 'info' | 'danger'> = {
  admin: 'danger',
  mine_manager: 'warn',
  safety_officer: 'info',
  environmental_officer: 'ok',
}

/** Read-only role/permission matrix, sourced from the backend RBAC map. */
export default function RolesPage() {
  const { data, loading, error, refetch } = useApiResource(() => adminApi.roles(), [])

  if (loading && !data) return <div className="page"><PageHeader title="Roles & Permissions" /><Skeleton lines={5} /></div>
  if (error) return <div className="page"><PageHeader title="Roles & Permissions" /><ErrorState message={error} onRetry={refetch} /></div>
  if (!data) return null

  const roleKeys = data.roles.map((r) => r.role)

  return (
    <div className="page">
      <PageHeader
        title="Roles & Permissions"
        subtitle="Authoritative permission map enforced by the backend — not a UI-only restriction"
        actions={<Badge text="BACKEND ENFORCED" tone="ok" dot />}
      />

      <div className="role-grid">
        {data.roles.map((role) => (
          <div className="card" key={role.role}>
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', gap: '.6rem' }}>
              <h3 style={{ margin: 0 }}>{role.label}</h3>
              <Badge text={`${role.users} user${role.users === 1 ? '' : 's'}`} tone={ROLE_TONE[role.role] ?? 'muted'} />
            </div>
            <p className="card-sub" style={{ marginTop: '.45rem' }}>{role.mine_access}</p>
            <div className="chip-row">
              {role.write_areas.length === 0
                ? <span className="role-chip role-chip-muted">Read-only</span>
                : role.write_areas.map((area) => (
                  <span className="role-chip" key={area}>{area.replace(/_/g, ' ')}</span>
                ))}
            </div>
          </div>
        ))}
      </div>

      <div className="card">
        <h3>Write permissions by area</h3>
        <p className="card-sub">
          The map is exhaustive: an area's allowed roles are listed explicitly and administrators
          have no implicit superuser bypass. Mine-level read isolation is applied on top of these
          permissions, so a permitted write never grants access outside the user's mines.
        </p>
        {Object.keys(data.write_matrix).length === 0
          ? <EmptyState title="No permission map" message="The backend returned no write-permission areas." />
          : (
            <div className="table-wrap">
              <table className="table permission-table">
                <thead>
                  <tr>
                    <th>Area</th>
                    {roleKeys.map((role) => (
                      <th key={role} className="perm-head">{role.replace(/_/g, ' ')}</th>
                    ))}
                  </tr>
                </thead>
                <tbody>
                  {Object.entries(data.write_matrix).map(([area, allowed]) => (
                    <tr key={area}>
                      <td>{area.replace(/_/g, ' ')}</td>
                      {roleKeys.map((role) => (
                        <td key={role} className="perm-cell">
                          {allowed.includes(role)
                            ? <span className="perm-yes" aria-label="allowed">✓</span>
                            : <span className="perm-no" aria-label="not allowed">—</span>}
                        </td>
                      ))}
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
      </div>

      <div className="card">
        <h3>How access is decided</h3>
        <ul className="plain-list">
          {data.notes.map((note) => <li key={note}>{note}</li>)}
        </ul>
        <p className="unavailable-note">
          Role definitions are fixed in code. Creating a new role requires a backend and schema
          change, which is outside this task, so this page is read-only.
        </p>
      </div>
    </div>
  )
}
