import { useRef, useState } from 'react'
import { ApiError, getStoredToken } from '../api/client'
import { minesApi } from '../api/endpoints'
import type { Mine } from '../api/types'
import { useApiResource } from '../hooks/useApiResource'
import {
  Badge, EmptyState, ErrorState, Loading, Modal, PageHeader, SeverityBadge, SimulatedDataNote, StatusBadge,
} from '../components/ui'

const API_BASE = import.meta.env.VITE_API_BASE_URL ?? ''

/** Shape of the JSON returned by POST /api/ai/detect/image|video. */
interface DetectResult {
  source: string
  detector: string
  model: string
  mine_id: string
  zone: { id: string; name: string } | null
  detections: {
    class: string; class_id: number; confidence: number; bbox: number[]
    frame_number?: number | null; timestamp_seconds?: number | null
  }[]
  detection_count: number
  classes_detected: string[]
  class_summary?: Record<string, number>
  safety_findings: { rule: string; event_type: string; severity: string; evidence: string }[]
  annotated_image_url?: string | null
  original_image_url?: string | null
  annotated_video_url?: string | null
  original_video_url?: string | null
  camera_event_ids: string[]
  events: { camera_event_id: string; event_type: string; class?: string; frame_number?: number; timestamp_seconds?: number; rule?: string }[]
  alerts: { id: string; title: string; severity: string; source: string }[]
  storage_provider: string
  video_metadata?: {
    filename: string; duration_seconds: number; fps: number; total_frames: number
    processed_frames: number; frame_stride: number; processing_seconds: number
  }
  uploaded_by: string
}

type Phase = 'idle' | 'uploading' | 'processing' | 'success' | 'error'

export default function CameraEventsPage() {
  const mines = useApiResource(() => minesApi.list({ limit: 200 }).then((r) => r.items), [])
  const [page, setPage] = useState(0)
  const [statusFilter, setStatusFilter] = useState('')
  const LIMIT = 20

  const [detectOpen, setDetectOpen] = useState(false)
  const [mediaKind, setMediaKind] = useState<'image' | 'video'>('image')
  const [file, setFile] = useState<File | null>(null)
  const [mineId, setMineId] = useState('')
  const [zoneId, setZoneId] = useState('')
  const [confidence, setConfidence] = useState(0.4)
  const [frameStride, setFrameStride] = useState(5)
  const [phase, setPhase] = useState<Phase>('idle')
  const [errorMsg, setErrorMsg] = useState<string | null>(null)
  const [result, setResult] = useState<DetectResult | null>(null)
  const [previewUrl, setPreviewUrl] = useState<string | null>(null)
  const fileInputRef = useRef<HTMLInputElement>(null)

  const zones = useApiResource(
    () => (mineId
      ? import('../api/endpoints').then(({ zonesApi }) => zonesApi.list({ mine_id: mineId, limit: 100 }).then((r) => r.items))
      : Promise.resolve([])),
    [mineId],
  )

  const [eventType, setEventType] = useState('')
  const events = useApiResource(
    () =>
      import('../api/endpoints').then(({ cameraEventsApi }) =>
        cameraEventsApi.list({
          event_type: eventType || undefined,
          status: statusFilter || undefined,
          skip: page * LIMIT,
          limit: LIMIT,
        }),
      ),
    [eventType, statusFilter, page],
  )

  async function runDetection() {
    if (!file || !mineId) {
      setErrorMsg('Select a mine and a file first.')
      return
    }
    setPhase('uploading')
    setErrorMsg(null)
    setResult(null)

    const form = new FormData()
    form.append('upload', file)
    const params = new URLSearchParams({
      mine_id: mineId,
      confidence: String(confidence),
    })
    if (zoneId) params.set('zone_id', zoneId)
    if (mediaKind === 'video') params.set('frame_stride', String(frameStride))

    setPhase('processing')
    try {
      const res = await fetch(
        `${API_BASE}/api/ai/detect/${mediaKind}?${params.toString()}`,
        {
          method: 'POST',
          headers: { Authorization: `Bearer ${getStoredToken()}` },
          body: form,
        },
      )
      const data = await res.json()
      if (!res.ok) {
        throw new ApiError(res.status, data?.detail ?? data?.error?.message ?? `Detection failed (${res.status})`)
      }
      setResult(data as DetectResult)
      setPhase('success')
      events.refetch()
    } catch (err) {
      setPhase('error')
      setErrorMsg(err instanceof ApiError ? err.message : 'Detection failed — is the backend running with AI_DETECTOR=yolo?')
    }
  }

  function resetPanel() {
    setDetectOpen(false)
    setFile(null)
    setResult(null)
    setPhase('idle')
    setErrorMsg(null)
    if (previewUrl) URL.revokeObjectURL(previewUrl)
    setPreviewUrl(null)
  }

  function pickFile(f: File | null) {
    setFile(f)
    setResult(null)
    setPhase('idle')
    if (previewUrl) URL.revokeObjectURL(previewUrl)
    setPreviewUrl(f ? URL.createObjectURL(f) : null)
  }

  function mediaUrl(path: string | null | undefined): string | null {
    if (!path) return null
    // Signed Supabase URLs pass through; local storage paths are served by the backend.
    return path.startsWith('http') ? path : `${API_BASE}/media/${path.replace(/^\/?media\//, '')}`
  }

  return (
    <div className="page">
      <PageHeader
        title="Camera Events & YOLO Detection"
        subtitle="Real YOLO object detection on uploaded media + clearly-labelled simulated events"
        actions={<button className="btn btn-primary" onClick={() => setDetectOpen(true)}>+ Run YOLO Detection</button>}
      />

      <div className="filter-bar">
        <select value={eventType} onChange={(e) => { setEventType(e.target.value); setPage(0) }} aria-label="Event type">
          <option value="">All event types</option>
          <option value="person_without_helmet">person without helmet (sim)</option>
          <option value="restricted_zone_entry">restricted zone entry</option>
          <option value="vehicle_in_restricted_area">vehicle in restricted area</option>
          <option value="unsafe_crowding">unsafe crowding</option>
          <option value="other">other (object detection)</option>
        </select>
        <select value={statusFilter} onChange={(e) => { setStatusFilter(e.target.value); setPage(0) }} aria-label="Status">
          <option value="">All statuses</option>
          <option value="new">new</option>
          <option value="investigating">investigating</option>
          <option value="resolved">resolved</option>
        </select>
      </div>

      {events.loading ? <Loading /> : events.error ? <ErrorState message={events.error} onRetry={events.refetch} /> : (
        <div className="card">
          {(events.data?.items.length ?? 0) === 0 ? <EmptyState message="No camera events match the filters." /> : (
            <table className="table">
              <thead>
                <tr>
                  <th>When</th><th>Event</th><th>Object</th><th>Source</th><th>Confidence</th>
                  <th>Frame</th><th>Severity</th><th>Status</th>
                </tr>
              </thead>
              <tbody>
                {events.data!.items.map((e) => (
                  <tr key={e.id}>
                    <td><small>{new Date(e.occurred_at).toLocaleString()}</small></td>
                    <td>{e.event_type.replace(/_/g, ' ')}</td>
                    <td>{e.detected_object ?? '—'}</td>
                    <td>
                      <Badge text={e.detection_source} tone={e.detection_source === 'yolo' ? 'info' : 'muted'} />
                    </td>
                    <td>{Math.round(e.confidence * 100)}%</td>
                    <td>{e.frame_number != null ? `#${e.frame_number}` : '—'}</td>
                    <td><SeverityBadge value={e.severity} /></td>
                    <td><StatusBadge value={e.status} /></td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
          <div className="pager">
            <button className="btn btn-sm" disabled={page === 0} onClick={() => setPage(page - 1)}>← Prev</button>
            <span>Page {page + 1} · {events.data?.total ?? 0} total</span>
            <button className="btn btn-sm" disabled={(page + 1) * LIMIT >= (events.data?.total ?? 0)} onClick={() => setPage(page + 1)}>Next →</button>
          </div>
        </div>
      )}

      <SimulatedDataNote />

      {detectOpen && (
        <Modal title="Run YOLO Detection" onClose={resetPanel}>
          <div className="form-grid">
            <label>Media type
              <select value={mediaKind} onChange={(e) => { setMediaKind(e.target.value as 'image' | 'video'); pickFile(null) }}>
                <option value="image">Image (JPG/PNG/WebP, ≤10 MB)</option>
                <option value="video">Video (MP4/WebM, ≤100 MB)</option>
              </select>
            </label>

            <label>Mine
              <select value={mineId} onChange={(e) => { setMineId(e.target.value); setZoneId('') }}>
                <option value="">— select mine —</option>
                {(mines.data ?? []).map((m: Mine) => <option key={m.id} value={m.id}>{m.name}</option>)}
              </select>
            </label>

            <label>Restricted zone (optional — enables zone safety rules)
              <select value={zoneId} onChange={(e) => setZoneId(e.target.value)} disabled={!mineId}>
                <option value="">none</option>
                {(zones.data ?? []).map((z) => <option key={z.id} value={z.id}>{z.name}</option>)}
              </select>
            </label>

            <label>Confidence threshold: {confidence.toFixed(2)}
              <input type="range" min="0.05" max="0.95" step="0.05" value={confidence}
                onChange={(e) => setConfidence(Number(e.target.value))} />
            </label>

            {mediaKind === 'video' && (
              <label>Frame stride (process every Nth frame): {frameStride}
                <input type="range" min="1" max="30" value={frameStride}
                  onChange={(e) => setFrameStride(Number(e.target.value))} />
              </label>
            )}

            <label>File
              <input ref={fileInputRef} type="file"
                accept={mediaKind === 'image' ? 'image/jpeg,image/png,image/webp' : 'video/mp4,video/webm,video/quicktime'}
                onChange={(e) => pickFile(e.target.files?.[0] ?? null)} />
            </label>

            {phase === 'uploading' && <div className="page-loading">Uploading…</div>}
            {phase === 'processing' && (
              <div className="page-loading">
                ⏳ Running YOLO inference{mediaKind === 'video' ? ' on sampled frames' : ''}… this can take a moment.
              </div>
            )}
            {phase === 'error' && <div className="form-error" role="alert">{errorMsg}</div>}

            <button className="btn btn-primary" onClick={runDetection}
              disabled={!file || !mineId || phase === 'uploading' || phase === 'processing'}>
              {phase === 'processing' ? 'Processing…' : 'Run YOLO Detection'}
            </button>
          </div>

          {phase === 'success' && result && (
            <div className="detection-results">
              <h3>Detection Summary</h3>
              <p>
                <Badge text={result.detector.toUpperCase()} tone="info" />{' '}
                <Badge text={result.model} tone="muted" />{' '}
                <Badge text={`storage: ${result.storage_provider}`} tone="muted" />
              </p>

              {result.class_summary ? (
                <table className="table">
                  <thead><tr><th>Class</th><th>Detections</th></tr></thead>
                  <tbody>
                    {Object.entries(result.class_summary).map(([cls, n]) => (
                      <tr key={cls}><td>{cls}</td><td>{n}</td></tr>
                    ))}
                  </tbody>
                </table>
              ) : (
                <p>{result.detection_count} object(s): {result.classes_detected.join(', ')}</p>
              )}

              {result.video_metadata && (
                <p className="muted">
                  Video: {result.video_metadata.total_frames} frames @ {result.video_metadata.fps} fps ·
                  processed {result.video_metadata.processed_frames} (stride {result.video_metadata.frame_stride}) ·
                  {result.video_metadata.processing_seconds}s
                </p>
              )}

              {result.safety_findings.length > 0 && (
                <>
                  <h4>Safety rule evaluation</h4>
                  <table className="table">
                    <thead><tr><th>Rule</th><th>Severity</th><th>Evidence</th></tr></thead>
                    <tbody>
                      {result.safety_findings.map((f) => (
                        <tr key={f.rule}>
                          <td>{f.rule.replace(/_/g, ' ')}</td>
                          <td><SeverityBadge value={f.severity} /></td>
                          <td><small>{f.evidence}</small></td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </>
              )}

              {result.alerts.length > 0 && (
                <p>
                  ⚠ {result.alerts.length} alert(s) raised:{' '}
                  {result.alerts.map((a) => `${a.title} (${a.severity})`).join('; ')}
                </p>
              )}

              <div className="media-row">
                {mediaKind === 'image' && previewUrl && (
                  <div>
                    <h4>Original</h4>
                    <img src={previewUrl} alt="Original upload" className="media-thumb" />
                  </div>
                )}
                {mediaKind === 'image' && result.annotated_image_url && (
                  <div>
                    <h4>Annotated (YOLO)</h4>
                    <img src={mediaUrl(result.annotated_image_url) ?? ''} alt="YOLO annotated" className="media-thumb" />
                  </div>
                )}
                {mediaKind === 'video' && result.annotated_video_url && (
                  <div>
                    <h4>Annotated video (YOLO)</h4>
                    <video src={mediaUrl(result.annotated_video_url) ?? ''} controls className="media-thumb" />
                  </div>
                )}
                {mediaKind === 'video' && previewUrl && (
                  <div>
                    <h4>Original video</h4>
                    <video src={previewUrl} controls className="media-thumb" />
                  </div>
                )}
              </div>

              <h4>Detections</h4>
              <table className="table">
                <thead>
                  <tr>
                    <th>Class</th><th>Confidence</th><th>BBox (x1,y1,x2,y2)</th>
                    {mediaKind === 'video' && <th>Frame</th>}
                  </tr>
                </thead>
                <tbody>
                  {result.detections.slice(0, 15).map((d, i) => (
                    <tr key={i}>
                      <td>{d.class}</td>
                      <td>{(d.confidence * 100).toFixed(1)}%</td>
                      <td><small>({d.bbox.map((v) => Math.round(v)).join(', ')})</small></td>
                      {mediaKind === 'video' && <td>#{d.frame_number ?? '—'}</td>}
                    </tr>
                  ))}
                </tbody>
              </table>
              {result.detections.length > 15 && (
                <p className="muted">…and {result.detections.length - 15} more detections.</p>
              )}
            </div>
          )}
        </Modal>
      )}
    </div>
  )
}
