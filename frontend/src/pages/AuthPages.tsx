import { useState, type FormEvent } from 'react'
import { Link, useLocation, useNavigate } from 'react-router-dom'
import { describeError } from '../api/messages'
import { useAuth } from '../auth/AuthProvider'
import { ErrorMessage, Field } from '../components/Field'

interface AuthFormProps {
  mode: 'login' | 'register'
}

const TEXTS = {
  login: {
    title: 'Zaloguj się',
    submit: 'Zaloguj',
    busy: 'Logowanie…',
    other: 'Nie masz konta?',
    otherLink: 'Zarejestruj się',
    otherTo: '/register',
    // 401 from /auth/login = wrong email or password; do not say which one.
    overrides: { 401: 'Nieprawidłowy e-mail lub hasło.' },
  },
  register: {
    title: 'Załóż konto',
    submit: 'Zarejestruj',
    busy: 'Zakładanie konta…',
    other: 'Masz już konto?',
    otherLink: 'Zaloguj się',
    otherTo: '/login',
    overrides: { 409: 'Konto z tym adresem e-mail już istnieje.' },
  },
} as const

function AuthForm({ mode }: AuthFormProps) {
  const text = TEXTS[mode]
  const { login, register } = useAuth()
  const navigate = useNavigate()
  const location = useLocation()
  const [email, setEmail] = useState('')
  const [password, setPassword] = useState('')
  const [error, setError] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)

  async function onSubmit(event: FormEvent) {
    event.preventDefault()
    setError(null)
    setBusy(true)
    try {
      await (mode === 'login' ? login : register)({ email, password })
      const from = (location.state as { from?: string } | null)?.from
      navigate(from ?? '/', { replace: true })
    } catch (caught) {
      setError(describeError(caught, text.overrides))
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="mx-auto mt-8 max-w-sm rounded-lg border border-slate-200 bg-white p-6 shadow-sm dark:border-slate-700 dark:bg-slate-800">
      <h1 className="mb-4 text-xl font-semibold">{text.title}</h1>
      <form onSubmit={onSubmit} className="space-y-4">
        <Field
          label="E-mail"
          type="email"
          autoComplete="email"
          required
          value={email}
          onChange={(event) => setEmail(event.target.value)}
        />
        <Field
          label="Hasło"
          type="password"
          autoComplete={mode === 'login' ? 'current-password' : 'new-password'}
          required
          value={password}
          onChange={(event) => setPassword(event.target.value)}
          hint={mode === 'register' ? 'Serwer sprawdzi siłę hasła i podpowie, czego brakuje.' : undefined}
        />
        <ErrorMessage message={error} />
        <button
          type="submit"
          disabled={busy}
          className="w-full rounded-md bg-emerald-700 px-4 py-2 font-medium text-white hover:bg-emerald-800 disabled:opacity-60"
        >
          {busy ? text.busy : text.submit}
        </button>
      </form>
      <p className="mt-4 text-sm text-slate-600 dark:text-slate-300">
        {text.other}{' '}
        <Link to={text.otherTo} className="font-medium text-emerald-700 underline dark:text-emerald-400">
          {text.otherLink}
        </Link>
      </p>
    </div>
  )
}

export const LoginPage = () => <AuthForm mode="login" />
export const RegisterPage = () => <AuthForm mode="register" />
