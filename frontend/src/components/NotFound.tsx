import { Link } from 'react-router-dom'
import { buttonClass } from './ui/buttonClass'

export function NotFound() {
  return (
    <section className="max-w-reading space-y-4">
      <h1 className="text-h1">404</h1>
      <p className="text-ink-2">Nie znaleziono strony.</p>
      <Link to="/" className={buttonClass('secondary')}>
        Wróć na stronę główną
      </Link>
    </section>
  )
}
