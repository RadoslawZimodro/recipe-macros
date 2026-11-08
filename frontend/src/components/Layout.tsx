import { Link, Outlet } from 'react-router-dom'
import { useAuth } from '../auth/AuthProvider'
import { Button } from './ui/Button'
import { Nav } from './ui/Nav'

const NAV_ITEMS = [
  { to: '/recipes', label: 'Przepisy' },
  { to: '/log', label: 'Dziennik' },
  { to: '/pantry', label: 'Lodówka' },
]

export function Layout() {
  const { user, logout } = useAuth()

  return (
    <div className="min-h-screen bg-canvas text-ink">
      <header className="border-b border-line">
        {/* Wraps on mobile: brand + logout on the first row, navigation on the second. */}
        <div className="mx-auto flex min-h-16 max-w-page flex-wrap items-center gap-x-6 gap-y-2 px-4 py-3 sm:px-6">
          <Link
            to="/"
            className="mr-auto font-display text-h4 font-semibold whitespace-nowrap tracking-tight sm:mr-0"
          >
            Recipe Macros
          </Link>
          {user && (
            <div className="order-last flex w-full sm:order-none sm:w-auto sm:flex-1">
              <Nav items={NAV_ITEMS} />
            </div>
          )}
          {user && (
            <div className="flex items-center gap-3">
              <span className="hidden text-small text-ink-3 sm:inline">{user.email}</span>
              <Button variant="secondary" onClick={() => void logout()}>
                Wyloguj
              </Button>
            </div>
          )}
        </div>
      </header>
      <main className="mx-auto max-w-page px-4 py-8 sm:px-6 sm:py-12">
        <Outlet />
      </main>
    </div>
  )
}
