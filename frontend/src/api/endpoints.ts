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


