import { useAuth } from '../auth/AuthProvider'

export function HomePage() {
  const { user } = useAuth()

  return (
    <section className="space-y-2">
      <h1 className="text-2xl font-semibold">Witaj!</h1>
      <p className="text-slate-600 dark:text-slate-300">
        Jesteś zalogowany jako {user?.email}. Kolejne widoki (przepisy, dziennik, lodówka) pojawią
        się w następnych krokach.
      </p>
    </section>
  )
}
