// Pantry API: mirrors backend/app/schemas/pantry.py and ingredient.py.

import { api } from './client'

export interface PantryItem {
  ingredient_id: number
  name: string
  added_at: string
}

export interface Staples {
  // Names every user has for free; they cannot be removed.
  defaults: string[]
  own: PantryItem[]
}

export interface MissingIngredient {
  line_id: number
  raw_text: string
  // True when the line has no linked product, so it can never be matched with the pantry.
  unlinked: boolean
}

export interface RecipeMatch {
  recipe_id: number
  title: string
  lines_total: number
  lines_have: number
  percent: number
  missing: MissingIngredient[]
}

export interface Ingredient {
  id: number
  canonical_name: string
  kcal_per_100g: number
  protein_per_100g: number
  fat_per_100g: number
  carbs_per_100g: number
  density_g_per_ml: number | null
  // off | manual | llm_estimate: where the numbers come from (they are estimates).
  source: string
  is_shared: boolean
}

export interface IngredientList {
  items: Ingredient[]
  total: number
  limit: number
  offset: number
}

export const listPantry = () => api.get<PantryItem[]>('/pantry')
export const addToPantry = (id: number) => api.put<PantryItem>(`/pantry/${id}`)
export const removeFromPantry = (id: number) => api.delete<void>(`/pantry/${id}`)
export const listMatches = () => api.get<RecipeMatch[]>('/pantry/recipes')

export const listStaples = () => api.get<Staples>('/staples')
export const addStaple = (id: number) => api.put<PantryItem>(`/staples/${id}`)
export const removeStaple = (id: number) => api.delete<void>(`/staples/${id}`)

export const searchIngredients = (q: string) =>
  api.get<IngredientList>(`/ingredients?q=${encodeURIComponent(q)}&limit=8`)
