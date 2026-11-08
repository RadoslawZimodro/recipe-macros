import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter } from 'react-router-dom'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import type { PantryItem, RecipeMatch, Staples } from '../../api/pantry'
import { PantryPage } from './PantryPage'

function reply(status: number, body?: unknown): Response {
  return new Response(body === undefined ? null : JSON.stringify(body), {
    status,
    headers: { 'Content-Type': 'application/json' },
  })
}

const NOW = '2026-11-06T10:00:00Z'
const INGREDIENTS = [
  { id: 1, canonical_name: 'Mleko' },
  { id: 2, canonical_name: 'Mąka' },
].map((item) => ({
  ...item,
  kcal_per_100g: 50,
  protein_per_100g: 3,
  fat_per_100g: 2,
  carbs_per_100g: 5,
  density_g_per_ml: null,
  source: 'off',
  is_shared: true,
}))

// A tiny in-memory API: state changes by PUT/DELETE, so the page's refetching is really tested.
interface Fake {
  pantry: PantryItem[]
  staples: Staples
  matches: RecipeMatch[]
  failMatches?: boolean
  // HTTP status to answer PUT / DELETE with instead of succeeding.
  failAdd?: number
  failRemove?: number
}

const fetchMock = vi.fn<typeof fetch>()
let fake: Fake

function serve() {
  fetchMock.mockImplementation(async (input, init) => {
    const path = String(input).replace(/^https?:\/\/[^/]+/, '')
    const method = init?.method ?? 'GET'
    if (path === '/pantry' && method === 'GET') return reply(200, fake.pantry)
    if (path === '/pantry/recipes') {
      return fake.failMatches ? reply(500, { detail: 'boom' }) : reply(200, fake.matches)
    }
    if (path === '/staples' && method === 'GET') return reply(200, fake.staples)
    const search = path.match(/^\/ingredients\?q=([^&]*)/)
    if (search) {
      const q = decodeURIComponent(search[1]).toLowerCase()
      const items = INGREDIENTS.filter((i) => i.canonical_name.toLowerCase().includes(q))
      return reply(200, { items, total: items.length, limit: 8, offset: 0 })
    }
    const target = path.match(/^\/(pantry|staples)\/(\d+)$/)
    if (target) {
      const id = Number(target[2])
      const list = target[1] === 'pantry' ? fake.pantry : fake.staples.own
      if (method === 'PUT') {
        if (fake.failAdd) return reply(fake.failAdd, { detail: 'boom' })
        const name = INGREDIENTS.find((i) => i.id === id)!.canonical_name
        const item = { ingredient_id: id, name, added_at: NOW }
        list.push(item)
        return reply(200, item)
      }
      if (method === 'DELETE') {
        if (fake.failRemove) return reply(fake.failRemove, { detail: 'boom' })
        list.splice(0, list.length, ...list.filter((i) => i.ingredient_id !== id))
        return reply(204)
      }
    }
    throw new Error(`unexpected request ${method} ${path}`)
  })
}

function renderPage() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return render(
    <QueryClientProvider client={client}>
      <MemoryRouter>
        <PantryPage />
      </MemoryRouter>
    </QueryClientProvider>,
  )
}

function called(method: string, path: string) {
  return fetchMock.mock.calls.some(
    (call) => String(call[0]).endsWith(path) && (call[1]?.method ?? 'GET') === method,
  )
}

beforeEach(() => {
  fake = { pantry: [], staples: { defaults: ['sól', 'woda'], own: [] }, matches: [] }
  vi.stubGlobal('fetch', fetchMock)
  serve()
})

afterEach(() => {
  fetchMock.mockReset()
  vi.unstubAllGlobals()
})

describe('pantry page', () => {
  it('shows empty states for an empty pantry, no own staples and no matches', async () => {
    renderPage()

    expect(await screen.findByText(/Lodówka jest pusta/)).toBeInTheDocument()
    expect(screen.getByText('Nie dodano własnych produktów.')).toBeInTheDocument()
    expect(screen.getByText(/Brak pasujących przepisów/)).toBeInTheDocument()
    expect(screen.getByText('Domyślnie: sól, woda.')).toBeInTheDocument()
  })

  it('adds a product found by the search and removes it again', async () => {
    renderPage()
    const user = userEvent.setup()

    await user.type(await screen.findByLabelText('Dodaj produkt'), 'mle')
    await user.click(await screen.findByRole('button', { name: 'Mleko' }))

    const chip = await screen.findByRole('button', { name: 'Usuń Mleko' })
    expect(called('PUT', '/pantry/1')).toBe(true)

    await user.click(chip)
    expect(await screen.findByText(/Lodówka jest pusta/)).toBeInTheDocument()
    expect(called('DELETE', '/pantry/1')).toBe(true)
  })

  it('says so when the search finds nothing', async () => {
    renderPage()
    const user = userEvent.setup()

    await user.type(await screen.findByLabelText('Dodaj produkt'), 'xyz')

    expect(await screen.findByText('Brak pasujących produktów.')).toBeInTheDocument()
  })

  it('adds and removes an own always-at-home product', async () => {
    renderPage()
    const user = userEvent.setup()

    await user.type(await screen.findByLabelText(/Dodaj do/), 'mąk')
    await user.click(await screen.findByRole('button', { name: 'Mąka' }))

    const chip = await screen.findByRole('button', { name: 'Usuń Mąka' })
    expect(called('PUT', '/staples/2')).toBe(true)

    await user.click(chip)
    expect(await screen.findByText('Nie dodano własnych produktów.')).toBeInTheDocument()
    expect(called('DELETE', '/staples/2')).toBe(true)
  })

  it('lists recipes by match with the missing lines and a link to the recipe', async () => {
    fake.matches = [
      {
        recipe_id: 7,
        title: 'Naleśniki',
        lines_total: 4,
        lines_have: 2,
        percent: 50,
        missing: [
          { line_id: 1, raw_text: '2 jajka', unlinked: false },
          { line_id: 2, raw_text: 'szczypta czegoś', unlinked: true },
        ],
      },
      {
        recipe_id: 9,
        title: 'Omlet',
        lines_total: 2,
        lines_have: 2,
        percent: 100,
        missing: [],
      },
    ]
    renderPage()

    const links = await screen.findAllByRole('link')
    expect(links.map((link) => link.textContent)).toEqual(['Omlet', 'Naleśniki'])
    expect(links[1]).toHaveAttribute('href', '/recipes/7')
    expect(screen.getByText('100%')).toBeInTheDocument()
    const card = screen.getByText('Naleśniki').closest('li')!
    expect(within(card).getByText('50%')).toBeInTheDocument()
    expect(within(card).getByText('2 jajka')).toBeInTheDocument()
    expect(within(card).getByText(/nierozpoznany produkt/)).toBeInTheDocument()
  })

  it('shows an error with a retry for the matches', async () => {
    fake.failMatches = true
    renderPage()

    expect(await screen.findByRole('button', { name: 'Spróbuj ponownie' })).toBeInTheDocument()
    expect(screen.getByText(/Błąd serwera/)).toBeInTheDocument()
  })

  it('shows an alert when adding a product fails', async () => {
    fake.failAdd = 500
    renderPage()
    const user = userEvent.setup()

    await user.type(await screen.findByLabelText('Dodaj produkt'), 'mle')
    await user.click(await screen.findByRole('button', { name: 'Mleko' }))

    expect(await screen.findByRole('alert')).toHaveTextContent(/Błąd serwera/)
  })

  it('clears a stale add error after a successful remove', async () => {
    fake.pantry = [{ ingredient_id: 2, name: 'Mąka', added_at: NOW }]
    fake.failAdd = 500
    renderPage()
    const user = userEvent.setup()

    await user.type(await screen.findByLabelText('Dodaj produkt'), 'mle')
    await user.click(await screen.findByRole('button', { name: 'Mleko' }))
    expect(await screen.findByRole('alert')).toHaveTextContent(/Błąd serwera/)

    await user.click(screen.getByRole('button', { name: 'Usuń Mąka' }))
    expect(await screen.findByText(/Lodówka jest pusta/)).toBeInTheDocument()
    expect(screen.queryByRole('alert')).not.toBeInTheDocument()
  })

  it('shows only the latest error when a remove fails after a failed add', async () => {
    fake.pantry = [{ ingredient_id: 2, name: 'Mąka', added_at: NOW }]
    fake.failAdd = 500
    fake.failRemove = 404
    renderPage()
    const user = userEvent.setup()

    await user.type(await screen.findByLabelText('Dodaj produkt'), 'mle')
    await user.click(await screen.findByRole('button', { name: 'Mleko' }))
    expect(await screen.findByRole('alert')).toHaveTextContent(/Błąd serwera/)

    await user.click(screen.getByRole('button', { name: 'Usuń Mąka' }))
    const alert = await screen.findByText('Nie znaleziono.')
    expect(alert.closest('[role="alert"]')).not.toBeNull()
    expect(screen.getAllByRole('alert')).toHaveLength(1)
  })
})
