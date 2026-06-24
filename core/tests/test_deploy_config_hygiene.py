"""Deploy-config alignment proofs for the demo/session knobs (Epic 13).

The core container reads its demo/session lifecycle knobs from the process
environment (`app/config.py`), but those values only reach the container if
`docker-compose.yml` actually passes them in via an explicit `core.environment`
entry. Before Epic 13 the seam carried only `DATABASE_URL` / `RABBITMQ_URL`, so
every other knob silently used its code default in the deployment regardless of
`ops/deploy/prod.env.defaults`. These guards catch the two ways that seam can
silently break:

- **Compose seam:** every demo/session knob `config.py` reads has a matching
  `core.environment` entry in `docker-compose.yml` (catches a silent typo or a
  forgotten knob — the env file value would never reach the app).
- **Env-file drift:** `ops/deploy/prod.env.defaults` sets each of the five demo
  values Epic 13 chose, so the compose seam and the env file can't drift apart.

Both read the files as text (no YAML/env parser dependency, matching the plain
file-scan style of `test_migration_hygiene.py`) and resolve their paths relative
to the repo root (`CORE_ROOT.parent`).
"""

import re

from tests.conftest import CORE_ROOT

REPO_ROOT = CORE_ROOT.parent
DOCKER_COMPOSE_PATH = REPO_ROOT / "docker-compose.yml"
PROD_ENV_DEFAULTS_PATH = REPO_ROOT / "ops" / "deploy" / "prod.env.defaults"

# The demo/session lifecycle knobs `app/config.py` reads from the environment.
# These are the knobs whose deploy-time values must actually reach the container,
# so each must have a `core.environment` entry in docker-compose.yml.
DEMO_SESSION_ENV_KNOBS = (
    "SESSION_LIFETIME_SECONDS",
    "DEMO_SESSION_LIFETIME_SECONDS",
    "DEMO_PURGE_INTERVAL_SECONDS",
    "DEMO_NIGHTLY_RESET_HOUR_UTC",
    "SESSION_COOKIE_SECURE",
)

# The demo values Epic 13 sets in ops/deploy/prod.env.defaults: knob -> value.
EXPECTED_PROD_DEMO_VALUES = {
    "SESSION_LIFETIME_SECONDS": "86400",
    "DEMO_SESSION_LIFETIME_SECONDS": "86400",
    "DEMO_PURGE_INTERVAL_SECONDS": "300",
    "DEMO_NIGHTLY_RESET_HOUR_UTC": "4",
    "SESSION_COOKIE_SECURE": "true",
}


def read_core_environment_keys() -> set[str]:
    """Return the env-var names declared under the `core` service's `environment`.

    Scans `docker-compose.yml` as text: find the `core:` service block, then the
    `environment:` mapping inside it, and collect each `KEY: value` line until the
    mapping ends (a line dedents back to the service-property indent level). Plain
    text rather than a YAML parser keeps the guard dependency-free, matching
    `test_migration_hygiene.py`'s file-scan style.
    """
    lines = DOCKER_COMPOSE_PATH.read_text(encoding="utf-8").splitlines()

    in_core_service = False
    in_environment = False
    environment_indent: int | None = None
    keys: set[str] = set()

    for line in lines:
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue

        indent = len(line) - len(line.lstrip())

        # Top-level service headers sit at two-space indent (`  core:`).
        if indent == 2 and stripped.endswith(":"):
            in_core_service = stripped == "core:"
            in_environment = False
            environment_indent = None
            continue

        if not in_core_service:
            continue

        if not in_environment:
            if stripped == "environment:":
                in_environment = True
            continue

        # First entry under `environment:` fixes the mapping's indent.
        if environment_indent is None:
            environment_indent = indent

        # A line that dedents below the mapping ends the environment block.
        if indent < environment_indent:
            in_environment = False
            environment_indent = None
            continue

        match = re.match(r"([A-Za-z_][A-Za-z0-9_]*)\s*:", stripped)
        if match:
            keys.add(match.group(1))

    return keys


def read_prod_env_defaults() -> dict[str, str]:
    """Return the `KEY=value` pairs declared in `prod.env.defaults`.

    Skips blank lines and `#` comments; the env file is a flat list of
    `KEY=value` lines (no quoting), so a plain split is enough.
    """
    pairs: dict[str, str] = {}
    for raw_line in PROD_ENV_DEFAULTS_PATH.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        pairs[key.strip()] = value.strip()
    return pairs


def test_every_demo_session_knob_has_a_compose_environment_entry():
    """Each demo/session knob config.py reads is passed in via core.environment.

    Without an explicit `core.environment` entry, the deploy-time `.env` value for
    a knob never reaches the container — it silently uses the code default. This
    guard fails if a knob is missing or its name is mistyped in the compose seam.
    """
    core_environment_keys = read_core_environment_keys()
    missing = [
        knob
        for knob in DEMO_SESSION_ENV_KNOBS
        if knob not in core_environment_keys
    ]
    assert not missing, (
        "docker-compose.yml core.environment is missing entries for "
        f"{missing}; without them the deploy-time .env value never reaches the "
        "container and the knob silently uses its code default."
    )


def test_prod_env_defaults_sets_the_demo_values():
    """prod.env.defaults sets each of the five demo values Epic 13 chose.

    Pairs with the compose-seam guard: the seam ensures the values *can* reach the
    container, this ensures the env file actually *sets* them, so the two can't
    drift apart.
    """
    prod_env = read_prod_env_defaults()
    mismatches = {
        knob: (expected, prod_env.get(knob))
        for knob, expected in EXPECTED_PROD_DEMO_VALUES.items()
        if prod_env.get(knob) != expected
    }
    assert not mismatches, (
        "ops/deploy/prod.env.defaults demo values disagree with Epic 13 "
        f"(knob -> (expected, actual)): {mismatches}"
    )
