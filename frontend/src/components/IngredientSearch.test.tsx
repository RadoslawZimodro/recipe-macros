import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import type { ComponentProps } from 'react'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { IngredientSearch } from './IngredientSearch'

const item = (id: number, canonical_name: string) => ({
  id,
  canonical_name,
  kcal_per_100g: 60,
  protein_per_100g: 3,
  fat_per_100g: 3,
  carbs_per_100g: 5,
  density_g_per_ml: null,
  source: 'off',
  is_shared: true,
})

function mockSearch(items: ReturnType<typeof item>[], status = 200) {
  const body = status === 200 ? { items, total: items.length, limit: 10, offset: 0 } : { detail: 'x' }
  const fetchMock = vi.fn(
    async () =>
      new Response(JSON.stringify(body), { status, headers: { 'Content-Type': 'application/json' } }),
  )
  vi.stubGlobal('fetch', fetchMock)
  return fetchMock
}

function setup(props: Partial<ComponentProps<typeof IngredientSearch>> = {}) {
  const onPick = vi.fn()
  render(
    <QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}>
      <IngredientSearch label="Produkt" onPick={onPick} {...props} />
    </QueryClientProvider>,
  )
  return { onPick, user: userEvent.setup() }
}

afterEach(() => vi.unstubAllGlobals())

describe('IngredientSearch', () => {
  it('searches once after a pause in typing, picks a result and clears the input', async () => {
    const fetchMock = mockSearch([item(1, 'Mleko')])
    const { onPick, user } = setup()
    await user.type(screen.getByLabelText('Produkt'), 'mle')
    await user.click(await screen.findByRole('button', { name: /Mleko/ }))
    expect(fetchMock).toHaveBeenCalledTimes(1)
    expect(onPick).toHaveBeenCalledWith(expect.objectContaining({ id: 1 }))
    expect(screen.getByLabelText('Produkt')).toHaveValue('')
  })

  it('hides excluded ids and says so when nothing is left', async () => {
    mockSearch([item(1, 'Mleko')])
    const { user } = setup({ excludeIds: [1] })
    await user.type(screen.getByLabelText('Produkt'), 'mle')
    expect(await screen.findByText('Brak pasujących produktów.')).toBeInTheDocument()
  })

  it('shows an error alert when the search fails', async () => {
    mockSearch([], 500)
    const { user } = setup()
    await user.type(screen.getByLabelText('Produkt'), 'mle')
    expect(await screen.findByRole('alert')).toBeInTheDocument()
  })

  it('shows the selected product and reports typing over it', async () => {
    mockSearch([])
    const onClear = vi.fn()
    const { user } = setup({ selected: item(1, 'Mleko'), onClear })
    expect(screen.getByLabelText('Produkt')).toHaveValue('Mleko')
    await user.type(screen.getByLabelText('Produkt'), 'x')
    expect(onClear).toHaveBeenCalled()
  })
})
