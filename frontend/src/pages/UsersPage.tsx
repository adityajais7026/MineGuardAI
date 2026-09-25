import { useState } from 'react'
import { usersApi } from '../api/endpoints'
import { useApiResource } from '../hooks/useApiResource'
import { ApiError } from '../api/client'
import {
  Badge, EmptyState, ErrorState, Loading, Modal, PageHeader,
} from '../components/ui'

const EMPTY_FORM = {
  email: '', full_name: '',
  role: 'safety_officer' as 'admin' | 'mine_manager' | 'safety_officer' | 'environmental_officer',
  password: '',
}

export default function UsersPage() {
  const { data, loading, error, refetch } = useApiResource(() => usersApi.list({ limit: 200 }), [])
  const [showCreate, setShowCreate] = useState(false)
  const [form, setForm] = useState(EMPTY_FORM)
  const [formError, setFormError] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)

  async function handleCreate(e: React.FormEvent) {
    e.preventDefault()
    setFormError(null)
    if (!form.email.trim() || !form.full_name.trim() || form.password.length < 8) {
      setFormError('Email, full name and a password of at least 8 characters are required.')
      return
    }
    setBusy(true)
    try {
      await usersApi.create(form)
      setShowCreate(false)
      setForm(EMPTY_FORM)
      refetch()
    } catch (err) {
      setFormError(err instanceof ApiError ? err.message : 'Could not create user.')
    } finally {
      setBusy(false)
    }
  }

  async function toggleActive(id: string, isActive: boolean) {
    try {
      await usersApi.update(id, { is_active: !isActive })
      refetch()
    } catch (err) {
      alert(err instanceof ApiError ? err.message : 'Update failed')
    }
  }

  if (loading) return <Loading />
  if (error) return <div className="page"><ErrorState message={error} onRetry={refetch} /></div>

  return (
    <div className="page">
      <PageHeader
        title="User Management"
        subtitle="Admin-only section"
        actions={<button className="btn btn-primary" onClick={() => setShowCreate(true)}>+ Add user</button>}
      />

      {(data?.items.length ?? 0) === 0 ? <EmptyState message="No users found." /> : (
        <div className="card">
          <table className="table">
            <thead><tr><th>Name</th><th>Email</th><th>Role</th><th>Status</th><th /></tr></thead>
            <tbody>
              {data!.items.map((u) => (
                <tr key={u.id}>
                  <td>{u.full_name}</td>
                  <td><code>{u.email}</code></td>
                  <td><Badge text={u.role.replace(/_/g, ' ')} tone="info" /></td>
                  <td><Badge text={u.is_active ? 'active' : 'deactivated'} tone={u.is_active ? 'ok' : 'danger'} /></td>
                  <td className="table-actions">
                    <button className="btn btn-sm" onClick={() => toggleActive(u.id, u.is_active)}>
                      {u.is_active ? 'Deactivate' : 'Activate'}
                    </button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      {showCreate && (
        <Modal title="Add user" onClose={() => setShowCreate(false)}>
          <form onSubmit={handleCreate} className="form-grid">
            <label>Full name<input value={form.full_name} onChange={(e) => setForm({ ...form, full_name: e.target.value })} /></label>
            <label>Email<input type="email" value={form.email} onChange={(e) => setForm({ ...form, email: e.target.value })} /></label>
            <label>Role
              <select value={form.role} onChange={(e) => setForm({ ...form, role: e.target.value as typeof form.role })}>
                <option value="safety_officer">safety officer</option>
                <option value="environmental_officer">environmental officer</option>
                <option value="mine_manager">mine manager</option>
                <option value="admin">admin</option>
              </select>
            </label>
            <label>Initial password (min 8 chars)<input type="password" value={form.password}
              onChange={(e) => setForm({ ...form, password: e.target.value })} /></label>
            {formError && <div className="form-error" role="alert">{formError}</div>}
            <button className="btn btn-primary" type="submit" disabled={busy}>{busy ? 'Saving…' : 'Create user'}</button>
          </form>
        </Modal>
      )}
    </div>
  )
}
