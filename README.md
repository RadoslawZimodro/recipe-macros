# Recipe Macros

Import a recipe from a link, get an **estimate** of its macros (kcal, protein, fat, carbs; total
and per serving), log what you ate during the day and find recipes that match what is in your
fridge.

> Status: Step 1 (users and authentication). See the plan in [AGENTS.md](AGENTS.md).

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

## Database schema

_Diagram coming in Step 2._

## Example SQL queries

_Coming with Steps 6-8 (macros per serving, daily totals, pantry matching)._

## License

[MIT](LICENSE)
