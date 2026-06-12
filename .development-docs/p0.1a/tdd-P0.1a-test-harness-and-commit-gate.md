# P0.1a — Test Harness & Commit Gate — Technical Design Document

## 1. Summary

Stand up the automated test harness and a blocking commit gate that every later
phase inherits. Backend gets `pytest` (+ `httpx`, `pytest-asyncio`) under `core/`
with the first real tests on the `/api/health` **ok** and **degraded** paths;
frontend gets Vitest + Testing Library under `frontend/` with a shell smoke test.
A `pre-commit` hook runs **both** suites and **blocks the commit on any failure**;
the same suites run in CI (a test step in CodeBuild's `buildspec.yml` *before*
image build, plus a GitHub Actions workflow on push/PR). A short `TESTING.md`
records the standing rule — *every change updates the relevant tests, and the
suite must be green to commit*. The gate is proven live by showing a deliberately
broken test fails the commit. This phase establishes test culture before any
feature exists; it does not gate the already-passed P0.1 exit test but must be
green before Milestone 1 feature work begins.

## 2. Business Requirements

Lifted from `program-and-phase-plan.md` → **P0.1a** (lines 158–180) and the
*Tests ship with every slice* principle:

- `pytest` runs core's suite, starting with the `/api/health` **ok** and
  **degraded** paths.
- Vitest runs the SPA suite — a smoke test until real React components land
  (P0.1 Epics 4–5 / P1.6+).
- A `pre-commit` hook runs **both** suites and **blocks the commit on any failure**.
- The **same suites run in CI**.
- A short `TESTING.md` states the standing rule: every change updates the relevant
  test cases and the suite must be green to commit.
- A deliberately broken test fails the commit — proving the gate is live, not
  decorative.
- Tooling is **frozen** by the program plan (Decide-Once #11): `pytest` (+ `httpx`,
  `pytest-asyncio`) for core/sidecars, Vitest + Testing Library for the SPA,
  orchestrated by the `pre-commit` framework as the commit gate; the same suites
  run in CI. Every later phase only adds cases behind this gate.

## 3. Goals / Non-Goals

**Goals**
- A runnable, fast, deterministic backend suite under `core/` covering health
  ok + degraded.
- A runnable frontend suite under `frontend/` with a passing shell smoke test.
- A `pre-commit` config that runs both suites and blocks red commits.
- CI runs both suites: inline in `ops/buildspec.yml` (gates image build) **and**
  a GitHub Actions workflow on push/PR.
- `TESTING.md` documenting the standing rule and how to run/set up each suite.
- Demonstrable proof the gate blocks a deliberately broken test.

**Non-Goals**
- Real FE component tests (arrive with P0.1 Epics 4–5 / P1.6+).
- Tenant-isolation / PII-masking fixtures (→ P1.2 / P1.3).
- End-to-end / browser tests (→ later, as UI surfaces land).
- Linting/formatting/type-check hooks — out of scope for this phase (the gate is
  about the **test** suites; lint/format can be added later without rework).
- Gating the P0.1 exit test (already passed); this phase is orthogonal to deploy.
- New Terraform / CodeBuild projects — the CI test step rides inside the existing
  `buildspec.yml` `pre_build` phase.

## 4. Current State

- **Backend** — [core/app/main.py](../../core/app/main.py) mounts the health
  router; [core/app/health.py](../../core/app/health.py) exposes `GET /api/health`
  returning `200 {"status":"ok",...}` when both checks pass and `503
  {"status":"degraded",...}` when any fails. Checks do **real**
  `asyncpg.connect()` + `SELECT 1` (db) and `aio_pika.connect()` + close (broker);
  URLs read from `DATABASE_URL` / `RABBITMQ_URL` via
  [core/app/config.py](../../core/app/config.py). Deps in
  [core/requirements.txt](../../core/requirements.txt) (FastAPI 0.115.6, asyncpg,
  aio-pika, alembic, psycopg); **Python 3.12**. No `pyproject.toml`. **No tests,
  no conftest, no pytest config exist yet.**
- **Frontend** — [frontend/package.json](../../frontend/package.json): Vite 5.4.11,
  React 18.3.1, TypeScript 5.6.3, react-router-dom 6.30.4; scripts `dev`/`build`/
  `preview` only. Shell in [frontend/src/App.tsx](../../frontend/src/App.tsx)
  (routes `/` → LandingPage, `/select-tenant` → SelectTenantPage),
  [frontend/src/main.tsx](../../frontend/src/main.tsx),
  [frontend/src/components/PageLayout.tsx](../../frontend/src/components/PageLayout.tsx).
  **No Vitest/Testing Library config or test files exist yet.**
- **CI/CD** — [ops/buildspec.yml](../../ops/buildspec.yml) (CodeBuild) builds +
  pushes core/frontend images to ECR; [appspec.yml](../../appspec.yml) + `ops/deploy/*`
  run CodeDeploy. **No `.github/workflows/`, no `.pre-commit-config.yaml`, no
  `TESTING.md`.**
- **Constraints** — `CLAUDE.md`: descriptive naming (no `cfg`/`req`/`res`/`e`),
  booleans read as questions, natural-language verbs. Frontend ID rule does not
  bite here (no new rendered DOM). Memory: minimal-churn, insertion-style doc edits;
  dev is local-only, prod on EC2.

## 5. Proposed Design

### High-level approach
Two self-contained suites, each idiomatic to its stack, wired behind one
`pre-commit` config and mirrored in CI. Health tests are **mock-based** (no live
Postgres/RabbitMQ) so the suite is fast, deterministic, and runs anywhere — laptop,
hook, CodeBuild, GitHub Actions.

### Components added

**Backend (`core/`)**
- `core/requirements-dev.txt` — `pytest`, `httpx`, `pytest-asyncio` (kept out of the
  runtime image; production `Dockerfile` keeps installing only `requirements.txt`).
- `core/pytest.ini` (or `[tool.pytest.ini_options]` in a new lightweight config) —
  sets `asyncio_mode = auto`, test paths, and a sane `testpaths`/`pythonpath` so
  `from app.health import ...` imports resolve.
- `core/tests/__init__.py`, `core/tests/conftest.py` — a FastAPI `TestClient` /
  `httpx.ASGITransport` fixture against `app.main:app`.
- `core/tests/test_health.py` — the first real tests:
  - **ok path**: monkeypatch the db-check and broker-check helpers to report
    healthy → assert `200` and `{"status":"ok","checks":{"db":"ok","broker":"ok"}}`.
  - **degraded path**: monkeypatch one (and/or both) checks to report failure →
    assert `503` and `{"status":"degraded", ...}` with the failed check marked
    `"error"`.
  - *Refactor enabler:* the two connection checks in `health.py` are extracted into
    named, individually-mockable functions (e.g. `check_database()` /
    `check_broker()` returning `"ok"`/`"error"`) if they are not already separable.
    This is the minimal seam needed for deterministic mocking — no behavior change.

**Frontend (`frontend/`)**
- Dev deps added to `package.json`: `vitest`, `@testing-library/react`,
  `@testing-library/jest-dom`, `@testing-library/dom`, `jsdom`,
  `@vitejs/plugin-react` (already present).
- `test` script(s): `"test": "vitest run"` and `"test:watch": "vitest"`.
- Vitest config — extend [frontend/vite.config.ts](../../frontend/vite.config.ts)
  with a `test` block (`environment: "jsdom"`, `globals: true`, a `setupFiles`
  entry) **or** a dedicated `vitest.config.ts`. Prefer extending `vite.config.ts`
  to reuse the React plugin and avoid a second config.
- `frontend/src/test/setup.ts` — imports `@testing-library/jest-dom/vitest`.
- `frontend/src/App.test.tsx` — smoke test: render `<App>` inside a router and
  assert the landing shell renders (a stable wordmark/heading from `PageLayout`),
  proving the harness wires React + Testing Library + jsdom end-to-end.

**Commit gate (`.pre-commit-config.yaml` at repo root)**
- Two `language: system` hooks (per decision — call the host toolchain, no
  pre-commit-managed envs):
  - `backend-tests` — runs `pytest` against `core/` (e.g.
    `bash -c 'cd core && python -m pytest -q'`).
  - `frontend-tests` — runs `npm run test --silent` in `frontend/`
    (e.g. `bash -c 'cd frontend && npm test --silent'`).
- Both hooks: `always_run: true`, `pass_filenames: false`, `stages: [pre-commit]`
  — **every commit runs both suites** (per decision; no path filtering). CI is the
  redundant safety net.
- A red suite → non-zero exit → commit blocked.

**CI**
- `ops/buildspec.yml` — add install + run steps to the **`pre_build`** phase that
  execute both suites **before** any `docker build`; a non-zero exit fails the
  build, so no image is pushed from a red tree. (Install Python dev deps + run
  `pytest`; `npm ci` + `npm test` in `frontend/`.)
- `.github/workflows/tests.yml` — on `push` and `pull_request`: a job that sets up
  Python 3.12 (install `requirements.txt` + `requirements-dev.txt`, run `pytest`)
  and a job that sets up Node 20 (`npm ci`, `npm test`) in `frontend/`. Mirrors the
  exact commands the hook + buildspec run.

**Docs**
- `TESTING.md` (repo root) — the standing rule, one-time setup (create venv +
  `pip install -r core/requirements.txt -r core/requirements-dev.txt`;
  `npm install` in `frontend/`; `pip install pre-commit && pre-commit install`),
  how to run each suite, and how the gate + CI mirror each other.

### Primary flow — a commit
```
dev edits code ──> git commit
                      │
                      ▼
         pre-commit gate (.pre-commit-config.yaml)
            ├─ backend-tests:  cd core && pytest -q
            └─ frontend-tests: cd frontend && npm test
                      │
              any non-zero? ──► commit REJECTED (red, message shown)
                      │
                   all green ──► commit created
                      │
                      ▼
        push to main ──► CodeBuild buildspec.yml
                          pre_build: run pytest + vitest ──► red? build fails (no ECR push)
                          build: docker build/push images
        (parallel)  GitHub Actions tests.yml on push/PR ──► red? checks fail
```

### Interfaces
- `check_database() -> str` and `check_broker() -> str` (returning `"ok"`/`"error"`)
  in `core/app/health.py` — the mockable seam; the route composes status from them.
  No public API/payload change to `/api/health`.
- npm scripts: `test`, `test:watch`. No change to `build`/`dev`/`preview`.

### Diagram
Not needed — the flow is the single linear gate above; no offer made.

## 6. Decisions

| # | Decision | Chosen | Alternatives considered | Rationale |
|---|---|---|---|---|
| A | Health-test isolation | **Mock-based** unit tests (monkeypatch db/broker checks) | Tests against live containers | Fast, deterministic, runs in the hook and CI without standing up Postgres/RabbitMQ. |
| B | Where CI runs the suites | **Both** — inline in `buildspec.yml` `pre_build` **and** a GitHub Actions workflow | buildspec-only; GHA-only | Belt-and-suspenders: build gate blocks a red image; GHA gives branch/PR-level signal without a push to `main`. |
| C | Hook execution model | **`language: system` hooks** calling host `pytest`/`npm` | pre-commit-managed Python env (+ `additional_dependencies`) | Simplest, fastest, no duplicated dependency tree; dev runs documented one-time setup; pre-commit is built for this. |
| D | Backend dev-dep placement | **Separate `core/requirements-dev.txt`** | Add to `core/requirements.txt` | Keeps test deps out of the production image; runtime `Dockerfile` unchanged. |
| E | Hook scope | **Always run both suites** every commit | Path-filtered (`core/**` / `frontend/**`) | Maximally safe locally; suites are tiny/fast at this stage; no risk of a cross-cutting change skipping a suite. |
| F | Vitest DOM environment | **jsdom** | happy-dom | Standard, broadest Testing Library compatibility; the safest default for the shell smoke test and future component tests. |
| G | CI gate placement | **Inline in `pre_build`** of existing `buildspec.yml` | Separate buildspec / new CodePipeline stage | No new Terraform/CodeBuild wiring for a Size-S phase; tests still gate the artifact before build. |

## 7. Risks and Open Questions

- **Host-toolchain dependency (Decision C/E).** `language: system` hooks assume the
  dev has set up the venv + `npm install`. *Mitigation:* `TESTING.md` documents the
  exact one-time setup; hooks fail with a clear message if `pytest`/`npm` is missing.
- **`health.py` mocking seam.** If the connection checks are inline in the route
  handler, the ok/degraded paths can't be mocked cleanly. *Mitigation:* extract
  `check_database()` / `check_broker()` as named functions (no behavior change) —
  small, in-scope refactor flagged in Work Breakdown.
- **CodeBuild image lacks Node/Python by default.** The `pre_build` test step needs
  both runtimes available. *Mitigation:* the CodeBuild image is already Docker-based
  for image builds; confirm Python 3.12 + Node 20 are installable/present in the
  build environment, or install them in `install` phase before the test step.
- **Async test mode.** `pytest-asyncio` mode must be set (`asyncio_mode = auto`) or
  async tests silently skip. *Mitigation:* assert it in config; the health smoke
  test exercises the async path so a misconfig fails loudly.
- **Commit speed creep (Decision E).** Always-run will get slower as suites grow.
  *Mitigation:* revisit path-filtering if/when commit time becomes a friction point;
  CI already runs unconditionally so local filtering would not reduce safety.
- **Open:** exact CodeBuild base image runtime availability — verified during the CI
  epic, not a blocker for the harness itself.

## 8. Rollout / Verification

**Manual verification (proves the gate is live)**
1. One-time setup per `TESTING.md` (venv + dev deps; `npm install`;
   `pre-commit install`).
2. `cd core && python -m pytest -q` → health ok + degraded tests pass.
3. `cd frontend && npm test` → App smoke test passes.
4. Stage a trivial change and `git commit` → both suites run, commit succeeds.
5. **Break a test deliberately** (e.g. assert `200` where `503` is expected) →
   `git commit` → gate **rejects** the commit with the failing suite's output.
   Revert the break.
6. Push to a branch → GitHub Actions `tests.yml` runs both suites and reports
   status on the PR; a red tree fails the checks.
7. (CI build path) a `pre_build` red suite fails the CodeBuild build before any ECR
   push — verified when the buildspec change lands.

**Rollout / compatibility**
- Purely additive: no runtime code path or API changes; production `Dockerfile`
  and images are untouched (dev deps excluded).
- Does **not** gate the P0.1 exit test; safe to land any time after P0.1, and
  **must be green before Milestone 1 (P1.1) feature work begins**.
- No migrations, no feature flags. Reversible by removing the configs/hooks.

## 9. Work Breakdown

Ordered simplest-first — a thin backend walking skeleton first, then frontend, then
the gate, then CI, then proof and docs. Each item is narrow and independently
reviewable.

1. **Backend harness skeleton.** Add `core/requirements-dev.txt` (`pytest`,
   `httpx`, `pytest-asyncio`); add pytest config (`asyncio_mode = auto`, testpaths,
   pythonpath); add `core/tests/__init__.py` + `core/tests/conftest.py` with an
   ASGI/`TestClient` fixture; add one trivial passing test to prove the harness
   runs.
2. **Health endpoint mocking seam.** Extract `check_database()` / `check_broker()`
   in `core/app/health.py` as named, individually-mockable functions (no behavior
   change); confirm `/api/health` still composes status from them.
3. **Health tests (ok + degraded).** `core/tests/test_health.py`: monkeypatch the
   two checks to assert the `200/"ok"` path and the `503/"degraded"` path
   (including a single-check-down case).
4. **Frontend harness skeleton.** Add Vitest + Testing Library + jsdom dev deps and
   `test`/`test:watch` scripts to `package.json`; add the Vitest `test` block to
   `vite.config.ts` (jsdom, globals, setupFiles); add `src/test/setup.ts`.
5. **Frontend smoke test.** `src/App.test.tsx` renders `<App>` (in a router) and
   asserts a stable shell element renders.
6. **Commit gate.** Add root `.pre-commit-config.yaml` with two `language: system`
   hooks (`backend-tests`, `frontend-tests`), `always_run: true`,
   `pass_filenames: false`; document `pre-commit install`.
7. **CI — CodeBuild.** Add install + run steps for both suites to the `pre_build`
   phase of `ops/buildspec.yml`, before `docker build`.
8. **CI — GitHub Actions.** Add `.github/workflows/tests.yml` (push + PR): Python
   3.12 job (pytest) and Node 20 job (vitest), mirroring the hook/buildspec commands.
9. **Prove the gate + docs.** Demonstrate a deliberately broken test blocks a commit
   (then revert); write `TESTING.md` (standing rule + one-time setup + how to run +
   how the gate and CI mirror each other).
