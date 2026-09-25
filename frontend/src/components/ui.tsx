/**
 * Shared UI primitives — one implementation reused by every page so the
 * interface stays consistent (badges, cards, table, modal, empty/error states).
 */
import type { ReactNode } from 'react'

export function StatCard({ label, value, tone, hint }: {
  label: string; value: ReactNode; tone?: 'default' | 'warn' | 'danger' | 'ok'; hint?: string
}) {
  return (
    <div className={`stat-card tone-${tone ?? 'default'}`}>
      <div className="stat-value">{value}</div>
      <div className="stat-label">{label}</div>
      {hint && <div className="stat-hint">{hint}</div>}
    </div>
  )
}

export function Badge({ text, tone }: { text: string; tone?: 'ok' | 'warn' | 'danger' | 'info' | 'muted' }) {
  return <span className={`badge badge-${tone ?? 'muted'}`}>{text}</span>
}

const SEVERITY_TONE: Record<string, 'ok' | 'warn' | 'danger' | 'info' | 'muted'> = {
  low: 'info', medium: 'warn', high: 'danger', critical: 'danger',
}
const STATUS_TONE: Record<string, 'ok' | 'warn' | 'danger' | 'info' | 'muted'> = {
  operational: 'ok', new: 'danger', acknowledged: 'warn', investigating: 'warn',
  resolved: 'ok', closed: 'muted', completed: 'ok', pending: 'info', scheduled: 'info',
  in_progress: 'warn', overdue: 'danger', open: 'danger', action_required: 'danger',
  compliant: 'ok', non_compliant: 'danger', partial: 'warn', cancelled: 'muted',
  normal: 'ok', violation: 'danger', maintenance: 'warn', suspended: 'danger',
}

export function SeverityBadge({ value }: { value: string }) {
  return <Badge text={value.toUpperCase()} tone={SEVERITY_TONE[value] ?? 'muted'} />
}

export function StatusBadge({ value }: { value: string }) {
  return <Badge text={value.replace(/_/g, ' ')} tone={STATUS_TONE[value] ?? 'muted'} />
}

export function PageHeader({ title, subtitle, actions }: { title: string; subtitle?: ReactNode; actions?: ReactNode }) {
  return (
    <div className="page-header">
      <div>
        <h1>{title}</h1>
        {subtitle && <p className="page-subtitle">{subtitle}</p>}
      </div>
      {actions && <div className="page-actions">{actions}</div>}
    </div>
  )
}

export function Loading() {
  return <div className="page-loading">Loading…</div>
}

export function ErrorState({ message, onRetry }: { message: string; onRetry?: () => void }) {
  return (
    <div className="card error-card">
      <h3>Something went wrong</h3>
      <p>{message}</p>
      {onRetry && <button className="btn" onClick={onRetry}>Retry</button>}
    </div>
  )
}

export function EmptyState({ message }: { message: string }) {
  return <div className="empty-state">{message}</div>
}

export function Modal({ title, onClose, children }: { title: string; onClose: () => void; children: ReactNode }) {
  return (
    <div className="modal-backdrop" onClick={onClose}>
      <div className="modal" role="dialog" aria-modal="true" onClick={(e) => e.stopPropagation()}>
        <div className="modal-header">
          <h3>{title}</h3>
          <button className="modal-close" onClick={onClose} aria-label="Close">×</button>
        </div>
        <div className="modal-body">{children}</div>
      </div>
    </div>
  )
}

export function ConfirmButton({ onConfirm, children, confirmLabel = 'Confirm delete' }: {
  onConfirm: () => void; children: ReactNode; confirmLabel?: string
}) {
  return (
    <button
      className="btn btn-danger btn-sm"
      onClick={(e) => {
        if (e.currentTarget.dataset.armed === 'yes') onConfirm()
        else {
          e.currentTarget.dataset.armed = 'yes'
          e.currentTarget.textContent = confirmLabel
          setTimeout(() => {
            const el = e.currentTarget
            if (el) { el.dataset.armed = 'no'; el.textContent = children as string }
          }, 2500)
        }
      }}
    >
      {children}
    </button>
  )
}

export function SimulatedDataNote() {
  return <p className="simulated-note">⚠ Simulated demo data — not real sensor or government data.</p>
}
