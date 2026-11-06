import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter } from 'react-router-dom'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import App from '../../App'
import { AuthProvider } from '../../auth/AuthProvider'

const USER = {
  id: 1,
  email: 'ala@example.com',
  is_active: true,
  created_at: '2026-11-05T10:00:00Z',
  daily_kcal_goal: null,
  daily_protein_goal: null,
}

const SUMMARY = {
  id: 7,
  title: 'Szakszuka',
  description: null,
  image_url: null,
  servings: 2,
  tags: ['jajka'],
  prep_time_min: null,
  cook_time_min: null,
  source_url: 'https://example.com/szakszuka',
  import_method: 'jsonld',
  created_at: '2026-11-05T10:00:00Z',
  updated_at: '2026-11-05T10:00:00Z',
}

const RECIPE = {
  ...SUMMARY,
  source_nutrition: null,
  imported_at: '2026-11-05T10:00:00Z',
  steps: [{ position: 1, instruction: 'Podsmaż cebulę.' }],
  ingredients: [
    {
      id: 11,
      position: 1,
      raw_text: '2 jajka',
      quantity: 2,
      unit: 'szt',
      is_optional: false,
      grams: null,
      ingredient_id: 5,
      ingredient_name: 'jajko',
    },
  ],
}

const NUTRITION = {
  recipe_id: 7,
  servings: 2,
  is_estimate: true,
  include_optional: false,
  total: { kcal: 300, protein: 20, fat: 22, carbs: 4 },
  per_serving: { kcal: 150, protein: 10, fat: 11, carbs: 2 },
  coverage: { lines_total: 1, lines_counted: 1, percent: 100 },
  measured_share: 1,
  lines: [
    {
      line_id: 11,
      position: 1,
      raw_text: '2 jajka',
      optional: false,
      included: true,
      quantity: 2,
      unit: 'szt',
      product: { id: 5, name: 'jajko', source: 'off' },
      grams: 100,
      weight_source: 'unit_weight',
      is_estimate: false,
      nutrition: { kcal: 300, protein: 20, fat: 22, carbs: 4 },
      problem: null,
      problem_message: null,
    },
  ],
  missing: [],
}

function reply(status: number, body?: unknown): Response {
  return new Response(body === undefined ? null : JSON.stringify(body), {
    status,
    headers: { 'Content-Type': 'application/json' },
  })
}

const fetchMock = vi.fn<typeof fetch>()

type Handler = (init?: RequestInit) => Response
function serve(routes: Record<string, Handler>) {
  fetchMock.mockImplementation(async (input, init) => {
    const path = String(input).replace(/^https?:\/\/[^/]+/, '')
    const method = init?.method ?? 'GET'
    const handler = routes[`${method} ${path}`]
    if (!handler) throw new Error(`unexpected request ${method} ${path}`)
    return handler(init)
  })
}

const AUTH = { 'GET /auth/me': () => reply(200, USER) }

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

beforeEach(() => {
  vi.stubGlobal('fetch', fetchMock)
})
afterEach(() => {
  fetchMock.mockReset()
  vi.unstubAllGlobals()
})

describe('recipe list', () => {
  it('lists recipes and searches by title', async () => {
    const page = (items: unknown[]) => reply(200, { items, total: items.length, limit: 20, offset: 0 })
    serve({
      ...AUTH,
      'GET /recipes?limit=20&offset=0': () => page([SUMMARY]),
      'GET /recipes?limit=20&offset=0&q=zupa': () => page([]),
    })
    renderAt('/recipes')

    expect(await screen.findByRole('link', { name: 'Szakszuka' })).toHaveAttribute('href', '/recipes/7')

    await userEvent.type(screen.getByLabelText('Szukaj przepisu'), 'zupa')
    await userEvent.click(screen.getByRole('button', { name: 'Szukaj' }))

    expect(await screen.findByText('Brak przepisów pasujących do wyszukiwania.')).toBeInTheDocument()
  })

  it('shows the empty state and the error state', async () => {
    serve({
      ...AUTH,
      'GET /recipes?limit=20&offset=0': () => reply(200, { items: [], total: 0, limit: 20, offset: 0 }),
    })
    const { unmount } = renderAt('/recipes')
    expect(await screen.findByText(/Nie masz jeszcze żadnych przepisów/)).toBeInTheDocument()
    unmount()

    serve({ ...AUTH, 'GET /recipes?limit=20&offset=0': () => reply(500, { detail: 'boom' }) })
    renderAt('/recipes')
    expect(await screen.findByRole('alert')).toHaveTextContent('Błąd serwera')
  })

  it('pages through results', async () => {
    const seen: string[] = []
    serve({
      ...AUTH,
      'GET /recipes?limit=20&offset=0': () => {
        seen.push('first')
        return reply(200, { items: [SUMMARY], total: 25, limit: 20, offset: 0 })
      },
      'GET /recipes?limit=20&offset=20': () => {
        seen.push('second')
        return reply(200, { items: [{ ...SUMMARY, id: 8, title: 'Zupa' }], total: 25, limit: 20, offset: 20 })
      },
    })
    renderAt('/recipes')
    await screen.findByText('Szakszuka')
    await userEvent.click(screen.getByRole('button', { name: 'Następna' }))
    expect(await screen.findByText('Zupa')).toBeInTheDocument()
    expect(seen).toEqual(['first', 'second'])
  })
})

describe('recipe import', () => {
  it('shows a loading state, then opens the imported recipe', async () => {
    let finish: (r: Response) => void = () => {}
    serve({
      ...AUTH,
      'POST /recipes/import': () => {
        throw new Error('replaced below')
      },
    })
    fetchMock.mockImplementation(async (input, init) => {
      const path = String(input).replace(/^https?:\/\/[^/]+/, '')
      if (path === '/auth/me') return reply(200, USER)
      if (path === '/recipes/import') {
        expect(JSON.parse(String(init?.body))).toEqual({ url: 'https://example.com/szakszuka', refresh: false })
        return new Promise<Response>((resolve) => (finish = resolve))
      }
      if (path === '/recipes/7') return reply(200, RECIPE)
      if (path === '/recipes/7/nutrition') return reply(200, NUTRITION)
      if (path.startsWith('/recipes?')) return reply(200, { items: [], total: 0, limit: 20, offset: 0 })
      throw new Error(`unexpected ${path}`)
    })
    renderAt('/recipes/import')

    await userEvent.type(
      await screen.findByLabelText('Adres strony z przepisem'),
      'https://example.com/szakszuka',
    )
    await userEvent.click(screen.getByRole('button', { name: 'Importuj' }))

    expect(await screen.findByRole('status')).toHaveTextContent('kilkadziesiąt sekund')
    expect(screen.getByRole('button', { name: 'Importowanie…' })).toBeDisabled()

    finish(reply(201, { status: 'created', recipe: RECIPE, ai_used: false, notice: null }))
    expect(await screen.findByRole('heading', { name: 'Szakszuka' })).toBeInTheDocument()
  })

  it('explains an unsupported social link', async () => {
    serve({
      ...AUTH,
      'POST /recipes/import': () =>
        reply(422, { detail: { code: 'unsupported_site', message: 'Instagram, TikTok ...' } }),
    })
    renderAt('/recipes/import')

    await userEvent.type(await screen.findByLabelText('Adres strony z przepisem'), 'https://instagram.com/p/1')
    await userEvent.click(screen.getByRole('button', { name: 'Importuj' }))

    expect(await screen.findByRole('alert')).toHaveTextContent('Instagrama, TikToka i YouTube')
  })

  it('explains a page without a recipe', async () => {
    serve({
      ...AUTH,
      'POST /recipes/import': () =>
        reply(422, { detail: { code: 'no_recipe_data', message: 'No recipe was found on this page.' } }),
    })
    renderAt('/recipes/import')

    await userEvent.type(await screen.findByLabelText('Adres strony z przepisem'), 'https://example.com/blog')
    await userEvent.click(screen.getByRole('button', { name: 'Importuj' }))

    expect(await screen.findByRole('alert')).toHaveTextContent('Nie znaleziono przepisu na tej stronie.')
  })
})

describe('recipe details', () => {
  it('shows steps, ingredients, the estimate label, macros and the source link', async () => {
    serve({
      ...AUTH,
      'GET /recipes/7': () => reply(200, RECIPE),
      'GET /recipes/7/nutrition': () => reply(200, NUTRITION),
    })
    renderAt('/recipes/7')

    expect(await screen.findByRole('heading', { name: 'Szakszuka' })).toBeInTheDocument()
    expect(screen.getByText('Podsmaż cebulę.')).toBeInTheDocument()
    expect(screen.getByRole('link', { name: 'Zobacz oryginalny przepis' })).toHaveAttribute(
      'href',
      'https://example.com/szakszuka',
    )
    expect(await screen.findByText('~300 kcal')).toBeInTheDocument()
    expect(screen.getByText('~150 kcal')).toBeInTheDocument()
    expect(screen.getByText('szacunek')).toBeInTheDocument()
    expect(screen.getByText(/Źródła: Open Food Facts/)).toBeInTheDocument()
    expect(screen.getByText(/~100 g · jajko \(Open Food Facts\)/)).toBeInTheDocument()
  })

  it('shows an error when the recipe does not exist', async () => {
    serve({ ...AUTH, 'GET /recipes/9': () => reply(404, { detail: 'Recipe not found' }) })
    renderAt('/recipes/9')
    expect(await screen.findByRole('alert')).toHaveTextContent('Nie znaleziono takiego przepisu.')
  })

  it('corrects the weight of an ingredient line and reloads the macros', async () => {
    let patched: unknown = null
    let nutritionCalls = 0
    serve({
      ...AUTH,
      'GET /recipes/7': () => reply(200, RECIPE),
      'GET /recipes/7/nutrition': () => {
        nutritionCalls += 1
        return reply(200, nutritionCalls === 1 ? NUTRITION : { ...NUTRITION, total: { ...NUTRITION.total, kcal: 450 } })
      },
      'PATCH /recipes/7/ingredients/11': (init) => {
        patched = JSON.parse(String(init?.body))
        return reply(200, { ...RECIPE, ingredients: [{ ...RECIPE.ingredients[0], grams: 150 }] })
      },
    })
    renderAt('/recipes/7')

    await userEvent.click(await screen.findByRole('button', { name: 'Popraw wagę: 2 jajka' }))
    const input = screen.getByLabelText(/Waga w gramach/)
    await userEvent.clear(input)
    await userEvent.type(input, '150')
    await userEvent.click(screen.getByRole('button', { name: 'Zapisz' }))

    await waitFor(() => expect(patched).toEqual({ grams: 150 }))
    expect(await screen.findByText('~450 kcal')).toBeInTheDocument()
    expect(screen.getByText(/\(ręcznie\)/)).toBeInTheDocument()
  })

  it('deletes a recipe after confirmation and returns to the list', async () => {
    let deleted = false
    serve({
      ...AUTH,
      'GET /recipes/7': () => reply(200, RECIPE),
      'GET /recipes/7/nutrition': () => reply(200, NUTRITION),
      'DELETE /recipes/7': () => {
        deleted = true
        return reply(204)
      },
      'GET /recipes?limit=20&offset=0': () => reply(200, { items: [], total: 0, limit: 20, offset: 0 }),
    })
    renderAt('/recipes/7')

    await userEvent.click(await screen.findByRole('button', { name: 'Usuń przepis' }))
    expect(deleted).toBe(false)
    const confirm = screen.getByText('Na pewno usunąć ten przepis?').parentElement!
    await userEvent.click(within(confirm).getByRole('button', { name: 'Tak, usuń' }))

    expect(await screen.findByRole('heading', { name: 'Przepisy' })).toBeInTheDocument()
    expect(deleted).toBe(true)
  })
})
