import { useState } from 'react'
import { Link } from 'react-router-dom'
import { riskApi } from '../api/endpoints'
import { useApiResource } from '../hooks/useApiResource'
import { ErrorState, PageHeader, RiskLevelBadge, Skeleton, SimulatedDataNote } from '../components/ui'

export default function RiskPage() {
  const { data, loading, error, refetch } = useApiResource(() => riskApi.allMines(), [])
  const [expanded, setExpanded] = useState<string | null>(null)

  if (loading) return <div className="page"><PageHeader title="Risk Overview" /><Skeleton lines={3} /></div>
  if (error) return <div className="page"><ErrorState message={error} onRetry={refetch} /></div>
  if (!data) return null

  return (
    <div className="page">
      <PageHeader
        title="Risk Overview"
        subtitle="Transparent rule-based scoring from system data — not machine learning, not a validated safety model."
      />
      <div className="risk-list">
        {data.map((r) => (
          <div key={r.mine_id} className="card risk-card">
            <div className="risk-head">
              <div>
                <h3 style={{ textTransform: 'none', letterSpacing: 0, color: 'var(--text)', fontSize: '.95rem' }}>
                  <Link to={`/mines/${r.mine_id}`}>{r.mine_name}</Link>
                </h3>
                <RiskLevelBadge level={r.level} />
              </div>
              <div className="risk-score">
                <div className="risk-score-number">{r.score}<small>/100</small></div>
                <div className={`risk-bar level-${r.level.toLowerCase()}`}>
                  <div style={{ width: `${r.score}%` }} />
                </div>
              </div>
            </div>
            <button className="btn btn-sm" onClick={() => setExpanded(expanded === r.mine_id ? null : r.mine_id)}>
              {expanded === r.mine_id ? 'Hide' : 'Show'} contributing factors
            </button>
            {expanded === r.mine_id && (
              <table className="table">
                <thead><tr><th>Factor</th><th>Points</th><th>Detail</th></tr></thead>
                <tbody>
                  {r.factors.map((f) => (
                    <tr key={f.factor}>
                      <td>{f.factor.replace(/_/g, ' ')}</td>
                      <td>{f.points} / {f.max_points}</td>
                      <td>{f.detail}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            )}
          </div>
        ))}
      </div>
      <SimulatedDataNote />
    </div>
  )
}
