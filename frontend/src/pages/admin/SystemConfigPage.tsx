import { adminApi } from '../../api/endpoints'
import { useApiResource } from '../../hooks/useApiResource'
import { Badge, ErrorState, PageHeader, Skeleton } from '../../components/ui'

type Group = Record<string, string | number | boolean | string[] | undefined>

function labelFor(key: string) {
  return key.replace(/_/g, ' ').replace(/\b\w/g, (c) => c.toUpperCase())
}

function valueFor(value: string | number | boolean | string[]) {
  if (Array.isArray(value)) return value.length ? value.join(', ') : '—'
  if (typeof value === 'boolean') return value ? 'Enabled' : 'Disabled'
  return String(value)
}

function ConfigGroup({ title, group }: { title: string; group: Group }) {
  return (
    <div className="card">
      <h3>{title}</h3>
      <div className="config-list">
        {Object.entries(group)
          .filter(([, value]) => value !== undefined)
          .map(([key, value]) => (
            <div className="config-row" key={key}>
              <span className="config-key">{labelFor(key)}</span>
              <span className="config-value">{valueFor(value as string | number | boolean | string[])}</span>
            </div>
          ))}
      </div>
    </div>
  )
}

/** Effective platform configuration, read directly from the running backend. */
export default function SystemConfigPage() {
  const { data, loading, error, refetch } = useApiResource(() => adminApi.config(), [])

  if (loading && !data) {
    return <div className="page"><PageHeader title="System Configuration" /><Skeleton lines={5} /></div>
  }
  if (error) {
    return (
      <div className="page">
        <PageHeader title="System Configuration" />
        <ErrorState message={error} onRetry={refetch} />
      </div>
    )
  }
  if (!data) return null

  return (
    <div className="page">
      <PageHeader
        title="System Configuration"
        subtitle="Effective settings the platform is running with"
        actions={<Badge text="READ-ONLY" tone="muted" dot />}
      />

      <p className="unavailable-note">{data.note}</p>

      <div className="two-col">
        <ConfigGroup title="Platform" group={data.platform} />
        <ConfigGroup title="Registration & invitations" group={data.registration} />
      </div>
      <div className="two-col">
        <ConfigGroup title="Session & security" group={data.session_security} />
        <ConfigGroup title="Platform preferences" group={data.platform_preferences} />
      </div>
    </div>
  )
}
