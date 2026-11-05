import { ApiError } from './client'

/**
 * A Polish message for a failed request. The API's own text is English, so the common cases get
 * a Polish sentence and the API's detail is appended only when it says something specific
 * (for example which password rule was broken).
 */
export function describeError(error: unknown, overrides: Record<number, string> = {}): string {
  if (!(error instanceof ApiError)) return 'Coś poszło nie tak. Spróbuj ponownie.'
  if (overrides[error.status]) return overrides[error.status]
  switch (error.status) {
    case 0:
      return 'Nie można połączyć się z serwerem. Sprawdź, czy działa, i spróbuj ponownie.'
    case 401:
      return 'Sesja wygasła. Zaloguj się ponownie.'
    case 404:
      return 'Nie znaleziono.'
    case 422:
      return `Sprawdź wpisane dane. (${error.detail})`
    case 429:
      return 'Zbyt wiele prób. Odczekaj chwilę i spróbuj ponownie.'
    default:
      return error.status >= 500
        ? 'Błąd serwera. Spróbuj ponownie za chwilę.'
        : 'Coś poszło nie tak. Spróbuj ponownie.'
  }
}
