import { useEffect, useState } from 'react'
import { usersApi } from '../api/endpoints'
import { useApiResource } from '../hooks/useApiResource'
import { ApiError } from '../api/client'
import type { InvitationLink, InvitationSummary, User, UserDeleteImpact } from '../api/types'
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

const EMPTY_INVITE_FORM = { full_name: '', email: '', role: 'safety_officer' }

export default function UsersPage() {
  const { data, loading, error, refetch } = useApiResource(() => usersApi.list({ limit: 200 }), [])
  const { data: invitations, refetch: refetchInvitations } = useApiResource(
    () => usersApi.invitations({ limit: 20 }), [],
  )

  const [showInvite, setShowInvite] = useState(false)
  const [inviteForm, setInviteForm] = useState(EMPTY_INVITE_FORM)
  const [inviteError, setInviteError] = useState<string | null>(null)
  const [createdLink, setCreatedLink] = useState<InvitationLink | null>(null)
  const [linkCopied, setLinkCopied] = useState(false)

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
      const link = await usersApi.invite(inviteForm)
      setCreatedLink(link)
      setLinkCopied(false)
      setInviteForm(EMPTY_INVITE_FORM)
      refetchInvitations()
    } catch (err) {
      setInviteError(err instanceof ApiError ? err.message : 'Could not create the invitation.')
    } finally {
      setBusy(false)
    }
  }

  async function handleCopyLink() {
    if (!createdLink) return
    try {
      await navigator.clipboard.writeText(createdLink.invitation_url)
      setLinkCopied(true)
    } catch {
      // Clipboard unavailable (permissions/insecure context): fall back to manual selection.
      setLinkCopied(false)
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

  const absoluteInviteLink = createdLink
    ? new URL(createdLink.invitation_url, window.location.origin).toString()
    : ''

  return (
    <div className="page">
      <PageHeader
        title="User Management"
        subtitle="Admin-only section"
        actions={<button className="btn btn-primary" onClick={() => { setShowInvite(true); setCreatedLink(null); setInviteError(null) }}>+ Invite user</button>}
      />

      {deleteSuccess && (
        <div className="card" style={{ borderColor: 'var(--ok, #2e7d32)' }}>
          <Badge text={deleteSuccess} tone="ok" />
        </div>
      )}

      {(data?.items.length ?? 0) === 0 ? <EmptyState message="No users found." /> : (
        <div className="card">
          <table className="table">
            <thead><tr><th>Name</th><th>Email</th><th>Role</th><th>Status</th><th /></tr></thead>
            <tbody>
              {data!.items.map((u) => (
                <tr key={u.id}>
                  <td>{u.full_name}</td>
                  <td><code>{u.email}</code></td>
                  <td><Badge text={ROLE_LABEL[u.role] ?? u.role.replace(/_/g, ' ')} tone="info" /></td>
                  <td><Badge text={u.is_active ? 'active' : 'deactivated'} tone={u.is_active ? 'ok' : 'danger'} /></td>
                  <td className="table-actions">
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
          <table className="table">
            <thead><tr><th>Name</th><th>Email</th><th>Role</th><th>Status</th><th>Expires</th></tr></thead>
            <tbody>
              {invitations.items.map((inv: InvitationSummary) => (
                <tr key={inv.id}>
                  <td>{inv.full_name}</td>
                  <td><code>{inv.email}</code></td>
                  <td><Badge text={ROLE_LABEL[inv.role] ?? inv.role.replace(/_/g, ' ')} tone="info" /></td>
                  <td>
                    <Badge
                      text={inv.status}
                      tone={inv.status === 'Pending' ? 'warn' : inv.status === 'Accepted' ? 'ok' : 'muted'}
                    />
                  </td>
                  <td className="muted">{new Date(inv.expires_at).toLocaleString()}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      {showInvite && (
        <Modal title="Invite user" onClose={() => setShowInvite(false)}>
          {createdLink ? (
            <div>
              <p><Badge text="Invitation created successfully." tone="ok" /></p>
              <p className="muted">
                Share this single-use link with <strong>{createdLink.invited_name}</strong> (
                {createdLink.invited_email}) via WhatsApp, email, etc. It expires{' '}
                {new Date(createdLink.expires_at).toLocaleString()} and is shown only once — copy it now.
              </p>
              <code style={{ display: 'block', padding: 8, wordBreak: 'break-all' }}>{absoluteInviteLink}</code>
              <div style={{ display: 'flex', gap: 8, marginTop: 12 }}>
                <button className="btn btn-primary" onClick={handleCopyLink}>
                  {linkCopied ? 'Copied!' : 'Copy Invitation Link'}
                </button>
                <button className="btn" onClick={() => { setShowInvite(false); setCreatedLink(null) }}>Done</button>
              </div>
            </div>
          ) : (
            <form onSubmit={handleInvite} className="form-grid">
              <p className="muted" style={{ marginTop: 0 }}>
                The invited person sets their own password on the invitation page. No password and no
                mobile number are collected here.
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
