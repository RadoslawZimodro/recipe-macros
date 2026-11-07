import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import type { ReactNode } from 'react'
import { MemoryRouter } from 'react-router-dom'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { addDays, todayInPoland } from '../../api/foodLog'
import type { DayOut, DayTotals, DaysOut, FoodLogEntry } from '../../api/foodLog'
import { AuthProvider } from '../../auth/AuthProvider'
import { LogPage } from './LogPage'

// Recharts needs real layout sizes, which jsdom lacks: the stub just exposes the data it got.
vi.mock('recharts', () => {
  const Nothing = () => null
  return {
    ResponsiveContainer: ({ children }: { children: ReactNode }) => <div>{children}</div>,
    BarChart: ({ data }: { data: unknown[] }) => (
      <div data-testid="chart" data-points={data.length} data-json={JSON.stringify(data)} />
    ),
    Bar: Nothing,
    CartesianGrid: Nothing,
    ReferenceLine: Nothing,
    Tooltip: Nothing,
    XAxis: Nothing,
    YAxis: Nothing,
  }
})

const TODAY = todayInPoland()

const USER = {
  id: 1,
  email: 'ala@example.com',
  is_active: true,
  created_at: '2026-11-05T10:00:00Z',
  daily_kcal_goal: 2000,
  daily_protein_goal: null as number | null,
}

const macros = (kcal: number) => ({ kcal, protein: 10, fat: 5, carbs: 20 })

function totals(day: string, entries: number, kcal: number, goal: number | null): DayTotals {
  return {
    day,
    entries,
    total: macros(kcal),
    is_estimate: false,
    complete: true,
    kcal: goal ? { goal, eaten: kcal, remaining: goal - kcal, percent: (kcal / goal) * 100 } : null,
    protein: null,
  }
}

const PIZZA: FoodLogEntry = {
  id: 7,
  logged_at: `${TODAY}T10:00:00+01:00`,
  kind: 'recipe',
  name: 'Pizza',
  recipe_id: 3,
  servings: 2,
  ingredient_id: null,
  grams: null,
  nutrition: macros(800),
  is_estimate: true,
  complete: true,
  lines_total: 4,
  lines_counted: 4,
}

function reply(status: number, body?: unknown): Response {
  return new Response(body === undefined ? null : JSON.stringify(body), {
    status,
    headers: { 'Content-Type': 'application/json' },
  })
}

const fetchMock = vi.fn<typeof fetch>()
let entries: FoodLogEntry[]
let user: typeof USER
let recipesTotal: number

function dayFor(day: string): DayOut {
  const list = day === TODAY ? entries : []
  const kcal = list.reduce((sum, e) => sum + (e.nutrition?.kcal ?? 0), 0)
  return {
    timezone: 'Europe/Warsaw',
    totals: totals(day, list.length, kcal, user.daily_kcal_goal),
    entries: list,
  }
}

// Routes the mocked API by "METHOD path?query", mirroring backend/app/schemas.
function serve() {
  fetchMock.mockImplementation(async (input, init) => {
    const url = new URL(String(input))
    const method = init?.method ?? 'GET'
    const body = init?.body ? JSON.parse(String(init.body)) : undefined
    const key = `${method} ${url.pathname}`
    if (key === 'GET /auth/me') return reply(200, user)
    if (key === 'GET /food-log') return reply(200, dayFor(url.searchParams.get('date') ?? TODAY))
    if (key === 'GET /food-log/days') {
      const from = url.searchParams.get('from')!
      const to = url.searchParams.get('to')!
      const days: DayTotals[] = []
      for (let d = from; d <= to; d = addDays(d, 1)) {
        days.push(d === TODAY ? dayFor(d).totals : totals(d, 0, 0, null))
      }
      return reply(200, { timezone: 'Europe/Warsaw', days } satisfies DaysOut)
    }
    if (key === 'GET /recipes') {
      return reply(200, {
        items: [{ id: 3, title: 'Pizza', servings: 4, tags: [], source_url: null }],
        total: recipesTotal,
        limit: 100,
        offset: 0,
      })
    }
    if (key === 'GET /ingredients') {
      return reply(200, {
        items: [
          {
            id: 11,
            canonical_name: 'Ryż biały',
            kcal_per_100g: 350,
            protein_per_100g: 7,
            fat_per_100g: 1,
            carbs_per_100g: 78,
            density_g_per_ml: null,
            source: 'off',
            is_shared: true,
          },
        ],
        total: 1,
        limit: 10,
        offset: 0,
      })
    }
    if (key === 'POST /food-log') {
      const entry: FoodLogEntry = {
        ...PIZZA,
        id: 100,
        kind: body.recipe_id ? 'recipe' : 'product',
        name: body.recipe_id ? 'Pizza' : 'Ryż biały',
        recipe_id: body.recipe_id ?? null,
        servings: body.servings ?? null,
        ingredient_id: body.ingredient_id ?? null,
        grams: body.grams ?? null,
        nutrition: macros(body.grams ? 350 : 400),
      }
      entries = [...entries, entry]
      return reply(201, entry)
    }
    if (method === 'DELETE' && url.pathname.startsWith('/food-log/')) {
      const id = Number(url.pathname.split('/').pop())
      entries = entries.filter((e) => e.id !== id)
      return reply(204)
    }
    if (key === 'PATCH /auth/me/goals') {
      user = { ...user, ...body }
      return reply(200, user)
    }
    throw new Error(`unexpected request ${key}`)
  })
}

const calls = (method: string, path: string) =>
  fetchMock.mock.calls.filter(
    ([input, init]) =>
      (init?.method ?? 'GET') === method && new URL(String(input)).pathname === path,
  )

function renderPage() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return render(
    <QueryClientProvider client={client}>
      <MemoryRouter>
        <AuthProvider>
          <LogPage />
        </AuthProvider>
      </MemoryRouter>
    </QueryClientProvider>,
  )
}

beforeEach(() => {
  vi.stubGlobal('fetch', fetchMock)
  entries = [PIZZA]
  recipesTotal = 1
  user = { ...USER }
  serve()
})

afterEach(() => {
  fetchMock.mockReset()
  vi.unstubAllGlobals()
})

describe('LogPage', () => {
  it('shows entries with a recipe link and the day total against the goal', async () => {
    renderPage()
    const link = await screen.findByRole('link', { name: 'Pizza' })
    expect(link).toHaveAttribute('href', '/recipes/3')
    const summary = screen.getByRole('region', { name: 'Suma dnia' })
    expect(within(summary).getByText('800 / 2000 kcal')).toBeInTheDocument()
    expect(within(summary).getByText(/Zostało 1200 kcal/)).toBeInTheDocument()
    expect(within(summary).getByText('Cel nie jest ustawiony')).toBeInTheDocument()
    expect(screen.getByText(/szacunek\)/)).toBeInTheDocument()
  })

  it('shows an empty state and an error state', async () => {
    entries = []
    renderPage()
    expect(await screen.findByText('Nic jeszcze nie zapisano tego dnia.')).toBeInTheDocument()
    expect(await screen.findByText('Brak wpisów w tym okresie.')).toBeInTheDocument()
  })

  it('shows an error when the day cannot be loaded', async () => {
    fetchMock.mockImplementation(async (input) => {
      const path = new URL(String(input)).pathname
      if (path === '/auth/me') return reply(200, user)
      return reply(500, { detail: 'boom' })
    })
    renderPage()
    expect((await screen.findAllByRole('alert'))[0]).toHaveTextContent('Błąd serwera')
  })

  it('loads another day when the date changes', async () => {
    renderPage()
    await screen.findByRole('link', { name: 'Pizza' })
    const other = addDays(TODAY, -3)
    fireEvent.change(screen.getByLabelText('Data'), { target: { value: other } })
    expect(await screen.findByText('Nic jeszcze nie zapisano tego dnia.')).toBeInTheDocument()
    expect(
      fetchMock.mock.calls.some(([input]) => String(input).includes(`/food-log?date=${other}`)),
    ).toBe(true)
  })

  it('adds servings of a recipe', async () => {
    entries = []
    const u = userEvent.setup()
    renderPage()
    await screen.findByText('Nic jeszcze nie zapisano tego dnia.')
    await u.selectOptions(await screen.findByLabelText('Przepis'), '3')
    await u.clear(screen.getByLabelText('Liczba porcji'))
    await u.type(screen.getByLabelText('Liczba porcji'), '1.5')
    await u.click(screen.getByRole('button', { name: 'Dodaj do dziennika' }))

    await waitFor(() => expect(calls('POST', '/food-log')).toHaveLength(1))
    expect(JSON.parse(String(calls('POST', '/food-log')[0][1]?.body))).toEqual({
      recipe_id: 3,
      servings: 1.5,
    })
    expect(await screen.findByRole('link', { name: 'Pizza' })).toBeInTheDocument()
  })

  it('hints when the recipe picker shows only part of the recipes', async () => {
    recipesTotal = 120
    renderPage()
    expect(await screen.findByText('Pokazano 1 z 120 przepisów.')).toBeInTheDocument()
  })

  it('does not show the hint when all recipes are listed', async () => {
    renderPage()
    await screen.findByLabelText('Przepis')
    expect(screen.queryByText(/Pokazano/)).not.toBeInTheDocument()
  })

  it('adds grams of a product found by search', async () => {
    entries = []
    const u = userEvent.setup()
    renderPage()
    await screen.findByText('Nic jeszcze nie zapisano tego dnia.')
    await u.click(screen.getByRole('tab', { name: 'Produkt w gramach' }))
    await u.type(screen.getByLabelText('Produkt'), 'ryż')
    await u.click(await screen.findByRole('button', { name: /Ryż biały/ }))
    await u.clear(screen.getByLabelText('Gramy'))
    await u.type(screen.getByLabelText('Gramy'), '150')
    await u.click(screen.getByRole('button', { name: 'Dodaj do dziennika' }))

    await waitFor(() => expect(calls('POST', '/food-log')).toHaveLength(1))
    expect(JSON.parse(String(calls('POST', '/food-log')[0][1]?.body))).toEqual({
      ingredient_id: 11,
      grams: 150,
    })
    expect(await screen.findByText('150 g')).toBeInTheDocument()
  })

  it('sends logged_at with a time zone when adding to a past day', async () => {
    const u = userEvent.setup()
    renderPage()
    await screen.findByRole('link', { name: 'Pizza' })
    const other = addDays(TODAY, -1)
    fireEvent.change(screen.getByLabelText('Data'), { target: { value: other } })
    await u.selectOptions(await screen.findByLabelText('Przepis'), '3')
    await u.click(screen.getByRole('button', { name: 'Dodaj do dziennika' }))
    await waitFor(() => expect(calls('POST', '/food-log')).toHaveLength(1))
    expect(JSON.parse(String(calls('POST', '/food-log')[0][1]?.body)).logged_at).toBe(
      `${other}T12:00:00+01:00`,
    )
  })

  it('deletes an entry', async () => {
    const u = userEvent.setup()
    renderPage()
    await u.click(await screen.findByRole('button', { name: 'Usuń wpis: Pizza' }))
    await waitFor(() => expect(calls('DELETE', '/food-log/7')).toHaveLength(1))
    expect(await screen.findByText('Nic jeszcze nie zapisano tego dnia.')).toBeInTheDocument()
  })

  it('saves goals and clears an empty one', async () => {
    const u = userEvent.setup()
    renderPage()
    // The form remounts once the user has loaded, so look the field up again.
    await waitFor(() => expect(screen.getByLabelText('Cel kalorii (kcal)')).toHaveValue(2000))
    const kcal = screen.getByLabelText('Cel kalorii (kcal)')
    await u.clear(kcal)
    await u.type(screen.getByLabelText('Cel białka (g)'), '120')
    await u.click(screen.getByRole('button', { name: 'Zapisz cele' }))

    await waitFor(() => expect(calls('PATCH', '/auth/me/goals')).toHaveLength(1))
    expect(JSON.parse(String(calls('PATCH', '/auth/me/goals')[0][1]?.body))).toEqual({
      daily_kcal_goal: null,
      daily_protein_goal: 120,
    })
    expect(await screen.findByText('Zapisano cele.')).toBeInTheDocument()
  })

  it('switches the chart between 7 and 30 days', async () => {
    const u = userEvent.setup()
    renderPage()
    const chart = await screen.findByTestId('chart')
    expect(chart).toHaveAttribute('data-points', '7')
    expect(chart.getAttribute('data-json')).toContain('"kcal":800')

    await u.click(screen.getByRole('button', { name: '30 dni' }))
    await waitFor(() => expect(screen.getByTestId('chart')).toHaveAttribute('data-points', '30'))
    const daysCall = calls('GET', '/food-log/days').at(-1)!
    const url = new URL(String(daysCall[0]))
    expect(url.searchParams.get('from')).toBe(addDays(TODAY, -29))
    expect(url.searchParams.get('to')).toBe(TODAY)
  })
})
