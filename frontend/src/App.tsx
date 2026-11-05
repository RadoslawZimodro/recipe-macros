import { Route, Routes } from 'react-router-dom'
import { Layout } from './components/Layout'
import { RedirectIfAuthenticated, RequireAuth } from './components/RequireAuth'
import { LoginPage, RegisterPage } from './pages/AuthPages'
import { HomePage } from './pages/HomePage'

function App() {
  return (
    <Routes>
      <Route element={<Layout />}>
        <Route element={<RedirectIfAuthenticated />}>
          <Route path="/login" element={<LoginPage />} />
          <Route path="/register" element={<RegisterPage />} />
        </Route>
        <Route element={<RequireAuth />}>
          <Route path="/" element={<HomePage />} />
        </Route>
        <Route path="*" element={<p>Nie znaleziono strony.</p>} />
      </Route>
    </Routes>
  )
}

export default App
