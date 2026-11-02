# Recipe Macros

Import a recipe from a link, get an **estimate** of its macros (kcal, protein, fat, carbs; total
and per serving), log what you ate during the day and find recipes that match what is in your
fridge.

> Status: Step 4 (import from a link, with AI). See the plan in [AGENTS.md](AGENTS.md).

## Stack

| Layer | Technology |
|---|---|
| Backend | Python 3.12, FastAPI |
| Database | PostgreSQL 18, SQLAlchemy 2 (sync, psycopg 3) + raw SQL, Alembic migrations |
| Cache | Redis 7 |
| Frontend | React + TypeScript (Vite), Tailwind CSS v4 |
| LLM | Anthropic API (backend only) |
| Tooling | Docker Compose, pytest, ruff, pre-commit |

## Running locally

Requirements: Docker Desktop (and git). Everything else runs in containers.

```bash
cp .env.example .env        # optional; empty values fall back to dev defaults
docker compose up --build
```

| Service | URL |
|---|---|
| Frontend | http://localhost:5180 |
| Backend API | http://localhost:8010 (docs: http://localhost:8010/docs) |
| Health check | http://localhost:8010/health |
| PostgreSQL | `localhost:5440` (user/password `postgres` by default) |

Host ports are chosen not to clash with the author's other local projects; DB and API ports
can be changed in `.env` (`DB_HOST_PORT`, `BACKEND_HOST_PORT`).
Both backend and frontend reload automatically when you edit code.

### Common commands

```bash
docker compose exec backend pytest                                   # tests (own `recipe_macros_test` DB)
docker compose exec backend ruff check . && docker compose exec backend ruff format .
docker compose exec backend alembic upgrade head                     # migrations (also run on startup)
docker compose exec backend alembic revision --autogenerate -m "..."  # new migration
docker compose exec db psql -U postgres -d recipe_macros             # SQL shell
```

### Pre-commit (on the host)

```bash
pip install pre-commit   # or: pipx install pre-commit
pre-commit install
```

## Authentication

Email + password accounts, no email confirmation. Interactive docs: http://localhost:8010/docs.

| Endpoint | Purpose |
|---|---|
| `POST /auth/register` | Create an account and start a session (`409` if the email is taken) |
| `POST /auth/login` | Verify credentials and start a session (rate limited per IP) |
| `POST /auth/refresh` | Rotate the refresh token, issue a new access token |
| `POST /auth/logout` | Revoke the refresh token and clear cookies |
| `GET /auth/me` | Current user; `401` without a valid session |

Design decisions:

- **Argon2id** password hashes (memory-hard, no 72-byte limit like bcrypt).
- **Short-lived access JWT (15 min, HS256) + opaque refresh token (6 h)**, both in `HttpOnly`
  cookies, so JavaScript can never read them (XSS cannot steal a session). The refresh cookie is
  scoped to `/auth`, so it is not sent with ordinary API calls.
- **Refresh rotation with reuse detection**: every refresh revokes the old token and links it to
  its successor (`refresh_tokens.replaced_by_id`). Replaying an already-rotated token revokes the
  user's whole token chain. Only the sha256 of a refresh token is stored. Rotation locks the row
  (`SELECT ... FOR UPDATE`), so two concurrent refreshes cannot both succeed.
- **CSRF**: double-submit cookie. State-changing endpoints depend on `require_csrf`, which compares
  the `csrf_token` cookie with the `X-CSRF-Token` header in constant time. `SameSite=Lax` is the
  second layer.
- **Data isolation**: the user id is taken only from the verified token (`get_current_user`),
  never from the request body, query or path.
- **Login hardening**: identical error for unknown email and wrong password, a dummy hash check
  keeps timing constant, and an in-memory per-IP limiter returns `429`. The limiter is
  process-local (single uvicorn worker); move it to Redis before scaling out.
- Emails are lowercased by the API and by a `CHECK (email = lower(email))` constraint in
  PostgreSQL, so `UNIQUE(email)` is effectively case-insensitive.

## Recipes API

Everything below needs a session; `POST`/`PUT`/`DELETE` also need the `X-CSRF-Token` header.

| Endpoint | Purpose |
|---|---|
| `POST /recipes` | Create a recipe with its steps and ingredient lines (`201`; `409` if the same `source_url` is already saved) |
| `GET /recipes?q=&tag=&limit=&offset=` | Page of recipes, newest first; `q` searches the title (substring + typos), `tag` filters |
| `GET /recipes/{id}` | One recipe with ordered steps and ingredient lines |
| `PUT /recipes/{id}` | Replace the whole recipe; steps and lines are replaced as a unit in one transaction |
| `DELETE /recipes/{id}` | Soft delete (`204`) |
| `GET /ingredients?q=` | Search products: the shared catalog plus your own |
| `POST /ingredients` | Add a private product (nutrition per 100 g, `source` is always `manual`) |
| `GET /units` | Allowed units for ingredient lines |
| `POST /recipes/import` | Import a recipe from a link (see below) |

Other users' recipes return `404`, not `403`, so their existence is not revealed.
Nutrition values are estimates and carry a `source` (`off`, `manual`, `llm_estimate`).

## Import from a link

`POST /recipes/import` with `{"url": "...", "refresh": false}` fetches a recipe page and saves it as a
normal recipe, keeping a link to the original in `source_url`. The page is read in two stages: its
own markup (schema.org JSON-LD, or Microdata when JSON-LD has no usable recipe) is read by plain
code, and **the AI then shapes the result** (see "AI import" below). Recipes the AI shaped have
`import_method = llm`; if the AI was not available they keep `jsonld` / `microdata`.

| Result | Meaning |
|---|---|
| `201 {"status": "created"}` | New recipe saved |
| `200 {"status": "existing"}` | You already have it; nothing was fetched (your edits are safe) |
| `200 {"status": "refreshed"}` | `refresh: true`: page fetched again, recipe overwritten in place (manual edits are lost) |
| `422/429/502/503/504` | `{"detail": {"code": ..., "message": ...}}` with a stable `code` such as `robots_disallowed`, `blocked_address`, `unsupported_site`, `no_recipe_data`, `access_denied`, `rate_limited`, `ai_unavailable`, `ai_invalid_output` |

Every successful answer also says `"ai_used": true|false` and, when the AI could not be used, a
`"notice"` that explains why.

Try the pipeline on any address without saving anything (`--ai` shows the AI's reading of every
ingredient line, so you can judge its quality on real pages; it calls the paid API):

```bash
docker compose exec backend python -m app.scripts.fetch_recipe "https://example.com/some-recipe" --ai
```

How a page is fetched (`app/services/safe_fetch.py`, `page_fetcher.py`, `robots.py`):

- **SSRF protection.** A user-supplied address must never make the server call its own network.
  The host name is resolved by us and rejected unless *every* address is public (loopback, private,
  link-local, cloud metadata `169.254.169.254`, CGNAT, multicast, IPv4-mapped/NAT64/6to4 IPv6 and
  odd literals like `2130706433` are all refused). The connection then goes to the **IP we checked**
  (the URL is rewritten to the IP; the name stays in the `Host` header and is used for TLS
  verification), so DNS cannot answer differently between check and connect (DNS rebinding).
- **Redirects** are never followed by the HTTP library: each hop is validated and resolved again (max 5).
  Proxy settings from the environment are ignored, since a proxy would bypass the pinned IP.
- **Limits:** only `http(s)` on ports 80/443, no credentials in the URL, HTML only, 2 MB measured
  *after* decompression (gzip bombs), connect 5 s / read 10 s / 15 s in total.
- **robots.txt** per RFC 9309 with a small parser of our own (`urllib.robotparser` ignores the `*`
  and `$` wildcards): a missing file allows, a disallow refuses, an unreachable one (5xx, network) is
  treated as a disallow. Rules are cached for 24 h (10 min when unreachable).
- **Politeness:** identifies itself as `RecipeMacrosBot/0.1 (+repo URL)`, no cookies, at most 10
  imports per minute per user (a Redis counter that works across workers), YouTube/Instagram/TikTok
  links are refused with a clear message, pages behind a login or paywall (401/402/403) are not bypassed.
- **Cache.** The fetched HTML is stored compressed in Redis for 24 h, keyed by the normalized URL, so
  re-parsing or the AI step does not hit the site again. Redis being down never breaks an import.
- **Microdata** (`app/services/microdata.py`) is converted into the same dictionary shape as JSON-LD, so
  one mapping handles both. It follows the HTML Microdata rules: properties of a nested item (an
  author's `name`, a review's text) never leak into the recipe, values come from the right
  attribute (`content` of `<meta>`, `src` of `<img>`, `datetime` of `<time>`, `href` of `<a>`/`<link>`),
  `itemref` pulls in properties defined elsewhere, and block elements (not inline tags like `<b>`)
  separate steps. JSON-LD wins when both formats carry a recipe.
- **URL normalization** (`source_url`, upsert key, cache key): host in lower case, default port and
  `#fragment` dropped, tracking parameters (`utm_*`, `fbclid`, `gclid`, ...) removed.

The save is one SQL statement, an upsert on the partial unique index
([`upsert_imported_recipe.sql`](backend/app/sql/upsert_imported_recipe.sql)):

```sql
INSERT INTO recipes (user_id, title, source_url, ..., import_method, imported_at)
VALUES (:user_id, :title, :source_url, ..., :import_method, now())
ON CONFLICT (user_id, source_url) WHERE source_url IS NOT NULL AND deleted_at IS NULL
DO UPDATE SET title = EXCLUDED.title, ..., imported_at = EXCLUDED.imported_at
RETURNING id, (xmax = 0) AS inserted;   -- xmax <> 0 means an existing row was updated
```

## AI import

The AI (Claude, `claude-haiku-5-5` by default, change it with `AI_MODEL`) is called from the backend
only, with **one request per import**. Its answer is forced into a JSON schema (structured outputs
through `messages.parse` with Pydantic models), so it cannot come back in another shape. It has no
tools and no access to the database or the internet, so text hidden in a web page can at most make
it return a wrong answer, which is then rejected.

| Page | What the AI gets | What it returns |
|---|---|---|
| Has markup (JSON-LD / Microdata) | the ingredient lines and steps from the markup | every ingredient line taken apart (quantity, unit from our `units` table, product, optional flag, estimated nutrition per 100 g) and tidied steps |
| No markup | the cleaned text of the page (menus, scripts, footers removed; max 30 000 characters, cut around the "Ingredients" heading) | the whole recipe (title, servings, times, tags, steps, ingredient lines) |

Title, description, servings, times, tags and image of a page **with** markup stay exactly as the
site published them; only the steps and ingredient lines go through the AI. Ingredient text
(`raw_text`) always stays the original wording.

**Products.** For every product the AI names, the catalog is searched in one query
([`match_products.sql`](backend/app/sql/match_products.sql), a `LATERAL` join over `unnest`): the
exact name first, then a very similar one (`pg_trgm` similarity >= 0.8, and the digits in the two
names must be identical, because "mleko 2%" and "mleko 3,2%" score exactly 0.80 and are different
products). The user's own product shadows a shared one. Anything else becomes a **private product with
`source = 'llm_estimate'`**; the AI never writes to the shared catalog. If the AI's numbers are not
believable (out of range, more than 100 g of nutrients in 100 g, calories far from 4/4/9 kcal per
gram) the product is not created and the line stays unlinked, with its quantity and unit.

**Checks on the answer.** The shape is guaranteed by the schema; the meaning is checked in code
(`validate_*` in [`ai_extract.py`](backend/app/services/ai_extract.py)): one entry per ingredient line,
steps present, quantities in range, ingredient lines of a whole-page reading must be *found on the
page* (an invented ingredient is caught), and pounds/ounces must be converted (a real test on a real
page once returned "1 pound" as `1 g`). A wrong answer gets **one correction attempt** that names the
problems; a second failure ends the import with `ai_invalid_output` and nothing is saved.

**Cost control.**

- Answers are cached in Redis for 7 days, keyed by model, prompt version and the exact input; only
  validated answers are cached, and a refresh of an unchanged page costs nothing.
- Each user has a daily allowance of AI imports (20); cache hits do not count.
- Every API call is logged (model, mode, tokens, request id) and counted in Redis per day:
  `redis-cli get ai:calls:<YYYY-MM-DD>`, `ai:input_tokens:<day>`, `ai:output_tokens:<day>`.
- Measured on real pages with Haiku: about **0.2 cents per import**.

**When the AI is not available** (no key, invalid key, no credit, rate limit, outage, daily limit)
a page with markup is still imported in its basic form (ingredients as plain text, `ai_used: false`
and a `notice`), and can be upgraded later with `refresh: true`. A page without markup cannot be
imported without the AI (`ai_unavailable`, or `no_recipe_data` when no key is configured).

**Measured on real pages** (Polish and English, via the `--ai` script): ingredient lines are taken
apart correctly (units, fractions, ranges, countable items such as "2 żółtka"), a page whose markup
put the *whole article* into the steps (52 lines) came out as 8 clean steps, pages with no usable
markup (Kwestia Smaku, Słodki Pomysł) are read from their text, and imperial units are converted
(`2 (28-ounce) cans` -> 1588 g). The design is deliberately the minimal one (a single request); if
quality on more pages turns out to be too low, the next step is a second request that lets the AI
choose the product from a list of candidates from the catalog.

**Tested on real sites** (read-only, nothing stored in the repo; tests use synthetic pages written
for them): works on Kuchnia Doroty, Kuchnia Lidla and Ania Gotuje (Microdata) in Polish, and on The
Modern Proper, Once Upon a Chef and The Daily Meal in English.

**Known limitations**

- Without the AI, pages whose markup is incomplete (some blogs mark up only the title, picture and
  rating) cannot be imported. Some sites (for example przepisy.pl) refuse automated clients with
  `403`; this is reported, never circumvented.
- AI output is an estimate. Nutrition values are the model's guess for a typical product (always
  `source = llm_estimate`), quantities of "to taste" lines stay empty, and a unit that is not in the
  dictionary is converted to metric or left empty. `cup` is 240 ml for US recipes, while a Polish
  "szklanka" is 250 ml; the exact conversion arrives with the nutrition step.
- Text a site gets wrong stays wrong: a typo in a site's own steps is copied faithfully.
- The shared product catalog is still empty, so almost every product starts as a private estimate;
  the Open Food Facts import (Step 6) fills it with measured data.
- A host name is resolved with the operating system's resolver, which has no timeout of its own
  (the 15 s budget applies from the first connection).

## Database schema

```mermaid
erDiagram
    users ||--o{ recipes : owns
    users ||--o{ ingredients : "owns private"
    users ||--o{ refresh_tokens : has
    recipes ||--o{ recipe_steps : has
    recipes ||--o{ recipe_ingredients : has
    ingredients |o--o{ recipe_ingredients : "linked by"
    units |o--o{ recipe_ingredients : "measured in"

    users {
        int id PK
        text email UK "lower-case CHECK"
        text password_hash
        bool is_active
    }
    recipes {
        int id PK
        int user_id FK "RLS"
        text title
        text source_url "unique per user while active"
        int servings
        text_array tags "GIN index"
        jsonb source_nutrition
        text import_method "jsonld | microdata | llm | manual"
        timestamptz updated_at "trigger"
        timestamptz deleted_at "soft delete"
    }
    recipe_steps {
        int recipe_id PK_FK
        int position PK
        int user_id "denormalized for RLS"
        text instruction
    }
    recipe_ingredients {
        int id PK
        int recipe_id FK
        int user_id "denormalized for RLS"
        int position
        int ingredient_id FK "nullable"
        text raw_text
        numeric quantity
        text unit_code FK "nullable"
        bool is_optional
    }
    ingredients {
        int id PK
        int user_id FK "NULL = shared catalog"
        text canonical_name "unique per scope"
        numeric kcal_per_100g
        text source "off | manual | llm_estimate"
    }
    units {
        text code PK
        text kind "mass | volume | count"
    }
```

Design decisions:

- **Row-Level Security.** The API connects as `app_user`, a role that is neither superuser nor
  table owner and has `NOBYPASSRLS`; migrations run as the owner. Each request sets
  `app.current_user_id` (transaction-local `set_config`, re-applied after every commit), and the
  policies compare `user_id` with `app_current_user_id()`. A forgotten `WHERE user_id = ...` cannot
  leak data, and an unset tenant sees nothing (fails closed). `tests/test_rls.py` proves this with
  raw SQL as `app_user`.
- **Least privilege.** `app_user` gets only the statements the code uses (for example no `DELETE`
  on `recipes`, read-only `units`), granted table by table in the migrations.
- **Denormalized `user_id` on children.** `recipe_steps` and `recipe_ingredients` carry `user_id`
  and reference `recipes(id, user_id)` with a composite foreign key. The database therefore
  refuses a child whose owner differs from its recipe's, and the RLS policy is the same cheap
  comparison everywhere instead of a sub-query.
- **Foreign keys bypass RLS**, so a guessed `ingredient_id` of someone else's private product would
  be accepted by the FK alone. The service checks ids through RLS (`visible_ingredient_ids.sql`).
- **Shared catalog + private products.** `ingredients.user_id IS NULL` marks the shared catalog
  (read-only for the API, filled by scripts later); users add private products. Names are unique
  per scope through two partial unique indexes on `lower(canonical_name)`.
- **Soft delete.** `deleted_at` keeps the row so the food log (Step 7) can still compute macros
  for old entries. The unique index on `(user_id, source_url)` is partial (`WHERE source_url IS NOT
  NULL AND deleted_at IS NULL`), so a deleted recipe can be imported again.
- **Units dictionary** (`units`) with a foreign key instead of free text; an unrecognised unit is
  `NULL` and the original wording stays in `raw_text`.
- **`updated_at` is maintained by a trigger** (`WHEN OLD.* IS DISTINCT FROM NEW.*`), so it is right
  for any writer, including manual SQL.
- **Writes through the ORM, reads as SQL files** in `backend/app/sql/`. The ORM does plain
  inserts/updates; every query that reads or searches is a readable `.sql` file.

## Example SQL queries

A recipe with its steps and ingredient lines in one round trip
([`get_recipe.sql`](backend/app/sql/get_recipe.sql), abridged): correlated sub-queries aggregate the
children into ordered JSON arrays. No `user_id` filter appears; RLS adds it.

```sql
SELECT r.id, r.title, r.servings,
       COALESCE((SELECT json_agg(json_build_object('position', s.position,
                                                   'instruction', s.instruction)
                                 ORDER BY s.position)
                 FROM recipe_steps s WHERE s.recipe_id = r.id), '[]'::json) AS steps
FROM recipes r
WHERE r.id = :recipe_id AND r.deleted_at IS NULL;
```

Title search ([`list_recipes.sql`](backend/app/sql/list_recipes.sql), abridged): `ILIKE '%q%'`
finds substrings and the `pg_trgm` operator `%` finds near matches (typos); both can use the
trigram GIN index `ix_recipes_title_trgm`. Best match first, otherwise newest first.

```sql
SELECT r.id, r.title
FROM recipes r
WHERE r.deleted_at IS NULL
  AND (r.title ILIKE :pattern OR r.title % :q)
ORDER BY similarity(r.title, :q) DESC, r.created_at DESC
LIMIT :limit OFFSET :offset;
```

Known limitations: search does not fold Polish diacritics (a typo in an accented letter may or may
not match through trigram similarity); the shared product catalog stays empty until the Open Food
Facts import in Step 6, and manual correction of shared products is intentionally left out for now
(users add their own private product instead).

## License

[MIT](LICENSE)
