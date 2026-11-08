import { useState, type FormEvent } from 'react'
import { Link, useLocation, useNavigate } from 'react-router-dom'
import { describeError } from '../api/messages'
import { useAuth } from '../auth/AuthProvider'
import { ErrorMessage, Field } from '../components/Field'
import { Button } from '../components/ui/Button'
import { Card } from '../components/ui/Card'
import { ACCENT_LINK } from '../components/ui/linkClass'

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
    <Card className="mx-auto mt-8 max-w-sm space-y-6">
      <h1 className="text-h2">{text.title}</h1>
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
        <Button type="submit" loading={busy} className="w-full">
          {busy ? text.busy : text.submit}
        </Button>
      </form>
      <p className="text-small text-ink-2">
        {text.other}{' '}
        <Link to={text.otherTo} className={`font-medium ${ACCENT_LINK}`}>
          {text.otherLink}
        </Link>
      </p>
    </Card>
  )
}

export const LoginPage = () => <AuthForm mode="login" />
export const RegisterPage = () => <AuthForm mode="register" />
