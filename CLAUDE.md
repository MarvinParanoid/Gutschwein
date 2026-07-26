# Sparschwein — notes for Claude

Family voucher (Gutschein) manager: FastAPI + Telegram Mini App. README.md is the product
description, `docs/deploy.md` the server guide, `docs/internals.md` the reasoning behind
the demo mode, the languages and the access model.

## Conventions

- **README and all docs in English**, like the code. The user writes Russian; the repo does not.
- **Comments and docstrings in English.** User-facing text is localized (ru/en), never
  written inline: the frontend reads `src/i18n/ru.ts` (source of truth) plus `en.ts` / `de.ts`, the
  backend raises `Message("error.…")` keys from `app/i18n.py`.
- Comment the *why*, not the *what*. Existing comments explain non-obvious decisions
  (capability URLs for images, `render_as_batch` for SQLite, id tiebreak in event ordering).
- Backend: async everywhere, SQLAlchemy 2 style (`Mapped[...]`, `select()`), no sync sessions.
- Demo mode (`src/demo/`) swaps the whole API client for one that answers from memory.
  If you add an endpoint, add it there too — `ApiClient` is `typeof httpApi`, so a gap
  is a compile error. It must never make a request; `e2e/demo.spec.ts` enforces that.
- Frontend: no router, no state library. Views are a discriminated union in `App.tsx`,
  server state is fetched per page with `useEffect`.
- New user-facing string? Add the key to `ru.ts` (source of truth), `en.ts` and `de.ts`, or
  to `MESSAGES` in `app/i18n.py` for all three languages. Both halves are covered by tests
  that fail on a gap — the frontend at compile time, the backend in `test_i18n.py`.

## Commands

```bash
make dev-api          # FastAPI :8000 with DEV_MODE=true, bot off
make dev-web          # Vite :5173, proxies /api
make test             # pytest (backend/tests)
make lint             # ruff + tsc --noEmit
make migration m="…"  # autogenerate an Alembic revision
make demo-gif         # re-record docs/demo.gif (Playwright + ffmpeg)
```

Both venv and node_modules are local: `backend/.venv`, `frontend/node_modules`.

## Things that will bite

- `settings` is a module-level singleton built at import time. Tests must set the environment
  in `tests/conftest.py` *before* importing anything from `app`.
- Migrations run inside the app's lifespan via `asyncio.to_thread` (Alembic is sync).
  A schema change means a new revision — there is no `create_all` fallback.
- `alembic/env.py` strips the async driver from `DATABASE_URL`; keep that in mind when
  switching to Postgres (`+asyncpg` → `+psycopg`).
- Two kinds of member, checked on every request in `check_allowed()`: a Telegram member is
  allowed while their id is in `ALLOWED_TELEGRAM_IDS`, a console member (`telegram_id IS
  NULL`, created by `python -m app.invite`) while their row exists. Neither path may become
  a way around the other; `tests/test_invite.py` guards that.
- Auth carries no session: every request re-validates `initData`, which expires after
  `INIT_DATA_MAX_AGE` (24h). Reopening the Mini App issues a fresh one.
- Uploads are two-step: `POST /api/uploads` returns an `image_id`, then the voucher is
  created/patched with it. An abandoned form leaves an orphan file (no GC yet).
- Status changes go through `_transition()` in `routers/vouchers.py`, which also writes the
  event. Don't set `voucher.status` directly.
- API errors carry a key, not a sentence: `raise HTTPException(404, Message("error.x"))`.
  `main.py` renders it in the reader's language at the boundary, so helpers stay language-free.
  Family-chat messages have no reader, so they use `group_t()` / `DEFAULT_LANGUAGE`.
- Gift card balance: `vouchers.balance_amount` is the current truth, and every change is an
  append-only `balance_updated` event carrying `{spent, remaining, note}` — there is no
  separate ledger table. Corrections are ordinary updates, so never mutate past events.
  Emptying the balance auto-marks the voucher `used`; `POST /use` conversely zeroes it.

## Deliberately not built

Per the product decisions: no OCR/vision recognition, no groups/households/invites,
no manual language switch (the client's language wins). The voucher model is recognition-ready (all fields optional) but nothing
fills it automatically.
