/**
 * Smart Governance & Compliance pages.
 *
 * One module, several exported pages, following existing page conventions
 * (useApiResource + ui components). All new pages are ADDITIVE: existing
 * pages (InspectionsPage, etc.) are untouched.
 */
import { useState } from 'react'
import { governanceApi } from '../api/endpoints'
import type {
  AiCapability, AuditEvent, ComplianceSummary, ContractorDocument, Emergency,
  GovernanceNotification, GovernanceTemplate, Geofence, RiskScore, SensorDevice,
  TelemetryReading,
} from '../api/endpoints'
import { useApiResource } from '../hooks/useApiResource'
import { ApiError } from '../api/client'
import {
  Badge, CertStatus, EmptyState, ErrorState, PageHeader, RiskLevelBadge,
  SeverityBadge, Skeleton, StatCard, StatusBadge, Tooltip,
} from '../components/ui'
import { useAuth } from '../context/AuthContext'
import { minesApi } from '../api/endpoints'
import type { Mine } from '../api/types'
import MineMap from '../components/MineMap'

function statusTone(status: string): 'ok' | 'warn' | 'danger' | 'info' | 'muted' {
  switch (status) {
    case 'compliant': case 'normal': case 'valid': case 'LIVE': case 'synced': return 'ok'
    case 'attention': case 'warning': case 'expiring': case 'EXPERIMENTAL': case 'pending': return 'warn'
    case 'violation': case 'critical': case 'expired': case 'open': case 'failed': return 'danger'
    default: return 'muted'
  }
}

// ---------------------------------------------------------------------------
// Compliance dashboard (GREEN/AMBER/RED/GREY)
// ---------------------------------------------------------------------------

export function GovernanceCompliancePage() {
  const { data: summary, loading, error, refetch } = useApiResource(
    () => governanceApi.summary(undefined, 'monthly'), [])
  const { data: reqs } = useApiResource(() => governanceApi.requirements(), [])

  if (loading) return <div className="page"><PageHeader title="Compliance" /><Skeleton lines={4} /></div>
  if (error) return <div className="page"><ErrorState message={error} onRetry={refetch} /></div>

  const s = summary as ComplianceSummary | null
  return (
    <div className="page">
      <PageHeader
        title="Compliance Status"
        subtitle="Regulatory compliance position — monthly aggregation of assessed requirements and deadlines"
      />
      {s && (
        <>
          <div className="card ppe-summary" style={{
            borderLeftColor: s.violation > 0 ? 'var(--danger)' : s.attention > 0 ? 'var(--warn)' : s.compliant > 0 ? 'var(--ok)' : 'var(--border-strong)',
          }}>
            <div style={{ display: 'flex', alignItems: 'baseline', gap: '.7rem', flexWrap: 'wrap' }}>
              <Badge
                text={s.violation > 0 ? 'NON-COMPLIANT — ACTION REQUIRED' : s.attention > 0 ? 'ATTENTION REQUIRED' : s.compliant > 0 ? 'COMPLIANT' : 'NOT ASSESSED'}
                tone={s.violation > 0 ? 'danger' : s.attention > 0 ? 'warn' : s.compliant > 0 ? 'ok' : 'muted'}
                dot large
              />
              <span className="muted">Overall score {s.score}% this period</span>
            </div>
          </div>
          <div className="stat-grid">
            <StatCard label="Score" value={`${s.score}%`} />
            <StatCard label="Compliant (GREEN)" value={s.compliant} tone="ok" />
            <StatCard label="Attention (AMBER)" value={s.attention} tone="warn" />
            <StatCard label="Violations (RED)" value={s.violation} tone="danger" flash={s.violation > 0} />
            <StatCard label="Not assessed (GREY)" value={s.not_assessed} tone="muted" />
            <StatCard label="Overdue actions" value={s.overdue_actions} tone="danger" flash={s.overdue_actions > 0} />
            <StatCard label="Due in 7 days" value={s.upcoming_deadlines} tone="warn" />
          </div>
        </>
      )}
      <div className="card">
        <h3>Configured requirements</h3>
        <p className="card-sub">Every requirement shows its configured source/reference. The system never claims a requirement is a legal one unless an administrator configured that source.</p>
        {(reqs ?? []).length === 0
          ? <EmptyState title="None configured" message="No compliance requirements configured yet. Administrators can add them from inspection templates." />
          : (
            <table className="table">
              <thead><tr><th>Title</th><th>Source / reference</th><th>Frequency</th></tr></thead>
              <tbody>
                {(reqs as GovernanceTemplate[]).map((r) => (
                  <tr key={r.id}>
                    <td className="table-link">{r.name}</td>
                    <td>{r.regulatory_reference ?? <span className="muted">not configured</span>}</td>
                    <td>{r.inspection_type}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
      </div>
    </div>
  )
}



// ---------------------------------------------------------------------------
// Workers & contractors
// ---------------------------------------------------------------------------

export function WorkforcePage() {
  const { data: workers, loading, error, refetch } = useApiResource(() => governanceApi.workers(), [])
  const { data: docs } = useApiResource(() => governanceApi.documents(), [])
  const [busyId, setBusyId] = useState<string | null>(null)

  if (loading) return <div className="page"><PageHeader title="Workforce" /><Skeleton lines={4} /></div>
  if (error) return <div className="page"><ErrorState message={error} onRetry={refetch} /></div>

  async function verifyDoc(id: string, status: string) {
    setBusyId(id)
    try { await governanceApi.verifyDocument(id, status) } catch (err) {
      alert(err instanceof ApiError ? err.message : 'Verification failed')
    } finally { setBusyId(null) }
  }

  return (
    <div className="page">
      <PageHeader title="Workforce" subtitle="Mine workers, contractors and certificate verification" />
      <div className="card">
        <h3>Workers ({(workers ?? []).length})</h3>
        {(workers ?? []).length === 0
          ? <EmptyState title="No workers" message="No workers registered yet. Workers can be registered once mines are configured." />
          : (
            <table className="table">
              <thead><tr><th>Code</th><th>Name</th><th>Role</th></tr></thead>
              <tbody>
                {(workers ?? []).map((w) => (
                  <tr key={w.id}><td><code>{w.employee_code}</code></td><td className="table-link">{w.full_name}</td><td>{w.role ?? '—'}</td></tr>
                ))}
              </tbody>
            </table>
          )}
      </div>
      <div className="card">
        <h3>Certificates &amp; documents ({(docs as ContractorDocument[] | undefined ?? []).length})</h3>
        <p className="card-sub">Verification status is what an authorized human recorded — the system does not claim cryptographic authenticity of scans.</p>
        {(docs as ContractorDocument[] | undefined ?? []).length === 0
          ? <EmptyState title="No documents" message="No certificates or documents uploaded yet. Upload via the contractor module API." />
          : (
            <table className="table">
              <thead><tr><th>Title</th><th>Type</th><th>Expires</th><th>Certificate status</th><th>Recorded status</th><th>Verify</th></tr></thead>
              <tbody>
                {(docs as ContractorDocument[]).map((d) => (
                  <tr key={d.id}>
                    <td className="table-link">{d.title}</td>
                    <td>{d.doc_type}</td>
                    <td><small>{d.expires_on?.slice(0, 10) ?? '—'}</small></td>
                    <td><CertStatus expiresOn={d.expires_on} verificationStatus={d.verification_status} /></td>
                    <td><Badge text={d.verification_status} tone={statusTone(d.verification_status)} /></td>
                    <td>
                      <button className="btn btn-sm" disabled={busyId === d.id} onClick={() => verifyDoc(d.id, 'valid')}>Mark valid</button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
      </div>
    </div>
  )
}

// ---------------------------------------------------------------------------
// Emergency
// ---------------------------------------------------------------------------

const EMERGENCY_TYPES = ['fire', 'gas_leak', 'collapse', 'ppe_critical', 'worker_emergency', 'other']

export function EmergencyPage() {
  const { data, loading, error, refetch } = useApiResource(() => governanceApi.emergencies(), [])
  const mines = useApiResource(() => minesApi.list({ limit: 200 }).then((r) => r.items), [])
  const [title, setTitle] = useState('')
  const [type, setType] = useState('fire')
  const [severity, setSeverity] = useState('critical')
  const [mineId, setMineId] = useState('')
  const [formError, setFormError] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)

  if (loading) return <div className="page"><PageHeader title="Emergency" /><Skeleton lines={3} /></div>
  if (error) return <div className="page"><ErrorState message={error} onRetry={refetch} /></div>

  async function create(e: React.FormEvent) {
    e.preventDefault()
    setFormError(null)
    if (!title || !mineId) { setFormError('Mine and title are required.'); return }
    setBusy(true)
    try {
      await governanceApi.createEmergency({ mine_id: mineId, emergency_type: type, severity, title })
      setTitle('')
      refetch()
    } catch (err) {
      setFormError(err instanceof ApiError ? err.message : 'Could not create emergency.')
    } finally { setBusy(false) }
  }

  async function resolve(id: string) {
    try { await governanceApi.updateEmergency(id, { status: 'resolved' }); refetch() } catch { /* listed error path */ }
  }

  const list = (data as Emergency[] | undefined) ?? []
  const open = list.filter((em) => em.status === 'open')
  const resolved = list.filter((em) => em.status !== 'open')

  return (
    <div className="page">
      <PageHeader
        title="Emergency"
        subtitle="Declare and manage emergency events. Declaring an emergency immediately notifies responsible personnel."
        actions={<Badge text={`${open.length} OPEN`} tone={open.length ? 'danger' : 'ok'} dot />}
      />
      <form onSubmit={create} className="card">
        <h3>Declare an emergency</h3>
        <div className="form-row">
          <label>Mine <span className="req" />
            <select value={mineId} onChange={(e) => setMineId(e.target.value)}>
              <option value="">Select mine…</option>
              {((mines.data ?? []) as Mine[]).map((m) => <option key={m.id} value={m.id}>{m.name}</option>)}
            </select>
          </label>
          <label>Type
            <select value={type} onChange={(e) => setType(e.target.value)}>
              {EMERGENCY_TYPES.map((t) => <option key={t} value={t}>{t.replace(/_/g, ' ')}</option>)}
            </select>
          </label>
          <label>Severity
            <select value={severity} onChange={(e) => setSeverity(e.target.value)}>
              {['low', 'medium', 'high', 'critical'].map((s) => <option key={s} value={s}>{s}</option>)}
            </select>
          </label>
          <label>Title <span className="req" />
            <input value={title} onChange={(e) => setTitle(e.target.value)} placeholder="Short, factual description" />
          </label>
        </div>
        {formError && <div className="form-error" role="alert" style={{ marginTop: 8 }}>{formError}</div>}
        <div style={{ marginTop: 10 }}>
          <button className="btn btn-danger" disabled={busy}>🚨 Declare emergency</button>
        </div>
      </form>
      {list.length === 0
        ? <EmptyState title="No emergencies" message="No emergency events have been declared. This page will show declared events with their status."
        />
        : (
          <>
            {open.length > 0 && (
              <div className="card">
                <h3>Open emergencies ({open.length})</h3>
                <table className="table">
                  <thead><tr><th>When</th><th>Type</th><th>Title</th><th>Severity</th><th>Status</th><th></th></tr></thead>
                  <tbody>
                    {open.map((em) => (
                      <tr key={em.id} className="row-critical">
                        <td><small>{new Date(em.created_at).toLocaleString()}</small></td>
                        <td>{em.emergency_type}</td>
                        <td className="table-link">{em.title}</td>
                        <td><SeverityBadge value={em.severity} /></td>
                        <td><StatusBadge value={em.status} /></td>
                        <td><button className="btn btn-sm btn-success" onClick={() => resolve(em.id)}>Mark resolved</button></td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
            {resolved.length > 0 && (
              <div className="card">
                <h3>Resolved ({resolved.length})</h3>
                <table className="table">
                  <thead><tr><th>When</th><th>Type</th><th>Title</th><th>Severity</th><th>Status</th></tr></thead>
                  <tbody>
                    {resolved.map((em) => (
                      <tr key={em.id}>
                        <td><small>{new Date(em.created_at).toLocaleString()}</small></td>
                        <td>{em.emergency_type}</td>
                        <td>{em.title}</td>
                        <td><SeverityBadge value={em.severity} /></td>
                        <td><StatusBadge value={em.status} /></td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
          </>
        )}
    </div>
  )
}

// ---------------------------------------------------------------------------
// Telemetry (clearly labeled DEMO devices)
// ---------------------------------------------------------------------------

export function TelemetryPage() {
  const { data: devices, loading, error, refetch } = useApiResource(() => governanceApi.devices(), [])
  const { data: readings } = useApiResource(() => governanceApi.readings({ limit: 50 }), [])

  if (loading) return <div className="page"><PageHeader title="Telemetry" /><Skeleton lines={4} /></div>
  if (error) return <div className="page"><ErrorState message={error} onRetry={refetch} /></div>

  return (
    <div className="page">
      <PageHeader
        title="Telemetry"
        subtitle="Environmental sensor readings with configured warning/critical thresholds"
        actions={<Badge text="DEMO SENSORS ONLY" tone="warn" />}
      />
      <UnavailTelemetryIntro />
      <div className="card">
        <h3>Sensor devices ({(devices as SensorDevice[] | undefined ?? []).length})</h3>
        {(devices as SensorDevice[] | undefined ?? []).length === 0
          ? <EmptyState title="No sensors" message="No sensor devices registered. Real sensors integrate via the same API; demo devices are labeled DEMO." />
          : (
            <table className="table">
              <thead><tr><th>Device</th><th>Parameter</th><th>Source</th><th>Warning at</th><th>Critical at</th><th>Last seen</th></tr></thead>
              <tbody>
                {(devices as SensorDevice[]).map((d) => (
                  <tr key={d.id}>
                    <td><code>{d.device_code}</code></td>
                    <td>{d.parameter} ({d.unit})</td>
                    <td>{d.source === 'demo'
                      ? <Tooltip text="This device is simulated for demonstration — its readings are generated data, never real measurements."><Badge text="DEMO" tone="warn" /></Tooltip>
                      : <Badge text="REAL" tone="ok" />}</td>
                    <td className="num">{d.warning_threshold ?? '—'}</td>
                    <td className="num">{d.critical_threshold ?? '—'}</td>
                    <td><small>{d.last_seen_at ? new Date(d.last_seen_at).toLocaleString() : 'never'}</small></td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
      </div>
      <div className="card">
        <h3>Recent readings</h3>
        {(readings as TelemetryReading[] | undefined ?? []).length === 0
          ? <EmptyState title="No readings" message="No telemetry readings recorded yet." />
          : (
            <table className="table">
              <thead><tr><th>When</th><th>Device</th><th>Value</th><th>Status</th></tr></thead>
              <tbody>
                {(readings as TelemetryReading[]).map((r) => (
                  <tr key={r.id} className={r.status === 'critical' ? 'row-critical' : undefined}>
                    <td><small>{new Date(r.recorded_at).toLocaleString()}</small></td>
                    <td><small><code>{r.device_id.slice(0, 8)}…</code></small></td>
                    <td className="num">{r.value} {r.unit}</td>
                    <td><Badge text={r.status} tone={statusTone(r.status)} dot /></td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
      </div>
    </div>
  )
}

function UnavailTelemetryIntro() {
  return null
}

// ---------------------------------------------------------------------------
// Risk (explainable)
// ---------------------------------------------------------------------------

export function GovernanceRiskPage() {
  const { data, loading, error, refetch } = useApiResource(() => governanceApi.riskAll(), [])
  if (loading) return <div className="page"><PageHeader title="Risk Score" /><Skeleton lines={3} /></div>
  if (error) return <div className="page"><ErrorState message={error} onRetry={refetch} /></div>

  return (
    <div className="page">
      <PageHeader
        title="Risk Score"
        subtitle="Deterministic weighted score — every contribution is shown. No opaque AI; no hidden inputs."
      />
      <div className="stat-grid">
        {(['low', 'medium', 'high', 'critical'] as const).map((bandUppercase) => {
          const bandLower = bandUppercase
          const n = ((data as RiskScore[] | undefined) ?? []).filter((r) => r.band === bandLower).length
          return <StatCard key={bandLower} label={`${bandLower.toUpperCase()} risk`} value={n}
            tone={bandLower === 'low' ? 'ok' : bandLower === 'medium' ? 'warn' : 'danger'} />
        })}
      </div>
      {((data as RiskScore[] | undefined) ?? []).length === 0
        ? <EmptyState title="No scores" message="No mines to score yet. Risk appears once system data is available."
        />
        : (data as RiskScore[]).map((r) => (
          <div key={r.mine_id} className="card">
            <div className="risk-head">
              <div>
                <h3 style={{ textTransform: 'none', letterSpacing: 0, color: 'var(--text)', fontSize: '.95rem' }}>Mine {r.mine_id.slice(0, 8)}…</h3>
                <RiskLevelBadge level={r.band} />
              </div>
              <div className="risk-score">
                <div className="risk-score-number">{r.score}<small>/100</small></div>
                <div className={`risk-bar level-${r.band.toLowerCase()}`}><div style={{ width: `${Math.min(100, r.score)}%` }} /></div>
              </div>
            </div>
            {r.factors.length === 0
              ? <div className="muted" style={{ marginTop: 8 }}>No contributing risk factors — nothing counts against this mine.</div>
              : (
                <div style={{ marginTop: 10 }}>
                  {r.factors.map((f, i) => (
                    <div key={i} className="risk-factor-row">
                      <span className="risk-factor-pts">+{f.points}</span>
                      <div>
                        <strong style={{ fontSize: '.84rem' }}>{f.factor.replace(/_/g, ' ')}</strong>
                        <div className="muted small">{f.detail}</div>
                      </div>
                    </div>
                  ))}
                </div>
              )}
          </div>
        ))}
    </div>
  )
}

// ---------------------------------------------------------------------------
// Audit log (admin; tamper-evident — hash chain, NOT blockchain)
// ---------------------------------------------------------------------------

export function AuditLogPage() {
  const { user } = useAuth()
  const isAdmin = user?.role === 'admin'
  const { data, loading, error, refetch } = useApiResource(
    () => (isAdmin ? governanceApi.audit({ limit: 200 }) : Promise.resolve([])), [isAdmin])
  const { data: verify } = useApiResource(
    () => (isAdmin ? governanceApi.auditVerify() : Promise.resolve(null)), [isAdmin])

  if (!isAdmin) {
    return <div className="page"><PageHeader title="Audit Log" /><div className="card"><p className="muted">Audit log is restricted to administrators.</p></div></div>
  }
  if (loading) return <div className="page"><PageHeader title="Audit Log" /><Skeleton lines={4} /></div>
  if (error) return <div className="page"><ErrorState message={error} onRetry={refetch} /></div>

  return (
    <div className="page">
      <PageHeader
        title="Audit Log"
        subtitle="Tamper-evident SHA-256 hash chain. Detection of any modification to past entries."
        actions={verify && (
          <Badge
            text={verify.valid ? `CHAIN VERIFIED — ${verify.entries} ENTRIES` : `CHAIN TAMPERED — SEQ ${(verify as { broken_at_seq?: number }).broken_at_seq}`}
            tone={verify.valid ? 'ok' : 'danger'} dot large
          />
        )}
      />
      <div className="card">
        <p className="card-sub">
          Each entry's hash includes the previous entry's hash. Changing any past record breaks
          every later hash, which the verification badge detects. (A hash chain — not a blockchain.)
        </p>
        {(data as AuditEvent[] | undefined ?? []).length === 0
          ? <EmptyState title="No events" message="No audit events recorded yet. Actions such as inspections, evidence uploads and approvals append to the chain."
          />
          : (
            <table className="table">
              <thead><tr><th>#</th><th>When</th><th>Actor</th><th>Action</th><th>Entity</th><th>Hash</th></tr></thead>
              <tbody>
                {(data as AuditEvent[]).map((e) => (
                  <tr key={e.id}>
                    <td className="num muted">{e.seq}</td>
                    <td><small>{new Date(e.created_at).toLocaleString()}</small></td>
                    <td>{e.actor_role ?? '—'}</td>
                    <td><code style={{ fontSize: '.78em' }}>{e.action}</code></td>
                    <td><small>{e.entity_type}{e.entity_id ? ` ${e.entity_id.slice(0, 8)}…` : ''}</small></td>
                    <td className="muted monospace">{e.event_hash.slice(0, 12)}…</td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
      </div>
    </div>
  )
}

// ---------------------------------------------------------------------------
// Notifications
// ---------------------------------------------------------------------------

export function NotificationsPage() {
  const { data, loading, error, refetch } = useApiResource(() => governanceApi.notifications(), [])
  const [busy, setBusy] = useState(false)

  if (loading) return <div className="page"><PageHeader title="Notifications" /><Skeleton lines={3} /></div>
  if (error) return <div className="page"><ErrorState message={error} onRetry={refetch} /></div>

  async function markAllRead() {
    const unread = (data as GovernanceNotification[] | undefined ?? []).filter((n) => !n.read_at).map((n) => n.id)
    if (!unread.length) return
    setBusy(true)
    try { await governanceApi.markRead(unread); refetch() } finally { setBusy(false) }
  }

  const list = (data as GovernanceNotification[] | undefined) ?? []
  const unreadCount = list.filter((n) => !n.read_at).length

  const CATEGORY_TONE: Record<string, 'ok' | 'warn' | 'danger' | 'info' | 'muted'> = {
    emergency: 'danger', overdue_action: 'warn', ppe: 'danger',
    compliance: 'warn', inspection: 'info', system: 'muted',
  }
  const CAT_LABEL: Record<string, string> = {
    emergency: 'Emergency', overdue_action: 'Corrective action',
    ppe: 'PPE violation', compliance: 'Compliance',
    inspection: 'Inspection', system: 'System',
  }

  return (
    <div className="page">
      <PageHeader
        title="Notifications"
        subtitle="Centralized alerts respecting mine-level permissions"
        actions={
          <>
            <Badge text={unreadCount ? `${unreadCount} UNREAD` : 'ALL READ'} tone={unreadCount ? 'danger' : 'ok'} dot />
            <button className="btn" disabled={busy || unreadCount === 0} onClick={markAllRead}>Mark all read</button>
          </>
        }
      />
      {list.length === 0
        ? <EmptyState title="Inbox empty" message="No notifications. You will be notified here about emergencies, overdue corrective actions and review outcomes."
        />
        : (
          <div>
            {list.map((n) => (
              <div key={n.id} className={`card${!n.read_at ? ' card-danger' : ''}`}
                style={{ padding: '.8rem 1rem', marginBottom: 8, opacity: n.read_at ? 0.72 : 1 }}>
                <div style={{ display: 'flex', gap: 8, alignItems: 'baseline', flexWrap: 'wrap' }}>
                  <Badge text={CAT_LABEL[n.category] ?? n.category} tone={CATEGORY_TONE[n.category] ?? 'muted'} dot={!n.read_at} />
                  <strong>{n.title}</strong>
                  <span className="muted" style={{ fontSize: 12, marginLeft: 'auto' }}>{new Date(n.created_at).toLocaleString()}</span>
                </div>
                {n.body && <div className="muted" style={{ marginTop: 4, fontSize: '.84rem' }}>{n.body}</div>}
              </div>
            ))}
          </div>
        )}
    </div>
  )
}

// ---------------------------------------------------------------------------
// AI workbench (honest capability matrix)
// ---------------------------------------------------------------------------

export function AiWorkbenchPage() {
  const { data, loading, error, refetch } = useApiResource(() => governanceApi.aiCapabilities(), [])
  if (loading) return <div className="page"><PageHeader title="AI Workbench" /><Skeleton lines={3} /></div>
  if (error) return <div className="page"><ErrorState message={error} onRetry={refetch} /></div>

  const labels: Record<string, string> = {
    ppe_detection: 'PPE Detection (Vyra)',
    inspection_photo_analysis: 'Inspection Photo Analysis',
    ocr: 'OCR — Document Digitization',
    voice_transcription: 'Voice Transcription',
    translation: 'Translation',
    risk_analysis: 'Risk Analysis (deterministic)',
  }
  const capTone = (status: string): 'ok' | 'warn' | 'danger' | 'info' | 'muted' =>
    status === 'LIVE' ? 'ok' : status === 'EXPERIMENTAL' || status === 'DEMO' ? 'warn' : 'muted'

  return (
    <div className="page">
      <PageHeader
        title="AI Workbench"
        subtitle="Capability matrix with honest status labels. The system never claims a capability is available when it is not."
      />
      <div className="card">
        <p className="card-sub">Status meanings — <Badge text="LIVE" tone="ok" dot /> production-ready and in use · <Badge text="EXPERIMENTAL / DEMO" tone="warn" dot /> working but restricted or simulated · <Badge text="UNAVAILABLE" tone="muted" dot /> not configured, no false output is produced.</p>
        <table className="table">
          <thead><tr><th>Capability</th><th>Status</th><th>Detail</th></tr></thead>
          <tbody>
            {Object.entries((data as Record<string, AiCapability>) ?? {}).map(([key, cap]) => (
              <tr key={key}>
                <td className="table-link">{labels[key] ?? key}</td>
                <td><Badge text={cap.status} tone={capTone(cap.status)} dot /></td>
                <td className="muted">{cap.note ?? cap.provider ?? ''}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  )
}

// ---------------------------------------------------------------------------
// Geofencing
// ---------------------------------------------------------------------------

export function GeofencePage() {
  const { data, loading, error, refetch } = useApiResource(() => governanceApi.geofences(), [])
  const mines = useApiResource(() => minesApi.list({ limit: 200 }).then((r) => r.items), [])
  const [lat, setLat] = useState<string>('')
  const [lng, setLng] = useState<string>('')
  const [mineId, setMineId] = useState('')
  const [result, setResult] = useState<{ status: string; message?: string; unver: boolean } | null>(null)

  if (loading) return <div className="page"><PageHeader title="Geofencing" /><Skeleton lines={3} /></div>
  if (error) return <div className="page"><ErrorState message={error} onRetry={refetch} /></div>

  function check() {
    setResult(null)
    const latNum = lat === '' ? undefined : Number(lat)
    const lngNum = lng === '' ? undefined : Number(lng)
    const unver = lat === '' || lng === ''
    governanceApi.verifyLocation(mineId, latNum, lngNum)
      .then((r) => setResult({ ...r, unver }))
      .catch((err) => setResult({ status: 'ERROR', message: err instanceof ApiError ? err.message : 'Verification failed', unver: true }))
  }

  const gfList = (data as Geofence[] | undefined) ?? []
  return (
    <div className="page">
      <PageHeader
        title="Geofencing"
        subtitle="Mine boundaries with server-side location verification. No GPS data is ever fabricated — devices without coordinates report that honestly."
      />
      <div className="card">
        <h3>Mine boundaries</h3>
        {gfList.length === 0
          ? <EmptyState title="No geofences" message="No mine boundaries configured yet. Geofences define radius or polygon boundaries used for zone safety rules."
          />
          : (
            <>
              <MineMap
                points={gfList
                  .filter((g) => g.boundary_type === 'radius' && g.center_lat != null && g.center_lng != null)
                  .map((g) => ({ id: g.id, label: g.name, latitude: g.center_lat as number, longitude: g.center_lng as number, kind: 'geofence' as const }))}
                height={280}
              />
              <table className="table" style={{ marginTop: 12 }}>
                <thead><tr><th>Name</th><th>Mine</th><th>Type</th><th>Center / polygon</th><th>Radius</th></tr></thead>
                <tbody>
                  {gfList.map((g) => (
                    <tr key={g.id}>
                      <td className="table-link">{g.name}</td>
                      <td><small>{(((mines.data ?? []) as Mine[]).find((m) => m.id === g.mine_id)?.name) ?? g.mine_id.slice(0, 8) + '…'}</small></td>
                      <td>{g.boundary_type}</td>
                      <td><small>{g.boundary_type === 'radius' ? `${g.center_lat}, ${g.center_lng}` : `${g.polygon_json?.length ?? 0} points`}</small></td>
                      <td className="num">{g.radius_m ? `${g.radius_m} m` : '—'}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </>
          )}
      </div>
      <div className="card">
        <h3>Verify a location</h3>
        <p className="card-sub">Leave coordinates blank to see how the system reports an honest UNAVAILABLE result (as devices without GPS do).</p>
        <div className="form-row">
          <label>Mine
            <select value={mineId} onChange={(e) => setMineId(e.target.value)}>
              <option value="">Select mine…</option>
              {((mines.data ?? []) as Mine[]).map((m) => <option key={m.id} value={m.id}>{m.name}</option>)}
            </select>
          </label>
          <label>Latitude
            <input value={lat} onChange={(e) => setLat(e.target.value)} placeholder="blank = unavailable" inputMode="decimal" />
          </label>
          <label>Longitude
            <input value={lng} onChange={(e) => setLng(e.target.value)} placeholder="blank = unavailable" inputMode="decimal" />
          </label>
        </div>
        <div style={{ marginTop: 10 }}>
          <button className="btn btn-primary" onClick={check} disabled={!mineId}>Verify</button>
        </div>
        {result && (
          <div style={{ marginTop: 10 }}>
            <Badge
              text={result.status.toUpperCase()}
              tone={result.status === 'inside' ? 'ok' : result.status === 'outside' ? 'danger' : 'muted'}
              dot large
            />
            {result.message && <span className="muted" style={{ marginLeft: 8 }}>{result.message}</span>}
          </div>
        )}
      </div>
    </div>
  )
}
