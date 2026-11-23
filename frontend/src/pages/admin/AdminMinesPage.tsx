import { useMemo, useState } from 'react'
import { Link } from 'react-router-dom'
import { minesApi, usersApi } from '../../api/endpoints'
import { ApiError } from '../../api/client'
import type { Mine, User } from '../../api/types'
import { useApiResource } from '../../hooks/useApiResource'
import {
  Badge, EmptyState, ErrorState, Loading, Modal, PageHeader, StatusBadge, useToast,
} from '../../components/ui'

const OFFICER_ROLES = ['safety_officer', 'environmental_officer']

type MineForm = {
  name: string
  code: string
  mine_type: Mine['mine_type']
  status: Mine['status']
  location: string
  manager_id: string
}

const EMPTY_FORM: MineForm = {
  name: '', code: '', mine_type: 'open_cast', status: 'operational', location: '', manager_id: '',
}

/** Platform mine registry: register, edit, activate/deactivate, assign staff. */
export default function AdminMinesPage() {
  const toast = useToast()
  const mines = useApiResource(() => minesApi.list({ limit: 200 }), [])
  const users = useApiResource(() => usersApi.list({ limit: 200 }), [])

  const [createOpen, setCreateOpen] = useState(false)
  const [editing, setEditing] = useState<Mine | null>(null)
  const [form, setForm] = useState<MineForm>(EMPTY_FORM)
  const [formError, setFormError] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)

  const [officerMine, setOfficerMine] = useState<Mine | null>(null)
  const [pendingScope, setPendingScope] = useState<Record<string, string[]>>({})
  const [scopeError, setScopeError] = useState<string | null>(null)

  const allUsers = useMemo(() => users.data?.items ?? [], [users.data])
  const managers = useMemo(() => allUsers.filter((u) => u.role === 'mine_manager' && u.is_active), [allUsers])
  const officers = useMemo(
    () => allUsers.filter((u) => OFFICER_ROLES.includes(u.role) && u.is_active),
    [allUsers],
  )
  const userName = (id: string | null) => allUsers.find((u) => u.id === id)?.full_name ?? null

  function openCreate() {
    setForm(EMPTY_FORM)
    setFormError(null)
    setCreateOpen(true)
  }

  function openEdit(mine: Mine) {
    setForm({
      name: mine.name,
      code: mine.code,
      mine_type: mine.mine_type,
      status: mine.status,
      location: mine.location,
      manager_id: mine.manager_id ?? '',
    })
    setFormError(null)
    setEditing(mine)
  }

  function payload() {
    return {
      name: form.name.trim(),
      code: form.code.trim().toUpperCase(),
      mine_type: form.mine_type,
      status: form.status,
      location: form.location.trim(),
      manager_id: form.manager_id || null,
    }
  }

  function validate() {
    if (!form.name.trim() || !form.code.trim() || !form.location.trim()) {
      setFormError('Name, code and location are required.')
      return false
    }
    if (!/^[A-Z0-9-]{2,20}$/.test(form.code.trim().toUpperCase())) {
      setFormError('Code must be 2–20 characters: A-Z, 0-9 and dashes.')
      return false
    }
    return true
  }

  async function handleCreate(e: React.FormEvent) {
    e.preventDefault()
    setFormError(null)
    if (!validate()) return
    setBusy(true)
    try {
      await minesApi.create(payload())
      setCreateOpen(false)
      toast('Mine registered.', 'ok')
      mines.refetch()
    } catch (err) {
      setFormError(err instanceof ApiError ? err.message : 'Could not register the mine.')
    } finally {
      setBusy(false)
    }
  }

  async function handleEdit(e: React.FormEvent) {
    e.preventDefault()
    if (!editing) return
    setFormError(null)
    if (!validate()) return
    setBusy(true)
    try {
      await minesApi.update(editing.id, payload())
      setEditing(null)
      toast('Mine updated.', 'ok')
      mines.refetch()
    } catch (err) {
      setFormError(err instanceof ApiError ? err.message : 'Could not update the mine.')
    } finally {
      setBusy(false)
    }
  }

  async function toggleMineStatus(mine: Mine) {
    const next: Mine['status'] = mine.status === 'operational' ? 'suspended' : 'operational'
    try {
      await minesApi.update(mine.id, { status: next })
      toast(`${mine.name} ${next === 'operational' ? 'activated' : 'deactivated'}.`, 'ok')
      mines.refetch()
    } catch (err) {
      toast(err instanceof ApiError ? err.message : 'Status change failed.', 'danger')
    }
  }

  function openOfficers(mine: Mine) {
    const scope: Record<string, string[]> = {}
    for (const officer of officers) {
      const ids = officer.permitted_mine_ids ?? []
      if (ids.includes(mine.id)) scope[officer.id] = [...ids]
    }
    for (const officer of officers) {
      if (!scope[officer.id]) scope[officer.id] = [...(officer.permitted_mine_ids ?? [])]
    }
    setPendingScope(scope)
    setScopeError(null)
    setOfficerMine(mine)
  }

  function toggleOfficer(user: User) {
    if (!officerMine) return
    setPendingScope((current) => {
      const ids = current[user.id] ?? []
      return {
        ...current,
        [user.id]: ids.includes(officerMine.id)
          ? ids.filter((id) => id !== officerMine.id)
          : [...ids, officerMine.id],
      }
    })
  }

  async function saveOfficers() {
    if (!officerMine) return
    setScopeError(null)
    setBusy(true)
    try {
      const changed = officers.filter((officer) => {
        const before = [...(officer.permitted_mine_ids ?? [])].sort().join(',')
        const after = [...(pendingScope[officer.id] ?? [])].sort().join(',')
        return before !== after
      })
      for (const officer of changed) {
        await usersApi.update(officer.id, { permitted_mine_ids: pendingScope[officer.id] ?? [] })
      }
      setOfficerMine(null)
      toast(changed.length ? `Mine access updated for ${changed.length} officer(s).` : 'No changes.', 'ok')
      users.refetch()
    } catch (err) {
      setScopeError(err instanceof ApiError ? err.message : 'Could not update mine access.')
    } finally {
      setBusy(false)
    }
  }

  if (mines.loading && !mines.data) return <Loading />
  if (mines.error) {
    return <div className="page"><PageHeader title="Mines" /><ErrorState message={mines.error} onRetry={mines.refetch} /></div>
  }

  const rows = mines.data?.items ?? []

  return (
    <div className="page">
      <PageHeader
        title="Mines"
        subtitle={`${mines.data?.total ?? 0} registered mine(s) · activate/deactivate, edit details and assign staff`}
        actions={<button className="btn btn-primary" onClick={openCreate}>+ Register mine</button>}
      />

      {rows.length === 0 ? <EmptyState title="No mines" message="No mines are registered yet." /> : (
        <div className="card">
          <div className="table-wrap">
            <table className="table table-responsive">
              <thead>
                <tr>
                  <th>Mine</th><th>Code</th><th>Type</th><th>Status</th>
                  <th>Mine Manager</th><th>Officers</th><th />
                </tr>
              </thead>
              <tbody>
                {rows.map((mine) => {
                  const assigned = officers.filter((o) => (o.permitted_mine_ids ?? []).includes(mine.id))
                  return (
                    <tr key={mine.id}>
                      <td data-label="Mine"><Link className="table-link" to={`/mines/${mine.id}`}>{mine.name}</Link></td>
                      <td data-label="Code"><code>{mine.code}</code></td>
                      <td data-label="Type">{mine.mine_type.replace(/_/g, ' ')}</td>
                      <td data-label="Status"><StatusBadge value={mine.status} /></td>
                      <td data-label="Manager">{userName(mine.manager_id) ?? <span className="muted">Unassigned</span>}</td>
                      <td data-label="Officers">
                        {assigned.length === 0
                          ? <span className="muted">None</span>
                          : <span className="badge badge-info">{assigned.length} assigned</span>}
                      </td>
                      <td className="table-actions">
                        <button className="btn btn-sm" onClick={() => openEdit(mine)}>Edit</button>
                        <button className="btn btn-sm" onClick={() => openOfficers(mine)}
                          title="Assign safety officers and government officers to this mine">Assign officers</button>
                        <button
                          className={`btn btn-sm${mine.status === 'operational' ? ' btn-danger' : ' btn-success'}`}
                          onClick={() => toggleMineStatus(mine)}
                        >
                          {mine.status === 'operational' ? 'Deactivate' : 'Activate'}
                        </button>
                      </td>
                    </tr>
                  )
                })}
              </tbody>
            </table>
          </div>
          <p className="card-sub" style={{ marginTop: '.6rem' }}>
            Mine Managers are assigned through the mine record; Safety and Government Officers
            receive explicit per-mine access. The backend enforces every assignment.
          </p>
        </div>
      )}

      {(createOpen || editing) && (
        <Modal
          title={editing ? `Edit mine — ${editing.name}` : 'Register mine'}
          onClose={() => { setCreateOpen(false); setEditing(null) }}
        >
          <form onSubmit={editing ? handleEdit : handleCreate} className="form-grid">
            <label>Name<input value={form.name} autoFocus
              onChange={(e) => setForm({ ...form, name: e.target.value })} /></label>
            <label>Code (e.g. MINE-KIR)<input value={form.code}
              onChange={(e) => setForm({ ...form, code: e.target.value.toUpperCase() })} /></label>
            <label>Type
              <select value={form.mine_type}
                onChange={(e) => setForm({ ...form, mine_type: e.target.value as Mine['mine_type'] })}>
                <option value="open_cast">open cast</option>
                <option value="underground">underground</option>
                <option value="mixed">mixed</option>
              </select>
            </label>
            <label>Status
              <select value={form.status}
                onChange={(e) => setForm({ ...form, status: e.target.value as Mine['status'] })}>
                <option value="operational">operational (active)</option>
                <option value="maintenance">maintenance</option>
                <option value="suspended">suspended</option>
                <option value="closed">closed</option>
              </select>
            </label>
            <label>Location<input value={form.location}
              onChange={(e) => setForm({ ...form, location: e.target.value })} /></label>
            <label>Mine Manager
              <select value={form.manager_id} onChange={(e) => setForm({ ...form, manager_id: e.target.value })}>
                <option value="">— unassigned —</option>
                {managers.map((m) => <option key={m.id} value={m.id}>{m.full_name} ({m.email})</option>)}
              </select>
            </label>
            {formError && <div className="form-error" role="alert">{formError}</div>}
            <button className="btn btn-primary" type="submit" disabled={busy}>
              {busy ? 'Saving…' : editing ? 'Save changes' : 'Register mine'}
            </button>
          </form>
        </Modal>
      )}

      {officerMine && (
        <Modal title={`Mine access — ${officerMine.name}`} onClose={() => setOfficerMine(null)}>
          <p className="muted" style={{ marginTop: 0 }}>
            Select the Safety Officers and Government Officers who may access this mine.
            Removing a mine revokes their access to its live detection, alerts and compliance data.
          </p>
          {officers.length === 0
            ? <p className="muted">No active Safety or Government Officers exist. Invite one from Users.</p>
            : (
              <div style={{ display: 'grid', gap: 6 }}>
                {officers.map((officer) => (
                  <label key={officer.id} style={{ display: 'flex', gap: 8, alignItems: 'center' }}>
                    <input type="checkbox"
                      checked={(pendingScope[officer.id] ?? []).includes(officerMine.id)}
                      onChange={() => toggleOfficer(officer)} />
                    <span>{officer.full_name} <span className="muted">({officer.role.replace(/_/g, ' ')})</span></span>
                  </label>
                ))}
              </div>
            )}
          {scopeError && <div className="form-error" role="alert">{scopeError}</div>}
          <div style={{ display: 'flex', gap: 8, marginTop: 12 }}>
            <button className="btn" onClick={() => setOfficerMine(null)} disabled={busy}>Cancel</button>
            <button className="btn btn-primary" onClick={saveOfficers} disabled={busy || officers.length === 0}>
              {busy ? 'Saving…' : 'Save assignments'}
            </button>
          </div>
        </Modal>
      )}

      {users.error && (
        <p className="unavailable-note">
          <Badge text="USER LIST UNAVAILABLE" tone="warn" /> Manager and officer assignment needs the user list: {users.error}
        </p>
      )}
    </div>
  )
}
