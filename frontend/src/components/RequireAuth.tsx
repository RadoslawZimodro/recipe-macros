import { Navigate, Outlet, useLocation } from 'react-router-dom'
import { useAuth } from '../auth/AuthProvider'

/** Lets logged-in users through; everyone else goes to the login page and comes back after. */
export function RequireAuth() {
  const { user } = useAuth()
  const location = useLocation()

  if (user === undefined) return <p className="text-slate-500">Ładowanie…</p>
  if (user === null) return <Navigate to="/login" replace state={{ from: location.pathname }} />
  return <Outlet />
}

/** The login and register pages make no sense for someone who is already logged in. */
export function RedirectIfAuthenticated() {
  const { user } = useAuth()

  if (user === undefined) return <p className="text-slate-500">Ładowanie…</p>
  if (user) return <Navigate to="/" replace />
  return <Outlet />
}
