// Thin wrapper around fetch for the Recipe Macros API.
//
// The session lives in HttpOnly cookies, so every request sends them (credentials: 'include').
// State-changing requests also echo the csrf_token cookie into the X-CSRF-Token header
// (double-submit CSRF protection, see backend/app/dependencies.py).
// The access token is short-lived: on a 401 the client asks /auth/refresh for a new one once and
// repeats the request; only if that fails is the user really logged out.

export const API_URL: string = import.meta.env.VITE_API_URL ?? 'http://localhost:8010'

export class ApiError extends Error {
  readonly status: number
  // The message the API sent (English), for details a generic Polish text cannot give.
  readonly detail: string

  constructor(status: number, detail: string) {
    super(detail)
    this.name = 'ApiError'
    this.status = status
    this.detail = detail
  }
}

function csrfToken(): string | null {
  const match = document.cookie.match(/(?:^|;\s*)csrf_token=([^;]+)/)
  return match ? decodeURIComponent(match[1]) : null
}

// FastAPI sends {"detail": "text"} or, for validation errors, {"detail": [{"msg": "..."}]}.
function detailOf(body: unknown, fallback: string): string {
  if (body && typeof body === 'object' && 'detail' in body) {
    const { detail } = body as { detail: unknown }
    if (typeof detail === 'string') return detail
    if (Array.isArray(detail)) {
      const messages = detail
        .map((item) => (item && typeof item === 'object' && 'msg' in item ? String(item.msg) : ''))
        .filter(Boolean)
      if (messages.length > 0) return messages.join('; ')
    }
  }
  return fallback
}

let onSessionLost: (() => void) | null = null

/** Called when a request ends in 401 even after a refresh: the session is gone. */
export function setSessionLostHandler(handler: (() => void) | null): void {
  onSessionLost = handler
}

// One refresh at a time: several requests failing together must not rotate the token twice
// (the second would look like a replayed token to the server).
let refreshing: Promise<boolean> | null = null

function refreshSession(): Promise<boolean> {
  refreshing ??= fetch(`${API_URL}/auth/refresh`, { method: 'POST', credentials: 'include' })
    .then((response) => response.ok)
    .catch(() => false)
    .finally(() => {
      refreshing = null
    })
  return refreshing
}

// These answer 401 for reasons that a refresh cannot fix (wrong password, no session at all).
const NO_REFRESH = ['/auth/login', '/auth/register', '/auth/refresh', '/auth/logout']

async function request<T>(
  method: string,
  path: string,
  body?: unknown,
  canRetry = true,
): Promise<T> {
  const headers: Record<string, string> = {}
  if (body !== undefined) headers['Content-Type'] = 'application/json'
  if (method !== 'GET') {
    const token = csrfToken()
    if (token) headers['X-CSRF-Token'] = token
  }

  let response: Response
  try {
    response = await fetch(`${API_URL}${path}`, {
      method,
      headers,
      credentials: 'include',
      body: body === undefined ? undefined : JSON.stringify(body),
    })
  } catch {
    throw new ApiError(0, 'The server is not reachable.')
  }

  if (response.status === 401 && canRetry && !NO_REFRESH.includes(path)) {
    if (await refreshSession()) return request<T>(method, path, body, false)
    // /auth/me IS the question "is anyone logged in?", so its 401 loses nothing; reporting it
    // would also clear the cache while that very query is still running.
    if (path !== '/auth/me') onSessionLost?.()
  }

  if (!response.ok) {
    let parsed: unknown = null
    try {
      parsed = await response.json()
    } catch {
      // not JSON (a proxy error page, for example): the status text will do
    }
    throw new ApiError(response.status, detailOf(parsed, response.statusText))
  }
  if (response.status === 204) return undefined as T
  return (await response.json()) as T
}

export const api = {
  get: <T>(path: string) => request<T>('GET', path),
  post: <T>(path: string, body?: unknown) => request<T>('POST', path, body),
  put: <T>(path: string, body?: unknown) => request<T>('PUT', path, body),
  patch: <T>(path: string, body?: unknown) => request<T>('PATCH', path, body),
  delete: <T>(path: string) => request<T>('DELETE', path),
}
