# Code Conventions

This is a personal project — not open for external contributions. These conventions document the standards the codebase follows, primarily so Claude Code sessions stay consistent with existing patterns.

---

## Python

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

## TypeScript / React

- TypeScript strict where possible.
- Next.js 15 App Router conventions.
- TanStack Query for all server state — no raw `useEffect` for data fetching.
- Recharts for charts — not D3, not Tremor.
- OKLCH color tokens from `globals.css` — no hard-coded hex or rgb values.
- shadcn/ui + Radix for interactive primitives — don't roll custom dialogs/tabs.
- `clsx` + `tailwind-merge` for conditional classes.

---

## Git

Conventional Commits (`feat:` `fix:` `chore:` `docs:` `refactor:` `test:` `perf:` `ci:`). Push directly to main — no feature branches, no PRs.

---

## Database changes

Add a new migration file: `backend/src/shc/db/migrations/000N_description.sql`. Migrations run in filename order at startup. Make them idempotent where possible (`CREATE TABLE IF NOT EXISTS`, `ALTER TABLE … ADD COLUMN IF NOT EXISTS`).

---

## Testing

Backend tests live in `backend/tests/`. Use `pytest-asyncio` for async routes. Don't mock the database — tests run against a real in-memory DuckDB instance spun up per test session.

All three checks must pass before pushing: `make lint` (ruff) · `make typecheck` (pyright) · `make test` (pytest).

---

## Secrets

Never commit secrets. Sensitive tokens go in macOS Keychain:

```bash
shc auth set-db-key   # DB encryption key
# WHOOP tokens managed automatically by the OAuth flow
# Hevy key stored under: shc.hevy.access_token.v1
```

`ANTHROPIC_API_KEY` is the exception — it lives in `.env` (gitignored).
