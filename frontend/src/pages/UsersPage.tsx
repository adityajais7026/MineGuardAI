import { useEffect, useState } from 'react'
import { minesApi, usersApi } from '../api/endpoints'
import { useApiResource } from '../hooks/useApiResource'
import { ApiError } from '../api/client'
import type { InvitationCreated, InvitationSummary, Mine, User, UserDeleteImpact } from '../api/types'
import {
  Badge, EmptyState, ErrorState, Loading, Modal, PageHeader,
} from '../components/ui'

const ROLE_OPTIONS = [
  { value: 'safety_officer', label: 'Safety Officer' },
  { value: 'mine_manager', label: 'Mine Manager' },
  { value: 'environmental_officer', label: 'Government Officer' },
  { value: 'admin', label: 'Administrator' },
] as const

const ROLE_LABEL: Record<string, string> = {
  admin: 'Administrator',
  mine_manager: 'Mine Manager',
  safety_officer: 'Safety Officer',
  environmental_officer: 'Government Officer',
}

const STATUS_TONE: Record<string, 'ok' | 'warn' | 'muted' | 'danger'> = {
  Active: 'warn',
  Used: 'ok',
  Expired: 'muted',
  Deleted: 'danger',
}

const EMPTY_INVITE_FORM = { full_name: '', email: '', role: 'safety_officer' }

/** Copy exactly `text` — no extra whitespace/quotes — with a legacy fallback. */
async function copyText(text: string): Promise<boolean> {
  try {
    await navigator.clipboard.writeText(text)
    return true
  } catch {
    try {
      const ta = document.createElement('textarea')
      ta.value = text
      ta.setAttribute('readonly', '')
      ta.style.position = 'fixed'
      ta.style.opacity = '0'
      document.body.appendChild(ta)
      ta.select()
      const ok = document.execCommand('copy')
      document.body.removeChild(ta)
      return ok
    } catch {
      return false
    }
  }
}

export default function UsersPage() {
  const { data, loading, error, refetch } = useApiResource(() => usersApi.list({ limit: 200 }), [])
  const { data: invitations, refetch: refetchInvitations } = useApiResource(
    () => usersApi.invitations({ limit: 50 }), [],
  )
  const { data: allMines } = useApiResource(() => minesApi.list({ limit: 200 }).then((r) => r.items), [])

  // --- Live-detection mine scope (admin-managed, backend-enforced) --------
  const [scopeTarget, setScopeTarget] = useState<User | null>(null)
  const [scopeSelected, setScopeSelected] = useState<string[]>([])
  const [scopeBusy, setScopeBusy] = useState(false)
  const [scopeError, setScopeError] = useState<string | null>(null)

  const [showInvite, setShowInvite] = useState(false)
  const [inviteForm, setInviteForm] = useState(EMPTY_INVITE_FORM)
  const [inviteError, setInviteError] = useState<string | null>(null)
  const [createdInvitation, setCreatedInvitation] = useState<InvitationCreated | null>(null)
  const [createdKind, setCreatedKind] = useState<'created' | 'regenerated'>('created')
  const [createdCopied, setCreatedCopied] = useState(false)

  const [copiedId, setCopiedId] = useState<string | null>(null)
  const [copyFailed, setCopyFailed] = useState<string | null>(null)

  const [regenBusy, setRegenBusy] = useState<string | null>(null)
  const [invDeleteTarget, setInvDeleteTarget] = useState<InvitationSummary | null>(null)
  const [invDeleteBusy, setInvDeleteBusy] = useState(false)
  const [invDeleteError, setInvDeleteError] = useState<string | null>(null)

  const [deleteTarget, setDeleteTarget] = useState<User | null>(null)
  const [deleteImpact, setDeleteImpact] = useState<UserDeleteImpact | null>(null)
  const [deleteLoading, setDeleteLoading] = useState(false)
  const [deleteError, setDeleteError] = useState<string | null>(null)
  const [deleteSuccess, setDeleteSuccess] = useState<string | null>(null)

  const [busy, setBusy] = useState(false)

  // Load the read-only impact report BEFORE the confirm dialog unlocks.
  useEffect(() => {
    if (!deleteTarget) { setDeleteImpact(null); setDeleteError(null); return }
    let cancelled = false
    setDeleteLoading(true)
    usersApi.deleteImpact(deleteTarget.id)
      .then((impact) => { if (!cancelled) setDeleteImpact(impact) })
      .catch((err) => { if (!cancelled) setDeleteError(err instanceof ApiError ? err.message : 'Could not load impact') })
      .finally(() => { if (!cancelled) setDeleteLoading(false) })
    return () => { cancelled = true }
  }, [deleteTarget])

  async function handleInvite(e: React.FormEvent) {
    e.preventDefault()
    setInviteError(null)
    if (!inviteForm.full_name.trim() || !inviteForm.email.trim()) {
      setInviteError('Full name and email are required.')
      return
    }
    setBusy(true)
    try {
      const invitation = await usersApi.invite(inviteForm)
      setCreatedKind('created')
      setCreatedInvitation(invitation)
      setCreatedCopied(false)
      setInviteForm(EMPTY_INVITE_FORM)
      refetchInvitations()
    } catch (err) {
      setInviteError(err instanceof ApiError ? err.message : 'Could not create the invitation.')
    } finally {
      setBusy(false)
    }
  }

  async function handleCopyInvitationCode(inv: { id: string; code: string | null }) {
    if (!inv.code) return
    const ok = await copyText(inv.code)
    if (ok) {
      setCopyFailed(null)
      setCopiedId(inv.id)
      setTimeout(() => setCopiedId((current) => (current === inv.id ? null : current)), 2000)
    } else {
      setCopiedId(null)
      setCopyFailed(inv.id)
      setTimeout(() => setCopyFailed((current) => (current === inv.id ? null : current)), 4000)
    }
  }

  async function handleCopyCreatedCode() {
    if (!createdInvitation) return
    const ok = await copyText(createdInvitation.code)
    setCreatedCopied(ok)
  }

  async function handleRegenerate(inv: InvitationSummary) {
    setRegenBusy(inv.id)
    setInviteError(null)
    try {
      const fresh = await usersApi.regenerateInvitation(inv.id)
      setCreatedKind('regenerated')
      setCreatedInvitation(fresh)
      setCreatedCopied(false)
      refetchInvitations()
    } catch (err) {
      setInviteError(err instanceof ApiError ? err.message : 'Could not regenerate the code.')
    } finally {
      setRegenBusy(null)
    }
  }

  async function handleDeleteInvitation() {
    if (!invDeleteTarget) return
    setInvDeleteBusy(true)
    setInvDeleteError(null)
    try {
      await usersApi.deleteInvitation(invDeleteTarget.id)
      setInvDeleteTarget(null)
      refetchInvitations()
    } catch (err) {
      setInvDeleteError(err instanceof ApiError ? err.message : 'Could not delete the invitation.')
    } finally {
      setInvDeleteBusy(false)
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

  function openScopeEditor(u: User) {
    setScopeError(null)
    setScopeSelected(u.permitted_mine_ids ?? [])
    setScopeTarget(u)
  }

  async function handleSaveScope() {
    if (!scopeTarget) return
    setScopeBusy(true)
    setScopeError(null)
    try {
      await usersApi.update(scopeTarget.id, { permitted_mine_ids: scopeSelected })
      setScopeTarget(null)
      refetch()
    } catch (err) {
      setScopeError(err instanceof ApiError ? err.message : 'Could not update mine access')
    } finally {
      setScopeBusy(false)
    }
  }

  function toggleScopeMine(id: string) {
    setScopeSelected((cur) => (cur.includes(id) ? cur.filter((m) => m !== id) : [...cur, id]))
  }

  async function handleDeletePermanently() {
    if (!deleteTarget) return
    setBusy(true)
    setDeleteError(null)
    try {
      const report = await usersApi.deletePermanent(deleteTarget.id)
      setDeleteSuccess(report.detail)
      setDeleteTarget(null)
      refetch()
    } catch (err) {
      setDeleteError(err instanceof ApiError ? err.message : 'Deletion failed')
    } finally {
      setBusy(false)
    }
  }

  if (loading) return <Loading />
  if (error) return <div className="page"><ErrorState message={error} onRetry={refetch} /></div>

  return (
    <div className="page">
      <PageHeader
        title="User Management"
        subtitle="Admin-only section"
        actions={<button className="btn btn-primary" onClick={() => { setShowInvite(true); setCreatedInvitation(null); setInviteError(null) }}>+ Invite user</button>}
      />

      {deleteSuccess && (
        <div className="card" style={{ borderColor: 'var(--ok, #2e7d32)' }}>
          <Badge text={deleteSuccess} tone="ok" />
        </div>
      )}

      {(data?.items.length ?? 0) === 0 ? <EmptyState message="No users found." /> : (
        <div className="card">
          <table className="table">
            <thead><tr><th>Name</th><th>Email</th><th>Role</th><th>Status</th><th>Live mines</th><th /></tr></thead>
            <tbody>
              {data!.items.map((u) => (
                <tr key={u.id}>
                  <td>{u.full_name}</td>
                  <td><code>{u.email}</code></td>
                  <td><Badge text={ROLE_LABEL[u.role] ?? u.role.replace(/_/g, ' ')} tone="info" /></td>
                  <td><Badge text={u.is_active ? 'active' : 'deactivated'} tone={u.is_active ? 'ok' : 'danger'} /></td>
                  <td>
                    {u.role === 'admin' ? <span className="muted">all mines</span>
                      : u.role === 'mine_manager' ? <span className="muted">managed mines</span>
                      : <Badge text={String(u.permitted_mine_ids?.length ?? 0)} tone={(u.permitted_mine_ids?.length ?? 0) > 0 ? 'ok' : 'muted'} />}
                  </td>
                  <td className="table-actions">
                    {u.role !== 'admin' && (
                      <button className="btn btn-sm" onClick={() => openScopeEditor(u)}
                        title="Choose which mines this user can run live detection in">
                        Assign mines
                      </button>
                    )}
                    <button className="btn btn-sm" onClick={() => toggleActive(u.id, u.is_active)}>
                      {u.is_active ? 'Deactivate' : 'Activate'}
                    </button>
                    <button
                      className="btn btn-danger btn-sm"
                      onClick={() => { setDeleteSuccess(null); setDeleteTarget(u) }}
                      title="Permanently delete this account (cannot be undone)"
                    >
                      Delete Permanently
                    </button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      {invitations && invitations.items.length > 0 && (
        <div className="card">
          <h3 style={{ marginTop: 0 }}>Invitations</h3>
          {inviteError && <div className="form-error" role="alert">{inviteError}</div>}
          <table className="table">
            <thead>
              <tr>
                <th>Name</th><th>Email</th><th>Role</th><th>Invitation code</th>
                <th>Status</th><th>Created by</th><th>Created</th><th>Expires</th><th />
              </tr>
            </thead>
            <tbody>
              {invitations.items.map((inv: InvitationSummary) => {
                const copyable = inv.code !== null && (inv.status === 'Active' || inv.status === 'Expired')
                return (
                  <tr key={inv.id}>
                    <td>{inv.full_name}</td>
                    <td><code>{inv.email}</code></td>
                    <td><Badge text={ROLE_LABEL[inv.role] ?? inv.role.replace(/_/g, ' ')} tone="info" /></td>
                    <td>
                      {inv.code ? <code style={{ wordBreak: 'break-all' }}>{inv.code}</code> : <span className="muted">—</span>}
                    </td>
                    <td><Badge text={inv.status} tone={STATUS_TONE[inv.status] ?? 'muted'} /></td>
                    <td className="muted">{inv.created_by ?? '—'}</td>
                    <td className="muted">{new Date(inv.created_at).toLocaleString()}</td>
                    <td className="muted">{new Date(inv.expires_at).toLocaleString()}</td>
                    <td className="table-actions">
                      {copyable && (
                        <button
                          className="btn btn-sm"
                          onClick={() => handleCopyInvitationCode(inv)}
                          title="Copy the complete invitation code"
                        >
                          {copiedId === inv.id ? 'Copied!' : 'Copy code'}
                        </button>
                      )}
                      {inv.status === 'Active' && (
                        <button
                          className="btn btn-sm"
                          disabled={regenBusy === inv.id}
                          onClick={() => handleRegenerate(inv)}
                          title="Issue a new code for the same email and role; the old code stops working"
                        >
                          {regenBusy === inv.id ? '…' : 'Regenerate'}
                        </button>
                      )}
                      {(inv.status === 'Active' || inv.status === 'Expired') && (
                        <button
                          className="btn btn-danger btn-sm"
                          onClick={() => { setInvDeleteError(null); setInvDeleteTarget(inv) }}
                          title="Delete this invitation; its code becomes invalid immediately"
                        >
                          Delete
                        </button>
                      )}
                      {copyFailed === inv.id && <span className="form-error">Copy failed — select the code manually.</span>}
                    </td>
                  </tr>
                )
              })}
            </tbody>
          </table>
        </div>
      )}

      {showInvite && (
        <Modal title="Invite user" onClose={() => setShowInvite(false)}>
          {createdInvitation ? (
            <div>
              <p><Badge text={createdKind === 'created' ? 'Invitation created successfully.' : 'New code issued — the previous code is now invalid.'} tone="ok" /></p>
              <p className="muted">
                Share this single-use code with <strong>{createdInvitation.full_name}</strong> ({createdInvitation.email}).
                They register with the code + this exact email, verify their mobile via SMS OTP, and set
                their own password. It expires {new Date(createdInvitation.expires_at).toLocaleString()} and stays
                visible in the invitation list until it is used, expired or deleted.
              </p>
              <code style={{ display: 'block', padding: 8, wordBreak: 'break-all', fontSize: '1.2em' }}>
                {createdInvitation.code}
              </code>
              <div style={{ display: 'flex', gap: 8, marginTop: 12 }}>
                <button className="btn btn-primary" onClick={handleCopyCreatedCode}>
                  {createdCopied ? 'Copied!' : 'Copy invitation code'}
                </button>
                <button className="btn" onClick={() => { setShowInvite(false); setCreatedInvitation(null) }}>Done</button>
              </div>
            </div>
          ) : (
            <form onSubmit={handleInvite} className="form-grid">
              <p className="muted" style={{ marginTop: 0 }}>
                Creates an invitation code bound to this exact email. The invited person sets their own
                password after verifying their mobile via SMS OTP. No password and no mobile number are
                collected here.
              </p>
              <label>Full name
                <input value={inviteForm.full_name} autoFocus
                  onChange={(e) => setInviteForm({ ...inviteForm, full_name: e.target.value })} />
              </label>
              <label>Email
                <input type="email" value={inviteForm.email}
                  onChange={(e) => setInviteForm({ ...inviteForm, email: e.target.value })} />
              </label>
              <label>Role
                <select value={inviteForm.role}
                  onChange={(e) => setInviteForm({ ...inviteForm, role: e.target.value as typeof inviteForm.role })}>
                  {ROLE_OPTIONS.map((r) => <option key={r.value} value={r.value}>{r.label}</option>)}
                </select>
              </label>
              {inviteError && <div className="form-error" role="alert">{inviteError}</div>}
              <button className="btn btn-primary" type="submit" disabled={busy}>
                {busy ? 'Creating…' : 'Create Invitation'}
              </button>
            </form>
          )}
        </Modal>
      )}

      {scopeTarget && (
        <Modal title={`Live-detection mines — ${scopeTarget.full_name}`} onClose={() => setScopeTarget(null)}>
          <p className="muted" style={{ marginTop: 0 }}>
            {scopeTarget.role === 'mine_manager'
              ? 'Mine Managers automatically get the mines where they are registered as manager (set on the Mines page). This list is used for Safety Officers and Government Officers.'
              : 'This user can only run live detection in the mines selected here. No selection means no live-detection access.'}
          </p>
          {(allMines ?? []).length === 0 ? <p className="muted">No mines exist yet — create one on the Mines page.</p> : (
            <div style={{ display: 'grid', gap: 6 }}>
              {(allMines as Mine[]).map((m) => (
                <label key={m.id} style={{ display: 'flex', gap: 8, alignItems: 'center' }}>
                  <input type="checkbox" checked={scopeSelected.includes(m.id)} onChange={() => toggleScopeMine(m.id)} />
                  <span>{m.name} <span className="muted">({m.code})</span></span>
                </label>
              ))}
            </div>
          )}
          {scopeError && <div className="form-error" role="alert">{scopeError}</div>}
          <div style={{ display: 'flex', gap: 8, marginTop: 12 }}>
            <button className="btn" onClick={() => setScopeTarget(null)} disabled={scopeBusy}>Cancel</button>
            <button className="btn btn-primary" onClick={handleSaveScope} disabled={scopeBusy}>
              {scopeBusy ? 'Saving…' : 'Save mine access'}
            </button>
          </div>
        </Modal>
      )}

      {invDeleteTarget && (
        <Modal title="Delete invitation" onClose={() => setInvDeleteTarget(null)}>
          <p>
            <strong>
              Delete the invitation for {invDeleteTarget.full_name} ({invDeleteTarget.email})?
            </strong>
          </p>
          <p className="muted">
            Code <code>{invDeleteTarget.code ?? '—'}</code> becomes invalid immediately and cannot be
            used to register. This cannot be undone.
          </p>
          {invDeleteError && <div className="form-error" role="alert">{invDeleteError}</div>}
          <div style={{ display: 'flex', gap: 8 }}>
            <button className="btn" onClick={() => setInvDeleteTarget(null)} disabled={invDeleteBusy}>Cancel</button>
            <button className="btn btn-danger" onClick={handleDeleteInvitation} disabled={invDeleteBusy}>
              {invDeleteBusy ? 'Deleting…' : 'Delete invitation'}
            </button>
          </div>
        </Modal>
      )}

      {deleteTarget && (
        <Modal title="Delete Permanently" onClose={() => setDeleteTarget(null)}>
          <p><strong>Are you sure you want to permanently delete this user?<br />This action cannot be undone.</strong></p>
          <table className="table">
            <tbody>
              <tr><th scope="row">User ID</th><td><code>{deleteTarget.id}</code></td></tr>
              <tr><th scope="row">Email</th><td><code>{deleteTarget.email}</code></td></tr>
              <tr><th scope="row">Role</th><td>{ROLE_LABEL[deleteTarget.role] ?? deleteTarget.role}</td></tr>
              <tr><th scope="row">Status</th><td>{deleteTarget.is_active ? 'Active' : 'Deactivated'}</td></tr>
            </tbody>
          </table>
          {deleteLoading && <Loading />}
          {deleteError && <div className="form-error" role="alert">{deleteError}</div>}
          {deleteImpact && (
            <div>
              <p className="muted">Records associated with this account that will be affected:</p>
              <ul>
                {Object.entries(deleteImpact.affected).map(([key, count]) => (
                  <li key={key}>{key.replace(/_/g, ' ')}: <strong>{count}</strong></li>
                ))}
              </ul>
            </div>
          )}
          <div style={{ display: 'flex', gap: 8 }}>
            <button className="btn" onClick={() => setDeleteTarget(null)} disabled={busy}>Cancel</button>
            <button
              className="btn btn-danger"
              onClick={handleDeletePermanently}
              disabled={busy || deleteLoading || !deleteImpact}
            >
              {busy ? 'Deleting…' : 'Delete Permanently'}
            </button>
          </div>
        </Modal>
      )}
    </div>
  )
}
