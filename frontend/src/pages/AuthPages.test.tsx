import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter } from 'react-router-dom'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import App from '../App'
import { AuthProvider } from '../auth/AuthProvider'

const USER = {
  id: 1,
  email: 'ala@example.com',
  is_active: true,
  created_at: '2026-11-05T10:00:00Z',
  daily_kcal_goal: null,
  daily_protein_goal: null,
}

function reply(status: number, body?: unknown): Response {
  return new Response(body === undefined ? null : JSON.stringify(body), {
    status,
    headers: { 'Content-Type': 'application/json' },
  })
}

const fetchMock = vi.fn<typeof fetch>()

function renderAt(path: string) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return render(
    <QueryClientProvider client={client}>
      <MemoryRouter initialEntries={[path]}>
        <AuthProvider>
          <App />
        </AuthProvider>
      </MemoryRouter>
    </QueryClientProvider>,
  )
}

// Routes the mocked API by URL, so the order of the calls does not matter.
function serve(routes: Record<string, () => Response>) {
  fetchMock.mockImplementation(async (input) => {
    const path = String(input).replace(/^https?:\/\/[^/]+/, '')
    const handler = routes[path]
    if (!handler) throw new Error(`unexpected request to ${path}`)
    return handler()
  })
}

// What the API answers to someone who is not logged in: no session and nothing to refresh.
function anonymous(): Record<string, () => Response> {
  return {
    '/auth/me': () => reply(401, { detail: 'Not authenticated' }),
    '/auth/refresh': () => reply(401, { detail: 'Not authenticated' }),
  }
}

beforeEach(() => {
  vi.stubGlobal('fetch', fetchMock)
})

afterEach(() => {
  fetchMock.mockReset()
  vi.unstubAllGlobals()
})

describe('authentication pages', () => {
  it('sends an anonymous visitor from a protected page to the login page', async () => {
    serve(anonymous())

    renderAt('/')

    expect(await screen.findByRole('heading', { name: 'Zaloguj się' })).toBeInTheDocument()
  })

  it('logs in and shows the home page', async () => {
    serve({
      ...anonymous(),
      '/auth/login': () => reply(200, USER),
    })
    renderAt('/login')
    const user = userEvent.setup()

    await user.type(await screen.findByLabelText('E-mail'), 'ala@example.com')
    await user.type(screen.getByLabelText('Hasło'), 'correcthorse7')
    await user.click(screen.getByRole('button', { name: 'Zaloguj' }))

    expect(await screen.findByRole('heading', { name: 'Witaj!' })).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Wyloguj' })).toBeInTheDocument()
    const login = fetchMock.mock.calls.find((call) => String(call[0]).endsWith('/auth/login'))
    expect(login?.[1]?.body).toBe('{"email":"ala@example.com","password":"correcthorse7"}')
  })

  it('says so, in Polish, when the password is wrong', async () => {
    serve({
      ...anonymous(),
      '/auth/login': () => reply(401, { detail: 'Invalid email or password.' }),
    })
    renderAt('/login')
    const user = userEvent.setup()

    await user.type(await screen.findByLabelText('E-mail'), 'ala@example.com')
    await user.type(screen.getByLabelText('Hasło'), 'zlehaslo')
    await user.click(screen.getByRole('button', { name: 'Zaloguj' }))

    expect(await screen.findByRole('alert')).toHaveTextContent('Nieprawidłowy e-mail lub hasło.')
    expect(screen.getByRole('heading', { name: 'Zaloguj się' })).toBeInTheDocument()
  })

  it('explains that the email is already taken when registering', async () => {
    serve({
      ...anonymous(),
      '/auth/register': () => reply(409, { detail: 'An account with this email already exists.' }),
    })
    renderAt('/register')
    const user = userEvent.setup()

    await user.type(await screen.findByLabelText('E-mail'), 'ala@example.com')
    await user.type(screen.getByLabelText('Hasło'), 'correcthorse7')
    await user.click(screen.getByRole('button', { name: 'Zarejestruj' }))

    expect(await screen.findByRole('alert')).toHaveTextContent(
      'Konto z tym adresem e-mail już istnieje.',
    )
  })

  it('shows the server password rules after a 422', async () => {
    serve({
      ...anonymous(),
      '/auth/register': () => reply(422, { detail: [{ msg: 'Value error, Password is too short' }] }),
    })
    renderAt('/register')
    const user = userEvent.setup()

    await user.type(await screen.findByLabelText('E-mail'), 'ala@example.com')
    await user.type(screen.getByLabelText('Hasło'), 'abc')
    await user.click(screen.getByRole('button', { name: 'Zarejestruj' }))

    expect(await screen.findByRole('alert')).toHaveTextContent('Password is too short')
  })

  it('keeps a logged-in user away from the login page and logs out', async () => {
    serve({
      '/auth/me': () => reply(200, USER),
      '/auth/logout': () => reply(200, { status: 'ok' }),
    })
    renderAt('/login')
    const user = userEvent.setup()

    expect(await screen.findByRole('heading', { name: 'Witaj!' })).toBeInTheDocument()

    await user.click(screen.getByRole('button', { name: 'Wyloguj' }))

    expect(await screen.findByRole('heading', { name: 'Zaloguj się' })).toBeInTheDocument()
  })
})
