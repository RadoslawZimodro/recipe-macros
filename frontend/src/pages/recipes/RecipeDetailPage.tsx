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
import { Button } from '../../components/ui/Button'
import { Card } from '../../components/ui/Card'
import { Chip } from '../../components/ui/Chip'
import { Input } from '../../components/ui/Input'
import { ACCENT_LINK, MUTED_LINK } from '../../components/ui/linkClass'
import { MacroFigure } from '../../components/ui/MacroFigure'
import { Modal } from '../../components/ui/Modal'
import { Skeleton, Spinner } from '../../components/ui/Spinner'

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
    <Card className="space-y-4">
      <h3 className="font-sans text-small font-medium text-ink-2">{title}</h3>
      <MacroFigure label="Kalorie" value={macros.kcal} unit="kcal" size="lg" />
      <div className="grid grid-cols-3 gap-4">
        <MacroFigure label="Białko" value={macros.protein} unit="g" />
        <MacroFigure label="Tłuszcz" value={macros.fat} unit="g" />
        <MacroFigure label="Węglowodany" value={macros.carbs} unit="g" />
      </div>
    </Card>
  )
}

function NutritionSection({ id }: { id: number }) {
  const nutrition = useQuery({
    queryKey: ['recipes', 'nutrition', id], queryFn: () => getNutrition(id),
    retry: retryUnlessNotFound,
  })

  return (
    <section className="space-y-4" aria-labelledby="nutrition-heading">
      <h2 id="nutrition-heading" className="flex flex-wrap items-center gap-3 text-h2">
        Makroskładniki <Chip tone="estimate">szacunek</Chip>
      </h2>
      {nutrition.isPending && (
        <div className="space-y-4">
          <p className="flex items-center gap-2 text-ink-2">
            <Spinner />
            Liczenie makroskładników…
          </p>
          <div className="grid gap-4 sm:grid-cols-2">
            <Skeleton className="h-40" />
            <Skeleton className="h-40" />
          </div>
        </div>
      )}
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
        <p className="text-ink-2">
          Nie udało się policzyć makroskładników dla żadnego składnika.
        </p>
      ) : (
        <div className="grid gap-4 sm:grid-cols-2">
          <MacroBox title="Cały przepis" macros={data.total} />
          <MacroBox title={`Na porcję (porcji: ${data.servings})`} macros={data.per_serving} />
        </div>
      )}
      <p className="max-w-reading text-small text-ink-3">
        To szacunek, nie dokładny pomiar.
        {data.coverage.percent !== null &&
          ` Uwzględniono ${data.coverage.lines_counted} z ${data.coverage.lines_total} składników.`}
        {data.measured_share !== null &&
          ` ${nf.format(data.measured_share * 100)}% kalorii pochodzi z danych niebędących szacunkiem AI.`}
        {sources.length > 0 && ` Źródła: ${sources.join(', ')}.`}
      </p>
      {data.missing.length > 0 && (
        <details className="text-small text-ink-2">
          <summary className="cursor-pointer rounded-sm py-2">Nieuwzględnione składniki ({data.missing.length})</summary>
          <ul className="mt-2 list-disc space-y-1 pl-6">
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
    <li className="space-y-2 py-4">
      <div className="flex items-start justify-between gap-4">
        <div className="min-w-0 space-y-1">
          <p className="text-body font-medium text-ink">
            {line.raw_text}
            {line.is_optional && ' (opcjonalnie)'}
          </p>
          <p className="text-small tabular-nums text-ink-3">
            {quantity && `${quantity} · `}
            {gramsShown !== null ? `~${nf.format(gramsShown)} g` : 'waga nieznana'}
            {line.grams !== null && ' (ręcznie)'}
            {computed?.product && ` · ${computed.product.name} (${SOURCE_LABELS[computed.product.source]})`}
          </p>
        </div>
        {!editing && (
          <Button
            variant="link"
            className="shrink-0"
            onClick={() => setEditing(true)}
            aria-label={`Popraw wagę: ${line.raw_text}`}
          >
            Popraw wagę
          </Button>
        )}
      </div>
      {editing && (
        <form onSubmit={save} className="flex flex-wrap items-center gap-2">
          <label className="flex items-center gap-2 text-small text-ink-2">
            Waga w gramach ({line.raw_text})
            <Input
              inputMode="decimal"
              value={value}
              onChange={(e) => setValue(e.target.value)}
              className="w-24"
            />
          </label>
          <Button type="submit" loading={mutation.isPending}>
            Zapisz
          </Button>
          <Button variant="secondary" onClick={cancel}>
            Anuluj
          </Button>
          <span className="w-full text-caption text-ink-3">Puste pole przywraca wagę wyliczoną automatycznie.</span>
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

  if (recipe.isPending) {
    return (
      <div className="space-y-4">
        <p className="flex items-center gap-2 text-ink-2">
          <Spinner />
          Wczytywanie przepisu…
        </p>
        <Skeleton className="h-10 max-w-reading" />
        <Skeleton className="h-40" />
      </div>
    )
  }
  if (recipe.isError) {
    return (
      <div className="max-w-reading space-y-4">
        <ErrorMessage
          message={describeError(recipe.error, { 404: 'Nie znaleziono takiego przepisu.' })}
        />
        <Link to="/recipes" className={`text-small ${MUTED_LINK}`}>
          Wróć do listy
        </Link>
      </div>
    )
  }

  const data = recipe.data
  const computedByLine = new Map((nutrition.data?.lines ?? []).map((l) => [l.line_id, l]))

  return (
    <article className="space-y-12">
      <div className="space-y-4">
        <Link to="/recipes" className="inline-flex h-10 items-center text-small text-ink-2 hover:text-ink">
          ← Wróć do listy
        </Link>
        {importNotice && (
          <p role="status" className="rounded-sm border border-line bg-surface px-4 py-3 text-small text-ink-2">
            {importNotice}
          </p>
        )}
        <header className="max-w-reading space-y-2">
          <h1 className="text-h1">{data.title}</h1>
          {data.description && <p className="text-ink-2">{data.description}</p>}
          <p className="text-small text-ink-3">
            Porcje: {data.servings}
            {data.prep_time_min !== null && ` · Przygotowanie: ${data.prep_time_min} min`}
            {data.cook_time_min !== null && ` · Gotowanie: ${data.cook_time_min} min`}
          </p>
          {data.source_url && isHttpUrl(data.source_url) && (
            <p className="text-small">
              <a
                href={data.source_url}
                target="_blank"
                rel="noopener noreferrer"
                className={ACCENT_LINK}
              >
                Zobacz oryginalny przepis
              </a>
            </p>
          )}
        </header>
      </div>

      <NutritionSection id={id} />

      <section aria-labelledby="ingredients-heading" className="space-y-4">
        <h2 id="ingredients-heading" className="text-h2">
          Składniki
        </h2>
        {data.ingredients.length === 0 ? (
          <p className="text-ink-2">Ten przepis nie ma składników.</p>
        ) : (
          // A list, not a table: every line can switch into an inline weight editor.
          <ul className="divide-y divide-line-soft">
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

      <section aria-labelledby="steps-heading" className="space-y-4">
        <h2 id="steps-heading" className="text-h2">
          Kroki
        </h2>
        {data.steps.length === 0 ? (
          <p className="text-ink-2">Ten przepis nie ma kroków.</p>
        ) : (
          <ol className="max-w-reading list-decimal space-y-4 pl-6 marker:text-ink-3">
            {data.steps.map((step) => (
              <li key={step.position} className="pl-2">
                {step.instruction}
              </li>
            ))}
          </ol>
        )}
      </section>

      <section className="space-y-4 border-t border-line pt-6">
        {remove.isError && <ErrorMessage message={describeError(remove.error)} />}
        <Button variant="danger" onClick={() => setConfirming(true)}>
          Usuń przepis
        </Button>
      </section>

      <Modal open={confirming} onClose={() => setConfirming(false)} title="Usunąć przepis?">
        <p className="text-ink-2">Na pewno usunąć ten przepis?</p>
        <div className="flex justify-end gap-2">
          <Button variant="secondary" onClick={() => setConfirming(false)}>
            Anuluj
          </Button>
          <Button
            variant="danger"
            loading={remove.isPending}
            onClick={() => remove.mutate(undefined, { onError: () => setConfirming(false) })}
          >
            Tak, usuń
          </Button>
        </div>
      </Modal>
    </article>
  )
}
