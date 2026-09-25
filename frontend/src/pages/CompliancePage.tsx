import { useState } from 'react'
import { complianceApi } from '../api/endpoints'
import { useApiResource } from '../hooks/useApiResource'
import { ApiError } from '../api/client'
import {
  Badge, ConfirmButton, EmptyState, ErrorState, Loading, Modal, PageHeader, SeverityBadge, SimulatedDataNote,
} from '../components/ui'

const EMPTY_RULE = {
  name: '', parameter: '', operator: '>', threshold: '', unit: '', severity: 'medium', mine_id: '',
}

export default function CompliancePage() {
  const { data, loading, error, refetch } = useApiResource(() => complianceApi.rules({ limit: 200 }), [])
  const [showCreate, setShowCreate] = useState(false)
  const [form, setForm] = useState(EMPTY_RULE)
  const [formError, setFormError] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)

  async function handleCreate(e: React.FormEvent) {
    e.preventDefault()
    setFormError(null)
    const threshold = Number(form.threshold)
    if (!form.name.trim() || !form.parameter.trim() || !form.unit.trim()) {
      setFormError('Name, parameter and unit are required.')
      return
    }
    if (Number.isNaN(threshold)) {
      setFormError('Threshold must be a number.')
      return
    }
    setBusy(true)
    try {
      await complianceApi.createRule({
        name: form.name, parameter: form.parameter, operator: form.operator,
        threshold, unit: form.unit, severity: form.severity as 'low' | 'medium' | 'high' | 'critical',
        mine_id: form.mine_id || null,
      })
      setShowCreate(false)
      setForm(EMPTY_RULE)
      refetch()
    } catch (err) {
      setFormError(err instanceof ApiError ? err.message : 'Could not create rule.')
    } finally {
      setBusy(false)
    }
  }

  async function toggleActive(id: string, current: boolean) {
    await complianceApi.updateRule(id, { is_active: !current })
    refetch()
  }

  if (loading) return <Loading />
  if (error) return <div className="page"><ErrorState message={error} onRetry={refetch} /></div>

  return (
    <div className="page">
      <PageHeader
        title="Compliance Rules"
        subtitle="Thresholds evaluated by the compliance engine. Demo values — not statutory limits."
        actions={<button className="btn btn-primary" onClick={() => setShowCreate(true)}>+ New rule</button>}
      />

      {(data?.items.length ?? 0) === 0 ? <EmptyState message="No compliance rules configured." /> : (
        <div className="card">
          <table className="table">
            <thead>
              <tr><th>Rule</th><th>Parameter</th><th>Condition</th><th>Severity</th><th>Scope</th><th>Active</th><th /></tr>
            </thead>
            <tbody>
              {data!.items.map((r) => (
                <tr key={r.id}>
                  <td>{r.name}</td>
                  <td><code>{r.parameter}</code></td>
                  <td>{r.operator} {r.threshold} {r.unit}</td>
                  <td><SeverityBadge value={r.severity} /></td>
                  <td>{r.mine_id ? <Badge text="mine-specific" tone="info" /> : <Badge text="all mines" tone="muted" />}</td>
                  <td><Badge text={r.is_active ? 'active' : 'inactive'} tone={r.is_active ? 'ok' : 'muted'} /></td>
                  <td className="table-actions">
                    <button className="btn btn-sm" onClick={() => toggleActive(r.id, r.is_active)}>
                      {r.is_active ? 'Disable' : 'Enable'}
                    </button>
                    <ConfirmButton onConfirm={async () => { await complianceApi.deleteRule(r.id); refetch() }}>Delete</ConfirmButton>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      {showCreate && (
        <Modal title="New compliance rule" onClose={() => setShowCreate(false)}>
          <form onSubmit={handleCreate} className="form-grid">
            <label>Rule name<input value={form.name} onChange={(e) => setForm({ ...form, name: e.target.value })} /></label>
            <label>Parameter (e.g. pm2_5)<input value={form.parameter} onChange={(e) => setForm({ ...form, parameter: e.target.value })} /></label>
            <div className="form-row">
              <label>Operator
                <select value={form.operator} onChange={(e) => setForm({ ...form, operator: e.target.value })}>
                  <option value=">">&gt;</option><option value=">=">&gt;=</option>
                  <option value="<">&lt;</option><option value="<=">&lt;=</option>
                </select>
              </label>
              <label>Threshold<input type="number" step="any" value={form.threshold}
                onChange={(e) => setForm({ ...form, threshold: e.target.value })} /></label>
              <label>Unit<input value={form.unit} onChange={(e) => setForm({ ...form, unit: e.target.value })} /></label>
            </div>
            <div className="form-row">
              <label>Severity
                <select value={form.severity} onChange={(e) => setForm({ ...form, severity: e.target.value })}>
                  <option value="low">low</option><option value="medium">medium</option>
                  <option value="high">high</option><option value="critical">critical</option>
                </select>
              </label>
              <label>Scope
                <select value={form.mine_id} onChange={(e) => setForm({ ...form, mine_id: e.target.value })}>
                  <option value="">all mines</option>
                </select>
              </label>
            </div>
            {formError && <div className="form-error" role="alert">{formError}</div>}
            <button className="btn btn-primary" type="submit" disabled={busy}>{busy ? 'Saving…' : 'Create rule'}</button>
          </form>
        </Modal>
      )}
      <SimulatedDataNote />
    </div>
  )
}
