import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { api, ApiError, setSessionLostHandler } from './client'

function reply(status: number, body?: unknown): Response {
  return new Response(body === undefined ? null : JSON.stringify(body), {
    status,
    headers: { 'Content-Type': 'application/json' },
  })
}

const fetchMock = vi.fn<typeof fetch>()

beforeEach(() => {
  vi.stubGlobal('fetch', fetchMock)
  document.cookie = 'csrf_token=abc123'
})

afterEach(() => {
  fetchMock.mockReset()
  setSessionLostHandler(null)
  document.cookie = 'csrf_token=; expires=Thu, 01 Jan 1970 00:00:00 GMT'
  vi.unstubAllGlobals()
})

function headersOf(call: number): Record<string, string> {
  return (fetchMock.mock.calls[call][1]?.headers ?? {}) as Record<string, string>
}

describe('api client', () => {
  it('sends the session cookies and no CSRF header on a GET', async () => {
    fetchMock.mockResolvedValueOnce(reply(200, { ok: true }))

    await api.get('/recipes')

    expect(fetchMock.mock.calls[0][1]?.credentials).toBe('include')
    expect(headersOf(0)['X-CSRF-Token']).toBeUndefined()
  })

  it('echoes the csrf cookie into a header on state-changing requests', async () => {
    fetchMock.mockResolvedValueOnce(reply(200, {}))

    await api.post('/food-log', { grams: 100 })

    expect(headersOf(0)['X-CSRF-Token']).toBe('abc123')
    expect(headersOf(0)['Content-Type']).toBe('application/json')
    expect(fetchMock.mock.calls[0][1]?.body).toBe('{"grams":100}')
  })

  it('returns undefined for 204', async () => {
    fetchMock.mockResolvedValueOnce(reply(204))

    await expect(api.delete('/pantry/1')).resolves.toBeUndefined()
  })

  it('refreshes the session once on a 401 and repeats the request', async () => {
    fetchMock
      .mockResolvedValueOnce(reply(401, { detail: 'Not authenticated' }))
      .mockResolvedValueOnce(reply(200, {})) // /auth/refresh
      .mockResolvedValueOnce(reply(200, { id: 7 }))

    const result = await api.get<{ id: number }>('/auth/me-like')

    expect(result).toEqual({ id: 7 })
    expect(fetchMock).toHaveBeenCalledTimes(3)
    expect(String(fetchMock.mock.calls[1][0])).toMatch(/\/auth\/refresh$/)
  })

  it('does not loop: a second 401 after a refresh is final and reports the lost session', async () => {
    const lost = vi.fn()
    setSessionLostHandler(lost)
    fetchMock
      .mockResolvedValueOnce(reply(401, { detail: 'Not authenticated' }))
      .mockResolvedValueOnce(reply(200, {}))
      .mockResolvedValueOnce(reply(401, { detail: 'Not authenticated' }))

    await expect(api.get('/recipes')).rejects.toMatchObject({ status: 401 })
    expect(fetchMock).toHaveBeenCalledTimes(3)
  })

  it('reports a lost session when the refresh itself fails', async () => {
    const lost = vi.fn()
    setSessionLostHandler(lost)
    fetchMock
      .mockResolvedValueOnce(reply(401, { detail: 'Not authenticated' }))
      .mockResolvedValueOnce(reply(401, { detail: 'Invalid refresh token' }))

    await expect(api.get('/recipes')).rejects.toBeInstanceOf(ApiError)
    expect(lost).toHaveBeenCalledOnce()
  })

  it('does not report a lost session for /auth/me: that request is the check itself', async () => {
    const lost = vi.fn()
    setSessionLostHandler(lost)
    fetchMock
      .mockResolvedValueOnce(reply(401, { detail: 'Not authenticated' }))
      .mockResolvedValueOnce(reply(401, { detail: 'Not authenticated' }))

    await expect(api.get('/auth/me')).rejects.toMatchObject({ status: 401 })
    expect(lost).not.toHaveBeenCalled()
  })

  it('does not try to refresh after a failed login', async () => {
    fetchMock.mockResolvedValueOnce(reply(401, { detail: 'Invalid email or password.' }))

    await expect(api.post('/auth/login', {})).rejects.toMatchObject({
      status: 401,
      detail: 'Invalid email or password.',
    })
    expect(fetchMock).toHaveBeenCalledTimes(1)
  })

  it('turns FastAPI validation errors into one readable detail', async () => {
    fetchMock.mockResolvedValueOnce(
      reply(422, { detail: [{ msg: 'Password too short' }, { msg: 'Needs a digit' }] }),
    )

    await expect(api.post('/auth/register', {})).rejects.toMatchObject({
      status: 422,
      detail: 'Password too short; Needs a digit',
    })
  })

  it('reports an unreachable server as status 0', async () => {
    fetchMock.mockRejectedValueOnce(new TypeError('Failed to fetch'))

    await expect(api.get('/recipes')).rejects.toMatchObject({ status: 0 })
  })
})
