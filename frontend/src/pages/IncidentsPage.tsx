import { useState } from 'react'
import { incidentsApi } from '../api/endpoints'
import type { Incident } from '../api/types'
import { useApiResource } from '../hooks/useApiResource'
import { ApiError } from '../api/client'
import {
  EmptyState, ErrorState, Loading, Modal, PageHeader, SeverityBadge, SimulatedDataNote, StatusBadge,
} from '../components/ui'

const EMPTY_FORM = { title: '', description: '', category: 'other', severity: 'medium', mine_id: '' }

export default function IncidentsPage() {
  const { data, loading, error, refetch } = useApiResource(() => incidentsApi.list({ limit: 100 }), [])
  const [showCreate, setShowCreate] = useState(false)
  const [form, setForm] = useState(EMPTY_FORM)
  const [formError, setFormError] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)
  const [busyId, setBusyId] = useState<string | null>(null)

  async function handleCreate(e: React.FormEvent) {
    e.preventDefault()
    setFormError(null)
    if (!form.title.trim() || !form.mine_id) {
      setFormError('Title and mine are required.')
      return
    }
    setBusy(true)
    try {
      await incidentsApi.create({
        title: form.title, description: form.description || null,
        category: form.category, severity: form.severity as 'low' | 'medium' | 'high' | 'critical',
        mine_id: form.mine_id,
      })
      setShowCreate(false)
      setForm(EMPTY_FORM)
      refetch()
    } catch (err) {
      setFormError(err instanceof ApiError ? err.message : 'Could not create incident.')
    } finally {
      setBusy(false)
    }
  }

  async function setStatus(id: string, next: Incident['status']) {
    setBusyId(id)
    try {
      await incidentsApi.update(id, { status: next })
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
        title="Incidents"
        subtitle="Safety incidents and their investigation workflow"
        actions={<button className="btn btn-primary" onClick={() => setShowCreate(true)}>+ Report incident</button>}
      />

      {(data?.items.length ?? 0) === 0 ? <EmptyState message="No incidents recorded." /> : (
        <div className="card">
          <table className="table">
            <thead><tr><th>Title</th><th>Category</th><th>Severity</th><th>Status</th><th>Occurred</th><th>Actions</th></tr></thead>
            <tbody>
              {data!.items.map((i) => (
                <tr key={i.id}>
                  <td>{i.title}{i.description && <><br /><small className="muted">{i.description}</small></>}</td>
                  <td>{i.category.replace(/_/g, ' ')}</td>
                  <td><SeverityBadge value={i.severity} /></td>
                  <td><StatusBadge value={i.status} /></td>
                  <td><small>{new Date(i.occurred_at).toLocaleDateString()}</small></td>
                  <td className="table-actions">
                    {i.status === 'open' && (
                      <button className="btn btn-sm" disabled={busyId === i.id} onClick={() => setStatus(i.id, 'investigating')}>Investigate</button>
                    )}
                    {i.status === 'investigating' && (
                      <button className="btn btn-sm" disabled={busyId === i.id} onClick={() => setStatus(i.id, 'action_required')}>Action required</button>
                    )}
                    {!['resolved', 'closed'].includes(i.status) && (
                      <button className="btn btn-sm btn-success" disabled={busyId === i.id} onClick={() => setStatus(i.id, 'resolved')}>Resolve</button>
                    )}
                    {i.status === 'resolved' && (
                      <button className="btn btn-sm" disabled={busyId === i.id} onClick={() => setStatus(i.id, 'closed')}>Close</button>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      {showCreate && (
        <Modal title="Report incident" onClose={() => setShowCreate(false)}>
          <form onSubmit={handleCreate} className="form-grid">
            <label>Title<input value={form.title} onChange={(e) => setForm({ ...form, title: e.target.value })} /></label>
            <label>Description<textarea rows={3} value={form.description} onChange={(e) => setForm({ ...form, description: e.target.value })} /></label>
            <div className="form-row">
              <label>Category
                <select value={form.category} onChange={(e) => setForm({ ...form, category: e.target.value })}>
                  <option value="fall_of_ground">fall of ground</option><option value="machinery">machinery</option>
                  <option value="vehicle">vehicle</option><option value="gas">gas</option>
                  <option value="fire">fire</option><option value="electrical">electrical</option>
                  <option value="other">other</option>
                </select>
              </label>
              <label>Severity
                <select value={form.severity} onChange={(e) => setForm({ ...form, severity: e.target.value })}>
                  <option value="low">low</option><option value="medium">medium</option>
                  <option value="high">high</option><option value="critical">critical</option>
                </select>
              </label>
            </div>
            <label>Mine ID (demo: m-iron-0001, m-coal-0002, m-baux-0003)
              <input value={form.mine_id} onChange={(e) => setForm({ ...form, mine_id: e.target.value })} placeholder="m-iron-0001" />
            </label>
            {formError && <div className="form-error" role="alert">{formError}</div>}
            <button className="btn btn-primary" type="submit" disabled={busy}>{busy ? 'Saving…' : 'Report incident'}</button>
          </form>
        </Modal>
      )}
      <SimulatedDataNote />
    </div>
  )
}
