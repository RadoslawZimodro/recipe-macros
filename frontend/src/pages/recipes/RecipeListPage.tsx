import { useQuery } from '@tanstack/react-query'
import { useState, type FormEvent } from 'react'
import { Link } from 'react-router-dom'
import { describeError } from '../../api/messages'
import { listRecipes, RECIPES_PAGE_SIZE } from '../../api/recipes'
import { ErrorMessage } from '../../components/Field'
import { Button } from '../../components/ui/Button'
import { CARD_LINK } from '../../components/ui/cardClass'
import { buttonClass } from '../../components/ui/buttonClass'
import { EmptyState } from '../../components/ui/EmptyState'
import { Input } from '../../components/ui/Input'
import { Spinner } from '../../components/ui/Spinner'

export function RecipeListPage() {
  const [input, setInput] = useState('')
  const [q, setQ] = useState('')
  const [offset, setOffset] = useState(0)

  const list = useQuery({
    queryKey: ['recipes', 'list', q, offset],
    queryFn: () => listRecipes(q, offset),
  })

  function search(event: FormEvent) {
    event.preventDefault()
    setOffset(0)
    setQ(input.trim())
  }

  const data = list.data
  const page = Math.floor(offset / RECIPES_PAGE_SIZE) + 1
  const pages = data ? Math.max(1, Math.ceil(data.total / RECIPES_PAGE_SIZE)) : 1

  return (
    <section className="space-y-6">
      <div className="flex flex-wrap items-center justify-between gap-4">
        <h1 className="text-h1">Przepisy</h1>
        <Link to="/recipes/import" className={buttonClass('primary')}>
          Importuj z linku
        </Link>
      </div>

      <form onSubmit={search} role="search" className="flex gap-2">
        <Input
          type="search"
          aria-label="Szukaj przepisu"
          placeholder="Szukaj po tytule"
          value={input}
          onChange={(e) => setInput(e.target.value)}
        />
        <Button type="submit" variant="secondary">
          Szukaj
        </Button>
      </form>

      {list.isPending && (
        <p className="flex items-center gap-2 text-ink-2">
          <Spinner />
          Wczytywanie przepisów…
        </p>
      )}
      {list.isError && <ErrorMessage message={describeError(list.error)} />}
      {data && data.items.length === 0 && (
        <EmptyState
          title={
            q
              ? 'Brak przepisów pasujących do wyszukiwania.'
              : 'Nie masz jeszcze żadnych przepisów. Zaimportuj pierwszy z linku.'
          }
        />
      )}
      {data && data.items.length > 0 && (
        <>
          <ul className="grid gap-4 sm:grid-cols-2">
            {data.items.map((recipe) => (
              <li
                key={recipe.id}
                className={`${CARD_LINK} relative h-full space-y-2 focus-within:border-line-strong`}
              >
                {/* The title link is stretched over the whole card; the meta line stays outside the link name. */}
                <Link
                  to={`/recipes/${recipe.id}`}
                  className="block rounded-sm font-display text-h3 font-semibold text-ink after:absolute after:inset-0 after:rounded-md"
                >
                  {recipe.title}
                </Link>
                <p className="text-small text-ink-3">
                  Porcje: {recipe.servings}
                  {recipe.tags.length > 0 && ` · ${recipe.tags.join(', ')}`}
                </p>
              </li>
            ))}
          </ul>
          <nav aria-label="Paginacja" className="flex items-center justify-between gap-4 text-small text-ink-2">
            <Button
              variant="secondary"
              disabled={offset === 0}
              onClick={() => setOffset(Math.max(0, offset - RECIPES_PAGE_SIZE))}
            >
              Poprzednia
            </Button>
            <span className="text-center tabular-nums">
              Strona {page} z {pages} ({data.total} przepisów)
            </span>
            <Button
              variant="secondary"
              disabled={offset + RECIPES_PAGE_SIZE >= data.total}
              onClick={() => setOffset(offset + RECIPES_PAGE_SIZE)}
            >
              Następna
            </Button>
          </nav>
        </>
      )}
    </section>
  )
}
