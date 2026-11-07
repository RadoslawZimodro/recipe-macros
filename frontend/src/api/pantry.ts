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

export const listPantry = () => api.get<PantryItem[]>('/pantry')
export const addToPantry = (id: number) => api.put<PantryItem>(`/pantry/${id}`)
export const removeFromPantry = (id: number) => api.delete<void>(`/pantry/${id}`)
export const listMatches = () => api.get<RecipeMatch[]>('/pantry/recipes')

export const listStaples = () => api.get<Staples>('/staples')
export const addStaple = (id: number) => api.put<PantryItem>(`/staples/${id}`)
export const removeStaple = (id: number) => api.delete<void>(`/staples/${id}`)
