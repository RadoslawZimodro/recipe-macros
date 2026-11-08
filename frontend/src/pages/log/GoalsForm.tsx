import { useMutation, useQueryClient } from '@tanstack/react-query'
import { useState, type FormEvent } from 'react'
import { foodLogKeys, setGoals } from '../../api/foodLog'
import { describeError } from '../../api/messages'
import { ME_KEY } from '../../auth/meKey'
import { useAuth } from '../../auth/AuthProvider'
import { ErrorMessage, Field } from '../../components/Field'
import { Button } from '../../components/ui/Button'
import { Card } from '../../components/ui/Card'

const toNumber = (text: string): number | null => (text.trim() === '' ? null : Number(text))

// Remounts the form once the user has loaded, so its fields start from the saved goals.
export function GoalsForm() {
  const { user } = useAuth()
  return (
    <GoalsFields
      key={user ? 'loaded' : 'loading'}
      kcalGoal={user?.daily_kcal_goal ?? null}
      proteinGoal={user?.daily_protein_goal ?? null}
    />
  )
}

function GoalsFields({ kcalGoal, proteinGoal }: { kcalGoal: number | null; proteinGoal: number | null }) {
  const queryClient = useQueryClient()
  const [kcal, setKcal] = useState(kcalGoal?.toString() ?? '')
  const [protein, setProtein] = useState(proteinGoal?.toString() ?? '')
  const save = useMutation({
    mutationFn: () =>
      setGoals({ daily_kcal_goal: toNumber(kcal), daily_protein_goal: toNumber(protein) }),
    onSuccess: (updated) => {
      queryClient.setQueryData(ME_KEY, updated)
      return queryClient.invalidateQueries({ queryKey: foodLogKeys.all })
    },
  })

  const submit = (event: FormEvent) => {
    event.preventDefault()
    save.mutate()
  }
  return (
    <Card as="section" aria-label="Cele dzienne" className="space-y-6">
      <h2 className="text-h3">Cele dzienne</h2>
      <form onSubmit={submit} className="space-y-4">
        <div className="grid gap-4 sm:grid-cols-2">
          <Field
            id="goal-kcal"
            label="Cel kalorii (kcal)"
            type="number"
            min="500"
            max="10000"
            step="1"
            hint="Puste = bez celu"
            value={kcal}
            onChange={(e) => setKcal(e.target.value)}
          />
          <Field
            id="goal-protein"
            label="Cel białka (g)"
            type="number"
            min="1"
            max="1000"
            step="1"
            hint="Puste = bez celu"
            value={protein}
            onChange={(e) => setProtein(e.target.value)}
          />
        </div>
        <ErrorMessage message={save.isError ? describeError(save.error) : null} />
        {save.isSuccess && (
          <p role="status" className="text-small text-accent">
            Zapisano cele.
          </p>
        )}
        <Button type="submit" loading={save.isPending}>
          Zapisz cele
        </Button>
      </form>
    </Card>
  )
}
