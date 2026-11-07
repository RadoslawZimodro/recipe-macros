import type { Macros } from '../../api/foodLog'

const nf = new Intl.NumberFormat('pl-PL', { maximumFractionDigits: 1 })

export const fmt = (value: number): string => nf.format(value)

export function macrosText(m: Macros): string {
  return `${fmt(m.kcal)} kcal · B ${fmt(m.protein)} g · T ${fmt(m.fat)} g · W ${fmt(m.carbs)} g`
}
