import { useEffect, useState } from 'react'
import { minesApi, usersApi } from '../api/endpoints'
import { useAuth } from '../context/AuthContext'
import { useApiResource } from '../hooks/useApiResource'
import { ApiError } from '../api/client'
import type {
  InvitationCreated, InvitationSummary, Mine, PasswordResetResult, User, UserDeleteImpact,
} from '../api/types'
import {
  Badge, EmptyState, ErrorState, Loading, Modal, PageHeader,
} from '../components/ui'

const ROLE_OPTIONS = [
  { value: 'safety_officer', label: 'Safety Officer' },
  { value: 'mine_manager', label: 'Mine Manager' },
  { value: 'environmental_officer', label: 'Government Officer' },
  { value: 'admin', label: 'Administrator' },
] as const

/** Label, badge tone and the permission scope shown before a role change. */
const ROLE_META: Record<string, { label: string; tone: 'ok' | 'warn' | 'danger' | 'info' | 'muted'; scope: string }> = {
  admin: {
    label: 'Administrator',
    tone: 'info',
    scope: 'Platform administration only: users, the mine registry and the sensor-device registry. Administrators cannot file inspections, resolve alerts, close corrective actions or touch telemetry.',
  },
  environmental_officer: {
    label: 'Government Officer',
    tone: 'warn',
    scope: 'Environment readings, compliance rules, alerts and corrective actions — limited to the mines assigned to them.',
  },
  mine_manager: {
    label: 'Mine Manager',
    tone: 'ok',
    scope: 'Day-to-day operations (inspections, incidents, alerts, actions, workforce) in the mines where they are the registered manager.',
  },
  safety_officer: {
    label: 'Safety Officer',
    tone: 'danger',
    scope: 'Alerts, incidents, inspections, camera events and AI simulation — limited to the mines assigned to them.',
  },
}

type TabValue = 'all' | User['role']

const ROLE_TABS: { value: TabValue; label: string; short: string }[] = [
  { value: 'all', label: 'All users', short: 'All' },
  { value: 'admin', label: 'Admin', short: 'Admin' },
  { value: 'environmental_officer', label: 'Government Officer', short: 'Gov. Officer' },
  { value: 'mine_manager', label: 'Mine Manager', short: 'Mine Mgr' },
  { value: 'safety_officer', label: 'Safety Officer', short: 'Safety' },
]

const PAGE_SIZE = 10

const STATUS_TONE: Record<string, 'ok' | 'warn' | 'muted' | 'danger'> = {
  Active: 'warn',
  Used: 'ok',
  Expired: 'muted',
  Deleted: 'danger',
}

const EMPTY_INVITE_FORM = { full_name: '', email: '', role: 'safety_officer' }

function roleLabel(role: string): string {
  return ROLE_META[role]?.label ?? role.replace(/_/g, ' ')
}

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
  const { user: currentUser } = useAuth()

  // --- Directory browsing: role tabs, search, status filter, pagination ----
  const [tab, setTab] = useState<TabValue>('all')
  const [search, setSearch] = useState('')
  const [query, setQuery] = useState('')
  const [statusFilter, setStatusFilter] = useState<'all' | 'active' | 'deactivated'>('all')
  const [page, setPage] = useState(0)

  // Debounce the search box so typing does not fire a request per keystroke.
  useEffect(() => {
    const timer = setTimeout(() => { setQuery(search.trim()); setPage(0) }, 300)
    return () => clearTimeout(timer)
  }, [search])

  const listParams = {
    skip: page * PAGE_SIZE,
    limit: PAGE_SIZE,
    ...(tab === 'all' ? {} : { role: tab }),
    ...(query ? { q: query } : {}),
    ...(statusFilter === 'all' ? {} : { is_active: statusFilter === 'active' }),
  }

  const { data, loading, error, refetch } = useApiResource(
    () => usersApi.list(listParams), [tab, query, statusFilter, page],
  )
  const { data: counts, refetch: refetchCounts } = useApiResource(
    () => usersApi.roleCounts(query ? { q: query } : undefined), [query],
  )
  const { data: invitations, refetch: refetchInvitations } = useApiResource(
    () => usersApi.invitations({ limit: 50 }), [],
  )
  const { data: allMines } = useApiResource(() => minesApi.list({ limit: 200 }).then((r) => r.items), [])

  const mines: Mine[] = allMines ?? []
  const mineById = new Map(mines.map((m) => [m.id, m]))

  /** Mines a user is actually assigned to, by role. */
  function assignedMines(u: User): Mine[] {
    if (u.role === 'admin') return mines
    if (u.role === 'mine_manager') return mines.filter((m) => m.manager_id === u.id)
    return (u.permitted_mine_ids ?? []).map((id) => mineById.get(id)).filter((m): m is Mine => Boolean(m))
  }

  function mineSummary(u: User): string {
    if (u.role === 'admin') return `All mines (${mines.length})`
    const assigned = assignedMines(u)
    if (assigned.length === 0) return 'No mines assigned'
    const names = assigned.slice(0, 2).map((m) => m.name).join(', ')
    return assigned.length > 2 ? `${names} +${assigned.length - 2} more` : names
  }

  const total = data?.total ?? 0
  const pageCount = Math.max(1, Math.ceil(total / PAGE_SIZE))
  const showingFrom = total === 0 ? 0 : page * PAGE_SIZE + 1
  const showingTo = Math.min(total, page * PAGE_SIZE + (data?.items.length ?? 0))

  useEffect(() => {
    if (page > pageCount - 1) setPage(pageCount - 1)
  }, [page, pageCount])

  function countFor(value: TabValue): number {
    if (!counts) return 0
    return value === 'all' ? counts.total : (counts.by_role[value] ?? 0)
  }

  function refreshDirectory() {
    refetch()
    refetchCounts()
  }

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
  // Typed confirmation: permanent deletion cannot be triggered by a stray click.
  const [deleteConfirmText, setDeleteConfirmText] = useState('')

  // --- User details ------------------------------------------------------
  const [detailUser, setDetailUser] = useState<User | null>(null)

  // --- Edit user information (name, role, mobile, status, password) -------
  const [editingUser, setEditingUser] = useState<User | null>(null)
  const [editForm, setEditForm] = useState({
    full_name: '', role: 'safety_officer' as User['role'], mobile: '', password: '', is_active: true,
  })
  const [editError, setEditError] = useState<string | null>(null)
  const [editBusy, setEditBusy] = useState(false)
  const [editSuccess, setEditSuccess] = useState<string | null>(null)
  // A role change is privileged: require an explicit acknowledgement.
  const [roleConfirmed, setRoleConfirmed] = useState(false)

  // --- Administrator password reset (temporary password, shown once) ------
  const [resetTarget, setResetTarget] = useState<User | null>(null)
  const [resetResult, setResetResult] = useState<PasswordResetResult | null>(null)
  const [resetBusy, setResetBusy] = useState(false)
  const [resetError, setResetError] = useState<string | null>(null)
  const [resetCopied, setResetCopied] = useState(false)

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

  async function toggleActive(u: User) {
    setEditSuccess(null)
    try {
      await usersApi.update(u.id, { is_active: !u.is_active })
      setEditSuccess(`${u.full_name} is now ${u.is_active ? 'deactivated' : 'active'}.`)
      refreshDirectory()
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
      setEditSuccess(`Mine assignment updated for ${scopeTarget.full_name}.`)
      refreshDirectory()
    } catch (err) {
      setScopeError(err instanceof ApiError ? err.message : 'Could not update mine access')
    } finally {
      setScopeBusy(false)
    }
  }

  function toggleScopeMine(id: string) {
    setScopeSelected((cur) => (cur.includes(id) ? cur.filter((m) => m !== id) : [...cur, id]))
  }

  function openEdit(u: User) {
    setEditForm({
      full_name: u.full_name,
      role: u.role,
      mobile: u.mobile ?? '',
      password: '',
      is_active: u.is_active,
    })
    setRoleConfirmed(false)
    setEditError(null)
    setEditingUser(u)
  }

  const pendingRoleChange = Boolean(editingUser && editForm.role !== editingUser.role)

  async function handleSaveEdit(e: React.FormEvent) {
    e.preventDefault()
    if (!editingUser) return
    setEditError(null)
    if (!editForm.full_name.trim()) {
      setEditError('Full name is required.')
      return
    }
    if (editForm.password && editForm.password.length < 8) {
      setEditError('A new password must be at least 8 characters.')
      return
    }
    if (pendingRoleChange && !roleConfirmed) {
      setEditError('Confirm the role change before saving.')
      return
    }
    setEditBusy(true)
    try {
      await usersApi.update(editingUser.id, {
        full_name: editForm.full_name.trim(),
        ...(pendingRoleChange ? { role: editForm.role } : {}),
        is_active: editForm.is_active,
        mobile: editForm.mobile.trim() || null,
        ...(editForm.password ? { password: editForm.password } : {}),
      })
      setEditingUser(null)
      setEditSuccess(pendingRoleChange
        ? `${editingUser.full_name} is now ${roleLabel(editForm.role)}. The change is recorded in the audit log.`
        : `User information updated for ${editingUser.full_name}.`)
      refreshDirectory()
    } catch (err) {
      setEditError(err instanceof ApiError ? err.message : 'Could not update the user.')
    } finally {
      setEditBusy(false)
    }
  }

  function openReset(u: User) {
    setResetResult(null)
    setResetError(null)
    setResetCopied(false)
    setResetTarget(u)
  }

  async function handleResetPassword() {
    if (!resetTarget) return
    setResetBusy(true)
    setResetError(null)
    try {
      const result = await usersApi.resetPassword(resetTarget.id)
      setResetResult(result)
      refreshDirectory()
    } catch (err) {
      setResetError(err instanceof ApiError ? err.message : 'Could not reset the password.')
    } finally {
      setResetBusy(false)
    }
  }

  async function handleCopyTemporaryPassword() {
    if (!resetResult) return
    setResetCopied(await copyText(resetResult.temporary_password))
  }

  async function handleDeletePermanently() {
    if (!deleteTarget) return
    setBusy(true)
    setDeleteError(null)
    try {
      const report = await usersApi.deletePermanent(deleteTarget.id)
      setDeleteSuccess(report.detail)
      setDeleteTarget(null)
      setDeleteConfirmText('')
      refreshDirectory()
    } catch (err) {
      setDeleteError(err instanceof ApiError ? err.message : 'Deletion failed')
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="page">
      <PageHeader
        title="User Management"
        subtitle="Admin-only section"
        actions={<button className="btn btn-primary" onClick={() => { setShowInvite(true); setCreatedInvitation(null); setInviteError(null) }}>+ Invite user</button>}
      />

      {(deleteSuccess || editSuccess) && (
        <div className="card" style={{ borderColor: 'var(--ok, #2e7d32)' }}>
          <Badge text={deleteSuccess ?? editSuccess ?? ''} tone="ok" />
        </div>
      )}

      <div className="card">
        <div className="user-tabs" role="tablist" aria-label="Users by role">
          {ROLE_TABS.map((t) => (
            <button
              key={t.value}
              role="tab"
              aria-selected={tab === t.value}
              className={`user-tab${tab === t.value ? ' is-active' : ''}`}
              onClick={() => { setTab(t.value); setPage(0) }}
            >
              <span className="user-tab-full">{t.label}</span>
              <span className="user-tab-short">{t.short}</span>
              <span className="user-tab-count">{countFor(t.value)}</span>
            </button>
          ))}
        </div>

        <div className="user-filters">
          <label className="user-search">
            <span className="sr-only">Search users</span>
            <input
              type="search"
              value={search}
              placeholder="Search name, email, role or assigned mine…"
              onChange={(e) => setSearch(e.target.value)}
            />
          </label>
          <label className="user-status-filter">
            <span className="muted">Status</span>
            <select
              value={statusFilter}
              onChange={(e) => { setStatusFilter(e.target.value as typeof statusFilter); setPage(0) }}
            >
              <option value="all">All</option>
              <option value="active">Active</option>
              <option value="deactivated">Deactivated</option>
            </select>
          </label>
          {(query || statusFilter !== 'all' || tab !== 'all') && (
            <button
              className="btn btn-sm"
              onClick={() => { setSearch(''); setQuery(''); setStatusFilter('all'); setTab('all'); setPage(0) }}
            >
              Clear filters
            </button>
          )}
        </div>

        <p className="muted user-counts" aria-live="polite">
          {loading ? 'Loading users…' : `Showing ${showingFrom}–${showingTo} of ${total} ${total === 1 ? 'user' : 'users'}`}
          {counts ? ` · ${counts.active} active · ${counts.inactive} deactivated` : ''}
        </p>

        {error ? (
          <ErrorState message={error} onRetry={refetch} />
        ) : loading && !data ? (
          <Loading />
        ) : (data?.items.length ?? 0) === 0 ? (
          <EmptyState message={query || statusFilter !== 'all'
            ? 'No users match these filters.'
            : 'No users in this role yet.'} />
        ) : (
          <table className="table table-responsive">
            <thead>
              <tr>
                <th>User</th><th>Role</th><th>Account</th><th>Assigned mines</th><th />
              </tr>
            </thead>
            <tbody>
              {data!.items.map((u) => {
                const meta = ROLE_META[u.role]
                const mineCount = assignedMines(u).length
                return (
                  <tr key={u.id}>
                    <td data-label="User">
                      <button className="user-name-btn" onClick={() => setDetailUser(u)} title="Show full account details">
                        {u.full_name}
                      </button>
                      <div className="muted"><code>{u.email}</code></div>
                    </td>
                    <td data-label="Role">
                      <Badge text={meta?.label ?? roleLabel(u.role)} tone={meta?.tone ?? 'muted'} dot />
                    </td>
                    <td data-label="Account">
                      <Badge
                        text={u.is_active ? 'active' : 'deactivated'}
                        tone={u.is_active ? 'ok' : 'danger'}
                        dot
                      />
                      {u.must_change_password && (
                        <div style={{ marginTop: 4 }}>
                          <Badge text="password change pending" tone="warn" />
                        </div>
                      )}
                      {u.id === currentUser?.id && (
                        <div style={{ marginTop: 4 }}><Badge text="you" tone="muted" /></div>
                      )}
                    </td>
                    <td data-label="Assigned mines">
                      <span className="muted">{mineSummary(u)}</span>
                      {u.role !== 'admin' && (
                        <div className="muted" style={{ fontSize: '.78rem' }}>
                          {mineCount === 0 ? 'no scoped access' : `${mineCount} of ${mines.length} mines`}
                        </div>
                      )}
                    </td>
                    <td className="table-actions">
                      <button className="btn btn-sm" onClick={() => setDetailUser(u)}>Details</button>
                      <button className="btn btn-sm" onClick={() => openEdit(u)}
                        title="Edit name, role, mobile, status or password">
                        Edit
                      </button>
                      {u.role !== 'admin' && (
                        <button className="btn btn-sm" onClick={() => openScopeEditor(u)}
                          title="Choose which mines this user can work in">
                          Assign mines
                        </button>
                      )}
                      <button className="btn btn-sm" onClick={() => toggleActive(u)}>
                        {u.is_active ? 'Deactivate' : 'Activate'}
                      </button>
                      <button
                        className="btn btn-sm"
                        onClick={() => openReset(u)}
                        disabled={u.id === currentUser?.id}
                        title={u.id === currentUser?.id
                          ? 'Change your own password from the Profile page'
                          : 'Issue a temporary password; the user must change it at next sign-in'}
                      >
                        Reset password
                      </button>
                      <button
                        className="btn btn-danger btn-sm"
                        onClick={() => { setDeleteSuccess(null); setEditSuccess(null); setDeleteConfirmText(''); setDeleteTarget(u) }}
                        disabled={u.id === currentUser?.id}
                        title={u.id === currentUser?.id
                          ? 'You cannot delete your own account'
                          : 'Permanently delete this account (cannot be undone)'}
                      >
                        Delete Permanently
                      </button>
                    </td>
                  </tr>
                )
              })}
            </tbody>
          </table>
        )}

        {total > PAGE_SIZE && (
          <div className="user-pagination">
            <button className="btn btn-sm" onClick={() => setPage((p) => Math.max(0, p - 1))} disabled={page === 0}>
              ← Previous
            </button>
            <span className="muted">Page {page + 1} of {pageCount}</span>
            <button
              className="btn btn-sm"
              onClick={() => setPage((p) => Math.min(pageCount - 1, p + 1))}
              disabled={page >= pageCount - 1}
            >
              Next →
            </button>
          </div>
        )}
      </div>

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
                    <td><Badge text={roleLabel(inv.role)} tone={ROLE_META[inv.role]?.tone ?? 'muted'} /></td>
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

      {detailUser && (
        <Modal title={`User details — ${detailUser.full_name}`} onClose={() => setDetailUser(null)}>
          <table className="table">
            <tbody>
              <tr><th scope="row">Name</th><td>{detailUser.full_name}</td></tr>
              <tr><th scope="row">Email</th><td><code>{detailUser.email}</code></td></tr>
              <tr><th scope="row">Role</th><td><Badge text={roleLabel(detailUser.role)} tone={ROLE_META[detailUser.role]?.tone ?? 'muted'} dot /></td></tr>
              <tr><th scope="row">Account</th>
                <td>
                  <Badge text={detailUser.is_active ? 'active' : 'deactivated'} tone={detailUser.is_active ? 'ok' : 'danger'} dot />
                  {detailUser.must_change_password && <span> <Badge text="password change pending" tone="warn" /></span>}
                </td>
              </tr>
              <tr><th scope="row">Mobile</th><td>{detailUser.mobile ? <code>{detailUser.mobile}</code> : <span className="muted">not registered</span>}</td></tr>
              <tr><th scope="row">User ID</th><td><code>{detailUser.id}</code></td></tr>
              <tr><th scope="row">Created</th><td>{new Date(detailUser.created_at).toLocaleString()}</td></tr>
              <tr><th scope="row">Last updated</th><td>{new Date(detailUser.updated_at).toLocaleString()}</td></tr>
              <tr>
                <th scope="row">Assigned mines</th>
                <td>
                  {detailUser.role === 'admin'
                    ? <span>All registered mines ({mines.length})</span>
                    : assignedMines(detailUser).length === 0
                      ? <span className="muted">None assigned — no scoped access</span>
                      : (
                        <ul style={{ margin: 0, paddingLeft: 18 }}>
                          {assignedMines(detailUser).map((m) => (
                            <li key={m.id}>{m.name} <span className="muted">({m.code})</span></li>
                          ))}
                        </ul>
                      )}
                </td>
              </tr>
            </tbody>
          </table>
          <p className="muted" style={{ marginBottom: 0 }}>
            <strong>Permissions of this role:</strong> {ROLE_META[detailUser.role]?.scope}
          </p>
          <div style={{ display: 'flex', gap: 8, marginTop: 12 }}>
            <button className="btn" onClick={() => setDetailUser(null)}>Close</button>
            <button className="btn btn-primary" onClick={() => { const u = detailUser; setDetailUser(null); openEdit(u) }}>Edit user</button>
          </div>
        </Modal>
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
        <Modal title={`Assigned mines — ${scopeTarget.full_name}`} onClose={() => setScopeTarget(null)}>
          <p className="muted" style={{ marginTop: 0 }}>
            {scopeTarget.role === 'mine_manager'
              ? 'Mine Managers work in the mines where they are registered as manager (set on the Mines page). This list is used for live detection by Safety Officers and Government Officers.'
              : 'This user can only work in the mines selected here. No selection means no mine-scoped access.'}
          </p>
          {mines.length === 0 ? <p className="muted">No mines exist yet — create one on the Mines page.</p> : (
            <div style={{ display: 'grid', gap: 6 }}>
              {mines.map((m) => (
                <label key={m.id} style={{ display: 'flex', gap: 8, alignItems: 'center' }}>
                  <input type="checkbox" checked={scopeSelected.includes(m.id)} onChange={() => toggleScopeMine(m.id)} />
                  <span>{m.name} <span className="muted">({m.code})</span></span>
                </label>
              ))}
            </div>
          )}
          <p className="muted" style={{ fontSize: '.8rem' }}>
            {scopeSelected.length} of {mines.length} mines selected. Changes are recorded in the audit log.
          </p>
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

      {editingUser && (
        <Modal title={`Edit user — ${editingUser.full_name}`} onClose={() => setEditingUser(null)}>
          <form onSubmit={handleSaveEdit} className="form-grid">
            <p className="muted" style={{ marginTop: 0 }}>
              Account email <code>{editingUser.email}</code> is fixed: it identifies the account and
              cannot be changed here. Deactivating keeps the account and its audit history.
            </p>
            <label>Full name
              <input value={editForm.full_name} autoFocus
                onChange={(e) => setEditForm({ ...editForm, full_name: e.target.value })} />
            </label>
            <label>Role
              <select value={editForm.role}
                onChange={(e) => {
                  setEditForm({ ...editForm, role: e.target.value as User['role'] })
                  setRoleConfirmed(false)
                }}>
                {ROLE_OPTIONS.map((r) => <option key={r.value} value={r.value}>{r.label}</option>)}
              </select>
            </label>

            {pendingRoleChange && (
              <div className="role-change-confirm" role="alert">
                <p style={{ marginTop: 0 }}>
                  <strong>Change role:</strong> {roleLabel(editingUser.role)} → {roleLabel(editForm.role)}
                </p>
                <p className="muted" style={{ marginTop: 0 }}>
                  {ROLE_META[editForm.role]?.scope}
                </p>
                <p className="muted" style={{ marginTop: 0 }}>
                  Mine assignments are not changed automatically. Review this account&apos;s assigned
                  mines after the role change.
                </p>
                <label style={{ display: 'flex', gap: 8, alignItems: 'flex-start' }}>
                  <input
                    type="checkbox"
                    checked={roleConfirmed}
                    onChange={(e) => setRoleConfirmed(e.target.checked)}
                  />
                  <span>
                    I understand {editingUser.full_name} will gain or lose the permissions listed above.
                  </span>
                </label>
              </div>
            )}

            <label>Mobile (optional, E.164 without +)
              <input value={editForm.mobile} inputMode="tel" placeholder="e.g. 919876543210"
                onChange={(e) => setEditForm({ ...editForm, mobile: e.target.value })} />
            </label>
            <label>Account status
              <select value={editForm.is_active ? 'active' : 'deactivated'}
                onChange={(e) => setEditForm({ ...editForm, is_active: e.target.value === 'active' })}>
                <option value="active">active</option>
                <option value="deactivated">deactivated</option>
              </select>
            </label>
            <label>Temporary password (optional)
              <input type="password" value={editForm.password} autoComplete="new-password"
                placeholder="Leave blank to keep the current password"
                onChange={(e) => setEditForm({ ...editForm, password: e.target.value })} />
            </label>
            <p className="muted" style={{ margin: 0, fontSize: '.8rem' }}>
              A password entered here is temporary: the account must choose its own on next
              sign-in, and every existing session for it is signed out immediately. Role, mine and
              account changes are all recorded in the audit log.
            </p>
            {editError && <div className="form-error" role="alert">{editError}</div>}
            <div style={{ display: 'flex', gap: 8 }}>
              <button className="btn" type="button" onClick={() => setEditingUser(null)} disabled={editBusy}>Cancel</button>
              <button
                className="btn btn-primary"
                type="submit"
                disabled={editBusy || (pendingRoleChange && !roleConfirmed)}
              >
                {editBusy ? 'Saving…' : pendingRoleChange ? 'Confirm role change' : 'Save changes'}
              </button>
            </div>
          </form>
        </Modal>
      )}

      {resetTarget && (
        <Modal title={'Reset password — ' + resetTarget.full_name} onClose={() => setResetTarget(null)}>
          {resetResult ? (
            <div>
              <p><Badge text='Temporary password created.' tone='ok' /></p>
              <p className='muted'>
                Hand this password to <strong>{resetTarget.full_name}</strong> ({resetTarget.email}) through a
                channel you trust. It is shown only once and is never stored in readable form. The account must
                choose a new password at next sign-in; until then every other screen is blocked. All existing
                sessions for the account were signed out.
              </p>
              <code style={{ display: 'block', padding: 8, wordBreak: 'break-all', fontSize: '1.2em' }}>
                {resetResult.temporary_password}
              </code>
              <div style={{ display: 'flex', gap: 8, marginTop: 12 }}>
                <button className='btn btn-primary' onClick={handleCopyTemporaryPassword}>
                  {resetCopied ? 'Copied!' : 'Copy temporary password'}
                </button>
                <button className='btn' onClick={() => setResetTarget(null)}>Done</button>
              </div>
            </div>
          ) : (
            <div>
              <p>
                Issue a temporary password for <strong>{resetTarget.full_name}</strong> ({resetTarget.email})?
              </p>
              <p className='muted'>
                The current password stops working immediately, every active session for the account is
                signed out, and the account must set a new password before it can use the platform again.
                The reset is recorded in the audit log.
              </p>
              {resetError && <div className='form-error' role='alert'>{resetError}</div>}
              <div style={{ display: 'flex', gap: 8 }}>
                <button className='btn' onClick={() => setResetTarget(null)} disabled={resetBusy}>Cancel</button>
                <button className='btn btn-primary' onClick={handleResetPassword} disabled={resetBusy}>
                  {resetBusy ? 'Resetting…' : 'Reset password'}
                </button>
              </div>
            </div>
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
              <tr><th scope="row">Role</th><td>{roleLabel(deleteTarget.role)}</td></tr>
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
          <p className="muted" style={{ marginBottom: '.2rem' }}>
            Records that reference this account (mines they managed, inspections they filed,
            alerts and actions assigned to them) are kept and de-attributed, so audit history and
            relationships survive. Deactivating instead keeps everything intact.
          </p>
          <label className="confirm-field">
            <span>Type <code>{deleteTarget.email}</code> to confirm</span>
            <input value={deleteConfirmText} autoComplete="off" autoCorrect="off" spellCheck={false}
              onChange={(e) => setDeleteConfirmText(e.target.value)} />
          </label>
          <div style={{ display: 'flex', gap: 8 }}>
            <button className="btn" onClick={() => setDeleteTarget(null)} disabled={busy}>Cancel</button>
            <button
              className="btn btn-danger"
              onClick={handleDeletePermanently}
              disabled={
                busy || deleteLoading || !deleteImpact
                || deleteConfirmText.trim().toLowerCase() !== deleteTarget.email.toLowerCase()
              }
            >
              {busy ? 'Deleting…' : 'Delete Permanently'}
            </button>
          </div>
        </Modal>
      )}
    </div>
  )
}
