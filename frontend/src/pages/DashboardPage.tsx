import { useState } from 'react'
import {
  Bar, BarChart, CartesianGrid, Cell, Legend, Line, LineChart, Pie, PieChart,
  ResponsiveContainer, Tooltip, XAxis, YAxis,
} from 'recharts'
import { Link } from 'react-router-dom'
import { actionsApi, dashboardApi, inspectionsApi } from '../api/endpoints'
import { useMineSelection } from '../context/MineSelectionContext'
import { useApiResource } from '../hooks/useApiResource'
import {
  Badge, EmptyState, ErrorState, PageHeader, SeverityBadge,
  SimulatedDataNote, Skeleton, StatCard, StatusBadge,
} from '../components/ui'

const SEVERITY_COLORS: Record<string, string> = {
  critical: '#a51d1d', high: '#c2410c', medium: '#b7791f', low: '#1c4fae',
}
const RISK_COLORS: Record<string, string> = {
  LOW: '#14713d', MEDIUM: '#b7791f', HIGH: '#c2410c', CRITICAL: '#a51d1d',
}

/** Failure-style chart tooltip (title-case labels, compact). */
const chartTooltipStyle = {
  contentStyle: { fontSize: 12, borderRadius: 6, border: '1px solid #d7dee8' },
  labelStyle: { fontSize: 12 },
} as const

export default function DashboardPage() {
  // Global mine selection (topbar selector) drives the dashboard scope; the
  // time range stays a local, page-level control.
  const { mineId } = useMineSelection()
  const [days, setDays] = useState(7)

  const { data, loading, error, refetch } = useApiResource(
    () => dashboardApi.summary({ mine_id: mineId || undefined, days }),
    [mineId, days],
  )
  // Lower panels — list APIs that already exist (no backend change).
  const upcoming = useApiResource(
    () => inspectionsApi.list({ limit: 6, sort: 'scheduled_at', order: 'asc' }),
    [],
  )
  const actions = useApiResource(
    () => actionsApi.list({ limit: 100 }),
    [],
  )

  if (loading && !data) return <div className="page"><PageHeader title="Dashboard" /><Skeleton lines={5} /></div>
  if (error) return <div className="page"><PageHeader title="Dashboard" /><ErrorState message={error} onRetry={refetch} /></div>
  if (!data) return null

  // ------------------------------------------------------------------
  // Overall safety posture — one honest headline derived from real data
  // ------------------------------------------------------------------
  const posture = (() => {
    if (data.alerts_critical > 0 || data.actions_overdue > 0) {
      return { text: 'ATTENTION REQUIRED', tone: 'danger' as const, detail: 'Critical alerts or overdue corrective actions present.' }
    }
    if (data.alerts_active > 0 || data.incidents_open > 0) {
      return { text: 'MONITORING', tone: 'warn' as const, detail: 'Active alerts or open incidents under watch.' }
    }
    return { text: 'NOMINAL', tone: 'ok' as const, detail: 'No critical alerts, open incidents or overdue actions in range.' }
  })()

  const severityData = Object.entries(data.alerts_by_severity).map(([name, value]) => ({ name, value }))
  const riskData = Object.entries(data.risk_distribution)
    .map(([name, value]) => ({ name, value })).filter((d) => d.value > 0)
  const incidentData = Object.entries(data.incidents_by_category)
    .map(([name, value]) => ({ name: name.replace(/_/g, ' '), value }))
  const trendParams = [...new Set(data.readings_trend.map((t) => t.parameter))]

  const upcomingRows = (upcoming.data?.items ?? [])
    .filter((i) => ['scheduled', 'in_progress', 'draft'].includes(i.status))
    .slice(0, 6)
  const openActions = (actions.data?.items ?? [])
    .filter((a) => !['completed', 'cancelled'].includes(a.status))
    .sort((a, b) => {
      const ov = (x: typeof a) => (x.status === 'overdue' ? 0 : 1)
      return ov(a) - ov(b) || new Date(a.due_date).getTime() - new Date(b.due_date).getTime()
    })
    .slice(0, 6)

  return (
    <div className="page">
      <PageHeader
        title="Dashboard"
        subtitle={<>Live operational overview — all mines{mineId ? ' · filtered' : ''} · generated {new Date(data.generated_at).toLocaleString()}</>}
        actions={
          <div className="filter-bar">
            <span className="muted" style={{ alignSelf: 'center' }}>
              Scope: {data.mines_total === 1 ? '1 mine' : `${data.mines_total} mines`}
            </span>
            <select value={days} onChange={(e) => setDays(Number(e.target.value))} aria-label="Time range">
              <option value={1}>Last 24 hours</option>
              <option value={7}>Last 7 days</option>
              <option value={30}>Last 30 days</option>
            </select>
          </div>
        }
      />

      {/* ---- 1. Overall status banner --------------------------------- */}
      <div className={`card ppe-summary verdict-${posture.tone === 'ok' ? 'ok' : posture.tone === 'warn' ? 'warn' : 'danger'}`}
        role="status">
        <div style={{ display: 'flex', alignItems: 'baseline', gap: '.7rem', flexWrap: 'wrap' }}>
          <Badge text={posture.text} tone={posture.tone} dot large />
          <span className="muted">{posture.detail}</span>
        </div>
      </div>

      {/* ---- 2. Key figures ------------------------------------------- */}
      <div className="stat-grid">
        <StatCard label="Active alerts" value={data.alerts_active}
          tone={data.alerts_active ? 'warn' : 'ok'} hint={`${data.alerts_critical} critical`} />
        <StatCard label="Open incidents" value={data.incidents_open}
          tone={data.incidents_open ? 'danger' : 'ok'} flash={data.incidents_open > 0} />
        <StatCard label="Overdue actions" value={data.actions_overdue}
          tone={data.actions_overdue ? 'danger' : 'ok'} flash={data.actions_overdue > 0} />
        <StatCard label="Compliance (7d)" value={`${data.compliance_rate}%`}
          tone={data.compliance_rate >= 90 ? 'ok' : data.compliance_rate >= 70 ? 'warn' : 'danger'} />
        <StatCard label="Pending inspections" value={data.inspections_pending} />
        <StatCard label="Mines" value={data.mines_total}
          tone="muted" hint={`${data.mines_operational} operational`} />
      </div>

      {/* ---- 3. Trends & distributions -------------------------------- */}
      <div className="chart-grid">
        <div className="card">
          <h3>Environmental readings — average by day</h3>
          {trendParams.length === 0
            ? <EmptyState title="No readings" message="No environmental readings recorded in the selected range." />
            : (
              <ResponsiveContainer width="100%" height={250}>
                <LineChart data={data.readings_trend}>
                  <CartesianGrid strokeDasharray="3 3" />
                  <XAxis dataKey="date" tick={{ fontSize: 11 }} />
                  <YAxis tick={{ fontSize: 11 }} />
                  <Tooltip {...chartTooltipStyle} />
                  <Legend />
                  {trendParams.map((p) => (
                    <Line key={p} type="monotone" dataKey="avg_value" name={p} stroke="#1c4fae"
                      data={data.readings_trend.filter((t) => t.parameter === p)} dot={false} />
                  ))}
                </LineChart>
              </ResponsiveContainer>
            )}
        </div>

        <div className="card">
          <h3>Active alerts by severity</h3>
          {severityData.every((d) => d.value === 0)
            ? <EmptyState title="No active alerts" message="No alerts are active in the selected range." />
            : (
              <ResponsiveContainer width="100%" height={250}>
                <BarChart data={severityData}>
                  <CartesianGrid strokeDasharray="3 3" />
                  <XAxis dataKey="name" tick={{ fontSize: 11 }} />
                  <YAxis allowDecimals={false} tick={{ fontSize: 11 }} />
                  <Tooltip {...chartTooltipStyle} />
                  <Bar dataKey="value">
                    {severityData.map((d) => <Cell key={d.name} fill={SEVERITY_COLORS[d.name] ?? '#5b6b7f'} />)}
                  </Bar>
                </BarChart>
              </ResponsiveContainer>
            )}
        </div>

        <div className="card">
          <h3>Risk distribution across mines</h3>
          {riskData.length === 0
            ? <EmptyState title="No risk scores" message="Risk scores appear once mines are assessed." />
            : (
              <ResponsiveContainer width="100%" height={250}>
                <PieChart>
                  <Pie data={riskData} dataKey="value" nameKey="name" cx="50%" cy="50%" innerRadius={58} outerRadius={92}>
                    {riskData.map((d) => <Cell key={d.name} fill={RISK_COLORS[d.name] ?? '#5b6b7f'} />)}
                  </Pie>
                  <Tooltip {...chartTooltipStyle} />
                  <Legend />
                </PieChart>
              </ResponsiveContainer>
            )}
        </div>

        <div className="card">
          <h3>Open incidents by category</h3>
          {incidentData.length === 0
            ? <EmptyState title="No open incidents" message="No open incidents in the selected range." />
            : (
              <ResponsiveContainer width="100%" height={250}>
                <BarChart data={incidentData} layout="vertical">
                  <CartesianGrid strokeDasharray="3 3" />
                  <XAxis type="number" allowDecimals={false} tick={{ fontSize: 11 }} />
                  <YAxis type="category" dataKey="name" width={110} tick={{ fontSize: 11 }} />
                  <Tooltip {...chartTooltipStyle} />
                  <Bar dataKey="value" fill="#1c4fae" />
                </BarChart>
              </ResponsiveContainer>
            )}
        </div>
      </div>

      {/* ---- 4. Priority attention lists ------------------------------ */}
      <div className="two-col">
        <div className="card">
          <h3>Highest-risk mines</h3>
          {(data.highest_risk_mines.length === 0)
            ? <EmptyState title="No assessments" message="No mines have been risk-assessed yet." />
            : (
              <table className="table">
                <thead><tr><th>Mine</th><th>Score</th><th>Level</th></tr></thead>
                <tbody>
                  {data.highest_risk_mines.map((m) => (
                    <tr key={m.mine_id}>
                      <td><Link className="table-link" to={`/mines/${m.mine_id}`}>{m.mine_name}</Link></td>
                      <td className="num">{m.score}/100</td>
                      <td><StatusBadge value={m.level.toLowerCase()} /></td>
                    </tr>
                  ))}
                </tbody>
              </table>
            )}
        </div>

        <div className="card">
          <h3>Upcoming / open inspections</h3>
          {upcoming.loading && !upcoming.data
            ? <Skeleton lines={3} />
            : upcomingRows.length === 0
              ? <EmptyState title="None scheduled" message="No scheduled or in-progress inspections." />
              : (
                <table className="table">
                  <thead><tr><th>Mine</th><th>Type</th><th>Status</th><th>Scheduled</th></tr></thead>
                  <tbody>
                    {upcomingRows.map((i) => (
                      <tr key={i.id}>
                        <td><small>{i.mine_id.slice(0, 12)}…</small></td>
                        <td>{i.inspection_type}</td>
                        <td><StatusBadge value={i.status} /></td>
                        <td><small>{new Date(i.scheduled_at).toLocaleDateString()}</small></td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              )}
        </div>
      </div>

      <div className="two-col">
        <div className="card">
          <h3>Corrective actions needing attention</h3>
          {actions.loading && !actions.data
            ? <Skeleton lines={3} />
            : openActions.length === 0
              ? <EmptyState title="All clear" message="No open corrective actions." />
              : (
                <table className="table">
                  <thead><tr><th>Action</th><th>Priority</th><th>Status</th><th>Due</th></tr></thead>
                  <tbody>
                    {openActions.map((a) => (
                      <tr key={a.id} className={a.status === 'overdue' ? 'row-overdue' : undefined}>
                        <td><small>{a.description.length > 70 ? `${a.description.slice(0, 70)}…` : a.description}</small></td>
                        <td><SeverityBadge value={a.priority} /></td>
                        <td><StatusBadge value={a.status} /></td>
                        <td><small>{new Date(a.due_date).toLocaleDateString()}</small></td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              )}
        </div>

        <div className="card">
          <h3>Recent alerts</h3>
          {data.recent_alerts.length === 0
            ? <EmptyState title="No alerts" message="No alerts in the selected range." />
            : (
              <table className="table">
                <thead><tr><th>Title</th><th>Severity</th><th>Status</th><th>When</th></tr></thead>
                <tbody>
                  {data.recent_alerts.slice(0, 7).map((a) => (
                    <tr key={a.id}>
                      <td><small>{a.title}</small></td>
                      <td><SeverityBadge value={a.severity} /></td>
                      <td><StatusBadge value={a.status} /></td>
                      <td><small>{new Date(a.created_at).toLocaleString()}</small></td>
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
