import { useState } from 'react'
import { cameraEventsApi } from '../api/endpoints'
import { useApiResource } from '../hooks/useApiResource'
import { ApiError } from '../api/client'
import {
  Badge, EmptyState, ErrorState, Loading, PageHeader, SeverityBadge, SimulatedDataNote, StatusBadge,
} from '../components/ui'

export default function CameraEventsPage() {
  const [eventType, setEventType] = useState('')
  const [statusFilter, setStatusFilter] = useState('')
  const [page, setPage] = useState(0)
  const [busyId, setBusyId] = useState<string | null>(null)
  const LIMIT = 20

  const { data, loading, error, refetch } = useApiResource(
    () => cameraEventsApi.list({
      event_type: eventType || undefined, status: statusFilter || undefined,
      skip: page * LIMIT, limit: LIMIT,
    }),
    [eventType, statusFilter, page],
  )

  async function setEventStatus(id: string, next: 'investigating' | 'resolved') {
    setBusyId(id)
    try {
      await cameraEventsApi.update(id, { status: next })
      refetch()
    } catch (err) {
      alert(err instanceof ApiError ? err.message : 'Update failed')
    } finally {
      setBusyId(null)
    }
  }

  if (loading) return <Loading />
  if (error) return <div className="page"><ErrorState message={error} onRetry={refetch} /></div>

  return (
    <div className="page">
      <PageHeader
        title="Camera Events"
        subtitle="Detection events from mine cameras. All detections are SIMULATED — no YOLO model is running in this build."
      />

      <div className="filter-bar">
        <select value={eventType} onChange={(e) => { setEventType(e.target.value); setPage(0) }} aria-label="Event type">
          <option value="">All event types</option>
          <option value="person_without_helmet">person without helmet</option>
          <option value="person_without_vest">person without vest</option>
          <option value="restricted_zone_entry">restricted zone entry</option>
          <option value="vehicle_in_restricted_area">vehicle in restricted area</option>
          <option value="fire_smoke">fire/smoke</option>
          <option value="unsafe_crowding">unsafe crowding</option>
        </select>
        <select value={statusFilter} onChange={(e) => { setStatusFilter(e.target.value); setPage(0) }} aria-label="Status">
          <option value="">All statuses</option>
          <option value="new">new</option><option value="investigating">investigating</option>
          <option value="resolved">resolved</option>
        </select>
      </div>

      {(data?.items.length ?? 0) === 0 ? <EmptyState message="No camera events match the filters." /> : (
        <div className="card">
          <table className="table">
            <thead><tr><th>When</th><th>Event</th><th>Zone</th><th>Camera</th><th>Confidence</th><th>Source</th><th>Severity</th><th>Status</th><th /></tr></thead>
            <tbody>
              {data!.items.map((e) => (
                <tr key={e.id}>
                  <td><small>{new Date(e.occurred_at).toLocaleString()}</small></td>
                  <td>{e.event_type.replace(/_/g, ' ')}</td>
                  <td>{e.zone_label ?? '—'}</td>
                  <td><code>{e.camera_id}</code></td>
                  <td>{Math.round(e.confidence * 100)}%</td>
                  <td>
                    <Badge text={e.detection_source} tone={e.detection_source === 'simulated' ? 'muted' : 'info'} />
                  </td>
                  <td><SeverityBadge value={e.severity} /></td>
                  <td><StatusBadge value={e.status} /></td>
                  <td className="table-actions">
                    {e.status === 'new' && (
                      <button className="btn btn-sm" disabled={busyId === e.id} onClick={() => setEventStatus(e.id, 'investigating')}>Investigate</button>
                    )}
                    {e.status !== 'resolved' && (
                      <button className="btn btn-sm btn-success" disabled={busyId === e.id} onClick={() => setEventStatus(e.id, 'resolved')}>Resolve</button>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
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
