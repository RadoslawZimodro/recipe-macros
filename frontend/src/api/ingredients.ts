import { api } from './client'

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

export const searchIngredients = (q: string) =>
  api.get<IngredientList>(`/ingredients?q=${encodeURIComponent(q)}&limit=10`)
