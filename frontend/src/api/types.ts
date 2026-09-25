/** TypeScript mirrors of the backend Pydantic schemas. */

export interface Paginated<T> {
  items: T[]
  total: number
  skip: number
  limit: number
}

export type Role = 'admin' | 'mine_manager' | 'safety_officer' | 'environmental_officer'
export type Severity = 'low' | 'medium' | 'high' | 'critical'

export interface User {
  id: string
  email: string
  full_name: string
  role: Role
  is_active: boolean
  created_at: string
  updated_at: string
}

export interface LoginResponse {
  access_token: string
  token_type: string
  user: User
}

export interface Mine {
  id: string
  name: string
  code: string
  mine_type: 'open_cast' | 'underground' | 'mixed'
  status: 'operational' | 'maintenance' | 'suspended' | 'closed'
  location: string
  latitude: number | null
  longitude: number | null
  manager_id: string | null
  description: string | null
  created_at: string
  updated_at: string
}

export interface ComplianceRule {
  id: string
  name: string
  description: string | null
  parameter: string
  operator: string
  threshold: number
  unit: string
  severity: Severity
  is_active: boolean
  mine_id: string | null
  created_at: string
  updated_at: string
}

export interface EnvironmentalReading {
  id: string
  mine_id: string
  parameter: string
  value: number
  unit: string
  threshold: number
  status: 'normal' | 'violation'
  source: string
  rule_id: string | null
  recorded_at: string
  created_at: string
}

export interface CameraEvent {
  id: string
  mine_id: string
  zone_id: string | null
  camera_id: string
  event_type: string
  detected_object: string | null
  zone_label: string | null
  confidence: number
  severity: Severity
  status: 'new' | 'investigating' | 'resolved'
  detection_source: 'simulated' | 'yolo' | 'opencv'
  model_version: string | null
  image_ref: string | null
  video_ref: string | null
  occurred_at: string
  created_at: string
}

export interface RestrictedZone {
  id: string
  mine_id: string
  name: string
  description: string | null
  camera_id: string | null
  is_active: boolean
  created_at: string
  updated_at: string
}

export interface Alert {
  id: string
  mine_id: string
  alert_type: string
  title: string
  description: string | null
  severity: Severity
  source: string
  status: 'new' | 'acknowledged' | 'investigating' | 'resolved'
  source_reading_id: string | null
  source_event_id: string | null
  assigned_to_id: string | null
  acknowledged_at: string | null
  resolved_at: string | null
  created_at: string
  updated_at: string
}

export interface Incident {
  id: string
  mine_id: string
  reported_by_id: string | null
  title: string
  description: string | null
  category: string
  severity: Severity
  status: 'open' | 'investigating' | 'action_required' | 'resolved' | 'closed'
  evidence_ref: string | null
  occurred_at: string
  resolved_at: string | null
  created_at: string
  updated_at: string
}

export interface Inspection {
  id: string
  mine_id: string
  inspector_id: string | null
  inspection_type: string
  status: 'scheduled' | 'in_progress' | 'completed' | 'cancelled'
  scheduled_at: string
  completed_at: string | null
  compliance_result: 'compliant' | 'non_compliant' | 'partial' | 'pending'
  findings: string | null
  notes: string | null
  created_at: string
  updated_at: string
}

export interface CorrectiveAction {
  id: string
  incident_id: string | null
  inspection_id: string | null
  description: string
  assigned_to_id: string | null
  priority: Severity
  status: 'pending' | 'in_progress' | 'completed' | 'overdue'
  due_date: string
  completion_date: string | null
  remarks: string | null
  created_at: string
  updated_at: string
}

// ---- Compliance engine / risk / dashboard ----

export interface IngestResult {
  reading_id: string
  mine_id: string
  parameter: string
  value: number
  status: 'COMPLIANT' | 'WARNING' | 'VIOLATION'
  threshold: number | null
  rule_id: string | null
  alert_generated: boolean
  alert_id: string | null
  message: string
}

export interface EvaluationResult {
  parameter: string
  value: number
  unit: string
  threshold: number | null
  operator: string | null
  rule_id: string | null
  status: 'COMPLIANT' | 'WARNING' | 'VIOLATION'
  severity: string | null
  message: string
}

export interface RiskFactor {
  factor: string
  points: number
  max_points: number
  detail: string
}

export interface RiskAssessment {
  mine_id: string
  mine_name: string
  score: number
  level: 'LOW' | 'MEDIUM' | 'HIGH' | 'CRITICAL'
  factors: RiskFactor[]
  counts: Record<string, number>
  disclaimer: string
}

export interface DashboardSummary {
  mines_total: number
  mines_operational: number
  alerts_active: number
  alerts_critical: number
  incidents_open: number
  inspections_pending: number
  actions_overdue: number
  actions_pending: number
  compliance_rate: number
  readings_24h: number
  camera_events_24h: number
  alerts_by_severity: Record<string, number>
  incidents_by_category: Record<string, number>
  camera_events_by_type: Record<string, number>
  readings_trend: { date: string; parameter: string; avg_value: number; count: number }[]
  risk_distribution: Record<string, number>
  highest_risk_mines: { mine_id: string; mine_name: string; score: number; level: string }[]
  recent_alerts: {
    id: string; mine_id: string; title: string; severity: Severity
    status: string; alert_type: string; source: string; created_at: string
  }[]
  recent_camera_events: {
    id: string; mine_id: string; event_type: string; zone_label: string | null
    camera_id: string; confidence: number; severity: Severity; status: string
    detection_source: string; occurred_at: string
  }[]
  recent_readings: {
    id: string; mine_id: string; parameter: string; value: number; unit: string
    threshold: number; status: string; recorded_at: string
  }[]
  generated_at: string
  data_note: string
}
