import { Link, Outlet } from 'react-router-dom'
import { useAuth } from '../auth/AuthProvider'

export function Layout() {
  const { user, logout } = useAuth()

  return (
    <div className="min-h-screen bg-slate-50 text-slate-900 dark:bg-slate-900 dark:text-slate-100">
      <header className="border-b border-slate-200 bg-white dark:border-slate-700 dark:bg-slate-800">
        <div className="mx-auto flex max-w-5xl items-center justify-between gap-4 px-4 py-3">
          <Link to="/" className="text-lg font-semibold">
            Recipe Macros
          </Link>
          {user && (
            <nav className="flex flex-1 gap-4 text-sm">
              <Link to="/recipes" className="hover:underline">
                Przepisy
              </Link>
            </nav>
          )}
          {user && (
            <div className="flex items-center gap-3 text-sm">
              <span className="hidden text-slate-600 sm:inline dark:text-slate-300">
                {user.email}
              </span>
              <button
                type="button"
                onClick={() => void logout()}
                className="rounded-md border border-slate-300 px-3 py-1.5 hover:bg-slate-100 dark:border-slate-600 dark:hover:bg-slate-700"
              >
                Wyloguj
              </button>
            </div>
          )}
        </div>
      </header>
      <main className="mx-auto max-w-5xl px-4 py-8">
        <Outlet />
      </main>
    </div>
  )
}
