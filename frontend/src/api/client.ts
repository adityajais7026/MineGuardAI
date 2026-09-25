/**
 * Central API client for MineGuardAI.
 *
 * - Base URL: VITE_API_BASE_URL env var; empty string uses the Vite dev proxy
 *   (same-origin `/api/...`), which is also correct behind a reverse proxy.
 * - Auth: bearer token stored in localStorage by the AuthContext.
 * - Errors: always throws ApiError with status + server-provided detail so
 *   pages can show useful messages instead of crashing.
 */

const BASE_URL = import.meta.env.VITE_API_BASE_URL ?? ''

export class ApiError extends Error {
  status: number
  details?: unknown

  constructor(status: number, message: string, details?: unknown) {
    super(message)
    this.name = 'ApiError'
    this.status = status
    this.details = details
  }
}

export const TOKEN_KEY = 'mineguardai_token'

export function getStoredToken(): string | null {
  return localStorage.getItem(TOKEN_KEY)
}

export function setStoredToken(token: string | null): void {
  if (token) localStorage.setItem(TOKEN_KEY, token)
  else localStorage.removeItem(TOKEN_KEY)
}

interface RequestOptions {
  method?: 'GET' | 'POST' | 'PATCH' | 'PUT' | 'DELETE'
  body?: unknown
  /** Sent as-is with application/x-www-form-urlencoded (OAuth2 login). */
  form?: URLSearchParams
  params?: Record<string, string | number | boolean | undefined | null>
}

export async function apiFetch<T>(path: string, options: RequestOptions = {}): Promise<T> {
  const url = new URL(`${BASE_URL}${path}`, window.location.origin)
  if (options.params) {
    for (const [key, value] of Object.entries(options.params)) {
      if (value !== undefined && value !== null && value !== '') {
        url.searchParams.set(key, String(value))
      }
    }
  }

  const headers: Record<string, string> = {}
  const token = getStoredToken()
  if (token) headers['Authorization'] = `Bearer ${token}`
  if (options.body !== undefined) headers['Content-Type'] = 'application/json'
  if (options.form) headers['Content-Type'] = 'application/x-www-form-urlencoded'

  let response: Response
  try {
    response = await fetch(url.toString(), {
      method: options.method ?? 'GET',
      headers,
      body: options.form
        ? options.form.toString()
        : options.body !== undefined
          ? JSON.stringify(options.body)
          : undefined,
    })
  } catch {
    // Network-level failure (backend down, CORS blocked, etc.)
    throw new ApiError(0, 'Cannot reach the MineGuardAI backend. Is it running?')
  }

  if (response.status === 204) return undefined as T

  let data: unknown = null
  try {
    data = await response.json()
  } catch {
    // non-JSON body (e.g. empty error page)
  }

  if (!response.ok) {
    // Expired/invalid session: drop the token and let the router send the
    // user to login on the next render.
    if (response.status === 401 && !url.pathname.endsWith('/auth/login')) {
      setStoredToken(null)
      window.dispatchEvent(new Event('mineguardai:unauthorized'))
    }
    // Backend error envelope: {"error": {...}} or FastAPI {"detail": ...}
    const errObj = (data as { error?: { message?: string; details?: unknown }; detail?: unknown }) ?? {}
    const message =
      errObj?.error?.message ??
      (typeof errObj?.detail === 'string' ? errObj.detail : null) ??
      `Request failed with status ${response.status}`
    throw new ApiError(response.status, message, errObj?.error?.details ?? errObj?.detail)
  }

  return data as T
}

export const api = {
  get: <T>(path: string, params?: RequestOptions['params']) => apiFetch<T>(path, { params }),
  post: <T>(path: string, body?: unknown, params?: RequestOptions['params']) =>
    apiFetch<T>(path, { method: 'POST', body, params }),
  postForm: <T>(path: string, form: URLSearchParams) =>
    apiFetch<T>(path, { method: 'POST', form }),
  patch: <T>(path: string, body?: unknown) => apiFetch<T>(path, { method: 'PATCH', body }),
  put: <T>(path: string, body?: unknown) => apiFetch<T>(path, { method: 'PUT', body }),
  delete: <T>(path: string) => apiFetch<T>(path, { method: 'DELETE' }),
}
