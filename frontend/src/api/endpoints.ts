/** Typed endpoint wrappers — one place where API paths live. */
import { api } from './client'
import type {
  Alert,
  CameraEvent,
  ComplianceRule,
  CorrectiveAction,
  DashboardSummary,
  DeleteUserReport,
  EnvironmentalReading,
  EvaluationResult,
  IngestResult,
  InvitationCreated,
  InvitationSummary,
  InvitationValidate,
  Incident,
  Inspection,
  LoginOtpStartResponse,
  LoginResponse,
  Mine,
  OtpSendResponse,
  Paginated,
  RegisterCompleteRequest,
  RegisterCompleteResponse,
  RegisterVerifyResponse,
  RestrictedZone,
  RiskAssessment,
  User,
  UserDeleteImpact,
} from './types'

export interface ListParams {
  skip?: number
  limit?: number
  sort?: string
  order?: 'asc' | 'desc'
  [key: string]: string | number | boolean | undefined | null
}

export const authApi = {
  login: (email: string, password: string) => {
    const form = new URLSearchParams({ username: email, password })
    return api.postForm<LoginResponse>('/api/auth/login', form)
  },
  me: () => api.get<User>('/api/auth/me'),

  // --- MSG91 SMS OTP flows (same JWT auth; secrets stay server-side) ---
  loginOtpStart: (email: string, password: string) =>
    api.post<LoginOtpStartResponse>('/api/auth/login/otp/start', { email, password }),
  loginOtpVerify: (email: string, otp: string) =>
    api.post<LoginResponse>('/api/auth/login/otp/verify', { email, otp }),
  registerOtpStart: (mobile: string) =>
    api.post<OtpSendResponse>('/api/auth/register/otp/start', { mobile }),
  registerOtpVerify: (mobile: string, otp: string) =>
    api.post<RegisterVerifyResponse>('/api/auth/register/otp/verify', { mobile, otp }),
  registerComplete: (body: RegisterCompleteRequest) =>
    api.post<RegisterCompleteResponse>('/api/auth/register/complete', body),

  /** Public pre-flight: validate code+email; the response carries the
   *  invitation-fixed role (the register form never offers a role choice). */
  validateInvitation: (code: string, email: string) =>
    api.get<InvitationValidate>('/api/auth/invitations/validate', { code, email }),
}

export const minesApi = {
  list: (params?: ListParams) => api.get<Paginated<Mine>>('/api/mines', params),
  get: (id: string) => api.get<Mine>(`/api/mines/${id}`),
  details: (id: string) =>
    api.get<{ mine: Mine; counts: Record<string, number> }>(`/api/mines/${id}/details`),
  create: (body: Partial<Mine>) => api.post<Mine>('/api/mines', body),
  update: (id: string, body: Partial<Mine>) => api.patch<Mine>(`/api/mines/${id}`, body),
  delete: (id: string) => api.delete<void>(`/api/mines/${id}`),
}

export const environmentApi = {
  list: (params?: ListParams) => api.get<Paginated<EnvironmentalReading>>('/api/environment', params),
}

export const complianceApi = {
  rules: (params?: ListParams) => api.get<Paginated<ComplianceRule>>('/api/compliance-rules', params),
  createRule: (body: Partial<ComplianceRule>) => api.post<ComplianceRule>('/api/compliance-rules', body),
  updateRule: (id: string, body: Partial<ComplianceRule>) =>
    api.patch<ComplianceRule>(`/api/compliance-rules/${id}`, body),
  deleteRule: (id: string) => api.delete<void>(`/api/compliance-rules/${id}`),
  ingest: (mineId: string, parameter: string, value: number, unit: string) =>
    api.post<IngestResult>('/api/compliance/ingest', undefined, {
      mine_id: mineId, parameter, value, unit,
    }),
  evaluate: (mineId: string) => api.get<EvaluationResult[]>(`/api/compliance/evaluate/${mineId}`),
}

export const riskApi = {
  allMines: () => api.get<RiskAssessment[]>('/api/risk/mines'),
  forMine: (mineId: string) => api.get<RiskAssessment>(`/api/risk/mines/${mineId}`),
}

export const dashboardApi = {
  summary: (params?: { mine_id?: string; days?: number }) =>
    api.get<DashboardSummary>('/api/dashboard/summary', params),
}

export const zonesApi = {
  list: (params?: ListParams) => api.get<Paginated<RestrictedZone>>('/api/restricted-zones', params),
  create: (body: Partial<RestrictedZone>) => api.post<RestrictedZone>('/api/restricted-zones', body),
  update: (id: string, body: Partial<RestrictedZone>) =>
    api.patch<RestrictedZone>(`/api/restricted-zones/${id}`, body),
  delete: (id: string) => api.delete<void>(`/api/restricted-zones/${id}`),
}

export const cameraEventsApi = {
  list: (params?: ListParams) => api.get<Paginated<CameraEvent>>('/api/camera-events', params),
  get: (id: string) => api.get<CameraEvent>(`/api/camera-events/${id}`),
  update: (id: string, body: Partial<CameraEvent>) =>
    api.patch<CameraEvent>(`/api/camera-events/${id}`, body),
}

export const alertsApi = {
  list: (params?: ListParams) => api.get<Paginated<Alert>>('/api/alerts', params),
  get: (id: string) => api.get<Alert>(`/api/alerts/${id}`),
  create: (body: Partial<Alert>) => api.post<Alert>('/api/alerts', body),
  update: (id: string, body: Partial<Alert>) => api.patch<Alert>(`/api/alerts/${id}`, body),
  delete: (id: string) => api.delete<void>(`/api/alerts/${id}`),
}

export const incidentsApi = {
  list: (params?: ListParams) => api.get<Paginated<Incident>>('/api/incidents', params),
  get: (id: string) => api.get<Incident>(`/api/incidents/${id}`),
  create: (body: Partial<Incident>) => api.post<Incident>('/api/incidents', body),
  update: (id: string, body: Partial<Incident>) => api.patch<Incident>(`/api/incidents/${id}`, body),
  delete: (id: string) => api.delete<void>(`/api/incidents/${id}`),
}

export const inspectionsApi = {
  list: (params?: ListParams) => api.get<Paginated<Inspection>>('/api/inspections', params),
  get: (id: string) => api.get<Inspection>(`/api/inspections/${id}`),
  create: (body: Partial<Inspection>) => api.post<Inspection>('/api/inspections', body),
  update: (id: string, body: Partial<Inspection>) =>
    api.patch<Inspection>(`/api/inspections/${id}`, body),
}

export const actionsApi = {
  list: (params?: ListParams) => api.get<Paginated<CorrectiveAction>>('/api/corrective-actions', params),
  get: (id: string) => api.get<CorrectiveAction>(`/api/corrective-actions/${id}`),
  create: (body: Partial<CorrectiveAction>) => api.post<CorrectiveAction>('/api/corrective-actions', body),
  update: (id: string, body: Partial<CorrectiveAction>) =>
    api.patch<CorrectiveAction>(`/api/corrective-actions/${id}`, body),
  delete: (id: string) => api.delete<void>(`/api/corrective-actions/${id}`),
}

export const usersApi = {
  list: (params?: ListParams) => api.get<Paginated<User>>('/api/users', params),
  update: (id: string, body: Partial<User> & { password?: string }) =>
    api.patch<User>(`/api/users/${id}`, body),
  /** Soft delete retained: deactivate instead of destroying audit history. */
  delete: (id: string) => api.delete<void>(`/api/users/${id}`),

  // --- Invitation codes (the ONLY registration path; admin-managed) ---
  invite: (body: { full_name: string; email: string; role: string }) =>
    api.post<InvitationCreated>('/api/users/invite', body),
  invitations: (params?: ListParams) =>
    api.get<Paginated<InvitationSummary>>('/api/users/invitations', params),
  /** New code, same email/role; the previous code is invalidated immediately. */
  regenerateInvitation: (id: string) =>
    api.post<InvitationCreated>(`/api/users/invitations/${encodeURIComponent(id)}/regenerate`),
  /** Soft-delete: the code stops working immediately (row kept for audit). */
  deleteInvitation: (id: string) =>
    api.delete<{ detail: string }>(`/api/users/invitations/${encodeURIComponent(id)}`),

  // --- Permanent deletion (admin, with explicit confirmation in the UI) ---
  deleteImpact: (id: string) => api.get<UserDeleteImpact>(`/api/users/${id}/impact`),
  deletePermanent: (id: string) => api.delete<DeleteUserReport>(`/api/users/${id}/permanent`),
}



// ===========================================================================
// Smart Governance & Compliance platform (additive; existing endpoints above)
// ===========================================================================

export interface GovernanceTemplate {
  id: string
  name: string
  description: string | null
  inspection_type: string
  mine_id: string | null
  regulatory_reference: string | null
  is_active: boolean
  created_at: string
  items: { id: string; position: number; label: string; category: string; result_options: string; severity_weight: number }[]
}

export interface ChecklistItem {
  id: string
  inspection_id: string
  position: number
  label: string
  category: string
  result: 'pass' | 'fail' | 'na' | 'unknown' | null
  comment: string | null
  ai_suggestion: string | null
  ai_confidence: number | null
  ai_model: string | null
}

export interface Geofence {
  id: string
  mine_id: string
  name: string
  boundary_type: 'radius' | 'polygon'
  center_lat: number | null
  center_lng: number | null
  radius_m: number | null
  polygon_json: number[][] | null
  is_active: boolean
}

export interface GovernanceWorker {
  id: string
  mine_id: string
  contractor_id: string | null
  employee_code: string
  full_name: string
  role: string | null
  phone: string | null
  is_active: boolean
}

export interface Contractor {
  id: string
  name: string
  contact_person: string | null
  phone: string | null
  email: string | null
  is_active: boolean
}

export interface ContractorDocument {
  id: string
  contractor_id: string | null
  worker_id: string | null
  mine_id: string | null
  doc_type: string
  title: string
  document_ref: string
  issued_on: string | null
  expires_on: string | null
  verification_status: string
}

export interface Emergency {
  id: string
  mine_id: string
  emergency_type: string
  severity: string
  status: string
  title: string
  description: string | null
  location_text: string | null
  created_at: string
}

export interface SensorDevice {
  id: string
  mine_id: string
  device_code: string
  parameter: string
  unit: string
  source: 'real' | 'demo'
  location_text: string | null
  warning_threshold: number | null
  critical_threshold: number | null
  is_active: boolean
  last_seen_at: string | null
}

export interface TelemetryReading {
  id: string
  device_id: string
  mine_id: string
  value: number
  unit: string
  status: 'normal' | 'warning' | 'critical' | 'unknown'
  recorded_at: string
}

export interface RiskScore {
  mine_id: string
  score: number
  band: 'low' | 'medium' | 'high' | 'critical'
  factors: { factor: string; points: number; detail: string }[]
}

export interface AuditEvent {
  id: string
  seq: number
  actor_id: string | null
  actor_role: string | null
  action: string
  entity_type: string
  entity_id: string | null
  mine_id: string | null
  prev_hash: string | null
  event_hash: string
  created_at: string
}

export interface GovernanceNotification {
  id: string
  category: string
  title: string
  body: string | null
  severity: string
  read_at: string | null
  created_at: string
}

export interface ComplianceSummary {
  total_requirements: number
  compliant: number
  attention: number
  violation: number
  not_assessed: number
  overdue_actions: number
  upcoming_deadlines: number
  score: number
}

export interface AiCapability {
  status: string
  model?: string
  provider?: string
  note?: string
}

export const governanceApi = {
  // Templates
  templates: () => api.get<GovernanceTemplate[]>('/api/governance/inspection-templates'),
  createTemplate: (body: Record<string, unknown>) =>
    api.post<GovernanceTemplate>('/api/governance/inspection-templates', body),

  // Inspection workflow
  startFromTemplate: (body: Record<string, unknown>) =>
    api.post<{ inspection_id: string; checklist: ChecklistItem[] }>('/api/governance/inspections/from-template', body),
  checklist: (inspectionId: string) =>
    api.get<ChecklistItem[]>(`/api/governance/inspections/${inspectionId}/checklist`),
  submitChecklist: (inspectionId: string, results: Record<string, { result?: string; comment?: string }>) =>
    api.put<ChecklistItem[]>(`/api/governance/inspections/${inspectionId}/checklist`, { results }),
  submitInspection: (inspectionId: string) =>
    api.post<{ compliance_result: string }>(`/api/governance/inspections/${inspectionId}/submit`),

  // Compliance
  requirements: () => api.get<GovernanceTemplate[]>('/api/governance/compliance/requirements'),
  summary: (mineId?: string, period?: string) =>
    api.get<ComplianceSummary>('/api/governance/compliance/summary', { mine_id: mineId, period }),

  // Geofencing
  geofences: (mineId?: string) => api.get<Geofence[]>('/api/governance/geofences', { mine_id: mineId }),
  createGeofence: (body: Record<string, unknown>) => api.post<Geofence>('/api/governance/geofences', body),
  verifyLocation: (mineId: string, latitude?: number, longitude?: number) =>
    api.post<{ status: string; message?: string }>('/api/governance/geofences/verify-location',
      { mine_id: mineId, latitude, longitude }),

  // Workers / shifts
  workers: (mineId?: string) => api.get<GovernanceWorker[]>('/api/governance/workers', { mine_id: mineId }),
  createWorker: (body: Record<string, unknown>) => api.post<GovernanceWorker>('/api/governance/workers', body),

  // Contractors + documents
  contractors: () => api.get<Contractor[]>('/api/governance/contractors'),
  createContractor: (body: Record<string, unknown>) => api.post<Contractor>('/api/governance/contractors', body),
  documents: (status?: string) => api.get<ContractorDocument[]>('/api/governance/contractors/documents', { status }),
  createDocument: (body: Record<string, unknown>) =>
    api.post<ContractorDocument>('/api/governance/contractors/documents', body),
  verifyDocument: (id: string, verificationStatus: string) =>
    api.post<ContractorDocument>(`/api/governance/contractors/documents/${id}/verify`,
      { verification_status: verificationStatus }),

  // Emergency
  emergencies: (mineId?: string, status?: string) =>
    api.get<Emergency[]>('/api/governance/emergencies', { mine_id: mineId, status }),
  createEmergency: (body: Record<string, unknown>) => api.post<Emergency>('/api/governance/emergencies', body),
  updateEmergency: (id: string, body: Record<string, unknown>) =>
    api.patch<Emergency>(`/api/governance/emergencies/${id}`, body),

  // Telemetry
  devices: (mineId?: string) => api.get<SensorDevice[]>('/api/governance/telemetry/devices', { mine_id: mineId }),
  createDevice: (body: Record<string, unknown>) => api.post<SensorDevice>('/api/governance/telemetry/devices', body),
  readings: (params?: ListParams) => api.get<TelemetryReading[]>('/api/governance/telemetry/readings', params),
  addReading: (deviceId: string, value: number) =>
    api.post<TelemetryReading>('/api/governance/telemetry/readings', { device_id: deviceId, value }),

  // Risk
  riskAll: () => api.get<RiskScore[]>('/api/governance/risk'),
  riskMine: (mineId: string) => api.get<RiskScore>(`/api/governance/risk/${mineId}`),

  // Audit (admin)
  audit: (params?: ListParams) => api.get<AuditEvent[]>('/api/governance/audit', params),
  auditVerify: () => api.get<{ valid: boolean; entries: number; head_hash?: string }>('/api/governance/audit/verify'),

  // Notifications
  notifications: (unreadOnly?: boolean) =>
    api.get<GovernanceNotification[]>('/api/governance/notifications', { unread_only: unreadOnly }),
  markRead: (ids: string[]) => api.post<void>('/api/governance/notifications/read', { ids }),
  escalateOverdue: () => api.post<GovernanceNotification[]>('/api/governance/notifications/escalate-overdue'),

  // Sync (offline-first)
  syncPush: (body: Record<string, unknown>) =>
    api.post<{ client_guid: string; status: string; result_ref_id?: string; error?: string }>('/api/governance/sync', body),
  syncQueue: (status?: string) => api.get<{ id: string; client_guid: string; status: string; error?: string }[]>(
    '/api/governance/sync/queue', { status }),

  // AI workbench
  aiCapabilities: () => api.get<Record<string, AiCapability>>('/api/governance/ai/capabilities'),

  // Lightweight status probes for the shell's attention indicators — thin
  // wrappers over EXISTING endpoints (no new backend routes).
  alertsStatus: async (): Promise<{ has_active: boolean; active: number }> => {
    const d = await api.get<{ items: unknown[]; total: number }>('/api/alerts',
      { status: 'new', limit: 1 })
    const investigate = await api.get<{ items: unknown[]; total: number }>('/api/alerts',
      { status: 'acknowledged', limit: 1 })
    return { has_active: d.total > 0 || investigate.total > 0, active: d.total + investigate.total }
  },
  emergencyStatus: async (): Promise<{ has_open: boolean }> => {
    const d = await api.get<Emergency[]>('/api/governance/emergencies', { status: 'open' })
    return { has_open: d.length > 0 }
  },
  unreadStatus: async (): Promise<{ has_unread: boolean }> => {
    const d = await api.get<GovernanceNotification[]>('/api/governance/notifications', { unread_only: true })
    return { has_unread: d.length > 0 }
  },
  ocr: (dataBase64: string, mimeType?: string) =>
    api.post<{ status: string; text: string | null; message: string | null }>('/api/governance/ai/ocr',
      { data_base64: dataBase64, mime_type: mimeType }),
  voice: (dataBase64: string) =>
    api.post<{ status: string; text: string | null; message: string | null }>('/api/governance/ai/voice',
      { data_base64: dataBase64 }),
  translate: (text: string, targetLanguage: string) =>
    api.post<{ status: string; text: string | null; message: string | null }>('/api/governance/ai/translate',
      { text, target_language: targetLanguage }),

  // Reports (PDF)
  reportUrl: {
    inspection: (id: string) => `/api/governance/reports/inspection/${id}.pdf`,
    compliance: (mineId: string) => `/api/governance/reports/compliance/${mineId}.pdf`,
    safety: (mineId: string) => `/api/governance/reports/safety/${mineId}.pdf`,
  },
}
