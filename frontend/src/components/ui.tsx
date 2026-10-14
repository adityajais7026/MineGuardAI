/**
 * Shared UI primitives — one implementation reused by every page so the
 * interface stays consistent (badges, cards, table, modal, empty/error states,
 * toasts, tool-tips, workflow steps, skeletons).
 *
 * STATUS SEMANTICS (single source of truth — pages must not invent colors):
 *   ok GREEN compliant/safe/completed/normal/approved
 *   warn AMBER attention/warning/pending/due soon
 *   danger RED violation/critical/emergency/overdue/rejected
 *   muted GREY unknown/not assessed/unavailable/no data
 *   info BLUE information/active/in progress
 */
import { createContext, useContext, useEffect, useState, type ReactNode } from 'react'

export type Tone = 'ok' | 'warn' | 'danger' | 'info' | 'muted'

export function StatCard({ label, value, tone, hint, flash }: {
  label: string; value: ReactNode; tone?: 'default' | 'warn' | 'danger' | 'ok' | 'muted'; hint?: string; flash?: boolean
}) {
  return (
    <div className={`stat-card tone-${tone ?? 'default'}${flash ? ' stat-critical-flash' : ''}`}>
      <div className="stat-value">{value}</div>
      <div className="stat-label">{label}</div>
      {hint && <div className="stat-hint">{hint}</div>}
    </div>
  )
}

export function Badge({ text, tone, dot, large }: { text: string; tone?: Tone; dot?: boolean; large?: boolean }) {
  return (
    <span className={`badge badge-${tone ?? 'muted'}${dot ? ' badge-dot' : ''}${large ? ' badge-lg' : ''}`}>
      {text}
    </span>
  )
}

const SEVERITY_TONE: Record<string, Tone> = {
  low: 'info', medium: 'warn', high: 'danger', critical: 'danger',
}
const STATUS_TONE: Record<string, Tone> = {
  // green
  operational: 'ok', resolved: 'ok', closed: 'ok', completed: 'ok', cancelled: 'muted',
  compliant: 'ok', normal: 'ok', approved: 'ok', valid: 'ok', synced: 'ok', passed: 'ok',
  protected: 'ok', connected: 'ok', detected: 'ok',
  // amber
  acknowledged: 'warn', investigating: 'warn', in_progress: 'warn', partial: 'warn',
  maintenance: 'warn', expiring: 'warn', attention: 'warn', warning: 'warn', due_soon: 'warn',
  // red
  new: 'danger', overdue: 'danger', open: 'danger', action_required: 'danger',
  non_compliant: 'danger', violation: 'danger', suspended: 'danger', expired: 'danger',
  failed: 'danger', rejected: 'danger', emergency: 'danger', critical: 'danger',
  // blue
  pending: 'info', scheduled: 'info', under_review: 'info', submitted: 'info', draft: 'info',
  active: 'info', in_progress_review: 'info',
}

export function SeverityBadge({ value }: { value: string }) {
  return <Badge text={value.toUpperCase()} tone={SEVERITY_TONE[value] ?? 'muted'} dot />
}

export function StatusBadge({ value, dot }: { value: string; dot?: boolean }) {
  return <Badge text={value.replace(/_/g, ' ')} tone={STATUS_TONE[value] ?? 'muted'} dot={dot} />
}

/** Unified risk-level badge (LOW/MEDIUM/HIGH/CRITICAL) used everywhere. */
export function RiskLevelBadge({ level }: { level: string }) {
  const tone: Tone = level === 'LOW' ? 'ok' : level === 'MEDIUM' ? 'warn' : 'danger'
  return <Badge text={level} tone={tone} dot large />
}

export function PageHeader({ title, subtitle, actions }: { title: string; subtitle?: ReactNode; actions?: ReactNode }) {
  return (
    <div className="page-header">
      <div>
        <h1><span className="page-title-flag" aria-hidden="true" />{title}</h1>
        {subtitle && <p className="page-subtitle">{subtitle}</p>}
      </div>
      {actions && <div className="page-actions">{actions}</div>}
    </div>
  )
}

export function Loading({ label = 'Loading…' }: { label?: string }) {
  return <div className="page-loading" role="status" aria-live="polite">{label}</div>
}

/** Skeleton block set for card- or table-shaped placeholders. */
export function Skeleton({ lines = 4, height }: { lines?: number; height?: string }) {
  return (
    <div className="card skeleton-line" aria-hidden="true">
      {Array.from({ length: lines }).map((_, i) => (
        <div key={i} className="skeleton" style={{ width: `${100 - (i % 3) * 18}%`, height }} />
      ))}
    </div>
  )
}

export function ErrorState({ message, onRetry }: { message: string; onRetry?: () => void }) {
  return (
    <div className="card error-card" role="alert">
      <h3>Something went wrong</h3>
      <p>{message}</p>
      {onRetry && <button className="btn" onClick={onRetry}>Retry</button>}
    </div>
  )
}

export function EmptyState({ message, title }: { message: string; title?: string }) {
  return (
    <div className="empty-state">
      {title && <span className="empty-title">{title}</span>}
      {message}
    </div>
  )
}

export function UnavailableNote({ children }: { children: ReactNode }) {
  return <p className="unavailable-note">{children}</p>
}

export function Modal({ title, onClose, children }: { title: string; onClose: () => void; children: ReactNode }) {
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => { if (e.key === 'Escape') onClose() }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [onClose])
  return (
    <div className="modal-backdrop" onClick={onClose}>
      <div className="modal" role="dialog" aria-modal="true" aria-label={title} onClick={(e) => e.stopPropagation()}>
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

// ---------------------------------------------------------------------------
// Toasts (success/error feedback that never relies on color alone)
// ---------------------------------------------------------------------------

interface ToastMsg { id: number; text: string; tone: Tone }
const ToastCtx = createContext<(text: string, tone?: Tone) => void>(() => {})

export function ToastProvider({ children }: { children: ReactNode }) {
  const [items, setItems] = useState<ToastMsg[]>([])
  const push = (text: string, tone: Tone = 'info') => {
    const id = Date.now() + Math.random()
    setItems((s) => [...s, { id, text, tone }])
    setTimeout(() => setItems((s) => s.filter((t) => t.id !== id)), 4500)
  }
  return (
    <ToastCtx.Provider value={push}>
      {children}
      <div className="toast-region" aria-live="polite">
        {items.map((t) => (
          <div key={t.id} className={`toast toast-${t.tone}`}>
            <span aria-hidden="true">{t.tone === 'ok' ? '✓' : t.tone === 'danger' ? '✕' : t.tone === 'warn' ? '⚠' : 'ℹ'}</span>
            <span>{t.text}</span>
          </div>
        ))}
      </div>
    </ToastCtx.Provider>
  )
}

export function useToast() {
  return useContext(ToastCtx)
}

/** Inline tooltip (hover + keyboard focus reachable). */
export function Tooltip({ text, children }: { text: string; children: ReactNode }) {
  return (
    <span className="tt" tabIndex={0}>
      {children}
      <span className="tt-body" role="tooltip">{text}</span>
    </span>
  )
}

/** Visual workflow: DRAFT → IN_PROGRESS → SUBMITTED → ... — reached steps highlighted. */
const FLOW_ORDER = ['draft', 'in_progress', 'submitted', 'under_review', 'approved', 'closed']

export function FlowSteps({ current }: { current: string }) {
  const idx = FLOW_ORDER.indexOf(current)
  const render = (s: string) => {
    const i = FLOW_ORDER.indexOf(s)
    const reached = idx >= i
    const terminalOk = s === 'closed' && current === 'closed'
    return (
      <span key={s} style={{ display: 'inline-flex', alignItems: 'center', gap: '.25rem' }}>
        <span className={`flow-step${reached ? (terminalOk ? ' terminal-ok' : ' reached') : ''}`}>
          {s.replace(/_/g, ' ')}
        </span>
        {s !== 'closed' && <span className="flow-arrow" aria-hidden="true">→</span>}
      </span>
    )
  }
  return (
    <div className="flow-steps" aria-label="Inspection workflow">
      {FLOW_ORDER.map(render)}
      {current === 'rejected' && <Badge text="REJECTED" tone="danger" />}
    </div>
  )
}

/** Certificate status pill: VALID / EXPIRING SOON / EXPIRED / MISSING. */
export function CertStatus({ expiresOn, verificationStatus }: { expiresOn?: string | null; verificationStatus?: string | null }) {
  if (!verificationStatus || verificationStatus === 'missing') return <span className="cert-dot cert-missing">MISSING</span>
  if (verificationStatus === 'expired' || !expiresOn) {
    return <span className="cert-dot cert-expired">{expiresOn ? 'EXPIRED' : 'NO EXPIRY RECORDED'}</span>
  }
  const days = Math.round((new Date(expiresOn).getTime() - Date.now()) / 86400000)
  if (days < 0) return <span className="cert-dot cert-expired">EXPIRED</span>
  if (days <= 30) return <span className="cert-dot cert-expiring">EXPIRING IN {days}d</span>
  return <span className="cert-dot cert-valid">VALID</span>
}

export function SimulatedDataNote() {
  return <p className="simulated-note">⚠ Simulated demo data — not real sensor or government data.</p>
}
