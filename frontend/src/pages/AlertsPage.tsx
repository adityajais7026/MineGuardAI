import { useState } from 'react'
import { alertsApi } from '../api/endpoints'
import { useApiResource } from '../hooks/useApiResource'
import { ApiError } from '../api/client'
import { EmptyState, ErrorState, Loading, PageHeader, SeverityBadge, SimulatedDataNote, StatusBadge } from '../components/ui'

export default function AlertsPage() {
  const [status, setStatus] = useState('')
  const [severity, setSeverity] = useState('')
  const [sort, setSort] = useState('created_at')
  const [order, setOrder] = useState<'asc' | 'desc'>('desc')
  const [page, setPage] = useState(0)
  const [busyId, setBusyId] = useState<string | null>(null)
  const LIMIT = 20

  const { data, loading, error, refetch } = useApiResource(
    () => alertsApi.list({
      status: status || undefined, severity: severity || undefined,
      sort, order, skip: page * LIMIT, limit: LIMIT,
    }),
    [status, severity, sort, order, page],
  )

  async function transition(id: string, next: 'acknowledged' | 'resolved' | 'investigating') {
    setBusyId(id)
    try {
      await alertsApi.update(id, { status: next })
      refetch()
    } catch (err) {
      alert(err instanceof ApiError ? err.message : 'Update failed')
    } finally {
      setBusyId(null)
    }
  }

  return (
    <div className="page">
      <PageHeader title="Alerts" subtitle="Environmental & safety alerts raised by the compliance and camera pipelines" />

      <div className="filter-bar">
        <select value={status} onChange={(e) => { setStatus(e.target.value); setPage(0) }} aria-label="Status">
          <option value="">All statuses</option>
          <option value="new">new</option><option value="acknowledged">acknowledged</option>
          <option value="investigating">investigating</option><option value="resolved">resolved</option>
        </select>
        <select value={severity} onChange={(e) => { setSeverity(e.target.value); setPage(0) }} aria-label="Severity">
          <option value="">All severities</option>
          <option value="critical">critical</option><option value="high">high</option>
          <option value="medium">medium</option><option value="low">low</option>
        </select>
        <select value={sort} onChange={(e) => setSort(e.target.value)} aria-label="Sort by">
          <option value="created_at">created</option><option value="severity">severity</option>
        </select>
        <select value={order} onChange={(e) => setOrder(e.target.value as 'asc' | 'desc')} aria-label="Order">
          <option value="desc">descending</option><option value="asc">ascending</option>
        </select>
      </div>

      {loading ? <Loading /> : error ? <ErrorState message={error} onRetry={refetch} /> : (
        <div className="card">
          {(data?.items.length ?? 0) === 0 ? <EmptyState message="No alerts match the filters." /> : (
            <table className="table">
              <thead><tr><th>Title</th><th>Severity</th><th>Status</th><th>Source</th><th>Created</th><th>Actions</th></tr></thead>
              <tbody>
                {data!.items.map((a) => (
                  <tr key={a.id}>
                    <td>
                      {a.title}
                      {a.description && <><br /><small className="muted">{a.description}</small></>}
                    </td>
                    <td><SeverityBadge value={a.severity} /></td>
                    <td><StatusBadge value={a.status} /></td>
                    <td><small>{a.source}</small></td>
                    <td><small>{new Date(a.created_at).toLocaleString()}</small></td>
                    <td className="table-actions">
                      {a.status === 'new' && (
                        <button className="btn btn-sm" disabled={busyId === a.id}
                          onClick={() => transition(a.id, 'acknowledged')}>Acknowledge</button>
                      )}
                      {(a.status === 'acknowledged') && (
                        <button className="btn btn-sm" disabled={busyId === a.id}
                          onClick={() => transition(a.id, 'investigating')}>Investigate</button>
                      )}
                      {a.status !== 'resolved' && a.status !== 'new' && (
                        <button className="btn btn-sm btn-success" disabled={busyId === a.id}
                          onClick={() => transition(a.id, 'resolved')}>Resolve</button>
                      )}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
          <div className="pager">
            <button className="btn btn-sm" disabled={page === 0} onClick={() => setPage(page - 1)}>← Prev</button>
            <span>Page {page + 1} · {data?.total ?? 0} total</span>
            <button className="btn btn-sm" disabled={(page + 1) * LIMIT >= (data?.total ?? 0)} onClick={() => setPage(page + 1)}>Next →</button>
          </div>
        </div>
      )}
      <SimulatedDataNote />
    </div>
  )
}
