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

## Epic 5 — Frontend smoke test — **COMPLETED**
- **Goal:** Prove the frontend harness wires React + Testing Library + jsdom end-to-end with a passing shell render test.
- **Rough scope:** `src/App.test.tsx` renders `<App>` inside a router and asserts a stable shell element (e.g. a wordmark/heading from `PageLayout`).
- **Open questions / decisions for stakeholders:** Which stable element to anchor the assertion on.
- **Depends on:** Epic 4.
- **Implementation notes:**
  - One new file `frontend/src/App.test.tsx`; purely additive — no production code, no rendered DOM, so the frontend `id` rule and `[UI]` tag do not apply.
  - Resolved open question: anchor on the shared-shell wordmark from `PageLayout` via the header's accessible `banner` role (`screen.getByRole("banner")` + `within(header).getByText("PolicyFlow")`). Chosen over the landing `<h1>` (page content changing in P1.6) and over a raw id lookup. `within(header)` disambiguates "PolicyFlow", which appears in both the header wordmark `<p>` and the hero `<h1>`.
  - `<App>` renders `<Routes>`, so it is wrapped in `MemoryRouter` for router context.
  - No test-framework imports — `vite.config.ts` sets `globals: true`, so `describe`/`it`/`expect` are global (matches `harness.test.ts`). `.toBeInTheDocument()` comes from the jest-dom matchers loaded in `src/test/setup.ts`.
  - Verified green: `cd frontend && npm test` → `2 passed` (this test + `harness.test.ts`), exit 0. `cd frontend && npm run build` (`tsc -b && vite build`) succeeded, exit 0. Test run logs two React Router v7 future-flag advisory warnings (stderr only, not failures).

## Epic 6 — Commit gate (pre-commit) — **COMPLETED**
- **Goal:** A blocking `pre-commit` gate that runs both suites on every commit and rejects any red commit.
- **Rough scope:** Root `.pre-commit-config.yaml` with two `language: system` hooks (`backend-tests`, `frontend-tests`), `always_run: true`, `pass_filenames: false`.
- **Open questions / decisions for stakeholders:** Exact invocation strings per host shell (Windows/PowerShell vs bash wrappers).
- **Depends on:** Epics 3, 5.
- **Implementation notes:**
  - One new file at repo root: `.pre-commit-config.yaml`. Purely additive — no production/test/config code touched. pre-commit 4.5.1 on the host.
  - Resolved open question (invocation strings): both hooks wrap the suite in `bash -c '…'` (Git Bash is available on this Windows host). Backend = `cd core && ./.venv/Scripts/python.exe -m pytest -q` — calls the project's Python 3.12 venv interpreter **explicitly** because the system Python is 3.14 and cannot import the app (the runtime pins have no 3.14 wheels). Frontend = `cd frontend && npm test --silent`.
  - Both hooks: `language: system`, `always_run: true`, `pass_filenames: false`, `stages: [pre-commit]`. No path filtering — every commit runs both full suites.
  - Verified via the framework: `pre-commit install` → installed at `.git/hooks/pre-commit`; `pre-commit run --all-files` → `backend-tests…Passed`, `frontend-tests…Passed` (backend 5 passed, frontend 2 passed under the hood).
  - Out of scope (Epic 9): proving a deliberately broken test blocks a commit, and `TESTING.md`. CI mirrors (buildspec / GitHub Actions) are Epics 7–8.
  - Caveat for Epic 9 `TESTING.md`: the backend `./.venv/Scripts/python.exe` path is Windows-venv-specific (POSIX venvs use `.venv/bin/python`) — document a one-line adjustment so a non-Windows contributor can run the hook locally. Local-dev tradeoff only; CI parity is owned by Epics 7–8.

## Epic 7 — CI: CodeBuild test step — **COMPLETED**
- **Goal:** Gate the image build on both suites — a red tree fails CodeBuild before any `docker build`, so no image is pushed.
- **Rough scope:** Add install + run steps for both suites to the `pre_build` phase of `ops/buildspec.yml`, before the build steps.
- **Open questions / decisions for stakeholders:** Whether Python 3.12 + Node 20 are present in the CodeBuild base image or must be installed in the `install` phase.
- **Depends on:** Epics 3, 5.
- **Implementation notes:**
  - One file changed: `ops/buildspec.yml`. Purely additive gate — no code, no Terraform. `build`/`post_build` phases untouched, so image build/push is functionally unchanged.
  - Resolved open question (runtimes): the base image bundles Python 3.12 + Node 20, so they are selected declaratively via a `runtime-versions` block (`python: 3.12`, `nodejs: 20`) in a new `install` phase — no manual install. *(Confirmed with stakeholder.)*
  - Resolved open question (frontend deps): `npm ci` (clean, lockfile-exact CI install). *(Confirmed with stakeholder.)*
  - Test gate prepended to `pre_build`, before `SHORT_SHA`/ECR-login: `pip install --quiet --requirement core/requirements.txt --requirement core/requirements-dev.txt`, then `(cd core && python -m pytest -q)`, then `(cd frontend && npm ci && npm test --silent)`. Both requirement files are needed because pytest imports `app.main` (runtime deps: asyncpg, aio-pika, fastapi) and `requirements-dev.txt` supplies pytest/httpx/pytest-asyncio.
  - Each `cd` wrapped in a subshell `(...)` so the working directory does not leak into the later root-relative `docker build core` / `docker build frontend`.
  - Updated the file's top comment with a one-line note about the pre_build test gate.
  - Command parity confirmed with the Epic 6 hook and the TDD primary flow: `pytest -q` in `core`, `npm test` in `frontend`.
  - Verified YAML validity via `yaml.safe_load`: phases parse as `install`, `pre_build`, `build`, `post_build`; runtime-versions and the three gate commands sit before `SHORT_SHA`/ECR-login. Live CodeBuild verification (a red `pre_build` failing the build before ECR push) is deferred per the TDD — out of scope for local review.
  - Post-review nit applied: the runtime versions are quoted as strings (`python: "3.12"`, `nodejs: "20"`) so a future YAML re-serializer can't read `3.12` as a float and risk truncation to `3.1`. Cosmetic only — CodeBuild accepts both forms.

## Epic 8 — CI: GitHub Actions workflow — **COMPLETED**
- **Goal:** Branch/PR-level test signal mirroring the hook and buildspec commands.
- **Rough scope:** `.github/workflows/tests.yml` on push + PR — a Python 3.12 job (pytest) and a Node 20 job (vitest).
- **Open questions / decisions for stakeholders:** Caching strategy for pip/npm (optional, can be deferred).
- **Depends on:** Epics 3, 5.
- **Implementation notes:**
  - One new file `.github/workflows/tests.yml`. Purely additive CI config — no app code, no Terraform, no behavior change. The `.github/workflows/` directory is created by this epic (none existed).
  - Two independent jobs run in parallel on `ubuntu-latest`: `backend` (checkout → setup-python 3.12 → pip install → pytest) and `frontend` (checkout → setup-node 20 → npm ci → npm test).
  - Resolved open question (caching): **enabled, not deferred** — `setup-python@v5` with `cache: "pip"` and `cache-dependency-path` covering both `core/requirements.txt` + `core/requirements-dev.txt`; `setup-node@v4` with `cache: "npm"` and `cache-dependency-path: frontend/package-lock.json`. Built-in to the setup actions, so it adds no extra steps.
  - Command parity (the third mirror of the same gate, with the hook + buildspec): backend install/run and frontend commands are verbatim from `ops/buildspec.yml` lines 25–27. Diff confirmed: installed packages identical, `python -m pytest -q` exact match, `npm ci`/`npm test --silent` exact match.
  - Two intentional, cosmetic deviations from the buildspec strings: (1) CI drops the buildspec's `--quiet` flag on `pip install` (GH Actions captures logs natively); (2) the buildspec's `npm ci && npm test --silent` is split into two separate `run:` steps, each with `working-directory: frontend`, since GH Actions has no subshell wrapper — `working-directory` replaces the buildspec's `(cd frontend && …)`. Both `cd`-via-subshell idioms from the buildspec become `working-directory:` here.
  - CI uses plain `python -m pytest` (no venv) because `setup-python` provides 3.12 on a clean runner — unlike the Windows hook (Epic 6), which calls `core/.venv/Scripts/python.exe` directly to dodge the host's Python 3.14.
  - Triggers: `on: [push, pull_request]`, no branch filter. (PyYAML parses the bare `on:` key as boolean `True` — a known YAML 1.1 quirk; the value `[push, pull_request]` and structure are correct.)
  - Added a top comment block describing the file's role as the branch/PR mirror of the hook + buildspec, consistent with the comment style of `ops/buildspec.yml` and `.pre-commit-config.yaml`.
  - Verified via `yaml.safe_load`: top-level `on`/`jobs` parse; `jobs.backend` + `jobs.frontend` both `ubuntu-latest` with the mirrored commands present. Live GitHub Actions run is deferred (no app behavior to exercise locally).
  - Out of scope (Epic 9): `TESTING.md` and the broken-test proof.

## Epic 9 — Prove the gate + TESTING.md — **COMPLETED**
- **Goal:** Demonstrate the gate is live (a deliberately broken test blocks a commit, then revert) and document the standing rule and one-time setup.
- **Rough scope:** Manual proof per the TDD's verification steps; write root `TESTING.md` (standing rule, setup, how to run each suite, how the gate and CI mirror each other).
- **Open questions / decisions for stakeholders:** None expected.
- **Depends on:** Epics 6, 7, 8.
- **Implementation notes:**
  - **No-production-code / no-frontend-DOM epic.** Only durable artifact = new root `TESTING.md` (additive). No app, config, or test code changed; the Phase 1 proof file was created, used, and deleted, leaving the tree clean.
  - **Phase 1 — gate proof (transient).** Added throwaway `core/tests/test_gate_proof.py` (`assert False`), staged it, and ran `git commit`. The installed `pre-commit` hook ran both suites; `backend-tests` went red and the hook **rejected the commit** with exit code 1. Then deleted the file and unstaged it. Verified: `git status --porcelain` empty, HEAD unchanged at `4398b27` (Epic 8) — **no commit was created**. Committing is left to the human per build-epic, so the proof is the *failed* commit attempt only.
  - **Captured gate-proof output (verbatim):**
    ```
    backend-tests............................................................Failed
    - hook id: backend-tests
    - exit code: 1

    F.....                                                                   [100%]
    ================================== FAILURES ===================================
    _______________________________ test_gate_proof _______________________________

        def test_gate_proof():
    >       assert False
    E       assert False

    tests\test_gate_proof.py:2: AssertionError
    =========================== short test summary info ===========================
    FAILED tests/test_gate_proof.py::test_gate_proof - assert False
    1 failed, 5 passed in 6.61s

    frontend-tests...........................................................Passed
    ```
  - **Phase 2 — `TESTING.md`.** Wrote root [TESTING.md](../../TESTING.md): standing rule (both suites green to commit), one-time setup (backend Python 3.12 `core/.venv` + `requirements.txt`/`requirements-dev.txt`; frontend `npm install`; gate `pip install pre-commit && pre-commit install`), how to run each suite (`cd core && python -m pytest -q`; `cd frontend && npm test`), the gate and its three mirrors (hook / buildspec / GitHub Actions), and the Windows-venv caveat (`core/.venv/Scripts/python.exe` here vs `core/.venv/bin/python` on POSIX).
  - **Command parity cross-checked verbatim** against the as-built configs: hook entries from `.pre-commit-config.yaml` (lines 12, 19), `pre_build` commands from `ops/buildspec.yml` (lines 25–27), and the workflow steps from `.github/workflows/tests.yml` (lines 27–28, 40–42). Documented commands match the source files exactly.
  - **No regressions:** both suites still green via `core/.venv` (`pytest -q` → `5 passed`; `npm test` → `2 passed`). `git status --porcelain` shows only `?? TESTING.md`.
