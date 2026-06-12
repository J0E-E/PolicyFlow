# Test Harness & Commit Gate — Epic Plan

Source TDD: [./tdd-P0.1a-test-harness-and-commit-gate.md](./tdd-P0.1a-test-harness-and-commit-gate.md)

> **Review budget:** ~150 changed lines · ~8 non-generated files · one focused commit per epic. Tunable per project.

> This is a high-level agile roadmap. Each epic's design specifics are confirmed
> with stakeholders at epic time (`3-plan-epic`) before any code is written.

## Epic 1 — Backend harness skeleton — **COMPLETED**
- **Goal:** A runnable `pytest` suite under `core/` proven by one trivial passing test — the foundation every later backend test builds on.
- **Rough scope:** New `core/requirements-dev.txt` (test-only deps kept out of the production image), pytest config (async mode, test paths, import path), and a `tests/` package with a shared client fixture.
- **Open questions / decisions for stakeholders:** Pytest config home (`pytest.ini` vs `pyproject.toml`); client fixture style (`TestClient` vs `httpx.ASGITransport`).
- **Depends on:** none.
- **Implementation notes:**
  - Config home = `core/pytest.ini` (no `pyproject.toml` exists; lightest touch). Settings: `asyncio_mode = auto`, `asyncio_default_fixture_loop_scope = function` (pins the async-fixture loop scope to silence the pytest-asyncio deprecation warning), `testpaths = tests`, `pythonpath = .`.
  - Fixture style = `httpx.ASGITransport` + `httpx.AsyncClient` (async-native; exercises the real async path; makes `asyncio_mode = auto` load-bearing).
  - Trivial test `test_health_endpoint_is_reachable` asserts `/api/health` reachability (a valid HTTP status code comes back), NOT ok/degraded content — that is Epic 3. A 503 "degraded" with no live Postgres/RabbitMQ is a valid reachable response here.
  - Files added: `core/requirements-dev.txt` (pytest, httpx, pytest-asyncio, pinned), `core/pytest.ini`, `core/tests/__init__.py`, `core/tests/conftest.py`, `core/tests/test_harness.py`. Purely additive — no production code touched.
  - Verified green on Python 3.12.10 (project target): `cd core && python -m pytest -q` → `1 passed`. Added `.venv/` and `.pytest_cache/` to root `.gitignore` (local verification venv must never be committed).
  - Env note (resolved): the project targets Python 3.12 (per `core/Dockerfile`), but only 3.14 was installed locally, and the pre-existing **runtime** pins `asyncpg==0.30.0` / `psycopg[binary]==3.2.3` have no 3.14 wheels — so `from app.main import app` could not import under 3.14. Resolved by installing Python 3.12.10 and creating `core/.venv` (gitignored); both runtime + dev deps install cleanly there. No production pins were loosened and no imports were stubbed.

## Epic 2 — Health endpoint mocking seam — **COMPLETED**
- **Goal:** Make the `/api/health` db and broker checks individually mockable so the ok/degraded paths can be tested deterministically — no behavior change to the endpoint.
- **Rough scope:** Extract the two connection checks in `core/app/health.py` into named functions the route composes its status from; confirm the public response is unchanged.
- **Open questions / decisions for stakeholders:** Exact function names and the `"ok"`/`"error"` return shape.
- **Depends on:** Epic 1.
- **Implementation notes:**
  - Seam already existed from commit `21c788a` (FastAPI core skeleton + health check); no refactor was needed — **zero production code change**.
  - Function names = `check_database` / `check_broker`; return shape = `"ok"` / `"error"` (constants `CHECK_OK` / `CHECK_ERROR`) — matches the TDD interface, resolves the epic's open question on names + return shape.
  - Verified mockable: `get_health` resolves both checks by module-level name at call time, so `monkeypatch.setattr("app.health.check_database", …)` / `check_broker` works for Epic 3.
  - Public `/api/health` response unchanged (`status` + `version` + `checks` dict); harness verified still green via `core/.venv`: `python -m pytest -q` → `1 passed`.

## Epic 3 — Health tests (ok + degraded) — **COMPLETED**
- **Goal:** The first real backend tests — assert the `200/"ok"` path and the `503/"degraded"` path (including a single-check-down case) by mocking the seam from Epic 2.
- **Rough scope:** `core/tests/test_health.py` monkeypatching `check_database` / `check_broker`; no live Postgres/RabbitMQ.
- **Open questions / decisions for stakeholders:** Which degraded combinations to cover (one check down vs both).
- **Depends on:** Epic 2.
- **Implementation notes:**
  - One new file `core/tests/test_health.py`; zero production/config change (purely additive).
  - Stakeholder decision honored: 4 tests — ok path + all three degraded combos (db-down, broker-down, both-down).
  - Seam mocked via `monkeypatch.setattr("app.health.check_database"/"check_broker", …)` with a module-level `make_check_returning(status)` factory yielding an `async` stub (real checks are async).
  - No hardcoded literals: reused `CHECK_OK` / `CHECK_ERROR` from `app.health` and `settings` from `app.config`; ok-path asserts `version == settings.app_version`. Reused the async `client` fixture from `conftest.py`.
  - Verified green via `core/.venv` (Python 3.12): `python -m pytest -q` → `5 passed` (4 new + Epic 1 harness test). No live Postgres/RabbitMQ needed.

## Epic 4 — Frontend harness skeleton — **COMPLETED**
- **Goal:** A runnable Vitest + Testing Library + jsdom setup under `frontend/`, wired but not yet exercising components.
- **Rough scope:** Add dev deps and `test`/`test:watch` scripts to `package.json`; add a Vitest `test` block (prefer extending `vite.config.ts`) and a `src/test/setup.ts`.
- **Open questions / decisions for stakeholders:** Extend `vite.config.ts` vs a dedicated `vitest.config.ts` (TDD leans toward extending).
- **Depends on:** none.
- **Implementation notes:**
  - Resolved open question: extended `vite.config.ts` with a `test` block (`environment: "jsdom"`, `globals: true`, `setupFiles: ["./src/test/setup.ts"]`) — no separate `vitest.config.ts`. Added `/// <reference types="vitest/config" />` at the top so the `test` key is typed.
  - Added trivial `src/test/harness.test.ts` (one passing `expect(true).toBe(true)`, no component import/render) to prove the harness is runnable — parallels backend Epic 1's `test_harness.py` and keeps `vitest run` from exiting non-zero on zero test files. Epic 5 adds the real `<App>` smoke test. This file stays permanently.
  - New files: `src/test/setup.ts` (`import "@testing-library/jest-dom/vitest";`) and `src/test/harness.test.ts`. Edited: `package.json` (scripts + devDeps), `vite.config.ts` (reference + test block), `tsconfig.app.json` (`"types": ["vitest/globals", "@testing-library/jest-dom"]`).
  - Dependency pins installed (exact, Vite 5-compatible): `vitest` `2.1.9`, `@testing-library/react` `16.1.0`, `@testing-library/dom` `10.4.0`, `@testing-library/jest-dom` `6.6.3`, `jsdom` `25.0.1`. Scripts added: `test` = `vitest run`, `test:watch` = `vitest`.
  - Verified green: `npm install` resolved cleanly (116 packages added; `package-lock.json` created); `npm test` → `1 passed` (exit 0, jsdom env); `npm run build` (`tsc -b && vite build`) succeeded (typecheck + build, exit 0), confirming the added types/config don't break the build.

## Epic 5 — Frontend smoke test
- **Goal:** Prove the frontend harness wires React + Testing Library + jsdom end-to-end with a passing shell render test.
- **Rough scope:** `src/App.test.tsx` renders `<App>` inside a router and asserts a stable shell element (e.g. a wordmark/heading from `PageLayout`).
- **Open questions / decisions for stakeholders:** Which stable element to anchor the assertion on.
- **Depends on:** Epic 4.
- **Implementation notes:** _none yet_

## Epic 6 — Commit gate (pre-commit)
- **Goal:** A blocking `pre-commit` gate that runs both suites on every commit and rejects any red commit.
- **Rough scope:** Root `.pre-commit-config.yaml` with two `language: system` hooks (`backend-tests`, `frontend-tests`), `always_run: true`, `pass_filenames: false`.
- **Open questions / decisions for stakeholders:** Exact invocation strings per host shell (Windows/PowerShell vs bash wrappers).
- **Depends on:** Epics 3, 5.
- **Implementation notes:** _none yet_

## Epic 7 — CI: CodeBuild test step
- **Goal:** Gate the image build on both suites — a red tree fails CodeBuild before any `docker build`, so no image is pushed.
- **Rough scope:** Add install + run steps for both suites to the `pre_build` phase of `ops/buildspec.yml`, before the build steps.
- **Open questions / decisions for stakeholders:** Whether Python 3.12 + Node 20 are present in the CodeBuild base image or must be installed in the `install` phase.
- **Depends on:** Epics 3, 5.
- **Implementation notes:** _none yet_

## Epic 8 — CI: GitHub Actions workflow
- **Goal:** Branch/PR-level test signal mirroring the hook and buildspec commands.
- **Rough scope:** `.github/workflows/tests.yml` on push + PR — a Python 3.12 job (pytest) and a Node 20 job (vitest).
- **Open questions / decisions for stakeholders:** Caching strategy for pip/npm (optional, can be deferred).
- **Depends on:** Epics 3, 5.
- **Implementation notes:** _none yet_

## Epic 9 — Prove the gate + TESTING.md
- **Goal:** Demonstrate the gate is live (a deliberately broken test blocks a commit, then revert) and document the standing rule and one-time setup.
- **Rough scope:** Manual proof per the TDD's verification steps; write root `TESTING.md` (standing rule, setup, how to run each suite, how the gate and CI mirror each other).
- **Open questions / decisions for stakeholders:** None expected.
- **Depends on:** Epics 6, 7, 8.
- **Implementation notes:** _none yet_
