import { useState } from 'react'
import { zonesApi } from '../api/endpoints'
import { useApiResource } from '../hooks/useApiResource'
import { ApiError } from '../api/client'
import {
  Badge, ConfirmButton, EmptyState, ErrorState, Loading, Modal, PageHeader, SimulatedDataNote,
} from '../components/ui'

const EMPTY_FORM = { mine_id: '', name: '', description: '', camera_id: '' }

export default function ZonesPage() {
  const { data, loading, error, refetch } = useApiResource(() => zonesApi.list({ limit: 200 }), [])
  const [showCreate, setShowCreate] = useState(false)
  const [form, setForm] = useState(EMPTY_FORM)
  const [formError, setFormError] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)

  async function handleCreate(e: React.FormEvent) {
    e.preventDefault()
    setFormError(null)
    if (!form.name.trim() || !form.mine_id.trim()) {
      setFormError('Mine ID and zone name are required.')
      return
    }
    setBusy(true)
    try {
      await zonesApi.create({
        mine_id: form.mine_id, name: form.name,
        description: form.description || null, camera_id: form.camera_id || null,
      })
      setShowCreate(false)
      setForm(EMPTY_FORM)
      refetch()
    } catch (err) {
      setFormError(err instanceof ApiError ? err.message : 'Could not create zone.')
    } finally {
      setBusy(false)
    }
  }

  if (loading) return <Loading />
  if (error) return <div className="page"><ErrorState message={error} onRetry={refetch} /></div>

  return (
    <div className="page">
      <PageHeader
        title="Restricted Zones"
        subtitle="Monitored no-entry areas with assigned cameras"
        actions={<button className="btn btn-primary" onClick={() => setShowCreate(true)}>+ Add zone</button>}
      />

      {(data?.items.length ?? 0) === 0 ? <EmptyState message="No restricted zones defined." /> : (
        <div className="card">
          <table className="table">
            <thead><tr><th>Zone</th><th>Mine</th><th>Camera</th><th>Active</th><th>Description</th><th /></tr></thead>
            <tbody>
              {data!.items.map((z) => (
                <tr key={z.id}>
                  <td>{z.name}</td>
                  <td><code>{z.mine_id.slice(0, 12)}…</code></td>
                  <td>{z.camera_id ? <code>{z.camera_id}</code> : <span className="muted">—</span>}</td>
                  <td><Badge text={z.is_active ? 'active' : 'inactive'} tone={z.is_active ? 'ok' : 'muted'} /></td>
                  <td><small>{z.description ?? '—'}</small></td>
                  <td className="table-actions">
                    <ConfirmButton onConfirm={async () => { await zonesApi.delete(z.id); refetch() }}>Delete</ConfirmButton>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      {showCreate && (
        <Modal title="Add restricted zone" onClose={() => setShowCreate(false)}>
          <form onSubmit={handleCreate} className="form-grid">
            <label>Mine ID (demo: m-iron-0001, m-coal-0002, m-baux-0003)
              <input value={form.mine_id} onChange={(e) => setForm({ ...form, mine_id: e.target.value })} placeholder="m-iron-0001" />
            </label>
            <label>Zone name<input value={form.name} onChange={(e) => setForm({ ...form, name: e.target.value })} /></label>
            <label>Camera ID<input value={form.camera_id} onChange={(e) => setForm({ ...form, camera_id: e.target.value })} placeholder="CAM-XXX-01" /></label>
            <label>Description<textarea rows={2} value={form.description}
              onChange={(e) => setForm({ ...form, description: e.target.value })} /></label>
            {formError && <div className="form-error" role="alert">{formError}</div>}
            <button className="btn btn-primary" type="submit" disabled={busy}>{busy ? 'Saving…' : 'Add zone'}</button>
          </form>
        </Modal>
      )}
      <SimulatedDataNote />
    </div>
  )
}
