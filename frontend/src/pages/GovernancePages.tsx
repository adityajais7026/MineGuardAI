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
import { Badge, EmptyState, ErrorState, Loading, PageHeader, StatCard, StatusBadge } from '../components/ui'
import { useAuth } from '../context/AuthContext'
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

  if (loading) return <Loading />
  if (error) return <div className="page"><ErrorState message={error} onRetry={refetch} /></div>

  const s = summary as ComplianceSummary | null
  return (
    <div className="page">
      <PageHeader title="Compliance" subtitle="Configured requirements, assessed status and deadlines" />
      {s && (
        <div className="stat-grid">
          <StatCard label="Score" value={`${s.score}%`} />
          <StatCard label="Compliant (GREEN)" value={s.compliant} tone="ok" />
          <StatCard label="Attention (AMBER)" value={s.attention} tone="warn" />
          <StatCard label="Violations (RED)" value={s.violation} tone="danger" />
          <StatCard label="Not assessed (GREY)" value={s.not_assessed} />
          <StatCard label="Overdue actions" value={s.overdue_actions} tone="danger" />
          <StatCard label="Due in 7 days" value={s.upcoming_deadlines} tone="warn" />
        </div>
      )}
      <h3>Configured requirements</h3>
      <p className="muted">Every requirement shows its configured source/reference. The system never claims a requirement is a legal one unless an administrator configured that source.</p>
      {(reqs ?? []).length === 0
        ? <EmptyState message="No compliance requirements configured yet." />
        : (
          <table className="table">
            <thead><tr><th>Title</th><th>Source / reference</th><th>Frequency</th></tr></thead>
            <tbody>
              {(reqs as GovernanceTemplate[]).map((r) => (
                <tr key={r.id}>
                  <td>{r.name}</td>
                  <td>{r.regulatory_reference ?? '—'}</td>
                  <td>{r.inspection_type}</td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
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

  if (loading) return <Loading />
  if (error) return <div className="page"><ErrorState message={error} onRetry={refetch} /></div>

  async function verifyDoc(id: string, status: string) {
    setBusyId(id)
    try { await governanceApi.verifyDocument(id, status) } catch (err) {
      alert(err instanceof ApiError ? err.message : 'Verification failed')
    } finally { setBusyId(null) }
  }

  return (
    <div className="page">
      <PageHeader title="Workforce" subtitle="Workers, contractors and certificate verification" />
      <h3>Workers</h3>
      {(workers ?? []).length === 0
        ? <EmptyState message="No workers registered yet." />
        : (
          <table className="table">
            <thead><tr><th>Code</th><th>Name</th><th>Role</th></tr></thead>
            <tbody>
              {(workers ?? []).map((w) => (
                <tr key={w.id}><td>{w.employee_code}</td><td>{w.full_name}</td><td>{w.role ?? '—'}</td></tr>
              ))}
            </tbody>
          </table>
        )}
      <h3 style={{ marginTop: 20 }}>Certificates / documents</h3>
      <p className="muted">Verification status is what an authorized human recorded — the system does not claim cryptographic authenticity of scans.</p>
      {(docs as ContractorDocument[] | undefined ?? []).length === 0
        ? <EmptyState message="No documents uploaded." />
        : (
          <table className="table">
            <thead><tr><th>Title</th><th>Type</th><th>Expires</th><th>Status</th><th>Verify</th></tr></thead>
            <tbody>
              {(docs as ContractorDocument[]).map((d) => (
                <tr key={d.id}>
                  <td>{d.title}</td><td>{d.doc_type}</td><td>{d.expires_on?.slice(0, 10) ?? '—'}</td>
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
  )
}

// ---------------------------------------------------------------------------
// Emergency
// ---------------------------------------------------------------------------

const EMERGENCY_TYPES = ['fire', 'gas_leak', 'collapse', 'ppe_critical', 'worker_emergency', 'other']

export function EmergencyPage() {
  const { data, loading, error, refetch } = useApiResource(() => governanceApi.emergencies(), [])
  const [title, setTitle] = useState('')
  const [type, setType] = useState('fire')
  const [severity, setSeverity] = useState('critical')
  const [mineId, setMineId] = useState('')
  const [formError, setFormError] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)

  if (loading) return <Loading />
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

  return (
    <div className="page">
      <PageHeader title="Emergency" subtitle="Raise and manage emergency events; responsible personnel are notified in-app" />
      <form onSubmit={create} style={{ display: 'flex', gap: 8, flexWrap: 'wrap', marginBottom: 16 }}>
        <select value={mineId} onChange={(e) => setMineId(e.target.value)} aria-label="Mine">
          <option value="">Select mine…</option>
          {/* mines come from minesApi elsewhere; id kept minimal here */}
          <option value={mineId || undefined}>{mineId || '—'}</option>
        </select>
        <select value={type} onChange={(e) => setType(e.target.value)} aria-label="Type">
          {EMERGENCY_TYPES.map((t) => <option key={t} value={t}>{t}</option>)}
        </select>
        <select value={severity} onChange={(e) => setSeverity(e.target.value)} aria-label="Severity">
          {['low', 'medium', 'high', 'critical'].map((s) => <option key={s} value={s}>{s}</option>)}
        </select>
        <input value={title} onChange={(e) => setTitle(e.target.value)} placeholder="Emergency title" />
        <button className="btn btn-primary" disabled={busy}>Declare emergency</button>
      </form>
      {formError && <div className="error">{formError}</div>}
      {(data as Emergency[] | undefined ?? []).length === 0
        ? <EmptyState message="No emergency events." />
        : (
          <table className="table">
            <thead><tr><th>When</th><th>Type</th><th>Title</th><th>Severity</th><th>Status</th><th></th></tr></thead>
            <tbody>
              {(data as Emergency[]).map((em) => (
                <tr key={em.id}>
                  <td>{new Date(em.created_at).toLocaleString()}</td>
                  <td>{em.emergency_type}</td>
                  <td>{em.title}</td>
                  <td><Badge text={em.severity} tone={statusTone(em.severity)} /></td>
                  <td><Badge text={em.status} tone={statusTone(em.status)} /></td>
                  <td>{em.status === 'open' && <button className="btn btn-sm" onClick={() => resolve(em.id)}>Resolve</button>}</td>
                </tr>
              ))}
            </tbody>
          </table>
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

  if (loading) return <Loading />
  if (error) return <div className="page"><ErrorState message={error} onRetry={refetch} /></div>

  return (
    <div className="page">
      <PageHeader title="Telemetry" subtitle="Environmental sensors — devices marked DEMO are simulated, never real data" />
      {(devices as SensorDevice[] | undefined ?? []).length === 0
        ? <EmptyState message="No sensor devices registered. Real sensors integrate via the same API; demo devices are labeled DEMO." />
        : (
          <table className="table">
            <thead><tr><th>Device</th><th>Parameter</th><th>Source</th><th>Warning</th><th>Critical</th><th>Last seen</th></tr></thead>
            <tbody>
              {(devices as SensorDevice[]).map((d) => (
                <tr key={d.id}>
                  <td>{d.device_code}</td><td>{d.parameter} ({d.unit})</td>
                  <td>{d.source === 'demo' ? <Badge text="DEMO" tone="muted" /> : <Badge text="REAL" tone="ok" />}</td>
                  <td>{d.warning_threshold ?? '—'}</td><td>{d.critical_threshold ?? '—'}</td>
                  <td>{d.last_seen_at ? new Date(d.last_seen_at).toLocaleString() : 'never'}</td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      <h3 style={{ marginTop: 20 }}>Recent readings</h3>
      {(readings as TelemetryReading[] | undefined ?? []).length === 0
        ? <EmptyState message="No telemetry readings." />
        : (
          <table className="table">
            <thead><tr><th>When</th><th>Device</th><th>Value</th><th>Status</th></tr></thead>
            <tbody>
              {(readings as TelemetryReading[]).map((r) => (
                <tr key={r.id}>
                  <td>{new Date(r.recorded_at).toLocaleString()}</td>
                  <td>{r.device_id.slice(0, 8)}…</td>
                  <td>{r.value} {r.unit}</td>
                  <td><Badge text={r.status} tone={statusTone(r.status)} /></td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
    </div>
  )
}

// ---------------------------------------------------------------------------
// Risk (explainable)
// ---------------------------------------------------------------------------

export function GovernanceRiskPage() {
  const { data, loading, error, refetch } = useApiResource(() => governanceApi.riskAll(), [])
  if (loading) return <Loading />
  if (error) return <div className="page"><ErrorState message={error} onRetry={refetch} /></div>

  return (
    <div className="page">
      <PageHeader title="Risk" subtitle="Deterministic weighted score — every contribution is shown (no opaque AI)" />
      {(data as RiskScore[] | undefined ?? []).length === 0
        ? <EmptyState message="No mines to score." />
        : (data as RiskScore[]).map((r) => (
          <div key={r.mine_id} className="card" style={{ padding: 14, marginBottom: 10 }}>
            <div style={{ display: 'flex', gap: 12, alignItems: 'baseline' }}>
              <strong>Mine {r.mine_id.slice(0, 8)}…</strong>
              <StatusBadge value={`${r.band.toUpperCase()} ${r.score}`} />
            </div>
            {r.factors.length === 0
              ? <div className="muted" style={{ marginTop: 6 }}>No contributing risk factors.</div>
              : (
                <ul style={{ marginTop: 6 }}>
                  {r.factors.map((f, i) => (
                    <li key={i} className="muted">{f.factor}: +{f.points} — {f.detail}</li>
                  ))}
                </ul>
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
    return <div className="page"><PageHeader title="Audit Log" /><div className="muted">Audit log is restricted to administrators.</div></div>
  }
  if (loading) return <Loading />
  if (error) return <div className="page"><ErrorState message={error} onRetry={refetch} /></div>

  return (
    <div className="page">
      <PageHeader title="Audit Log" subtitle="Tamper-evident audit log (SHA-256 hash chain — not a blockchain)" />
      {verify && (
        <p>
          Chain verification:{' '}
          {verify.valid
            ? <Badge text={`VALID (${verify.entries} entries)`} tone="ok" />
            : <Badge text={`TAMPERED at seq ${(verify as { broken_at_seq?: number }).broken_at_seq}`} tone="danger" />}
        </p>
      )}
      {(data as AuditEvent[] | undefined ?? []).length === 0
        ? <EmptyState message="No audit events." />
        : (
          <table className="table">
            <thead><tr><th>#</th><th>When</th><th>Actor</th><th>Action</th><th>Entity</th><th>Hash</th></tr></thead>
            <tbody>
              {(data as AuditEvent[]).map((e) => (
                <tr key={e.id}>
                  <td>{e.seq}</td>
                  <td>{new Date(e.created_at).toLocaleString()}</td>
                  <td>{e.actor_role ?? '—'}</td>
                  <td>{e.action}</td>
                  <td>{e.entity_type}{e.entity_id ? ` ${e.entity_id.slice(0, 8)}…` : ''}</td>
                  <td className="muted" style={{ fontFamily: 'monospace', fontSize: 11 }}>{e.event_hash.slice(0, 12)}…</td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
    </div>
  )
}

// ---------------------------------------------------------------------------
// Notifications
// ---------------------------------------------------------------------------

export function NotificationsPage() {
  const { data, loading, error, refetch } = useApiResource(() => governanceApi.notifications(false), [])
  const [busy, setBusy] = useState(false)

  if (loading) return <Loading />
  if (error) return <div className="page"><ErrorState message={error} onRetry={refetch} /></div>

  async function markAllRead() {
    const unread = (data as GovernanceNotification[] | undefined ?? []).filter((n) => !n.read_at).map((n) => n.id)
    if (!unread.length) return
    setBusy(true)
    try { await governanceApi.markRead(unread); refetch() } finally { setBusy(false) }
  }

  return (
    <div className="page">
      <PageHeader title="Notifications" subtitle="Centralized alerts respecting mine-level permissions" />
      <button className="btn" style={{ marginBottom: 12 }} disabled={busy} onClick={markAllRead}>Mark all read</button>
      {(data as GovernanceNotification[] | undefined ?? []).length === 0
        ? <EmptyState message="No notifications." />
        : (
          <ul style={{ listStyle: 'none', padding: 0 }}>
            {(data as GovernanceNotification[]).map((n) => (
              <li key={n.id} className="card" style={{ padding: 12, marginBottom: 8, opacity: n.read_at ? 0.6 : 1 }}>
                <div style={{ display: 'flex', gap: 8, alignItems: 'baseline' }}>
                  <StatusBadge value={n.category} />
                  <strong>{n.title}</strong>
                  <span className="muted" style={{ fontSize: 12 }}>{new Date(n.created_at).toLocaleString()}</span>
                </div>
                {n.body && <div className="muted" style={{ marginTop: 4 }}>{n.body}</div>}
              </li>
            ))}
          </ul>
        )}
    </div>
  )
}

// ---------------------------------------------------------------------------
// AI workbench (honest capability matrix)
// ---------------------------------------------------------------------------

export function AiWorkbenchPage() {
  const { data, loading, error, refetch } = useApiResource(() => governanceApi.aiCapabilities(), [])
  if (loading) return <Loading />
  if (error) return <div className="page"><ErrorState message={error} onRetry={refetch} /></div>

  const labels: Record<string, string> = {
    ppe_detection: 'PPE Detection (Vyra YOLOv8m)',
    inspection_photo_analysis: 'Inspection Photo Analysis',
    ocr: 'OCR — Document Digitization',
    voice_transcription: 'Voice Transcription',
    translation: 'Translation (English/Hindi ready)',
    risk_analysis: 'Risk Analysis (deterministic)',
  }

  return (
    <div className="page">
      <PageHeader title="AI Workbench" subtitle="Every capability is labeled LIVE, EXPERIMENTAL, DEMO or UNAVAILABLE — no unsupported claims" />
      <table className="table">
        <thead><tr><th>Capability</th><th>Status</th><th>Detail</th></tr></thead>
        <tbody>
          {Object.entries(data as Record<string, AiCapability> ?? {}).map(([key, cap]) => (
            <tr key={key}>
              <td>{labels[key] ?? key}</td>
              <td><Badge text={cap.status} tone={cap.status === 'LIVE' ? 'ok' : cap.status === 'UNAVAILABLE' ? 'muted' : 'warn'} /></td>
              <td className="muted">{cap.note ?? cap.provider ?? ''}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}

// ---------------------------------------------------------------------------
// Geofencing
// ---------------------------------------------------------------------------

export function GeofencePage() {
  const { data, loading, error, refetch } = useApiResource(() => governanceApi.geofences(), [])
  const [lat, setLat] = useState<string>('')
  const [lng, setLng] = useState<string>('')
  const [mineId, setMineId] = useState('')
  const [result, setResult] = useState<string | null>(null)

  if (loading) return <Loading />
  if (error) return <div className="page"><ErrorState message={error} onRetry={refetch} /></div>

  function check() {
    setResult(null)
    const latNum = lat === '' ? undefined : Number(lat)
    const lngNum = lng === '' ? undefined : Number(lng)
    governanceApi.verifyLocation(mineId, latNum, lngNum)
      .then((r) => setResult(`${r.status.toUpperCase()}${r.message ? ` — ${r.message}` : ''}`))
      .catch((err) => setResult(err instanceof ApiError ? err.message : 'Verification failed'))
  }

  return (
    <div className="page">
      <PageHeader title="Geofencing" subtitle="Mine boundaries; device GPS is verified server-side. No GPS data is ever fabricated." />
      <MineMap
        points={((data as Geofence[] | undefined) ?? [])
          .filter((g) => g.boundary_type === 'radius' && g.center_lat != null && g.center_lng != null)
          .map((g) => ({ id: g.id, label: g.name, latitude: g.center_lat as number, longitude: g.center_lng as number, kind: 'geofence' as const }))}
        height={280}
      />
      {(data as Geofence[] | undefined ?? []).length === 0
        ? <EmptyState message="No geofences configured." />
        : (
          <table className="table">
            <thead><tr><th>Name</th><th>Mine</th><th>Type</th><th>Center / polygon</th><th>Radius</th></tr></thead>
            <tbody>
              {(data as Geofence[]).map((g) => (
                <tr key={g.id}>
                  <td>{g.name}</td><td>{g.mine_id.slice(0, 8)}…</td><td>{g.boundary_type}</td>
                  <td>{g.boundary_type === 'radius' ? `${g.center_lat}, ${g.center_lng}` : `${g.polygon_json?.length ?? 0} points`}</td>
                  <td>{g.radius_m ? `${g.radius_m} m` : '—'}</td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      <h3 style={{ marginTop: 20 }}>Verify a location</h3>
      <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap' }}>
        <input value={mineId} onChange={(e) => setMineId(e.target.value)} placeholder="Mine ID" />
        <input value={lat} onChange={(e) => setLat(e.target.value)} placeholder="Latitude (blank = unavailable)" />
        <input value={lng} onChange={(e) => setLng(e.target.value)} placeholder="Longitude (blank = unavailable)" />
        <button className="btn" onClick={check}>Verify</button>
      </div>
      {result && <p><strong>{result}</strong></p>}
    </div>
  )
}
