# Test Harness & Commit Gate — Epic Plan

Source TDD: [./tdd-P0.1a-test-harness-and-commit-gate.md](./tdd-P0.1a-test-harness-and-commit-gate.md)

> **Review budget:** ~150 changed lines · ~8 non-generated files · one focused commit per epic. Tunable per project.

> This is a high-level agile roadmap. Each epic's design specifics are confirmed
> with stakeholders at epic time (`3-plan-epic`) before any code is written.

## Epic 1 — Backend harness skeleton
- **Goal:** A runnable `pytest` suite under `core/` proven by one trivial passing test — the foundation every later backend test builds on.
- **Rough scope:** New `core/requirements-dev.txt` (test-only deps kept out of the production image), pytest config (async mode, test paths, import path), and a `tests/` package with a shared client fixture.
- **Open questions / decisions for stakeholders:** Pytest config home (`pytest.ini` vs `pyproject.toml`); client fixture style (`TestClient` vs `httpx.ASGITransport`).
- **Depends on:** none.
- **Implementation notes:** _none yet_

## Epic 2 — Health endpoint mocking seam
- **Goal:** Make the `/api/health` db and broker checks individually mockable so the ok/degraded paths can be tested deterministically — no behavior change to the endpoint.
- **Rough scope:** Extract the two connection checks in `core/app/health.py` into named functions the route composes its status from; confirm the public response is unchanged.
- **Open questions / decisions for stakeholders:** Exact function names and the `"ok"`/`"error"` return shape.
- **Depends on:** Epic 1.
- **Implementation notes:** _none yet_

## Epic 3 — Health tests (ok + degraded)
- **Goal:** The first real backend tests — assert the `200/"ok"` path and the `503/"degraded"` path (including a single-check-down case) by mocking the seam from Epic 2.
- **Rough scope:** `core/tests/test_health.py` monkeypatching `check_database` / `check_broker`; no live Postgres/RabbitMQ.
- **Open questions / decisions for stakeholders:** Which degraded combinations to cover (one check down vs both).
- **Depends on:** Epic 2.
- **Implementation notes:** _none yet_

## Epic 4 — Frontend harness skeleton
- **Goal:** A runnable Vitest + Testing Library + jsdom setup under `frontend/`, wired but not yet exercising components.
- **Rough scope:** Add dev deps and `test`/`test:watch` scripts to `package.json`; add a Vitest `test` block (prefer extending `vite.config.ts`) and a `src/test/setup.ts`.
- **Open questions / decisions for stakeholders:** Extend `vite.config.ts` vs a dedicated `vitest.config.ts` (TDD leans toward extending).
- **Depends on:** none.
- **Implementation notes:** _none yet_

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
