import { useMutation, useQueryClient } from '@tanstack/react-query'
import { useState, type FormEvent } from 'react'
import { Link, useNavigate } from 'react-router-dom'
import { ApiError } from '../../api/client'
import { describeError } from '../../api/messages'
import { importRecipe } from '../../api/recipes'
import { ErrorMessage, Field } from '../../components/Field'
import { Button } from '../../components/ui/Button'
import { Spinner } from '../../components/ui/Spinner'

// Polish texts for the API's stable import error codes.
const IMPORT_ERRORS: Record<string, string> = {
  invalid_url: 'To nie jest poprawny adres http(s).',
  unsupported_site:
    'Linki z Instagrama, TikToka i YouTube nie są obsługiwane. Podaj link do strony z przepisem.',
  blocked_address: 'Ten adres jest zablokowany (adresy lokalne i prywatne nie są dozwolone).',
  dns_failure: 'Nie znaleziono takiej strony. Sprawdź adres.',
  robots_disallowed: 'Ta strona nie pozwala na automatyczne pobieranie treści.',
  access_denied: 'Strona odmówiła dostępu (np. wymaga logowania).',
  not_found: 'Nie znaleziono strony pod tym adresem.',
  not_html: 'Ten adres nie prowadzi do strony internetowej.',
  too_large: 'Strona jest zbyt duża, by ją zaimportować.',
  too_many_redirects: 'Strona przekierowuje zbyt wiele razy.',
  no_recipe_data: 'Nie znaleziono przepisu na tej stronie.',
  rate_limited: 'Zbyt wiele importów. Odczekaj chwilę i spróbuj ponownie.',
  upstream_error: 'Serwis z przepisem zwrócił błąd. Spróbuj ponownie później.',
  robots_unavailable: 'Nie udało się sprawdzić zasad strony. Spróbuj ponownie później.',
  ai_invalid_output: 'Nie udało się przetworzyć tej strony na przepis. Spróbuj później.',
  timeout: 'Strona odpowiadała zbyt długo. Spróbuj ponownie.',
  service_unavailable: 'Import jest chwilowo niedostępny. Spróbuj ponownie później.',
  ai_unavailable: 'Ta strona nie ma danych strukturalnych, a import z pomocą AI jest niedostępny.',
}

function describeImportError(error: unknown): string {
  if (error instanceof ApiError && error.code && IMPORT_ERRORS[error.code]) {
    return IMPORT_ERRORS[error.code]
  }
  return describeError(error)
}

export function RecipeImportPage() {
  const [url, setUrl] = useState('')
  const navigate = useNavigate()
  const queryClient = useQueryClient()

  const mutation = useMutation({
    mutationFn: (value: string) => importRecipe(value),
    onSuccess: async (result) => {
      await queryClient.invalidateQueries({ queryKey: ['recipes'] })
      void navigate(`/recipes/${result.recipe.id}`, {
        state: { notice: result.notice, status: result.status },
      })
    },
  })

  function submit(event: FormEvent) {
    event.preventDefault()
    if (url.trim() && !mutation.isPending) mutation.mutate(url.trim())
  }

  return (
    <section className="max-w-reading space-y-6">
      <h1 className="text-h1">Importuj przepis z linku</h1>
      <form onSubmit={submit} className="space-y-4">
        <Field
          label="Adres strony z przepisem"
          type="url"
          placeholder="https://..."
          value={url}
          onChange={(e) => setUrl(e.target.value)}
          required
          hint="Instagram, TikTok i YouTube nie są obsługiwane."
        />
        {mutation.isPending && (
          <p role="status" className="flex items-center gap-2 text-small text-ink-2">
            <Spinner />
            Importuję przepis… To może potrwać nawet kilkadziesiąt sekund.
          </p>
        )}
        <ErrorMessage message={mutation.isError ? describeImportError(mutation.error) : null} />
        <div className="flex items-center gap-4">
          <Button type="submit" loading={mutation.isPending}>
            {mutation.isPending ? 'Importowanie…' : 'Importuj'}
          </Button>
          <Link to="/recipes" className="text-small text-ink-2 underline underline-offset-2 hover:text-ink">
            Wróć do listy
          </Link>
        </div>
      </form>
    </section>
  )
}
