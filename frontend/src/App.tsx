import { Route, Routes } from 'react-router-dom'
import { Layout } from './components/Layout'
import { RedirectIfAuthenticated, RequireAuth } from './components/RequireAuth'
import { LoginPage, RegisterPage } from './pages/AuthPages'
import { HomePage } from './pages/HomePage'
import { RecipeDetailPage } from './pages/recipes/RecipeDetailPage'
import { RecipeImportPage } from './pages/recipes/RecipeImportPage'
import { RecipeListPage } from './pages/recipes/RecipeListPage'
import { LogPage } from './pages/log/LogPage'

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
          <Route path="/recipes" element={<RecipeListPage />} />
          <Route path="/recipes/import" element={<RecipeImportPage />} />
          <Route path="/recipes/:id" element={<RecipeDetailPage />} />
          <Route path="/log" element={<LogPage />} />
        </Route>
        <Route path="*" element={<p>Nie znaleziono strony.</p>} />
      </Route>
    </Routes>
  )
}

export default App
