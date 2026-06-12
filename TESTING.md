# Testing

How to run the test suites, set up the commit gate, and where the same gate runs
in CI. There are two suites — a backend `pytest` suite under `core/` and a
frontend Vitest suite under `frontend/` — and one gate that runs both.

## Standing rule

Every change updates the relevant tests, and **both suites must be green to
commit**. The local `pre-commit` hook enforces this: a red suite blocks the
commit. The same two suites also gate the CodeBuild image build and run on every
push and pull request in GitHub Actions, so a red tree cannot ship.

## One-time setup

### Backend (`core/`)

Create a Python 3.12 virtual environment and install the runtime and dev
dependencies into it:

```bash
cd core
python -m venv .venv
.venv/Scripts/python.exe -m pip install -r requirements.txt -r requirements-dev.txt
```

The runtime dependencies (`requirements.txt`) are needed because the tests import
`app.main`; the dev-only test dependencies (`requirements-dev.txt`) supply pytest,
httpx, and pytest-asyncio. The `.venv/` directory is gitignored and must never be
committed.

> On macOS/Linux the interpreter is `.venv/bin/python` instead of
> `.venv/Scripts/python.exe`. See the Windows-venv caveat below.

### Frontend (`frontend/`)

Install the Node dependencies (Node 20):

```bash
cd frontend
npm install
```

### Commit gate

Install [pre-commit](https://pre-commit.com/) and register the git hook:

```bash
pip install pre-commit
pre-commit install
```

This installs the hook at `.git/hooks/pre-commit` from
[.pre-commit-config.yaml](.pre-commit-config.yaml), so both suites run on every
`git commit`.

## How to run each suite

Run the backend suite:

```bash
cd core
python -m pytest -q
```

Run the frontend suite:

```bash
cd frontend
npm test
```

On a green tree the backend reports `5 passed` and the frontend reports
`2 passed`.

## The gate and its three mirrors

The same two commands — backend `pytest` and frontend Vitest — run in three
places so a red tree is caught at every stage. A red suite blocks the commit and
fails the build.

1. **Local `pre-commit` hook** —
   [.pre-commit-config.yaml](.pre-commit-config.yaml). Two `language: system`
   hooks with `always_run: true` run on every commit:
   - `backend-tests`: `bash -c 'cd core && ./.venv/Scripts/python.exe -m pytest -q'`
   - `frontend-tests`: `bash -c 'cd frontend && npm test --silent'`

   A failing suite exits non-zero and the hook rejects the commit.

2. **CodeBuild `pre_build` step** — [ops/buildspec.yml](ops/buildspec.yml). Both
   suites run in `pre_build`, before any ECR login or `docker build`, so a red
   tree fails the build and no image is pushed:
   - `pip install --quiet --requirement core/requirements.txt --requirement core/requirements-dev.txt`
   - `(cd core && python -m pytest -q)`
   - `(cd frontend && npm ci && npm test --silent)`

3. **GitHub Actions workflow** —
   [.github/workflows/tests.yml](.github/workflows/tests.yml). On every push and
   pull request, two parallel jobs run on `ubuntu-latest`:
   - `backend`: `pip install --requirement core/requirements.txt --requirement core/requirements-dev.txt` then `python -m pytest -q` (working directory `core`).
   - `frontend`: `npm ci` then `npm test --silent` (working directory `frontend`).

## Windows-venv caveat

This host's system Python is 3.14, which cannot import the app (the runtime pins
have no 3.14 wheels), so the backend hook calls the project's Python 3.12
interpreter directly: `core/.venv/Scripts/python.exe`. On a POSIX host
(macOS/Linux) the venv interpreter lives at `core/.venv/bin/python` instead — a
one-line adjustment to the `backend-tests` hook `entry` in
[.pre-commit-config.yaml](.pre-commit-config.yaml):

```yaml
# Windows (as committed):
entry: bash -c 'cd core && ./.venv/Scripts/python.exe -m pytest -q'

# macOS/Linux:
entry: bash -c 'cd core && ./.venv/bin/python -m pytest -q'
```

This affects only the local hook. CodeBuild and GitHub Actions provide Python 3.12
on a clean runner and call plain `python -m pytest -q`, so they need no venv.
