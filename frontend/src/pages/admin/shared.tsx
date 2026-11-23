import type { ReactNode } from 'react'
import { Badge, type Tone } from '../../components/ui'

/** Map a backend health status string onto the one semantic status system. */
const TONE: Record<string, Tone> = {
  OPERATIONAL: 'ok',
  CONNECTED: 'ok',
  AVAILABLE: 'ok',
  CONFIGURED: 'ok',
  DEGRADED: 'warn',
  UNAVAILABLE: 'danger',
  FAILED: 'danger',
  UNKNOWN: 'muted',
  'NOT CONFIGURED': 'muted',
}

export function healthTone(status: string): Tone {
  return TONE[status.toUpperCase()] ?? 'muted'
}

export function HealthBadge({ status }: { status: string }) {
  return <Badge text={status} tone={healthTone(status)} dot />
}

/** A compact label/value row used inside administration cards. */
export function InfoRow({ label, children }: { label: string; children: ReactNode }) {
  return (
    <div className="info-row">
      <span className="info-row-label">{label}</span>
      <span className="info-row-value">{children}</span>
    </div>
  )
}

/** Trigger a client-side CSV download of real data (no server round-trip). */
export function downloadCsv(filename: string, rows: Record<string, unknown>[]) {
  if (rows.length === 0) return
  const headers = Object.keys(rows[0])
  const escape = (value: unknown) => {
    const text = value === null || value === undefined ? '' : String(value)
    return /[",\n]/.test(text) ? `"${text.replace(/"/g, '""')}"` : text
  }
  const csv = [
    headers.join(','),
    ...rows.map((row) => headers.map((h) => escape(row[h])).join(',')),
  ].join('\n')
  const blob = new Blob([csv], { type: 'text/csv;charset=utf-8;' })
  const url = URL.createObjectURL(blob)
  const link = document.createElement('a')
  link.href = url
  link.download = filename
  document.body.appendChild(link)
  link.click()
  document.body.removeChild(link)
  URL.revokeObjectURL(url)
}
