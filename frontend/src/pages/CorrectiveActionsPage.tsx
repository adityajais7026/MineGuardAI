import { useState } from 'react'
import { actionsApi } from '../api/endpoints'
import { useApiResource } from '../hooks/useApiResource'
import { ApiError } from '../api/client'
import {
  EmptyState, ErrorState, Loading, Modal, PageHeader, SeverityBadge, SimulatedDataNote, StatusBadge,
} from '../components/ui'

const EMPTY_FORM = { incident_id: '', inspection_id: '', description: '', priority: 'medium', due_date: '' }

export default function CorrectiveActionsPage() {
  const { data, loading, error, refetch } = useApiResource(() => actionsApi.list({ limit: 100 }), [])
  const [showCreate, setShowCreate] = useState(false)
  const [form, setForm] = useState(EMPTY_FORM)
  const [formError, setFormError] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)
  const [busyId, setBusyId] = useState<string | null>(null)

  async function handleCreate(e: React.FormEvent) {
    e.preventDefault()
    setFormError(null)
    if (!form.description.trim() || (!form.incident_id && !form.inspection_id)) {
      setFormError('Description and an incident or inspection ID are required.')
      return
    }
    if (!form.due_date) {
      setFormError('Due date is required.')
      return
    }
    setBusy(true)
    try {
      await actionsApi.create({
        description: form.description,
        incident_id: form.incident_id || null,
        inspection_id: form.inspection_id || null,
        priority: form.priority as 'low' | 'medium' | 'high' | 'critical',
        due_date: new Date(form.due_date).toISOString(),
      })
      setShowCreate(false)
      setForm(EMPTY_FORM)
      refetch()
    } catch (err) {
      setFormError(err instanceof ApiError ? err.message : 'Could not create action.')
    } finally {
      setBusy(false)
    }
  }

  async function setStatus(id: string, status: 'pending' | 'in_progress' | 'completed') {
    setBusyId(id)
    try {
      await actionsApi.update(id, { status })
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
        title="Corrective Actions"
        subtitle="Actions linked to incidents and inspections — overdue items are highlighted"
        actions={<button className="btn btn-primary" onClick={() => setShowCreate(true)}>+ New action</button>}
      />

      {(data?.items.length ?? 0) === 0 ? <EmptyState message="No corrective actions recorded." /> : (
        <div className="card">
          <table className="table">
            <thead><tr><th>Description</th><th>Linked to</th><th>Priority</th><th>Status</th><th>Due</th><th>Actions</th></tr></thead>
            <tbody>
              {data!.items.map((a) => (
                <tr key={a.id} className={a.status === 'overdue' ? 'row-overdue' : undefined}>
                  <td>{a.description}</td>
                  <td><small>{a.incident_id ? `incident ${a.incident_id.slice(0, 8)}…` : `inspection ${a.inspection_id?.slice(0, 8)}…`}</small></td>
                  <td><SeverityBadge value={a.priority} /></td>
                  <td><StatusBadge value={a.status} /></td>
                  <td><small>{new Date(a.due_date).toLocaleDateString()}</small></td>
                  <td className="table-actions">
                    {a.status === 'pending' && (
                      <button className="btn btn-sm" disabled={busyId === a.id} onClick={() => setStatus(a.id, 'in_progress')}>Start</button>
                    )}
                    {['pending', 'in_progress', 'overdue'].includes(a.status) && (
                      <button className="btn btn-sm btn-success" disabled={busyId === a.id} onClick={() => setStatus(a.id, 'completed')}>Complete</button>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      {showCreate && (
        <Modal title="New corrective action" onClose={() => setShowCreate(false)}>
          <form onSubmit={handleCreate} className="form-grid">
            <label>Description<textarea rows={2} value={form.description}
              onChange={(e) => setForm({ ...form, description: e.target.value })} /></label>
            <div className="form-row">
              <label>Incident ID<input value={form.incident_id} onChange={(e) => setForm({ ...form, incident_id: e.target.value })} placeholder="i-0001" /></label>
              <label>or Inspection ID<input value={form.inspection_id} onChange={(e) => setForm({ ...form, inspection_id: e.target.value })} placeholder="ins-0001" /></label>
            </div>
            <div className="form-row">
              <label>Priority
                <select value={form.priority} onChange={(e) => setForm({ ...form, priority: e.target.value })}>
                  <option value="low">low</option><option value="medium">medium</option>
                  <option value="high">high</option><option value="critical">critical</option>
                </select>
              </label>
              <label>Due date<input type="date" value={form.due_date}
                onChange={(e) => setForm({ ...form, due_date: e.target.value })} /></label>
            </div>
            {formError && <div className="form-error" role="alert">{formError}</div>}
            <button className="btn btn-primary" type="submit" disabled={busy}>{busy ? 'Saving…' : 'Create action'}</button>
          </form>
        </Modal>
      )}
      <SimulatedDataNote />
    </div>
  )
}
