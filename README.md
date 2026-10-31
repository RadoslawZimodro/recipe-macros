# Recipe Macros

Import a recipe from a link, get an **estimate** of its macros (kcal, protein, fat, carbs; total
and per serving), log what you ate during the day and find recipes that match what is in your
fridge.

> Status: Step 0 (repository foundation). See the plan in [AGENTS.md](AGENTS.md).

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
docker compose exec backend pytest                                   # tests
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

## Database schema

_Diagram coming in Step 2._

## Example SQL queries

_Coming with Steps 6-8 (macros per serving, daily totals, pantry matching)._

## License

[MIT](LICENSE)
