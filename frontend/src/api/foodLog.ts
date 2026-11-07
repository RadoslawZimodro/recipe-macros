// Day log API (mirrors backend/app/schemas/food_log.py) plus the small lookups the log form needs:
// the user's recipes and the product search. Goals live on the user (PATCH /auth/me/goals).

import { api } from './client'
import type { User } from './types'

export interface Macros {
  kcal: number
  protein: number
  fat: number
  carbs: number
}

export interface FoodLogEntry {
  id: number
  logged_at: string
  kind: 'recipe' | 'product'
  name: string
  recipe_id: number | null
  servings: number | null
  ingredient_id: number | null
  grams: number | null
  nutrition: Macros | null
  is_estimate: boolean
  complete: boolean
  lines_total: number | null
  lines_counted: number | null
}

export interface GoalProgress {
  goal: number
  eaten: number
  remaining: number
  percent: number
}

export interface DayTotals {
  day: string
  entries: number
  total: Macros
  is_estimate: boolean
  complete: boolean
  kcal: GoalProgress | null
  protein: GoalProgress | null
}

export interface DayOut {
  timezone: string
  totals: DayTotals
  entries: FoodLogEntry[]
}

export interface DaysOut {
  timezone: string
  days: DayTotals[]
}

export type FoodLogIn =
  | { recipe_id: number; servings: number; logged_at?: string }
  | { ingredient_id: number; grams: number; logged_at?: string }

export interface GoalsIn {
  daily_kcal_goal: number | null
  daily_protein_goal: number | null
}

export interface IngredientOut {
  id: number
  canonical_name: string
  kcal_per_100g: number
  protein_per_100g: number
  fat_per_100g: number
  carbs_per_100g: number
  density_g_per_ml: number | null
  source: string
  is_shared: boolean
}

export interface IngredientListOut {
  items: IngredientOut[]
  total: number
  limit: number
  offset: number
}

// The API groups days by Polish time, so "today" and the chart ranges must be Polish dates too.
const TIME_ZONE = 'Europe/Warsaw'

/** Today's date (YYYY-MM-DD) in Polish time. */
export function todayInPoland(now: Date = new Date()): string {
  return new Intl.DateTimeFormat('en-CA', { timeZone: TIME_ZONE }).format(now)
}

/** Shifts a YYYY-MM-DD date by a number of days (calendar arithmetic, no time zone involved). */
export function addDays(day: string, delta: number): string {
  const date = new Date(`${day}T00:00:00Z`)
  date.setUTCDate(date.getUTCDate() + delta)
  return date.toISOString().slice(0, 10)
}

/**
 * The logged_at to send for a day. Today: undefined (the server uses "now"). Another day: noon
 * at +01:00, which falls on the same Polish calendar day in winter and summer time alike.
 * Noon +01:00 is 11:00 UTC, i.e. 12:00 (winter, UTC+1) or 13:00 (summer, UTC+2) in Warsaw, so
 * it never crosses midnight, including on the DST change days.
 */
export function loggedAtFor(day: string): string | undefined {
  return day === todayInPoland() ? undefined : `${day}T12:00:00+01:00`
}

export const foodLogKeys = {
  all: ['food-log'] as const,
  day: (day: string) => ['food-log', 'day', day] as const,
  days: (from: string, to: string) => ['food-log', 'days', from, to] as const,
}

export const getDay = (day: string) => api.get<DayOut>(`/food-log?date=${day}`)
export const getDays = (from: string, to: string) =>
  api.get<DaysOut>(`/food-log/days?from=${from}&to=${to}`)
export const addEntry = (payload: FoodLogIn) => api.post<FoodLogEntry>('/food-log', payload)
export const deleteEntry = (id: number) => api.delete<void>(`/food-log/${id}`)
export const setGoals = (goals: GoalsIn) => api.patch<User>('/auth/me/goals', goals)

export const searchIngredients = (q: string) =>
  api.get<IngredientListOut>(`/ingredients?q=${encodeURIComponent(q)}&limit=10`)
