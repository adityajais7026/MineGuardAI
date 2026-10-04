import { useCallback, useEffect, useRef, useState } from 'react'
import { ApiError, getStoredToken } from '../api/client'
import { minesApi } from '../api/endpoints'
import type { Mine } from '../api/types'
import { useApiResource } from '../hooks/useApiResource'
import { useAuth } from '../context/AuthContext'
import { Badge, EmptyState, PageHeader, SeverityBadge } from '../components/ui'
import {
  buildPpeSummary, friendlyEvidence, PPE_RELIABILITY_NOTES, ppeLabel, ruleLabel,
  type LiveFrameResult,
} from '../utils/ppe'

const API_BASE = import.meta.env.VITE_API_BASE_URL ?? ''

const POLL_INTERVAL_MS = 1500 // ~0.7 fps — respects inference cost + rate safety

type Phase = 'idle' | 'starting' | 'live' | 'paused' | 'error'

interface LogEntry {
  at: string
  verdict: string
  tone: 'ok' | 'warn' | 'danger' | 'muted'
  text: string
}

/**
 * Draw YOLO boxes on a canvas overlay, scaled to the displayed video size.
 *
 * Coordinate chain (verified end-to-end):
 *   YOLO px (inference frame) -> backend API px (same frame, unchanged)
 *   -> client: multiply by (videoWidth/sentW, videoHeight/sentH) to return to
 *      the camera-source pixel space the <video> element renders
 *   -> object-fit: cover math (scale + centering offsets)
 *   -> canvas overlay px.
 * The client sends a downscaled frame (MAX_W=960), so the sent-frame dims are
 * captured per request; assuming boxes are already in source space would
 * shrink/shift every box when the camera exceeds 960px width.
 */
function drawBoxes(
  canvas: HTMLCanvasElement, video: HTMLVideoElement,
  result: LiveFrameResult | null, floor = 0,
  sent?: { w: number; h: number },
) {
  const ctx = canvas.getContext('2d')
  if (!ctx) return
  const w = video.clientWidth
  const h = video.clientHeight
  if (canvas.width !== w || canvas.height !== h) {
    canvas.width = w
    canvas.height = h
  }
  ctx.clearRect(0, 0, w, h)
  if (!result) return
  // Video is rendered with object-fit: cover; map frame pixels -> element box.
  const vw = video.videoWidth || w
  const vh = video.videoHeight || h
  const scale = Math.max(w / vw, h / vh)
  const dx = (w - vw * scale) / 2
  const dy = (h - vh * scale) / 2
  // Backend boxes are in the SENT frame's pixel space (possibly downscaled);
  // lift them back to source pixels before the cover math.
  const bx = sent && sent.w > 0 ? vw / sent.w : 1
  const by = sent && sent.h > 0 ? vh / sent.h : 1

  const colorFor = (cls: string): string => {
    const c = cls.toLowerCase()
    if (c.startsWith('no-') || c === 'fall-detected' || c === 'no_harness') return '#dc2626'
    if (c === 'person') return '#2563eb'
    return '#16a34a'
  }

  // Anchor strategy: tracked person boxes (magenta, ByteTrack IDs). PPE-only
  // detections stay in result.detections and never carry person boxes.
  for (const p of result.persons ?? []) {
    const [x1, y1, x2, y2] = [p.bbox[0] * bx, p.bbox[1] * by, p.bbox[2] * bx, p.bbox[3] * by]
    ctx.strokeStyle = '#c026d3'
    ctx.lineWidth = 3
    ctx.strokeRect(dx + x1 * scale, dy + y1 * scale, (x2 - x1) * scale, (y2 - y1) * scale)
    const label = `Person #${p.track_id ?? '?'} ${(p.confidence * 100).toFixed(0)}%`
    ctx.font = 'bold 12px system-ui, sans-serif'
    const tw = ctx.measureText(label).width + 6
    const ly = Math.max(dy + y1 * scale - 16, 2)
    ctx.fillStyle = '#c026d3'
    ctx.fillRect(dx + x1 * scale, ly, tw, 15)
    ctx.fillStyle = '#fff'
    ctx.fillText(label, dx + x1 * scale + 3, ly + 12)
  }
  for (const d of result.detections) {
    if (d.confidence < floor) continue // display floor highlights strong evidence only
    const [x1, y1, x2, y2] = [d.bbox[0] * bx, d.bbox[1] * by, d.bbox[2] * bx, d.bbox[3] * by]
    ctx.strokeStyle = colorFor(d.class)
    ctx.lineWidth = 2
    ctx.strokeRect(dx + x1 * scale, dy + y1 * scale, (x2 - x1) * scale, (y2 - y1) * scale)
    const label = `${ppeLabel(d.class)} ${(d.confidence * 100).toFixed(0)}%`
    ctx.font = '11px system-ui, sans-serif'
    const tw = ctx.measureText(label).width + 6
    const ly = Math.max(dy + y1 * scale - 14, 2)
    ctx.fillStyle = colorFor(d.class)
    ctx.fillRect(dx + x1 * scale, ly, tw, 14)
    ctx.fillStyle = '#fff'
    ctx.fillText(label, dx + x1 * scale + 3, ly + 11)
  }
}

/** PPE rule families the model reports; person/vehicle/zone context classes excluded. */
const PPE_RULES = new Set([
  'no_hardhat', 'hardhat_detected', 'no_safety_vest', 'safety_vest_detected',
  'no_gloves', 'gloves_detected', 'no_goggles', 'goggles_detected',
  'no_mask', 'mask_detected', 'no_harness', 'fall_detected',
])

/** Verdict for a live frame: zero detections / person-only ≠ confirmed compliance. */
function liveSummary(result: LiveFrameResult) {
  return buildPpeSummary(
    result.safety_findings,
    result.alerts.length,
    result.detection_count > 0 && result.safety_findings.some((f) => PPE_RULES.has(f.rule)),
  )
}

const ANCHOR_STATUS: Record<string, { icon: string; text: string }> = {
  PROTECTED: { icon: '✓', text: 'helmet + vest evidenced' },
  PARTIAL: { icon: '◐', text: 'partial PPE evidence — not a compliance claim' },
  VIOLATION: { icon: '❌', text: 'PPE violation' },
  UNDETERMINED: { icon: '❔', text: 'insufficient PPE evidence' },
}

/** Track-id badge text: "Person #12" when tracked, honest fallback when not. */
function personName(trackId: number | null | undefined): string {
  return trackId != null ? `Person #${trackId}` : 'Person (untracked)'
}

export default function LiveDetectionPage() {
  const { user } = useAuth()
  // Every role except none may open the page — the BACKEND enforces per-mine
  // scope (admin: all, mine_manager: managed mines, officers: permitted mines).
  // The backend 403 remains the real gate; this is UI convenience only.
  const canRunDetection = !!user

  const mines = useApiResource(() => minesApi.list({ limit: 200 }).then((r) => r.items), [])
  // Backend-enforced scope, mirrored for the dropdown: admin sees every mine,
  // mine_manager only mines they manage, officers only their permitted mines
  // (empty = none). A hand-crafted request is still rejected server-side.
  const scopedMines = (mines.data ?? []).filter((m: Mine) => {
    if (!user) return false
    if (user.role === 'admin') return true
    if (user.role === 'mine_manager') return m.manager_id === user.id
    return (user.permitted_mine_ids ?? []).includes(m.id)
  })
  const videoRef = useRef<HTMLVideoElement>(null)
  const canvasRef = useRef<HTMLCanvasElement>(null)
  const streamRef = useRef<MediaStream | null>(null)
  const timerRef = useRef<number | null>(null)
  const inFlightRef = useRef(false)
  const lastResultRef = useRef<LiveFrameResult | null>(null)
  // Pixel size of the frame actually sent to the backend (boxes are in THIS space).
  const sentFrameRef = useRef<{ w: number; h: number } | null>(null)
  const displayFloorRef = useRef(0.4) // mirror of displayFloor for stable callbacks
  // Single-loop gate: true only while a camera session should be polling.
  // Guards against the forked-poll-chain bug where a second Start (or a late-
  // resolving second getUserMedia) spawned a second self-rescheduling loop that
  // Stop/Reset could not kill (they only cleared the latest timer).
  const runningRef = useRef(false)

  const [phase, setPhase] = useState<Phase>('idle')
  const [errorMsg, setErrorMsg] = useState<string | null>(null)
  const [mineId, setMineId] = useState('')
  const [zoneId, setZoneId] = useState('')
  // UI display floor only — NOT sent to the backend. Inference always runs at the
  // backend's low capture threshold (0.10) so the two-stage PPE policy (gate at
  // 0.35) can evaluate sub-0.40 candidates instead of them being dropped upfront.
  const [displayFloor, setDisplayFloor] = useState(0.4)
  const [lastResult, setLastResult] = useState<LiveFrameResult | null>(null)
  const [sessionStats, setSessionStats] = useState({ frames: 0, alerts: 0, violations: 0 })
  const [log, setLog] = useState<LogEntry[]>([])
  const zones = useApiResource(
    () => (mineId
      ? import('../api/endpoints').then(({ zonesApi }) => zonesApi.list({ mine_id: mineId, limit: 100 }).then((r) => r.items))
      : Promise.resolve([])),
    [mineId],
  )

  useEffect(() => {
    // Redraw boxes whenever a new result arrives (also handles resizes).
    const onResize = () => {
      if (videoRef.current) drawBoxes(canvasRef.current!, videoRef.current, lastResultRef.current, displayFloorRef.current, sentFrameRef.current ?? undefined)
    }
    window.addEventListener('resize', onResize)
    return () => {
      window.removeEventListener('resize', onResize)
      stopCamera()
      if (timerRef.current) window.clearTimeout(timerRef.current)
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  const stopCamera = useCallback(() => {
    runningRef.current = false // kills any pending/self-rescheduling loop
    if (timerRef.current) { window.clearTimeout(timerRef.current); timerRef.current = null }
    streamRef.current?.getTracks().forEach((t) => t.stop())
    streamRef.current = null
    if (videoRef.current) videoRef.current.srcObject = null // release the device handle
    const canvas = canvasRef.current
    if (canvas) canvas.getContext('2d')?.clearRect(0, 0, canvas.width, canvas.height)
    setPhase('idle')
  }, [])

  const pushLog = useCallback((entry: Omit<LogEntry, 'at'>) => {
    setLog((l) => [{ ...entry, at: new Date().toLocaleTimeString() }, ...l].slice(0, 40))
  }, [])

  const captureAndSend = useCallback(async () => {
    if (!runningRef.current) return // stale chain (stopped/reset) — never run or reschedule
    const video = videoRef.current
    if (!video || !mineId || inFlightRef.current) return
    if (video.readyState < 2 || video.videoWidth === 0) { scheduleNext(); return }
    inFlightRef.current = true
    try {
      const canvas = document.createElement('canvas')
      const MAX_W = 960
      const scale = Math.min(1, MAX_W / video.videoWidth)
      canvas.width = Math.round(video.videoWidth * scale)
      canvas.height = Math.round(video.videoHeight * scale)
      sentFrameRef.current = { w: canvas.width, h: canvas.height } // for box mapping
      canvas.getContext('2d')!.drawImage(video, 0, 0, canvas.width, canvas.height)
      const dataUrl = canvas.toDataURL('image/jpeg', 0.8)
      // NOTE: no `confidence` here — the backend applies its own capture threshold.
      const payload: Record<string, unknown> = { mine_id: mineId, image_base64: dataUrl }
      if (zoneId) payload.zone_id = zoneId
      const res = await fetch(`${API_BASE}/api/ai/detect/frame`, {
        method: 'POST',
        headers: { Authorization: `Bearer ${getStoredToken()}`, 'Content-Type': 'application/json' },
        body: JSON.stringify(payload),
      })
      const data = await res.json()
      if (!res.ok) throw new ApiError(res.status, data?.detail ?? `Live detection failed (${res.status})`)
      const result = data as LiveFrameResult
      lastResultRef.current = result
      setLastResult(result)
      setSessionStats((s) => ({
        frames: s.frames + 1,
        alerts: s.alerts + result.alerts.length,
        violations: s.violations + result.events.filter((e) => e.recorded && e.ppe_status === 'violation').length,
      }))
      const summary = liveSummary(result)
      const cooldownNote = result.events.some((e) => e.reason === 'cooldown') ? ' (cooldown)' : ''
      pushLog({
        verdict: summary.title.replace(/^\S+\s/, ''),
        tone: summary.title.startsWith('🔴') ? 'danger'
          : summary.title.startsWith('🟠') ? 'warn'
          : summary.title.startsWith('🟡') ? 'muted'
          : 'ok',
        text: `${result.detection_count} det · ${result.events.length} finding(s)${cooldownNote}`
          + (result.persons?.length ? ` · ${result.persons.length} person(s)` : '')
          + (result.alerts.length ? ` · ⚠ ${result.alerts.length} alert(s)` : ''),
      })
      drawBoxes(canvasRef.current!, video, result, displayFloorRef.current, sentFrameRef.current ?? undefined)
    } catch (err) {
      const message = err instanceof ApiError ? err.message : 'Live detection failed — is the backend running?'
      setErrorMsg(message)
      pushLog({ verdict: 'ERROR', tone: 'muted', text: message })
      // Stop the loop on hard failures (401/403/503) but stay live on transient ones.
      if (err instanceof ApiError && (err.status === 401 || err.status === 403 || err.status === 503)) {
        stopCamera()
        return
      }
    } finally {
      inFlightRef.current = false
    }
    if (runningRef.current) scheduleNext() // reschedule only while the session is live
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [mineId, zoneId, pushLog, stopCamera])

  const scheduleNext = useCallback(() => {
    if (timerRef.current) window.clearTimeout(timerRef.current)
    timerRef.current = window.setTimeout(() => { void captureAndSend() }, POLL_INTERVAL_MS)
  }, [captureAndSend])

  async function startCamera() {
    if (!mineId) { setErrorMsg('Select a mine first.'); return }
    if (runningRef.current) return // already starting/live — a second Start must not fork a second loop
    setErrorMsg(null)
    setPhase('starting')
    runningRef.current = true // claim before the await so double-clicks cannot race
    try {
      const stream = await navigator.mediaDevices.getUserMedia({
        video: { width: { ideal: 1280 }, height: { ideal: 720 }, facingMode: 'environment' },
        audio: false,
      })
      if (!runningRef.current) { // stopped/reset while permission dialog was open
        stream.getTracks().forEach((t) => t.stop())
        return
      }
      streamRef.current = stream
      if (videoRef.current) {
        videoRef.current.srcObject = stream
        await videoRef.current.play()
      }
      setPhase('live')
      void captureAndSend()
    } catch (err) {
      runningRef.current = false
      setPhase('error')
      setErrorMsg(
        err instanceof Error && err.name === 'NotAllowedError'
          ? 'Camera permission was denied. Allow camera access and try again.'
          : 'No camera available on this device (or the page is not served over http://localhost / HTTPS).',
      )
    }
  }

  function pauseCamera() {
    if (timerRef.current) { window.clearTimeout(timerRef.current); timerRef.current = null }
    setPhase('paused')
  }

  function resumeCamera() {
    setPhase('live')
    void captureAndSend()
  }

  function resetSession() {
    stopCamera() // also flips runningRef off, killing any loop
    lastResultRef.current = null
    sentFrameRef.current = null
    setLastResult(null)
    setSessionStats({ frames: 0, alerts: 0, violations: 0 })
    setLog([])
    setErrorMsg(null)
  }

  if (!canRunDetection) {
    return (
      <div className="page">
        <div className="card error-card">
          <h2>403 — Forbidden</h2>
          <p>Live detection requires an account. Please sign in again.</p>
        </div>
      </div>
    )
  }

  const summary = lastResult ? liveSummary(lastResult) : null
  const worst = lastResult?.safety_findings.find((f) => f.status === 'violation')
    ?? lastResult?.safety_findings.find((f) => f.status === 'undetermined')
    ?? lastResult?.safety_findings[0]

  return (
    <div className="page">
      <PageHeader
        title="Live Webcam Detection"
        subtitle="Real-time YOLO PPE detection from your webcam — same model, policy and alert pipeline as uploads"
        actions={phase === 'live' || phase === 'paused' || phase === 'starting' ? (
          <button className="btn btn-danger" onClick={stopCamera}>■ Stop camera</button>
        ) : undefined}
      />

      <div className="live-grid">
        {/* ------------------------- left: video ------------------------- */}
        <div className="card live-video-card">
          <div className="live-video-wrap">
            <video ref={videoRef} className="live-video" playsInline muted />
            <canvas ref={canvasRef} className="live-overlay" />
            {phase !== 'live' && phase !== 'paused' && (
              <div className="live-placeholder">
                {phase === 'starting' ? 'Starting camera…' : 'Camera stopped'}
              </div>
            )}
            {phase === 'live' && lastResult && (
              <div className="live-verdict-chip">{summary?.title ?? 'Analysing…'}</div>
            )}
          </div>

          <div className="live-controls">
            {phase === 'idle' || phase === 'error' ? (
              <button className="btn btn-primary" onClick={startCamera} disabled={!mineId || mines.loading}>
                ● Start live detection
              </button>
            ) : phase === 'paused' ? (
              <button className="btn btn-primary" onClick={resumeCamera}>● Resume</button>
            ) : (
              <button className="btn" onClick={pauseCamera} disabled={phase !== 'live'}>⏸ Pause</button>
            )}
            <button className="btn" onClick={resetSession} disabled={phase === 'idle'}>Reset session</button>
            <span className={`live-status-dot ${phase === 'live' ? 'dot-live' : 'dot-off'}`}>
              {phase === 'live' ? 'LIVE' : phase === 'paused' ? 'PAUSED' : 'OFF'}
            </span>
          </div>

          {errorMsg && <div className="form-error" role="alert">{errorMsg}</div>}
        </div>

        {/* ------------------------ right: controls ---------------------- */}
        <div className="card live-controls-card">
          <label>Mine
            <select value={mineId} onChange={(e) => { setMineId(e.target.value); setZoneId('') }} disabled={phase === 'live' || phase === 'paused'}>
              <option value="">— select mine —</option>
              {scopedMines.map((m: Mine) => <option key={m.id} value={m.id}>{m.name}</option>)}
            </select>
          </label>

          <label>Restricted zone (optional — enables zone safety rules)
            <select value={zoneId} onChange={(e) => setZoneId(e.target.value)} disabled={!mineId || phase === 'live' || phase === 'paused'}>
              <option value="">none</option>
              {(zones.data ?? []).map((z) => <option key={z.id} value={z.id}>{z.name}</option>)}
            </select>
          </label>

          <label>Display floor (UI only): {displayFloor.toFixed(2)}
            <input type="range" min="0.05" max="0.95" step="0.05" value={displayFloor}
              onChange={(e) => { const v = Number(e.target.value); setDisplayFloor(v); displayFloorRef.current = v }} />
          </label>
          <p className="muted small">Inference always runs at the backend capture threshold; this slider only filters what is highlighted on screen.</p>

          <div className="live-stats">
            <div><strong>{sessionStats.frames}</strong><span>frames analysed</span></div>
            <div><strong>{sessionStats.violations}</strong><span>violations recorded</span></div>
            <div><strong>{sessionStats.alerts}</strong><span>alerts raised</span></div>
          </div>
          <p className="muted small">
            Frames are analysed every {POLL_INTERVAL_MS / 1000}s. Events persist once per
            cooldown window; every frame is still fully evaluated. Alerts follow the same
            60-minute dedupe as uploads.
          </p>
        </div>
      </div>

      {/* --------------------------- verdict --------------------------- */}
      {summary && (
        <div className="card ppe-summary">
          <h3>{summary.title}</h3>
          {summary.lines.map((l) => <p key={l}>{l}</p>)}
          {lastResult && (
            <p>
              Model: <Badge text={lastResult.model} tone="muted" /> · Camera: <code>{lastResult.camera_id}</code>
              {worst && (
                <>
                  {' '}· Confidence: {worst.confidence != null ? `${Math.round((worst.confidence ?? 0) * 100)}%` : '—'}
                  {' '}· Status:{' '}
                  {worst.status === 'violation' && <Badge text="VIOLATION" tone="danger" />}
                  {worst.status === 'undetermined' && <Badge text="UNDETERMINED" tone="warn" />}
                  {worst.status === 'compliance' && <Badge text="DETECTED" tone="ok" />}
                  {lastResult.alerts.length > 0 && <> · Alert: <SeverityBadge value={lastResult.alerts[0].severity} /></>}
                </>
              )}
            </p>
          )}
          {lastResult?.timings && (
            <p className="muted small">
              Latency — anchor {Math.round(lastResult.timings.anchor_ms)} ms · PPE {Math.round(lastResult.timings.ppe_ms)} ms{lastResult.timings.crop_ms ? ` · crop ${Math.round(lastResult.timings.crop_ms)} ms` : ''} · policy {Math.round(lastResult.timings.policy_ms)} ms · response {Math.round(lastResult.timings.total_response_ms)} ms
            </p>
          )}
        </div>
      )}

      {/* ---------------- per-person verdicts (anchor strategy) --------- */}
      {lastResult?.strategy === 'person_anchor' && (lastResult.persons?.length ?? 0) > 0 && (
        <div className="card">
          <h4>Per-person verdicts (tracked)</h4>
          <div className="person-grid">
            {(lastResult.persons ?? []).map((p) => {
              const row = (lastResult.person_ppe_report ?? []).find((r) => r.track_id === p.track_id)
              const st = ANCHOR_STATUS[row?.ppe_status ?? 'UNDETERMINED']
              return (
                <div key={p.track_id ?? `u-${p.bbox.join('-')}`} className="person-card">
                  <div className="person-card-head">
                    <strong>{personName(p.track_id)}</strong>
                    <Badge
                      text={`${st.icon} ${st.text}`}
                      tone={row?.ppe_status === 'VIOLATION' ? 'danger' : row?.ppe_status === 'PROTECTED' ? 'ok' : 'warn'}
                    />
                    {row?.ppe_status === 'PARTIAL' && (
                      <p className="muted small">evidence for only one priority class — not compliance.</p>
                    )}
                  </div>
                  {row?.ppe?.length
                    ? row.ppe.map((e, i) => (
                      <div key={i} className="person-ppe-row">
                        <span>{e.decision === 'violation' ? '❌' : e.decision === 'compliance' ? '✓' : '❔'}</span>
                        <span>{ppeLabel(e.class)}</span>
                        <span className="muted">{Math.round(e.confidence * 100)}%</span>
                      </div>
                    ))
                    : <p className="muted small">no PPE evidence — this is not a compliance confirmation.</p>}
                </div>
              )
            })}
          </div>
        </div>
      )}

      {/* ---------------- capability honesty notes (anchor) ------------- */}
      {lastResult?.strategy === 'person_anchor' && (
        <div className="card">
          <h4>PPE capability notes</h4>
          <ul className="muted small">
            {Object.entries(PPE_RELIABILITY_NOTES).map(([k, v]) => (
              <li key={k}><strong>{k}:</strong> {v}.</li>
            ))}
            <li>Person tracking uses COCO YOLO11n + ByteTrack; PPE classification stays on the production Vyra model. YOLO11n is never used for PPE classification.</li>
          </ul>
        </div>
      )}

      {/* ---------------------- session activity log -------------------- */}
      <div className="card">
        <h4>Session activity</h4>
        {log.length === 0 ? <EmptyState message="No frames analysed yet — start the camera." /> : (
          <table className="table">
            <thead><tr><th>Time</th><th>Verdict</th><th>Detail</th></tr></thead>
            <tbody>
              {log.map((e, i) => (
                <tr key={i}>
                  <td><small>{e.at}</small></td>
                  <td><Badge text={e.verdict} tone={e.tone} /></td>
                  <td><small>{e.text}</small></td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>

      {/* --------------------- last frame technical view ---------------- */}
      {lastResult && lastResult.detection_count > 0 && (
        <div className="card">
          <h4>Last frame — detections</h4>
          <table className="table">
            <thead><tr><th>Class</th><th>Confidence</th><th>BBox (x1,y1,x2,y2)</th></tr></thead>
            <tbody>
              {lastResult.detections.slice(0, 15).map((d, i) => (
                <tr key={i}>
                  <td>{ppeLabel(d.class)}</td>
                  <td>{(d.confidence * 100).toFixed(1)}%</td>
                  <td><small>({d.bbox.map((v) => Math.round(v)).join(', ')})</small></td>
                </tr>
              ))}
            </tbody>
          </table>
          {lastResult.detections.length > 15 && (
            <p className="muted">…and {lastResult.detections.length - 15} more detections.</p>
          )}
        </div>
      )}

      {lastResult && lastResult.safety_findings.length > 0 && (
        <div className="card">
          <h4>Last frame — safety rule evaluation</h4>
          <table className="table">
            <thead><tr><th>Rule</th><th>Conf.</th><th>Status</th><th>Person</th><th>Alert</th><th>Evidence</th></tr></thead>
            <tbody>
              {lastResult.safety_findings.map((f, i) => (
                <tr key={i}>
                  <td>{ruleLabel(f.rule)}</td>
                  <td>{f.confidence != null ? `${Math.round(f.confidence * 100)}%` : '—'}</td>
                  <td>
                    {f.status === 'violation' && <Badge text="VIOLATION" tone="danger" />}
                    {f.status === 'undetermined' && <Badge text="UNDETERMINED" tone="warn" />}
                    {f.status === 'compliance' && <Badge text="DETECTED" tone="ok" />}
                    {!f.status && <span className="muted">—</span>}
                  </td>
                  <td>
                    {f.track_id != null
                      ? <Badge text={`#${f.track_id}`} tone="muted" />
                      : <span className="muted">—</span>}
                  </td>
                  <td>
                    {f.status === 'violation'
                      ? <SeverityBadge value={f.severity} />
                      : lastResult.events.find(
                          (e) => e.rule === f.rule && (e.track_id ?? null) === (f.track_id ?? null),
                        )?.reason === 'cooldown'
                        ? <Badge text="cooldown" tone="muted" />
                        : <span className="muted">none</span>}
                  </td>
                  <td><small>{friendlyEvidence(f.evidence)}</small></td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  )
}
