import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useState, type FormEvent } from 'react'
import { Link, useLocation, useNavigate, useParams } from 'react-router-dom'
import { ApiError } from '../../api/client'
import { describeError } from '../../api/messages'
import {
  deleteRecipe,
  getNutrition,
  getRecipe,
  patchIngredientGrams,
  type IngredientLine,
  type Macros,
  type Nutrition,
  type NutritionLine,
  type Source,
} from '../../api/recipes'
import { ErrorMessage } from '../../components/Field'

const SOURCE_LABELS: Record<Source, string> = {
  off: 'Open Food Facts',
  usda: 'USDA',
  manual: 'wpisane ręcznie',
  llm_estimate: 'szacunek AI',
}

// No retries on 4xx (a missing recipe stays missing); transient errors get two retries.
function retryUnlessNotFound(count: number, error: Error) {
  return !(error instanceof ApiError && error.status >= 400 && error.status < 500) && count < 2
}

function isHttpUrl(value: string) {
  try {
    const { protocol } = new URL(value)
    return protocol === 'http:' || protocol === 'https:'
  } catch {
    return false
  }
}

const nf = new Intl.NumberFormat('pl-PL', { maximumFractionDigits: 1 })

function MacroBox({ title, macros }: { title: string; macros: Macros }) {
  return (
    <div className="rounded-md border border-slate-200 bg-white p-3 dark:border-slate-700 dark:bg-slate-800">
      <h3 className="text-sm font-medium">{title}</h3>
      <p className="text-lg font-semibold">~{nf.format(macros.kcal)} kcal</p>
      <p className="text-sm text-slate-600 dark:text-slate-300">
        Białko {nf.format(macros.protein)} g · Tłuszcz {nf.format(macros.fat)} g · Węglowodany{' '}
        {nf.format(macros.carbs)} g
      </p>
    </div>
  )
}

function NutritionSection({ id }: { id: number }) {
  const nutrition = useQuery({
    queryKey: ['recipes', 'nutrition', id], queryFn: () => getNutrition(id),
    retry: retryUnlessNotFound,
  })

  return (
    <section className="space-y-3" aria-labelledby="nutrition-heading">
      <h2 id="nutrition-heading" className="text-xl font-semibold">
        Makroskładniki{' '}
        <span className="rounded bg-amber-100 px-2 py-0.5 text-xs font-medium text-amber-900 dark:bg-amber-900 dark:text-amber-100">
          szacunek
        </span>
      </h2>
      {nutrition.isPending && <p>Liczenie makroskładników…</p>}
      {nutrition.isError && <ErrorMessage message={describeError(nutrition.error)} />}
      {nutrition.data && <NutritionBody data={nutrition.data} />}
    </section>
  )
}

function NutritionBody({ data }: { data: Nutrition }) {
  const sources = [
    ...new Set(
      data.lines
        .filter((line) => line.included && line.product)
        .map((line) => SOURCE_LABELS[line.product!.source]),
    ),
  ]
  return (
    <>
      {data.coverage.lines_counted === 0 ? (
        <p className="text-slate-600 dark:text-slate-300">
          Nie udało się policzyć makroskładników dla żadnego składnika.
        </p>
      ) : (
        <div className="grid gap-3 sm:grid-cols-2">
          <MacroBox title="Cały przepis" macros={data.total} />
          <MacroBox title={`Na porcję (porcji: ${data.servings})`} macros={data.per_serving} />
        </div>
      )}
      <p className="text-sm text-slate-600 dark:text-slate-300">
        To szacunek, nie dokładny pomiar.
        {data.coverage.percent !== null &&
          ` Uwzględniono ${data.coverage.lines_counted} z ${data.coverage.lines_total} składników.`}
        {data.measured_share !== null &&
          ` ${nf.format(data.measured_share * 100)}% kalorii pochodzi z danych niebędących szacunkiem AI.`}
        {sources.length > 0 && ` Źródła: ${sources.join(', ')}.`}
      </p>
      {data.missing.length > 0 && (
        <details className="text-sm">
          <summary className="cursor-pointer">Nieuwzględnione składniki ({data.missing.length})</summary>
          <ul className="mt-1 list-disc pl-5">
            {data.missing.map((m) => (
              <li key={m.line_id}>
                {m.raw_text}: {m.message}
              </li>
            ))}
          </ul>
        </details>
      )}
    </>
  )
}

function IngredientRow({
  recipeId,
  line,
  computed,
}: {
  recipeId: number
  line: IngredientLine
  computed: NutritionLine | undefined
}) {
  const queryClient = useQueryClient()
  const [editing, setEditing] = useState(false)
  const initialValue = line.grams === null ? '' : String(line.grams)
  const [value, setValue] = useState(initialValue)
  const [inputError, setInputError] = useState<string | null>(null)

  const mutation = useMutation({
    mutationFn: (grams: number | null) => patchIngredientGrams(recipeId, line.id, grams),
    onSuccess: async (recipe) => {
      queryClient.setQueryData(['recipes', recipeId], recipe)
      await queryClient.invalidateQueries({ queryKey: ['recipes', 'nutrition', recipeId] })
      setInputError(null)
      setEditing(false)
    },
  })

  function cancel() {
    setValue(initialValue)
    setInputError(null)
    setEditing(false)
  }

  function save(event: FormEvent) {
    event.preventDefault()
    const text = value.trim().replace(',', '.')
    const grams = text === '' ? null : Number(text)
    if (grams !== null && (!Number.isFinite(grams) || grams < 0)) {
      setInputError('Podaj liczbę gramów większą lub równą 0.')
      return
    }
    setInputError(null)
    mutation.mutate(grams)
  }

  const gramsShown = line.grams ?? computed?.grams ?? null
  const quantity = [line.quantity, line.unit].filter((part) => part !== null).join(' ')

  return (
    <li className="space-y-1 py-2">
      <div className="flex flex-wrap items-baseline justify-between gap-2">
        <span>
          {line.raw_text}
          {line.is_optional && ' (opcjonalnie)'}
        </span>
        <span className="text-sm text-slate-600 dark:text-slate-300">
          {quantity && `${quantity} · `}
          {gramsShown !== null ? `~${nf.format(gramsShown)} g` : 'waga nieznana'}
          {line.grams !== null && ' (ręcznie)'}
          {computed?.product && ` · ${computed.product.name} (${SOURCE_LABELS[computed.product.source]})`}
        </span>
      </div>
      {editing ? (
        <form onSubmit={save} className="flex flex-wrap items-center gap-2">
          <label className="text-sm">
            Waga w gramach ({line.raw_text})
            <input
              inputMode="decimal"
              value={value}
              onChange={(e) => setValue(e.target.value)}
              className="ml-2 w-24 rounded-md border border-slate-300 bg-white px-2 py-1 dark:border-slate-600 dark:bg-slate-900"
            />
          </label>
          <button
            type="submit"
            disabled={mutation.isPending}
            className="rounded-md bg-emerald-600 px-3 py-1 text-sm text-white hover:bg-emerald-700 disabled:opacity-60"
          >
            Zapisz
          </button>
          <button
            type="button"
            onClick={cancel}
            className="rounded-md border border-slate-300 px-3 py-1 text-sm dark:border-slate-600"
          >
            Anuluj
          </button>
          <span className="text-xs text-slate-500">Puste pole przywraca wagę wyliczoną automatycznie.</span>
          {inputError && (
            <div className="w-full">
              <ErrorMessage message={inputError} />
            </div>
          )}
          {mutation.isError && (
            <div className="w-full">
              <ErrorMessage message={describeError(mutation.error)} />
            </div>
          )}
        </form>
      ) : (
        <button
          type="button"
          onClick={() => setEditing(true)}
          aria-label={`Popraw wagę: ${line.raw_text}`}
          className="text-sm text-emerald-700 hover:underline dark:text-emerald-400"
        >
          Popraw wagę
        </button>
      )}
    </li>
  )
}

export function RecipeDetailPage() {
  const params = useParams()
  const id = Number(params.id)
  const navigate = useNavigate()
  const queryClient = useQueryClient()
  const location = useLocation()
  const importNotice = (location.state as { notice?: string | null } | null)?.notice ?? null
  const [confirming, setConfirming] = useState(false)

  const recipe = useQuery({
    queryKey: ['recipes', id],
    queryFn: () => getRecipe(id),
    enabled: Number.isInteger(id) && id > 0,
    retry: retryUnlessNotFound,
  })
  // Shares the cache entry with NutritionSection; used here to show the computed weights.
  const nutrition = useQuery({
    queryKey: ['recipes', 'nutrition', id],
    queryFn: () => getNutrition(id),
    enabled: recipe.isSuccess,
    retry: retryUnlessNotFound,
  })

  const remove = useMutation({
    mutationFn: () => deleteRecipe(id),
    onSuccess: async () => {
      void navigate('/recipes')
      // Mark stale without refetching: the deleted recipe's mounted queries would 404.
      await queryClient.invalidateQueries({ queryKey: ['recipes'], refetchType: 'none' })
    },
  })

  if (recipe.isPending) return <p>Wczytywanie przepisu…</p>
  if (recipe.isError) {
    return (
      <div className="space-y-3">
        <ErrorMessage
          message={describeError(recipe.error, { 404: 'Nie znaleziono takiego przepisu.' })}
        />
        <Link to="/recipes" className="text-sm hover:underline">
          Wróć do listy
        </Link>
      </div>
    )
  }

  const data = recipe.data
  const computedByLine = new Map((nutrition.data?.lines ?? []).map((l) => [l.line_id, l]))

  return (
    <article className="space-y-6">
      <Link to="/recipes" className="text-sm hover:underline">
        ← Wróć do listy
      </Link>
      {importNotice && (
        <p role="status" className="rounded-md bg-sky-50 px-3 py-2 text-sm dark:bg-sky-950">
          {importNotice}
        </p>
      )}
      <header className="space-y-2">
        <h1 className="text-2xl font-semibold">{data.title}</h1>
        {data.description && <p className="text-slate-600 dark:text-slate-300">{data.description}</p>}
        <p className="text-sm text-slate-600 dark:text-slate-300">
          Porcje: {data.servings}
          {data.prep_time_min !== null && ` · Przygotowanie: ${data.prep_time_min} min`}
          {data.cook_time_min !== null && ` · Gotowanie: ${data.cook_time_min} min`}
        </p>
        {data.source_url && isHttpUrl(data.source_url) && (
          <p className="text-sm">
            <a
              href={data.source_url}
              target="_blank"
              rel="noopener noreferrer"
              className="text-emerald-700 hover:underline dark:text-emerald-400"
            >
              Zobacz oryginalny przepis
            </a>
          </p>
        )}
      </header>

      <NutritionSection id={id} />

      <section aria-labelledby="ingredients-heading" className="space-y-2">
        <h2 id="ingredients-heading" className="text-xl font-semibold">
          Składniki
        </h2>
        {data.ingredients.length === 0 ? (
          <p className="text-slate-600 dark:text-slate-300">Ten przepis nie ma składników.</p>
        ) : (
          <ul className="divide-y divide-slate-200 dark:divide-slate-700">
            {data.ingredients.map((line) => (
              <IngredientRow
                key={line.id}
                recipeId={id}
                line={line}
                computed={computedByLine.get(line.id)}
              />
            ))}
          </ul>
        )}
      </section>

      <section aria-labelledby="steps-heading" className="space-y-2">
        <h2 id="steps-heading" className="text-xl font-semibold">
          Kroki
        </h2>
        {data.steps.length === 0 ? (
          <p className="text-slate-600 dark:text-slate-300">Ten przepis nie ma kroków.</p>
        ) : (
          <ol className="list-decimal space-y-2 pl-5">
            {data.steps.map((step) => (
              <li key={step.position}>{step.instruction}</li>
            ))}
          </ol>
        )}
      </section>

      <section className="space-y-2 border-t border-slate-200 pt-4 dark:border-slate-700">
        {remove.isError && <ErrorMessage message={describeError(remove.error)} />}
        {confirming ? (
          <div className="flex items-center gap-2">
            <span className="text-sm">Na pewno usunąć ten przepis?</span>
            <button
              type="button"
              disabled={remove.isPending}
              onClick={() => remove.mutate()}
              className="rounded-md bg-red-600 px-3 py-1.5 text-sm text-white hover:bg-red-700 disabled:opacity-60"
            >
              Tak, usuń
            </button>
            <button
              type="button"
              onClick={() => setConfirming(false)}
              className="rounded-md border border-slate-300 px-3 py-1.5 text-sm dark:border-slate-600"
            >
              Anuluj
            </button>
          </div>
        ) : (
          <button
            type="button"
            onClick={() => setConfirming(true)}
            className="rounded-md border border-red-300 px-3 py-1.5 text-sm text-red-700 hover:bg-red-50 dark:border-red-800 dark:text-red-300 dark:hover:bg-red-950"
          >
            Usuń przepis
          </button>
        )}
      </section>
    </article>
  )
}
