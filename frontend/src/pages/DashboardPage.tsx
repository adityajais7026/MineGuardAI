import { useState } from 'react'
import {
  Bar, BarChart, CartesianGrid, Cell, Legend, Line, LineChart, Pie, PieChart,
  ResponsiveContainer, Tooltip, XAxis, YAxis,
} from 'recharts'
import { dashboardApi, minesApi } from '../api/endpoints'
import type { Mine } from '../api/types'
import { useApiResource } from '../hooks/useApiResource'
import { ErrorState, Loading, PageHeader, SeverityBadge, SimulatedDataNote, StatCard, StatusBadge } from '../components/ui'

const SEVERITY_COLORS: Record<string, string> = {
  critical: '#dc2626', high: '#ea580c', medium: '#d97706', low: '#2563eb',
}
const RISK_COLORS: Record<string, string> = {
  LOW: '#16a34a', MEDIUM: '#d97706', HIGH: '#ea580c', CRITICAL: '#dc2626',
}

export default function DashboardPage() {
  const [mineId, setMineId] = useState('')
  const [days, setDays] = useState(7)

  const mines = useApiResource(() => minesApi.list({ limit: 200 }).then((r) => r.items), [])
  const { data, loading, error, refetch } = useApiResource(
    () => dashboardApi.summary({ mine_id: mineId || undefined, days }),
    [mineId, days],
  )

  if (loading && !data) return <Loading />
  if (error) return <div className="page"><ErrorState message={error} onRetry={refetch} /></div>
  if (!data) return null

  const severityData = Object.entries(data.alerts_by_severity)
    .map(([name, value]) => ({ name, value }))
  const riskData = Object.entries(data.risk_distribution)
    .map(([name, value]) => ({ name, value })).filter((d) => d.value > 0)
  const incidentData = Object.entries(data.incidents_by_category)
    .map(([name, value]) => ({ name: name.replace(/_/g, ' '), value }))
  const trendParams = [...new Set(data.readings_trend.map((t) => t.parameter))]

  return (
    <div className="page">
      <PageHeader title="Dashboard" subtitle={`Live overview — generated ${new Date(data.generated_at).toLocaleString()}`} />

      <div className="filter-bar">
        <select value={mineId} onChange={(e) => setMineId(e.target.value)} aria-label="Filter by mine">
          <option value="">All mines</option>
          {(mines.data ?? []).map((m: Mine) => <option key={m.id} value={m.id}>{m.name}</option>)}
        </select>
        <select value={days} onChange={(e) => setDays(Number(e.target.value))} aria-label="Time range">
          <option value={1}>Last 24 hours</option>
          <option value={7}>Last 7 days</option>
          <option value={30}>Last 30 days</option>
        </select>
      </div>

      <div className="stat-grid">
        <StatCard label="Total mines" value={data.mines_total} hint={`${data.mines_operational} operational`} />
        <StatCard label="Active alerts" value={data.alerts_active} tone={data.alerts_active ? 'warn' : 'ok'}
          hint={`${data.alerts_critical} critical`} />
        <StatCard label="Open incidents" value={data.incidents_open} tone={data.incidents_open ? 'danger' : 'ok'} />
        <StatCard label="Pending inspections" value={data.inspections_pending} />
        <StatCard label="Overdue actions" value={data.actions_overdue} tone={data.actions_overdue ? 'danger' : 'ok'} />
        <StatCard label="Compliance (7d)" value={`${data.compliance_rate}%`}
          tone={data.compliance_rate >= 90 ? 'ok' : data.compliance_rate >= 70 ? 'warn' : 'danger'} />
      </div>

      <div className="chart-grid">
        <div className="card">
          <h3>Environmental readings (avg by day)</h3>
          {trendParams.length === 0 ? <p className="empty-state">No readings in range.</p> : (
            <ResponsiveContainer width="100%" height={260}>
              <LineChart data={data.readings_trend}>
                <CartesianGrid strokeDasharray="3 3" />
                <XAxis dataKey="date" tick={{ fontSize: 11 }} />
                <YAxis tick={{ fontSize: 11 }} />
                <Tooltip />
                <Legend />
                {trendParams.map((p) => (
                  <Line key={p} type="monotone" dataKey="avg_value" name={p} stroke="#1d4ed8"
                    data={data.readings_trend.filter((t) => t.parameter === p)} dot={false} />
                ))}
              </LineChart>
            </ResponsiveContainer>
          )}
        </div>

        <div className="card">
          <h3>Active alerts by severity</h3>
          {severityData.every((d) => d.value === 0)
            ? <p className="empty-state">No active alerts. 🎉</p>
            : (
              <ResponsiveContainer width="100%" height={260}>
                <BarChart data={severityData}>
                  <CartesianGrid strokeDasharray="3 3" />
                  <XAxis dataKey="name" tick={{ fontSize: 11 }} />
                  <YAxis allowDecimals={false} tick={{ fontSize: 11 }} />
                  <Tooltip />
                  <Bar dataKey="value">
                    {severityData.map((d) => <Cell key={d.name} fill={SEVERITY_COLORS[d.name] ?? '#64748b'} />)}
                  </Bar>
                </BarChart>
              </ResponsiveContainer>
            )}
        </div>

        <div className="card">
          <h3>Risk distribution</h3>
          {riskData.length === 0 ? <p className="empty-state">No mines yet.</p> : (
            <ResponsiveContainer width="100%" height={260}>
              <PieChart>
                <Pie data={riskData} dataKey="value" nameKey="name" cx="50%" cy="50%" innerRadius={55} outerRadius={90}>
                  {riskData.map((d) => <Cell key={d.name} fill={RISK_COLORS[d.name] ?? '#64748b'} />)}
                </Pie>
                <Tooltip />
                <Legend />
              </PieChart>
            </ResponsiveContainer>
          )}
        </div>

        <div className="card">
          <h3>Open incidents by category</h3>
          {incidentData.length === 0 ? <p className="empty-state">No open incidents.</p> : (
            <ResponsiveContainer width="100%" height={260}>
              <BarChart data={incidentData} layout="vertical">
                <CartesianGrid strokeDasharray="3 3" />
                <XAxis type="number" allowDecimals={false} tick={{ fontSize: 11 }} />
                <YAxis type="category" dataKey="name" width={110} tick={{ fontSize: 11 }} />
                <Tooltip />
                <Bar dataKey="value" fill="#0891b2" />
              </BarChart>
            </ResponsiveContainer>
          )}
        </div>
      </div>

      <div className="two-col">
        <div className="card">
          <h3>Highest-risk mines</h3>
          <table className="table">
            <thead><tr><th>Mine</th><th>Score</th><th>Level</th></tr></thead>
            <tbody>
              {data.highest_risk_mines.map((m) => (
                <tr key={m.mine_id}>
                  <td>{m.mine_name}</td>
                  <td>{m.score}/100</td>
                  <td><StatusBadge value={m.level} /></td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        <div className="card">
          <h3>Recent alerts</h3>
          <table className="table">
            <thead><tr><th>Title</th><th>Severity</th><th>Status</th><th>When</th></tr></thead>
            <tbody>
              {data.recent_alerts.map((a) => (
                <tr key={a.id}>
                  <td>{a.title}</td>
                  <td><SeverityBadge value={a.severity} /></td>
                  <td><StatusBadge value={a.status} /></td>
                  <td>{new Date(a.created_at).toLocaleString()}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>

      <SimulatedDataNote />
    </div>
  )
}
