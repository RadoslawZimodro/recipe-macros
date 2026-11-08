import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useState, type FormEvent } from 'react'
import {
  addEntry,
  foodLogKeys,
  loggedAtFor,
} from '../../api/foodLog'
import { listRecipes } from '../../api/recipes'
import { describeError } from '../../api/messages'
import type { Ingredient } from '../../api/ingredients'
import { ErrorMessage, Field } from '../../components/Field'
import { IngredientSearch } from '../../components/IngredientSearch'
import { Button } from '../../components/ui/Button'
import { Card } from '../../components/ui/Card'
import { Select } from '../../components/ui/Input'
import { SegmentedControl } from '../../components/ui/SegmentedControl'
import { Spinner } from '../../components/ui/Spinner'

type Mode = 'recipe' | 'product'

function SubmitButton({ disabled, loading }: { disabled: boolean; loading: boolean }) {
  return (
    <Button type="submit" disabled={disabled} loading={loading}>
      Dodaj do dziennika
    </Button>
  )
}

function RecipePicker({ day }: { day: string }) {
  const queryClient = useQueryClient()
  const recipes = useQuery({ queryKey: ['recipes', 'picker'], queryFn: () => listRecipes('', 0, 100) })
  const [recipeId, setRecipeId] = useState('')
  const [servings, setServings] = useState('1')
  const add = useMutation({
    mutationFn: () =>
      addEntry({
        recipe_id: Number(recipeId),
        servings: Number(servings),
        logged_at: loggedAtFor(day),
      }),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: foodLogKeys.all }),
  })

  if (recipes.isPending) {
    return (
      <p className="flex items-center gap-2 text-ink-2">
        <Spinner />
        Ładowanie przepisów…
      </p>
    )
  }
  if (recipes.isError) return <ErrorMessage message={describeError(recipes.error)} />
  if (recipes.data.items.length === 0) {
    return <p className="text-ink-2">Nie masz jeszcze żadnych przepisów.</p>
  }

  const valid = recipeId !== '' && Number(servings) > 0
  const submit = (event: FormEvent) => {
    event.preventDefault()
    if (valid) add.mutate()
  }
  return (
    <form onSubmit={submit} className="space-y-4">
      <div className="space-y-1">
        <label htmlFor="log-recipe" className="block text-small font-medium text-ink-2">
          Przepis
        </label>
        <Select id="log-recipe" value={recipeId} onChange={(e) => setRecipeId(e.target.value)}>
          <option value="">Wybierz przepis…</option>
          {recipes.data.items.map((recipe) => (
            <option key={recipe.id} value={recipe.id}>
              {recipe.title}
            </option>
          ))}
        </Select>
        {recipes.data.total > recipes.data.items.length && (
          <p className="text-caption text-ink-3">
            Pokazano {recipes.data.items.length} z {recipes.data.total} przepisów.
          </p>
        )}
      </div>
      <Field
        id="log-servings"
        label="Liczba porcji"
        type="number"
        min="0.25"
        max="100"
        step="0.25"
        value={servings}
        onChange={(e) => setServings(e.target.value)}
      />
      <ErrorMessage message={add.isError ? describeError(add.error) : null} />
      <SubmitButton disabled={!valid} loading={add.isPending} />
    </form>
  )
}

function ProductPicker({ day }: { day: string }) {
  const queryClient = useQueryClient()
  const [chosen, setChosen] = useState<Ingredient | null>(null)
  const [grams, setGrams] = useState('100')
  const add = useMutation({
    mutationFn: (ingredient: Ingredient) =>
      addEntry({
        ingredient_id: ingredient.id,
        grams: Number(grams),
        logged_at: loggedAtFor(day),
      }),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: foodLogKeys.all }),
  })

  const valid = chosen !== null && Number(grams) > 0
  const submit = (event: FormEvent) => {
    event.preventDefault()
    if (chosen && valid) add.mutate(chosen)
  }
  return (
    <form onSubmit={submit} className="space-y-4">
      <IngredientSearch
        label="Produkt"
        showKcal
        selected={chosen}
        onPick={setChosen}
        onClear={() => setChosen(null)}
      />
      <Field
        id="log-grams"
        label="Gramy"
        type="number"
        min="1"
        max="10000"
        step="1"
        value={grams}
        onChange={(e) => setGrams(e.target.value)}
      />
      <ErrorMessage message={add.isError ? describeError(add.error) : null} />
      <SubmitButton disabled={!valid} loading={add.isPending} />
    </form>
  )
}

const PANEL_ID = 'add-entry-panel'

export function AddEntryForm({ day }: { day: string }) {
  const [mode, setMode] = useState<Mode>('recipe')
  return (
    <Card as="section" aria-label="Dodaj wpis" className="space-y-6">
      <h2 className="text-h3">Dodaj wpis</h2>
      <SegmentedControl
        mode="tabs"
        label="Rodzaj wpisu"
        panelId={PANEL_ID}
        value={mode}
        onChange={setMode}
        options={[
          { value: 'recipe', label: 'Porcja przepisu' },
          { value: 'product', label: 'Produkt w gramach' },
        ]}
      />
      <div id={PANEL_ID} role="tabpanel">
        {mode === 'recipe' ? <RecipePicker day={day} /> : <ProductPicker day={day} />}
      </div>
    </Card>
  )
}
