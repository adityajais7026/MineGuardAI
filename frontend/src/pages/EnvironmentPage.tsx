import { useState } from 'react'
import { CartesianGrid, Line, LineChart, ResponsiveContainer, Tooltip, XAxis, YAxis } from 'recharts'
import { environmentApi, minesApi } from '../api/endpoints'
import type { Mine } from '../api/types'
import { useApiResource } from '../hooks/useApiResource'
import { Badge, EmptyState, ErrorState, Loading, PageHeader, SimulatedDataNote } from '../components/ui'

export default function EnvironmentPage() {
  const [mineId, setMineId] = useState('')
  const [status, setStatus] = useState('')
  const [page, setPage] = useState(0)
  const LIMIT = 25

  const mines = useApiResource(() => minesApi.list({ limit: 200 }).then((r) => r.items), [])
  const { data, loading, error, refetch } = useApiResource(
    () => environmentApi.list({ mine_id: mineId || undefined, status: status || undefined, skip: page * LIMIT, limit: LIMIT }),
    [mineId, status, page],
  )

  // Simple trend of the current page's readings by parameter
  const chartData = (data?.items ?? [])
    .slice()
    .sort((a, b) => a.recorded_at.localeCompare(b.recorded_at))
    .map((r) => ({ time: new Date(r.recorded_at).toLocaleDateString(), value: r.value, parameter: r.parameter }))

  return (
    <div className="page">
      <PageHeader title="Environmental Monitoring" subtitle="Readings evaluated against configured compliance rules" />

      <div className="filter-bar">
        <select value={mineId} onChange={(e) => { setMineId(e.target.value); setPage(0) }} aria-label="Mine filter">
          <option value="">All mines</option>
          {(mines.data ?? []).map((m: Mine) => <option key={m.id} value={m.id}>{m.name}</option>)}
        </select>
        <select value={status} onChange={(e) => { setStatus(e.target.value); setPage(0) }} aria-label="Status filter">
          <option value="">All statuses</option>
          <option value="normal">normal</option>
          <option value="violation">violation</option>
        </select>
      </div>

      {loading ? <Loading /> : error ? <ErrorState message={error} onRetry={refetch} /> : (
        <>
          {chartData.length > 1 && (
            <div className="card">
              <h3>Readings on this page (value over time)</h3>
              <ResponsiveContainer width="100%" height={220}>
                <LineChart data={chartData}>
                  <CartesianGrid strokeDasharray="3 3" />
                  <XAxis dataKey="time" tick={{ fontSize: 11 }} />
                  <YAxis tick={{ fontSize: 11 }} />
                  <Tooltip />
                  <Line type="monotone" dataKey="value" stroke="#1d4ed8" dot={false} />
                </LineChart>
              </ResponsiveContainer>
            </div>
          )}

          <div className="card">
            {(data?.items.length ?? 0) === 0 ? <EmptyState message="No readings match the filters." /> : (
              <table className="table">
                <thead><tr><th>When</th><th>Parameter</th><th>Value</th><th>Threshold</th><th>Status</th><th>Source</th></tr></thead>
                <tbody>
                  {data!.items.map((r) => (
                    <tr key={r.id}>
                      <td>{new Date(r.recorded_at).toLocaleString()}</td>
                      <td>{r.parameter}</td>
                      <td>{r.value} {r.unit}</td>
                      <td>{r.threshold} {r.unit}</td>
                      <td><Badge text={r.status} tone={r.status === 'violation' ? 'danger' : 'ok'} /></td>
                      <td><Badge text={r.source} tone="muted" /></td>
                    </tr>
                  ))}
                </tbody>
              </table>
            )}
            <div className="pager">
              <button className="btn btn-sm" disabled={page === 0} onClick={() => setPage(page - 1)}>← Prev</button>
              <span>Page {page + 1} · {data?.total ?? 0} total</span>
              <button className="btn btn-sm" disabled={(page + 1) * LIMIT >= (data?.total ?? 0)}
                onClick={() => setPage(page + 1)}>Next →</button>
            </div>
          </div>
        </>
      )}
      <SimulatedDataNote />
    </div>
  )
}
