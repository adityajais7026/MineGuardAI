import { adminApi } from '../../api/endpoints'
import { useApiResource } from '../../hooks/useApiResource'
import { ErrorState, PageHeader, Skeleton } from '../../components/ui'
import { HealthBadge } from './shared'

interface Row {
  key: string
  label: string
  status: string
  detail?: string
  extra?: string
}

/** Live health of every platform dependency. Absent services stay NOT CONFIGURED. */
export default function SystemHealthPage() {
  const { data, loading, error, refetch } = useApiResource(() => adminApi.systemHealth(), [])

  if (loading && !data) {
    return <div className="page"><PageHeader title="System Health" /><Skeleton lines={5} /></div>
  }
  if (error) {
    return (
      <div className="page">
        <PageHeader title="System Health" />
        <ErrorState message={error} onRetry={refetch} />
      </div>
    )
  }
  if (!data) return null

  const rows: Row[] = [
    { key: 'api', label: 'Backend API', status: data.api.status, detail: data.api.detail, extra: data.api.version },
    {
      key: 'database',
      label: `Database (${data.database.engine ?? 'unknown'})`,
      status: data.database.status,
      detail: data.database.detail,
    },
    { key: 'ai', label: 'AI worker', status: data.ai_worker.status, detail: data.ai_worker.detail },
    {
      key: 'storage',
      label: `Storage (${data.storage.provider ?? 'unknown'})`,
      status: data.storage.status,
      detail: data.storage.detail,
    },
    ...Object.entries(data.integrations ?? {}).map(([key, value]) => ({
      key,
      label: key.replace(/_/g, ' '),
      status: value.status,
      detail: value.provider ? `Provider: ${value.provider}` : undefined,
    })),
    { key: 'errors', label: 'System error log', status: data.error_log.status, detail: data.error_log.detail },
  ]

  const issues = rows.filter((r) => !['OPERATIONAL', 'CONNECTED', 'AVAILABLE', 'CONFIGURED'].includes(r.status.toUpperCase()))

  return (
    <div className="page">
      <PageHeader
        title="System Health"
        subtitle={<>Checked {new Date(data.checked_at).toLocaleString()} · nothing here is simulated</>}
        actions={<button className="btn" onClick={refetch}>Re-check now</button>}
      />

      {issues.length > 0 && (
        <p className="unavailable-note">
          {issues.length} component(s) are not fully operational: {issues.map((i) => i.label).join(', ')}.
          Components that are not deployed report NOT CONFIGURED rather than a guessed status.
        </p>
      )}

      <div className="health-grid">
        {rows.map((row) => (
          <div className="card health-card" key={row.key}>
            <div className="health-card-head">
              <h3 style={{ margin: 0 }}>{row.label}</h3>
              <HealthBadge status={row.status} />
            </div>
            {row.detail && <p className="card-sub" style={{ marginTop: '.5rem' }}>{row.detail}</p>}
            {row.extra && <p className="card-sub" style={{ margin: 0 }}>Version {row.extra}</p>}
          </div>
        ))}
      </div>

      <div className="card">
        <h3>Recent system errors</h3>
        <p className="muted">
          No persistent error-log store is configured in this deployment, so individual error
          records cannot be listed. Responses that depend on an unavailable dependency surface as
          UNKNOWN / NOT CONFIGURED above instead of an invented status.
        </p>
      </div>
    </div>
  )
}
