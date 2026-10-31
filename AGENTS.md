# AGENTS.md: instrukcje dla agentów programistycznych

Ten plik jest źródłem prawdy o projekcie. Przeczytaj go w całości na początku każdej sesji
i wracaj do sekcji "Plan" przed rozpoczęciem każdego kroku. Po zakończeniu kroku zaznacz go
jako wykonany (`[x]`) w tym pliku i zrób commit.

## 1. Czym jest projekt

Aplikacja do przepisów kulinarnych z liczeniem makroskładników:

1. **Import przepisu z linku**: użytkownik podaje URL, aplikacja pobiera przepis (najpierw
   dane strukturalne schema.org/Recipe, w razie braku LLM jako fallback) i zapisuje:
   tytuł, kroki, składniki z ilościami.
2. **Makroskładniki**: dla każdego przepisu liczone kcal, białko, tłuszcze, węglowodany
   (całość i na porcję). Wynik jest SZACUNKIEM i tak ma być pokazywany w UI.
3. **Dziennik dnia**: użytkownik loguje zjedzone porcje przepisów lub pojedyncze produkty,
   aplikacja sumuje makro dnia i porównuje z celem.
4. **Lodówka**: użytkownik wpisuje produkty, które ma; aplikacja zwraca przepisy posortowane
   wg zgodności (% składników, które użytkownik posiada), z listą braków.
5. **Później (NIE w obecnym zakresie)**: rozpoznawanie produktów ze zdjęcia lodówki.

## 2. Cel i kontekst autora (ważne dla stylu pracy)

To projekt portfolio/CV. Autor jest juniorem (młodszy architekt systemów, Python) i chce
rozwijać się w stronę **baz danych i analizy danych**. Autor będzie musiał wytłumaczyć każdą
decyzję na rozmowie kwalifikacyjnej, dlatego:

- Pracuj w **małych, weryfikowalnych krokach**. Po każdym kroku coś ma działać i dać się
  uruchomić/przetestować.
- **Wyjaśniaj krótko "dlaczego"** przy decyzjach dotyczących schematu bazy, indeksów,
  zapytań SQL i architektury. Bez długich wykładów.
- Przy decyzjach, które mają realne alternatywy (schemat, biblioteka, strategia zapisu),
  **zadaj pytanie przed implementacją**, z rekomendacją i jednym zdaniem uzasadnienia.
  Nie pytaj o rzeczy z konwencjonalną odpowiedzią.
- Kluczowa logika bazodanowa ma być w **czytelnym SQL** (upserty `INSERT ... ON CONFLICT`,
  agregacje, window functions, CTE), a nie schowana za ORM-em. Autor ma to umieć pokazać.
- Nie dodawaj funkcji spoza bieżącego kroku planu.

## 3. Stack (docelowy od początku, nie zmieniamy go w trakcie)

| Warstwa | Technologia |
|---|---|
| Backend | Python 3.12 + FastAPI |
| Baza | PostgreSQL |
| Dostęp do bazy | SQLAlchemy 2.x (Core/ORM) + surowy SQL tam, gdzie liczy się kompetencja bazodanowa |
| Migracje | Alembic (każda zmiana schematu = migracja, nigdy ręczne zmiany w bazie) |
| Cache | Redis (cache pobranych stron/odpowiedzi LLM, TTL; bez kolejek zadań) |
| Frontend | React (Vite) + Tailwind |
| LLM | Anthropic API (klucz w `.env`), wywołania tylko z backendu |
| Kontenery | Docker Compose: postgres, redis, backend, frontend |
| Testy | pytest (backend): parser składników, przeliczanie jednostek, liczenie makro, dopasowanie lodówki |
| Jakość | ruff (lint + format), pre-commit |

Brak Celery i kolejek zadań: dłuższe operacje wykonuj synchronicznie z rozsądnym timeoutem
albo jako polecenia CLI (`python -m app.scripts.<nazwa>`).

## 4. Struktura repozytorium (docelowa)

```
.
├── AGENTS.md
├── README.md
├── docker-compose.yml
├── .env.example
├── .gitignore
├── backend/
│   ├── pyproject.toml
│   ├── alembic.ini
│   ├── migrations/
│   ├── app/
│   │   ├── main.py
│   │   ├── config.py
│   │   ├── db.py
│   │   ├── models/
│   │   ├── schemas/
│   │   ├── routers/
│   │   ├── services/        # logika: import, parser składników, makro, lodówka
│   │   ├── sql/             # zapytania SQL w plikach .sql lub stałych
│   │   └── scripts/
│   └── tests/
└── frontend/
```

## 5. Zasady Git (publikacja na GitHubie)

- Repozytorium publiczne, więc **nigdy nie commituj sekretów**. `.env` jest w `.gitignore`,
  w repo jest tylko `.env.example` z pustymi wartościami. Przed pierwszym pushem sprawdź
  `git status` i `git diff --cached` pod kątem kluczy.
- Gałąź główna: `main`. Praca na krótkich gałęziach `feat/<opis>`, `fix/<opis>`,
  scalanie do `main` po zakończeniu kroku.
- Commity w stylu Conventional Commits, po angielsku: `feat: add recipe import endpoint`,
  `fix: handle missing yield in parser`, `docs: update README`. Jeden commit = jedna
  logiczna zmiana. Migracja Alembic idzie w tym samym commicie co zmiana modelu.
- Po zakończeniu każdego kroku z planu: `git push`.
- README ma być na bieżąco: opis projektu, jak uruchomić (`docker compose up`), diagram
  schematu bazy, przykładowe zapytania SQL z wyjaśnieniem. To wizytówka w CV.
- Do tworzenia repo na GitHubie użyj `gh` (GitHub CLI), jeśli jest zalogowane
  (`gh auth status`). Jeśli nie jest, NIE próbuj obejść autoryzacji. Podaj autorowi
  dokładne komendy do wykonania ręcznie.

## 6. Wymagania jakościowe i ograniczenia

- Makro i przeliczenia jednostek to **szacunki**: w API i UI oznaczaj pochodzenie wartości
  (`source`: `off`, `manual`, `llm_estimate`) i pozwalaj użytkownikowi ręcznie poprawić.
  Nie udawaj precyzji.
- Wywołania LLM: zawsze wymuszaj strukturalny JSON, waliduj go (Pydantic), obsługuj błędy
  i niepoprawne odpowiedzi, cache'uj wyniki w Redis, loguj liczbę wywołań.
- Pobieranie stron: ustaw User-Agent, timeout, limit rozmiaru odpowiedzi, szanuj `robots.txt`.
  Nie pobieraj treści za logowaniem/paywallem. Przy każdym przepisie przechowuj `source_url`
  i pokazuj link do oryginału.
- Linki z Instagrama/TikToka/YouTube są POZA zakresem. Zwracaj czytelny błąd.
- Bezpieczeństwo: walidacja URL (blokuj adresy lokalne i prywatne, ochrona przed SSRF),
  parametryzowane zapytania SQL, brak sekretów w logach.
- Kod i komentarze po angielsku. Komunikacja z autorem po polsku.

## 7. Szkic schematu bazy (do dopracowania w Kroku 2; pytaj o decyzje przed implementacją)

- `users`: id, email, password_hash, daily_kcal_goal, daily_protein_goal, created_at
- `recipes`: id, user_id, title, source_url, servings, image_url, imported_at, import_method
  (`jsonld` | `llm` | `manual`)
- `recipe_steps`: recipe_id, position, instruction
- `ingredients`: katalog znormalizowanych składników (id, canonical_name, kcal/protein/fat/carbs
  na 100 g, density_g_per_ml NULL, source)
- `recipe_ingredients`: recipe_id, ingredient_id NULL, raw_text, quantity, unit, grams_estimated,
  is_optional
- `unit_conversions`: unit, ingredient_id NULL (NULL = ogólny przelicznik), grams_per_unit
- `food_logs`: user_id, logged_at, recipe_id NULL, ingredient_id NULL, grams NULL,
  servings NULL (CHECK: dokładnie jedno źródło)
- `pantry_items`: user_id, ingredient_id, added_at
- `staple_ingredients`: user_id, ingredient_id (rzeczy "zawsze w domu": sól, woda, olej)
- `ingredient_substitutes`: ingredient_id, substitute_id (później)
- Zapytania/widoki: makro przepisu na porcję, suma dnia, dopasowanie lodówki (% składników
  posiadanych, lista braków), indeksy pod `(user_id, logged_at)` i wyszukiwanie po nazwie
  (`pg_trgm`).

## 8. PLAN (realizuj po kolei, nie przeskakuj)

Każdy krok kończy się: działa, ma testy tam gdzie jest logika, README zaktualizowane,
commit + push, zaznaczenie `[x]` poniżej.

- [x] **Krok 0: Fundament repo**
  Struktura katalogów, `docker-compose.yml` (postgres, redis, backend, frontend),
  `.env.example`, `.gitignore`, ruff + pre-commit, FastAPI z endpointem `/health`,
  Alembic skonfigurowany (pusta migracja inicjalna), README ze szkicem.
  Utworzenie repo na GitHubie i pierwszy push.
  Kryterium: `docker compose up` stawia całość, `/health` zwraca 200, repo jest na GitHubie.
- [ ] **Krok 1: Użytkownicy i auth**
  Tabela `users`, rejestracja, logowanie, JWT, izolacja danych per użytkownik.
  Kryterium: testy rejestracji/logowania, chronione endpointy zwracają 401 bez tokenu.
- [ ] **Krok 2: Schemat przepisów**
  Dopracowanie schematu (pytaj o decyzje), migracje, indeksy, ręczne dodawanie przepisu
  przez API (bez importu).
  Kryterium: CRUD przepisów, składników i kroków, testy.
- [ ] **Krok 3: Import z linku, ścieżka JSON-LD**
  Bezpieczne pobieranie strony (sekcja 6), wyciąganie `schema.org/Recipe`, zapis przepisu,
  cache w Redis, upsert po `(user_id, source_url)`.
  Kryterium: import działa dla kilku polskich i angielskich serwisów, testy na zapisanych
  fixtures HTML.
- [ ] **Krok 4: Import z linku, fallback LLM**
  Gdy brak JSON-LD: oczyszczenie HTML do tekstu, wywołanie LLM ze strukturalnym wyjściem,
  walidacja, obsługa błędów.
  Kryterium: fallback działa na stronie bez JSON-LD, błędy są czytelne.
- [ ] **Krok 5: Parser składników**
  `raw_text` → ilość, jednostka, nazwa składnika (LLM w batchu na cały przepis, wynik
  cache'owany), normalizacja do `ingredients`.
  Kryterium: testy na typowych zapisach ("2 łyżki oliwy", "1 średnia cebula",
  "szczypta soli", "200 g mąki").
- [ ] **Krok 6: Przeliczanie na gramy i makro**
  Tabela `unit_conversions`, przeliczanie jednostek domowych na gramy, dane odżywcze
  (Open Food Facts i/lub ręczne), makro przepisu i na porcję, oznaczanie źródła wartości,
  ręczna korekta.
  Kryterium: testy rachunkowe, endpoint zwraca makro z flagą szacunku.
- [ ] **Krok 7: Dziennik dnia**
  `food_logs`, logowanie porcji przepisu lub produktu, suma dnia (SQL), porównanie z celem.
  Kryterium: zapytania agregujące w czytelnym SQL, test na kilku dniach danych.
- [ ] **Krok 8: Lodówka**
  `pantry_items`, `staple_ingredients`, zapytanie o dopasowanie (% składników, braki,
  sortowanie), opcjonalnie zamienniki.
  Kryterium: testy dopasowania, `EXPLAIN` zapytania opisany w README.
- [ ] **Krok 9: Frontend**
  Widoki: logowanie, lista przepisów, import z linku, szczegóły przepisu z makro,
  dziennik dnia z wykresem, lodówka z wynikami.
  Kryterium: całość przechodzi w UI.
- [ ] **Krok 10: Dopracowanie pod portfolio**
  README z diagramem schematu i przykładami SQL, screenshoty, GitHub Actions
  (lint + testy), seed z danymi demo, opis ograniczeń i decyzji projektowych.
- [ ] **Później (poza zakresem)**: zdjęcie lodówki (model wizyjny, wynik jako sugestia do
  zatwierdzenia), import z social media, planer posiłków na tydzień, lista zakupów.

## 9. Jak raportować postęp

Po każdym kroku napisz autorowi krótkie podsumowanie: co działa, jak to uruchomić,
jakie decyzje zapadły i dlaczego (2-5 zdań), co jest następne. Bez długich recapów kodu.
