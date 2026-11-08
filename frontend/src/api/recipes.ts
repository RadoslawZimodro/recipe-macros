// Recipe API: types mirror backend/app/schemas/recipe.py and nutrition.py.
import { api } from './client'

export interface RecipeStep {
  position: number
  instruction: string
  image_url: string | null // relative to the API, e.g. /recipes/12/steps/3/image
}

export interface IngredientLine {
  id: number
  position: number
  raw_text: string
  quantity: number | null
  unit: string | null
  is_optional: boolean
  grams: number | null // the manually entered weight, if any
  ingredient_id: number | null
  ingredient_name: string | null
}

export interface RecipeSummary {
  id: number
  title: string
  description: string | null
  image_url: string | null
  servings: number
  tags: string[]
  prep_time_min: number | null
  cook_time_min: number | null
  source_url: string | null
  import_method: string
  created_at: string
  updated_at: string
}

export interface Recipe extends RecipeSummary {
  source_nutrition: Record<string, unknown> | null
  imported_at: string | null
  steps: RecipeStep[]
  ingredients: IngredientLine[]
}

export interface RecipeList {
  items: RecipeSummary[]
  total: number
  limit: number
  offset: number
}

export interface RecipeImport {
  status: 'created' | 'existing' | 'refreshed'
  recipe: Recipe
  ai_used: boolean
  notice: string | null
}

export type Source = 'off' | 'usda' | 'manual' | 'llm_estimate'

export interface Macros {
  kcal: number
  protein: number
  fat: number
  carbs: number
}

export interface NutritionLine {
  line_id: number
  position: number
  raw_text: string
  optional: boolean
  included: boolean
  quantity: number | null
  unit: string | null
  product: { id: number; name: string; source: Source } | null
  grams: number | null
  weight_source: string | null
  is_estimate: boolean | null
  nutrition: Macros | null
  problem: string | null
  problem_message: string | null
}

export interface Nutrition {
  recipe_id: number
  servings: number
  is_estimate: true
  include_optional: boolean
  total: Macros
  per_serving: Macros
  coverage: { lines_total: number; lines_counted: number; percent: number | null }
  measured_share: number | null
  lines: NutritionLine[]
  missing: { line_id: number; raw_text: string; problem: string; message: string }[]
}

export const RECIPES_PAGE_SIZE = 20

export function listRecipes(
  q: string,
  offset: number,
  limit = RECIPES_PAGE_SIZE,
): Promise<RecipeList> {
  const params = new URLSearchParams({ limit: String(limit), offset: String(offset) })
  if (q.trim()) params.set('q', q.trim())
  return api.get<RecipeList>(`/recipes?${params}`)
}

export const getRecipe = (id: number) => api.get<Recipe>(`/recipes/${id}`)
export const getNutrition = (id: number) => api.get<Nutrition>(`/recipes/${id}/nutrition`)
export const importRecipe = (url: string, refresh = false) =>
  api.post<RecipeImport>('/recipes/import', { url, refresh })
export const patchIngredientGrams = (id: number, lineId: number, grams: number | null) =>
  api.patch<Recipe>(`/recipes/${id}/ingredients/${lineId}`, { grams })
export const deleteRecipe = (id: number) => api.delete<void>(`/recipes/${id}`)
