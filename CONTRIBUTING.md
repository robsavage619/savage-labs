# Contributing

This is a personal project. These conventions keep the codebase consistent whether changes come from me or from Claude Code.

---

## Code style

### Python

- Python 3.12+. `from __future__ import annotations` at the top of every file.
- `uv` for package management — never `pip` or `poetry`.
- `ruff` for lint, format, and import sorting — not black, not flake8.
- `pyright` in basic mode for type checking.
- `X | None` — never `Optional[X]`.
- f-strings only — never `.format()` or `%`.
- No bare `except:` — always catch a specific exception.
- No `print()` in library code — use `logging`.
- No comments unless the WHY is non-obvious (hidden constraint, workaround for a specific bug, subtle invariant).
- Google-style docstrings on public and complex functions.
- `src/` layout: `backend/src/shc/`.

### TypeScript / React

- TypeScript strict where possible.
- Next.js 15 App Router conventions.
- TanStack Query for all server state — no raw `useEffect` for data fetching.
- Recharts for charts — not D3, not Tremor.
- OKLCH color tokens from `globals.css` — no hard-coded hex or rgb values.
- shadcn/ui + Radix for interactive primitives — don't roll custom dialogs/tabs.
- `clsx` + `tailwind-merge` for conditional classes.

---

## Git

### Commit messages

[Conventional Commits](https://www.conventionalcommits.org/):

```
feat:     new feature
fix:      bug fix
chore:    tooling, deps, config — no production code change
docs:     documentation only
refactor: code change that neither fixes a bug nor adds a feature
test:     adding or updating tests
perf:     performance improvement
ci:       CI/CD changes
```

Examples:

```
feat: add 90-day HRV trend with ±1 SD band
fix: guard nullable volume_kg before chart render
chore: bump recharts to 2.15
docs: add API endpoint reference
```

### Branches

```
<type>/<short-kebab-description>

feat/sleep-consistency-score
fix/acwr-null-guard
chore/update-anthropic-sdk
```

### PRs

Short title (under 70 chars). Body: What / Why / Changes / Test plan.

---

## Development workflow

```bash
make install     # first-time setup
cp env.example .env && vim .env
make seed        # seed synthetic data
make dev         # start API + frontend

make lint        # ruff check + format check
make typecheck   # pyright
make test        # pytest
```

All three checks (lint, typecheck, test) should pass before pushing.

### Database changes

Add a new migration file: `backend/src/shc/db/migrations/000N_description.sql`. Migrations are run in filename order at startup. Make them idempotent where possible (`CREATE TABLE IF NOT EXISTS`, `ALTER TABLE … ADD COLUMN IF NOT EXISTS`).

---

## Testing

Backend tests live in `backend/tests/`. Use `pytest-asyncio` for async routes and `vcrpy` for recording/replaying external HTTP calls (WHOOP API, Anthropic API).

Don't mock the database — tests run against a real in-memory DuckDB instance spun up per test session.

---

## Adding a new data source

1. Write an ingest module in `backend/src/shc/ingest/`.
2. Add the schema changes as a new migration.
3. Add a background sync job in `backend/src/shc/scheduler/jobs.py`.
4. Expose new endpoints in `backend/src/shc/api/routers/dashboard.py`.
5. Wire the frontend component with a typed fetch wrapper in `frontend/lib/api.ts`.

---

## Secrets

Never commit secrets. Sensitive tokens go in macOS Keychain:

```bash
# WHOOP tokens — managed automatically by the OAuth flow
# DB encryption key
shc auth set-db-key

# Hevy API key
# stored under: shc.hevy.access_token.v1
```

The `.env` file holds non-secret config only (API keys for external services that have no Keychain path are the exception — `ANTHROPIC_API_KEY` lives in `.env`).
