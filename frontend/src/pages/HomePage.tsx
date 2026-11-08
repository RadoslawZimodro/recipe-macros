import { Link } from 'react-router-dom'
import { useAuth } from '../auth/AuthProvider'
import { CARD_LINK } from '../components/ui/cardClass'

const SHORTCUTS = [
  { to: '/recipes', title: 'Przepisy', hint: 'Twoje zapisane przepisy' },
  { to: '/recipes/import', title: 'Import', hint: 'Dodaj przepis z linku' },
  { to: '/log', title: 'Dziennik', hint: 'Co dziś zjedzone' },
  { to: '/pantry', title: 'Lodówka', hint: 'Co możesz ugotować' },
]

export function HomePage() {
  const { user } = useAuth()

  return (
    <section className="space-y-8">
      <div className="max-w-reading space-y-2">
        <h1 className="text-h1">Witaj!</h1>
        <p className="text-ink-2">Jesteś zalogowany jako {user?.email}.</p>
      </div>
      <nav aria-label="Skróty">
        <ul className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
          {SHORTCUTS.map((s) => (
            <li key={s.to}>
              <Link
                to={s.to}
                className={`${CARD_LINK} block h-full space-y-1`}
              >
                <span className="block font-display text-h3 font-semibold">{s.title}</span>
                <span className="block text-small text-ink-3">{s.hint}</span>
              </Link>
            </li>
          ))}
        </ul>
      </nav>
    </section>
  )
}
