import { useState } from 'react'
import { Link } from 'react-router-dom'
import { minesApi } from '../api/endpoints'
import { useApiResource } from '../hooks/useApiResource'
import { ApiError } from '../api/client'
import {
  ConfirmButton, EmptyState, ErrorState, Loading, Modal, PageHeader, StatusBadge,
} from '../components/ui'

const EMPTY_FORM = {
  name: '', code: '',
  mine_type: 'open_cast' as 'open_cast' | 'underground' | 'mixed',
  status: 'operational' as 'operational' | 'maintenance' | 'suspended' | 'closed',
  location: '',
}

export default function MinesPage() {
  const { data, loading, error, refetch } = useApiResource(() => minesApi.list({ limit: 200 }), [])
  const [showCreate, setShowCreate] = useState(false)
  const [form, setForm] = useState(EMPTY_FORM)
  const [formError, setFormError] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)

  async function handleCreate(e: React.FormEvent) {
    e.preventDefault()
    setFormError(null)
    if (!form.name.trim() || !form.code.trim() || !form.location.trim()) {
      setFormError('Name, code and location are required.')
      return
    }
    if (!/^[A-Z0-9-]{2,20}$/.test(form.code)) {
      setFormError('Code must be 2-20 chars: A-Z, 0-9 and dashes (e.g. MINE-KIR).')
      return
    }
    setBusy(true)
    try {
      await minesApi.create(form)
      setShowCreate(false)
      setForm(EMPTY_FORM)
      refetch()
    } catch (err) {
      setFormError(err instanceof ApiError ? err.message : 'Could not create mine.')
    } finally {
      setBusy(false)
    }
  }

  async function handleDelete(id: string) {
    try {
      await minesApi.delete(id)
      refetch()
    } catch (err) {
      alert(err instanceof ApiError ? err.message : 'Delete failed')
    }
  }

  if (loading) return <Loading />
  if (error) return <div className="page"><ErrorState message={error} onRetry={refetch} /></div>

  return (
    <div className="page">
      <PageHeader
        title="Mines"
        subtitle={`${data?.total ?? 0} site(s) registered`}
        actions={<button className="btn btn-primary" onClick={() => setShowCreate(true)}>+ Add mine</button>}
      />

      {(data?.items.length ?? 0) === 0 ? <EmptyState message="No mines registered yet." /> : (
        <div className="card">
          <table className="table">
            <thead>
              <tr><th>Name</th><th>Code</th><th>Type</th><th>Status</th><th>Location</th><th /></tr>
            </thead>
            <tbody>
              {data!.items.map((m) => (
                <tr key={m.id}>
                  <td><Link to={`/mines/${m.id}`} className="table-link">{m.name}</Link></td>
                  <td><code>{m.code}</code></td>
                  <td>{m.mine_type.replace(/_/g, ' ')}</td>
                  <td><StatusBadge value={m.status} /></td>
                  <td>{m.location}</td>
                  <td className="table-actions">
                    <Link className="btn btn-sm" to={`/mines/${m.id}`}>Details</Link>
                    <ConfirmButton onConfirm={() => handleDelete(m.id)}>Delete</ConfirmButton>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      {showCreate && (
        <Modal title="Add mine" onClose={() => setShowCreate(false)}>
          <form onSubmit={handleCreate} className="form-grid">
            <label>Name<input value={form.name} onChange={(e) => setForm({ ...form, name: e.target.value })} /></label>
            <label>Code (e.g. MINE-KIR)<input value={form.code} onChange={(e) => setForm({ ...form, code: e.target.value.toUpperCase() })} /></label>
            <label>Type
              <select value={form.mine_type} onChange={(e) => setForm({ ...form, mine_type: e.target.value as typeof form.mine_type })}>
                <option value="open_cast">open cast</option>
                <option value="underground">underground</option>
                <option value="mixed">mixed</option>
              </select>
            </label>
            <label>Status
              <select value={form.status} onChange={(e) => setForm({ ...form, status: e.target.value as typeof form.status })}>
                <option value="operational">operational</option>
                <option value="maintenance">maintenance</option>
                <option value="suspended">suspended</option>
                <option value="closed">closed</option>
              </select>
            </label>
            <label>Location<input value={form.location} onChange={(e) => setForm({ ...form, location: e.target.value })} /></label>
            {formError && <div className="form-error" role="alert">{formError}</div>}
            <button className="btn btn-primary" type="submit" disabled={busy}>{busy ? 'Saving…' : 'Create mine'}</button>
          </form>
        </Modal>
      )}
    </div>
  )
}
