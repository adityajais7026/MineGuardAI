import { useState } from 'react'
import { Link, useParams } from 'react-router-dom'
import { complianceApi, minesApi, riskApi } from '../api/endpoints'
import { useApiResource } from '../hooks/useApiResource'
import { ApiError } from '../api/client'
import {
  Badge, ErrorState, Loading, Modal, PageHeader, SimulatedDataNote, StatCard, StatusBadge,
} from '../components/ui'

export default function MineDetailPage() {
  const { mineId = '' } = useParams()
  const detail = useApiResource(() => minesApi.details(mineId), [mineId])
  const risk = useApiResource(() => riskApi.forMine(mineId), [mineId])
  const evaluation = useApiResource(() => complianceApi.evaluate(mineId), [mineId])
  const [showIngest, setShowIngest] = useState(false)
  const [ingestValue, setIngestValue] = useState('')
  const [ingestMsg, setIngestMsg] = useState<string | null>(null)
  const [ingestBusy, setIngestBusy] = useState(false)

  if (detail.loading) return <Loading />
  if (detail.error) return <div className="page"><ErrorState message={detail.error} onRetry={detail.refetch} /></div>
  if (!detail.data) return null

  const { mine, counts } = detail.data

  async function handleIngest(e: React.FormEvent) {
    e.preventDefault()
    setIngestMsg(null)
    const value = Number(ingestValue)
    if (ingestValue === '' || Number.isNaN(value)) {
      setIngestMsg('❌ Value must be a number.')
      return
    }
    setIngestBusy(true)
    try {
      const result = await complianceApi.ingest(mineId, 'pm2_5', value, 'µg/m³')
      setIngestMsg(
        `Result: ${result.status}` +
        (result.alert_generated ? ' — ⚠ alert generated' : result.status === 'VIOLATION' ? ' — duplicate suppressed' : ''),
      )
      setIngestValue('')
      setShowIngest(false)
      detail.refetch()
      risk.refetch()
      evaluation.refetch()
    } catch (err) {
      setIngestMsg(err instanceof ApiError ? `❌ ${err.message}` : '❌ Ingest failed')
    } finally {
      setIngestBusy(false)
    }
  }

  return (
    <div className="page">
      <PageHeader
        title={mine.name}
        subtitle={<><code>{mine.code}</code> · {mine.location} · {mine.mine_type.replace(/_/g, ' ')} · <StatusBadge value={mine.status} /></>}
        actions={<Link className="btn" to="/mines">← All mines</Link>}
      />

      <div className="stat-grid">
        <StatCard label="Readings" value={counts.environmental_readings} />
        <StatCard label="Camera events" value={counts.camera_events} />
        <StatCard label="Alerts" value={counts.alerts} tone={counts.alerts ? 'warn' : 'ok'} />
        <StatCard label="Incidents" value={counts.incidents} tone={counts.incidents ? 'danger' : 'ok'} />
        <StatCard label="Inspections" value={counts.inspections} />
        <StatCard label="Restricted zones" value={counts.restricted_zones} />
      </div>

      <div className="two-col">
        <div className="card">
          <h3>Risk assessment</h3>
          {risk.loading ? <Loading /> : risk.error ? <ErrorState message={risk.error} onRetry={risk.refetch} /> : risk.data && (
            <>
              <p className="risk-line">
                Score <strong>{risk.data.score}/100</strong> — <Badge text={risk.data.level}
                  tone={risk.data.level === 'LOW' ? 'ok' : risk.data.level === 'MEDIUM' ? 'warn' : 'danger'} />
              </p>
              <table className="table">
                <thead><tr><th>Factor</th><th>Points</th></tr></thead>
                <tbody>
                  {risk.data.factors.map((f) => (
                    <tr key={f.factor}><td>{f.factor.replace(/_/g, ' ')}</td><td>{f.points}/{f.max_points}</td></tr>
                  ))}
                </tbody>
              </table>
              <p className="simulated-note">{risk.data.disclaimer}</p>
            </>
          )}
        </div>

        <div className="card">
          <h3>Compliance evaluation (last 7 days)</h3>
          <button className="btn btn-sm" onClick={() => setShowIngest(true)}>+ Simulate pm2_5 reading</button>
          {showIngest && (
            <Modal title="Simulate pm2_5 reading" onClose={() => setShowIngest(false)}>
              <form onSubmit={handleIngest} className="form-grid">
                <label>Value (µg/m³ — rule threshold is 60)
                  <input type="number" step="any" value={ingestValue} autoFocus
                    onChange={(e) => setIngestValue(e.target.value)} placeholder="e.g. 95.5" />
                </label>
                <button className="btn btn-primary" type="submit" disabled={ingestBusy}>
                  {ingestBusy ? 'Submitting…' : 'Submit reading'}
                </button>
              </form>
            </Modal>
          )}
          {ingestMsg && <p className="simulated-note">{ingestMsg}</p>}
          {evaluation.loading ? <Loading /> : evaluation.error ? <ErrorState message={evaluation.error} onRetry={evaluation.refetch} /> : (
            <table className="table">
              <thead><tr><th>Parameter</th><th>Value</th><th>Status</th><th>Detail</th></tr></thead>
              <tbody>
                {(evaluation.data ?? []).slice(0, 12).map((e, i) => (
                  <tr key={i}>
                    <td>{e.parameter}</td>
                    <td>{e.value} {e.unit}</td>
                    <td><Badge text={e.status} tone={e.status === 'COMPLIANT' ? 'ok' : e.status === 'WARNING' ? 'warn' : 'danger'} /></td>
                    <td>{e.message}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </div>
      </div>
      <SimulatedDataNote />
    </div>
  )
}
