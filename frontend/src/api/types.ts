// Shapes of the API's answers (mirrors backend/app/schemas).

export interface User {
  id: number
  email: string
  is_active: boolean
  created_at: string
  daily_kcal_goal: number | null
  daily_protein_goal: number | null
}
