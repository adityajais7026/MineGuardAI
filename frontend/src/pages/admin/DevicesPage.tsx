import { useMemo, useState } from 'react'
import { governanceApi, minesApi } from '../../api/endpoints'
import type { SensorDevice } from '../../api/endpoints'
import { ApiError } from '../../api/client'
import type { Mine } from '../../api/types'
import { useApiResource } from '../../hooks/useApiResource'
import {
  Badge, EmptyState, ErrorState, Loading, Modal, PageHeader, Tooltip, useToast,
} from '../../components/ui'

const ONLINE_WINDOW_MINUTES = 15

type DeviceForm = {
  mine_id: string
  device_code: string
  parameter: string
  unit: string
  source: 'real' | 'demo'
  location_text: string
  warning_threshold: string
  critical_threshold: string
}

const EMPTY_FORM: DeviceForm = {
  mine_id: '', device_code: '', parameter: '', unit: 'µg/m³', source: 'real',
  location_text: '', warning_threshold: '', critical_threshold: '',
}

/** Connectivity is derived from is_active + last_seen_at; never fabricated. */
function connectivity(device: SensorDevice): { label: string; tone: 'ok' | 'warn' | 'muted' | 'danger' } {
  if (!device.is_active) return { label: 'INACTIVE', tone: 'muted' }
  if (!device.last_seen_at) return { label: 'NEVER CONNECTED', tone: 'warn' }
  const ageMinutes = (Date.now() - new Date(device.last_seen_at).getTime()) / 60000
  return ageMinutes <= ONLINE_WINDOW_MINUTES
    ? { label: 'ONLINE', tone: 'ok' }
    : { label: 'OFFLINE', tone: 'danger' }
}

/** Platform sensor-device registry (infrastructure administration). */
export default function DevicesPage() {
  const toast = useToast()
  const devices = useApiResource(() => governanceApi.devices(), [])
  const mines = useApiResource(() => minesApi.list({ limit: 200 }), [])

  const [createOpen, setCreateOpen] = useState(false)
  const [editing, setEditing] = useState<SensorDevice | null>(null)
  const [form, setForm] = useState<DeviceForm>(EMPTY_FORM)
  const [formError, setFormError] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)

  const mineList = useMemo(() => mines.data?.items ?? [], [mines.data])
  const mineName = (id: string) => mineList.find((m: Mine) => m.id === id)?.name ?? `${id.slice(0, 12)}…`

  function openCreate() {
    setForm({ ...EMPTY_FORM, mine_id: mineList[0]?.id ?? '' })
    setFormError(null)
    setCreateOpen(true)
  }

  function openEdit(device: SensorDevice) {
    setForm({
      mine_id: device.mine_id,
      device_code: device.device_code,
      parameter: device.parameter,
      unit: device.unit,
      source: device.source,
      location_text: device.location_text ?? '',
      warning_threshold: device.warning_threshold === null ? '' : String(device.warning_threshold),
      critical_threshold: device.critical_threshold === null ? '' : String(device.critical_threshold),
    })
    setFormError(null)
    setEditing(device)
  }

  function body() {
    return {
      mine_id: form.mine_id,
      device_code: form.device_code.trim(),
      parameter: form.parameter.trim(),
      unit: form.unit.trim(),
      source: form.source,
      location_text: form.location_text.trim() || null,
      warning_threshold: form.warning_threshold === '' ? null : Number(form.warning_threshold),
      critical_threshold: form.critical_threshold === '' ? null : Number(form.critical_threshold),
    }
  }

  async function handleCreate(e: React.FormEvent) {
    e.preventDefault()
    setFormError(null)
    if (!form.mine_id || !form.device_code.trim() || !form.parameter.trim() || !form.unit.trim()) {
      setFormError('Mine, device code, parameter and unit are required.')
      return
    }
    setBusy(true)
    try {
      await governanceApi.createDevice(body())
      setCreateOpen(false)
      toast('Sensor device registered.', 'ok')
      devices.refetch()
    } catch (err) {
      setFormError(err instanceof ApiError ? err.message : 'Could not register the device.')
    } finally {
      setBusy(false)
    }
  }

  async function handleEdit(e: React.FormEvent) {
    e.preventDefault()
    if (!editing) return
    setFormError(null)
    setBusy(true)
    try {
      await governanceApi.updateDevice(editing.id, body())
      setEditing(null)
      toast('Device updated.', 'ok')
      devices.refetch()
    } catch (err) {
      setFormError(err instanceof ApiError ? err.message : 'Could not update the device.')
    } finally {
      setBusy(false)
    }
  }

  async function toggleActive(device: SensorDevice) {
    try {
      await governanceApi.updateDevice(device.id, { is_active: !device.is_active })
      toast(`${device.device_code} ${device.is_active ? 'deactivated' : 'activated'}.`, 'ok')
      devices.refetch()
    } catch (err) {
      toast(err instanceof ApiError ? err.message : 'Status change failed.', 'danger')
    }
  }

  if (devices.loading && !devices.data) return <Loading />
  if (devices.error) {
    return <div className="page"><PageHeader title="Sensor Devices" /><ErrorState message={devices.error} onRetry={devices.refetch} /></div>
  }

  const rows = devices.data ?? []
  const active = rows.filter((d) => d.is_active)
  const online = rows.filter((d) => connectivity(d).label === 'ONLINE')

  return (
    <div className="page">
      <PageHeader
        title="Sensor Devices"
        subtitle={`${rows.length} registered · ${active.length} active · ${online.length} online in the last ${ONLINE_WINDOW_MINUTES} min`}
        actions={<button className="btn btn-primary" onClick={openCreate} disabled={mineList.length === 0}>
          + Register device
        </button>}
      />

      {rows.length === 0 ? (
        <EmptyState
          title="No sensor devices"
          message={mineList.length === 0
            ? 'Register a mine before adding sensor devices.'
            : 'No sensor devices are registered. Devices appear here once registered and report connectivity via their last communication time.'}
        />
      ) : (
        <div className="card">
          <div className="table-wrap">
            <table className="table table-responsive">
              <thead>
                <tr>
                  <th>Device</th><th>Mine</th><th>Parameter</th><th>Source</th>
                  <th>Thresholds (warn / critical)</th><th>Connectivity</th><th>Last communication</th><th />
                </tr>
              </thead>
              <tbody>
                {rows.map((device) => {
                  const conn = connectivity(device)
                  return (
                    <tr key={device.id}>
                      <td data-label="Device">
                        <code>{device.device_code}</code><br />
                        <small className="muted">{device.location_text ?? 'no location'}</small>
                      </td>
                      <td data-label="Mine">{mineName(device.mine_id)}</td>
                      <td data-label="Parameter">{device.parameter} <span className="muted">({device.unit})</span></td>
                      <td data-label="Source">
                        {device.source === 'demo'
                          ? <Tooltip text="Simulated demonstration device — never a real measurement."><Badge text="DEMO" tone="warn" /></Tooltip>
                          : <Badge text="REAL" tone="ok" />}
                      </td>
                      <td className="num" data-label="Thresholds (warn / critical)">{device.warning_threshold ?? '—'} / {device.critical_threshold ?? '—'}</td>
                      <td data-label="Connectivity"><Badge text={conn.label} tone={conn.tone} dot /></td>
                      <td data-label="Last communication"><small>{device.last_seen_at ? new Date(device.last_seen_at).toLocaleString() : 'never'}</small></td>
                      <td className="table-actions">
                        <button className="btn btn-sm" onClick={() => openEdit(device)}>Edit</button>
                        <button className={`btn btn-sm${device.is_active ? ' btn-danger' : ' btn-success'}`}
                          onClick={() => toggleActive(device)}>
                          {device.is_active ? 'Deactivate' : 'Activate'}
                        </button>
                      </td>
                    </tr>
                  )
                })}
              </tbody>
            </table>
          </div>
          <p className="card-sub" style={{ marginTop: '.6rem' }}>
            Connectivity is derived from the device's active flag and its last communication
            timestamp. A device with no communication record shows NEVER CONNECTED.
          </p>
        </div>
      )}

      {(createOpen || editing) && (
        <Modal
          title={editing ? `Edit device — ${editing.device_code}` : 'Register sensor device'}
          onClose={() => { setCreateOpen(false); setEditing(null) }}
        >
          <form onSubmit={editing ? handleEdit : handleCreate} className="form-grid">
            <label>Mine
              <select value={form.mine_id} onChange={(e) => setForm({ ...form, mine_id: e.target.value })}>
                <option value="">— select mine —</option>
                {mineList.map((mine: Mine) => <option key={mine.id} value={mine.id}>{mine.name}</option>)}
              </select>
            </label>
            <label>Device code<input value={form.device_code} autoFocus
              onChange={(e) => setForm({ ...form, device_code: e.target.value })} /></label>
            <label>Parameter<input value={form.parameter} placeholder="e.g. pm2_5"
              onChange={(e) => setForm({ ...form, parameter: e.target.value })} /></label>
            <label>Unit<input value={form.unit}
              onChange={(e) => setForm({ ...form, unit: e.target.value })} /></label>
            <label>Source
              <select value={form.source}
                onChange={(e) => setForm({ ...form, source: e.target.value as 'real' | 'demo' })}>
                <option value="real">real device</option>
                <option value="demo">demo / simulated</option>
              </select>
            </label>
            <label>Location (optional)<input value={form.location_text}
              onChange={(e) => setForm({ ...form, location_text: e.target.value })} /></label>
            <label>Warning threshold<input type="number" step="any" value={form.warning_threshold}
              onChange={(e) => setForm({ ...form, warning_threshold: e.target.value })} /></label>
            <label>Critical threshold<input type="number" step="any" value={form.critical_threshold}
              onChange={(e) => setForm({ ...form, critical_threshold: e.target.value })} /></label>
            {formError && <div className="form-error" role="alert">{formError}</div>}
            <button className="btn btn-primary" type="submit" disabled={busy}>
              {busy ? 'Saving…' : editing ? 'Save changes' : 'Register device'}
            </button>
          </form>
        </Modal>
      )}
    </div>
  )
}
