import { useState } from 'react'
import { inspectionsApi } from '../api/endpoints'
import { useApiResource } from '../hooks/useApiResource'
import { ApiError } from '../api/client'
import {
  EmptyState, ErrorState, Loading, Modal, PageHeader, SimulatedDataNote, StatusBadge,
} from '../components/ui'

const EMPTY_FORM = { mine_id: '', inspection_type: 'safety', scheduled_at: '' }

export default function InspectionsPage() {
  const { data, loading, error, refetch } = useApiResource(() => inspectionsApi.list({ limit: 100 }), [])
  const [showCreate, setShowCreate] = useState(false)
  const [form, setForm] = useState(EMPTY_FORM)
  const [formError, setFormError] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)
  const [busyId, setBusyId] = useState<string | null>(null)

  async function handleCreate(e: React.FormEvent) {
    e.preventDefault()
    setFormError(null)
    if (!form.mine_id || !form.scheduled_at) {
      setFormError('Mine and schedule date are required.')
      return
    }
    setBusy(true)
    try {
      await inspectionsApi.create({
        mine_id: form.mine_id, inspection_type: form.inspection_type,
        scheduled_at: new Date(form.scheduled_at).toISOString(),
      })
      setShowCreate(false)
      setForm(EMPTY_FORM)
      refetch()
    } catch (err) {
      setFormError(err instanceof ApiError ? err.message : 'Could not schedule inspection.')
    } finally {
      setBusy(false)
    }
  }

  async function patch(id: string, body: Record<string, unknown>) {
    setBusyId(id)
    try {
      await inspectionsApi.update(id, body)
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
        title="Inspections"
        subtitle="Scheduled site inspections and compliance results"
        actions={<button className="btn btn-primary" onClick={() => setShowCreate(true)}>+ Schedule inspection</button>}
      />

      {(data?.items.length ?? 0) === 0 ? <EmptyState message="No inspections scheduled." /> : (
        <div className="card">
          <table className="table">
            <thead><tr><th>Mine</th><th>Type</th><th>Status</th><th>Scheduled</th><th>Result</th><th>Actions</th></tr></thead>
            <tbody>
              {data!.items.map((i) => (
                <tr key={i.id}>
                  <td><code>{i.mine_id.slice(0, 12)}…</code></td>
                  <td>{i.inspection_type}</td>
                  <td><StatusBadge value={i.status} /></td>
                  <td><small>{new Date(i.scheduled_at).toLocaleString()}</small></td>
                  <td><StatusBadge value={i.compliance_result} /></td>
                  <td className="table-actions">
                    {i.status === 'scheduled' && (
                      <button className="btn btn-sm" disabled={busyId === i.id}
                        onClick={() => patch(i.id, { status: 'in_progress' })}>Start</button>
                    )}
                    {i.status === 'in_progress' && (
                      <>
                        <select defaultValue="" onChange={(e) => e.target.value && patch(i.id, {
                          status: 'completed', compliance_result: e.target.value,
                          findings: e.target.value === 'non_compliant' ? 'Findings recorded via UI (demo).' : 'No issues found.',
                        })} aria-label="Complete with result">
                          <option value="">Complete as…</option>
                          <option value="compliant">compliant</option>
                          <option value="partial">partial</option>
                          <option value="non_compliant">non-compliant</option>
                        </select>
                      </>
                    )}
                    {i.status !== 'completed' && i.status !== 'cancelled' && (
                      <button className="btn btn-sm" disabled={busyId === i.id}
                        onClick={() => patch(i.id, { status: 'cancelled' })}>Cancel</button>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      {showCreate && (
        <Modal title="Schedule inspection" onClose={() => setShowCreate(false)}>
          <form onSubmit={handleCreate} className="form-grid">
            <label>Mine ID (demo: m-iron-0001, m-coal-0002, m-baux-0003)
              <input value={form.mine_id} onChange={(e) => setForm({ ...form, mine_id: e.target.value })} placeholder="m-iron-0001" />
            </label>
            <label>Type
              <select value={form.inspection_type} onChange={(e) => setForm({ ...form, inspection_type: e.target.value })}>
                <option value="safety">safety</option><option value="environmental">environmental</option>
                <option value="equipment">equipment</option><option value="compliance">compliance</option>
              </select>
            </label>
            <label>Scheduled for
              <input type="datetime-local" value={form.scheduled_at}
                onChange={(e) => setForm({ ...form, scheduled_at: e.target.value })} />
            </label>
            {formError && <div className="form-error" role="alert">{formError}</div>}
            <button className="btn btn-primary" type="submit" disabled={busy}>{busy ? 'Saving…' : 'Schedule'}</button>
          </form>
        </Modal>
      )}
      <SimulatedDataNote />
    </div>
  )
}
