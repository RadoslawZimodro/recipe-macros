import { useQuery } from '@tanstack/react-query'
import { useState, type FormEvent } from 'react'
import { Link } from 'react-router-dom'
import { describeError } from '../../api/messages'
import { listRecipes, RECIPES_PAGE_SIZE } from '../../api/recipes'
import { ErrorMessage } from '../../components/Field'

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
    <section className="space-y-4">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <h1 className="text-2xl font-semibold">Przepisy</h1>
        <Link
          to="/recipes/import"
          className="rounded-md bg-emerald-600 px-4 py-2 text-sm font-medium text-white hover:bg-emerald-700"
        >
          Importuj z linku
        </Link>
      </div>

      <form onSubmit={search} role="search" className="flex gap-2">
        <input
          type="search"
          aria-label="Szukaj przepisu"
          placeholder="Szukaj po tytule"
          value={input}
          onChange={(e) => setInput(e.target.value)}
          className="block w-full rounded-md border border-slate-300 bg-white px-3 py-2 dark:border-slate-600 dark:bg-slate-900"
        />
        <button
          type="submit"
          className="rounded-md border border-slate-300 px-4 py-2 hover:bg-slate-100 dark:border-slate-600 dark:hover:bg-slate-700"
        >
          Szukaj
        </button>
      </form>

      {list.isPending && <p>Wczytywanie przepisów…</p>}
      {list.isError && <ErrorMessage message={describeError(list.error)} />}
      {data && data.items.length === 0 && (
        <p className="text-slate-600 dark:text-slate-300">
          {q
            ? 'Brak przepisów pasujących do wyszukiwania.'
            : 'Nie masz jeszcze żadnych przepisów. Zaimportuj pierwszy z linku.'}
        </p>
      )}
      {data && data.items.length > 0 && (
        <>
          <ul className="grid gap-3 sm:grid-cols-2">
            {data.items.map((recipe) => (
              <li
                key={recipe.id}
                className="rounded-md border border-slate-200 bg-white p-4 dark:border-slate-700 dark:bg-slate-800"
              >
                <Link to={`/recipes/${recipe.id}`} className="font-medium hover:underline">
                  {recipe.title}
                </Link>
                <p className="mt-1 text-sm text-slate-600 dark:text-slate-300">
                  Porcje: {recipe.servings}
                  {recipe.tags.length > 0 && ` · ${recipe.tags.join(', ')}`}
                </p>
              </li>
            ))}
          </ul>
          <nav aria-label="Paginacja" className="flex items-center justify-between text-sm">
            <button
              type="button"
              disabled={offset === 0}
              onClick={() => setOffset(Math.max(0, offset - RECIPES_PAGE_SIZE))}
              className="rounded-md border border-slate-300 px-3 py-1.5 disabled:opacity-50 dark:border-slate-600"
            >
              Poprzednia
            </button>
            <span>
              Strona {page} z {pages} ({data.total} przepisów)
            </span>
            <button
              type="button"
              disabled={offset + RECIPES_PAGE_SIZE >= data.total}
              onClick={() => setOffset(offset + RECIPES_PAGE_SIZE)}
              className="rounded-md border border-slate-300 px-3 py-1.5 disabled:opacity-50 dark:border-slate-600"
            >
              Następna
            </button>
          </nav>
        </>
      )}
    </section>
  )
}
