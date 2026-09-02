"""Apply the SQL migrations that live with the DBAL schemas.

DBAL builds each table from its entity definition, but its create-table
template emits columns only. Foreign keys and indexes an entity declares are
never created, and a column it stops declaring is never dropped. The
migrations close those gaps, so a database rebuilt from scratch ends up
matching one that has been running.

They belong to DBAL, not to the deployer -- they describe DBAL's tables and
change when its entities do, so they sit beside the schemas in the dbal repo.
Only the running of them lives here, because that needs to know about
containers.

Each file runs once, inside a transaction, and is recorded in
schema_migrations. Files are applied in filename order, so they are named
0001_, 0002_ and so on.
"""

from __future__ import annotations

import argparse
import hashlib
import subprocess
from pathlib import Path

from cli.helpers import (
    BLUE, GREEN, NC, YELLOW, PROJECT_ROOT, log_err, log_ok, log_warn,
)

# Beside the entity schemas they complete, in the sibling dbal checkout.
DBAL_ROOT = PROJECT_ROOT / "dbal"
MIGRATIONS_DIR = (
    DBAL_ROOT / "libraries" / "dbal" / "shared" / "api" / "schema" / "migrations"
)
DBAL_REMOTE = "https://github.com/johndoe6345789/dbal.git"
POSTGRES_CONTAINER = "metabuilder-postgres"

LEDGER = """
CREATE TABLE IF NOT EXISTS schema_migrations (
  name        text PRIMARY KEY,
  checksum    text NOT NULL,
  applied_at  timestamptz NOT NULL DEFAULT now()
);
"""


def _psql(sql: str, container: str) -> subprocess.CompletedProcess:
    """Run SQL inside the Postgres container, using its own credentials."""
    script = (
        'psql -v ON_ERROR_STOP=1 -U "$POSTGRES_USER" -d "$POSTGRES_DB" -f /dev/stdin'
    )
    return subprocess.run(
        ["docker", "exec", "-i", container, "sh", "-lc", script],
        input=sql,
        capture_output=True,
        text=True,
    )


def _applied(container: str) -> dict[str, str]:
    setup = _psql(LEDGER, container)
    if setup.returncode != 0:
        raise RuntimeError(setup.stderr.strip())
    res = _psql("SELECT name || ' ' || checksum FROM schema_migrations;", container)
    if res.returncode != 0:
        raise RuntimeError(res.stderr.strip())
    out: dict[str, str] = {}
    for line in res.stdout.splitlines():
        parts = line.strip().split()
        if len(parts) == 2:
            out[parts[0]] = parts[1]
    return out


def _sync_dbal_checkout() -> None:
    """Keep the sibling dbal checkout current.

    Nothing else in this repo touches DBAL_ROOT -- it exists solely so this
    file has migrations to read -- so it is this file's job to keep it
    fresh. Without this, a migration added to dbal sits here unseen no
    matter how many times a deploy runs: found live, when a migration
    fixing PageConfig's tenant-scoped uniqueness had already landed on
    dbal's main but three consecutive deploys kept reporting the same
    single pre-existing migration file, because DBAL_ROOT was a one-time
    clone from long before this deploy pipeline existed and nothing had
    ever pulled it since.

    Best-effort: a network hiccup here should not fail a deploy over an
    informational sibling checkout, so failures are warned and swallowed --
    the run then proceeds against whatever is already on disk, same as if
    this function did not exist.
    """
    if not DBAL_ROOT.is_dir():
        result = subprocess.run(
            ["git", "clone", "--quiet", DBAL_REMOTE, str(DBAL_ROOT)],
            capture_output=True, text=True,
        )
        if result.returncode != 0:
            log_warn(f"could not clone dbal into {DBAL_ROOT}: {result.stderr.strip()}")
        return

    fetch = subprocess.run(
        ["git", "-C", str(DBAL_ROOT), "fetch", "--quiet", "origin", "main"],
        capture_output=True, text=True,
    )
    if fetch.returncode != 0:
        log_warn(f"could not update dbal checkout at {DBAL_ROOT}: {fetch.stderr.strip()}")
        return
    reset = subprocess.run(
        ["git", "-C", str(DBAL_ROOT), "reset", "--quiet", "--hard", "origin/main"],
        capture_output=True, text=True,
    )
    if reset.returncode != 0:
        log_warn(f"could not update dbal checkout at {DBAL_ROOT}: {reset.stderr.strip()}")


def run_cmd(args: argparse.Namespace, config: dict) -> int:
    container = getattr(args, "container", None) or POSTGRES_CONTAINER
    _sync_dbal_checkout()
    if not MIGRATIONS_DIR.is_dir():
        # The dbal checkout is a sibling; without it there is nothing to apply
        # and no way to tell whether that is correct.
        log_warn(f"no dbal checkout at {MIGRATIONS_DIR}; skipping migrations")
        return 0

    files = sorted(MIGRATIONS_DIR.glob("*.sql"))
    if not files:
        log_warn(f"no migrations in {MIGRATIONS_DIR}")
        return 0

    try:
        applied = _applied(container)
    except RuntimeError as exc:
        log_err(f"cannot reach {container}: {exc}")
        return 1

    print(f"\n{BLUE}{'=' * 43}{NC}")
    print(f"{BLUE}  Migrations: {len(files)} file(s){NC}")
    print(f"{BLUE}{'=' * 43}{NC}\n")

    pending = 0
    for path in files:
        body = path.read_text()
        checksum = hashlib.sha256(body.encode()).hexdigest()[:16]
        seen = applied.get(path.name)

        if seen == checksum:
            print(f"  {GREEN}applied{NC}  {path.name}")
            continue
        if seen is not None:
            # A file that already ran has been edited. Silently re-running it
            # would hide the divergence; refuse and let a new file be added.
            log_err(
                f"{path.name} changed after it was applied "
                f"(recorded {seen}, now {checksum}). Add a new migration "
                "rather than editing one that has run."
            )
            return 1

        if args.dry_run:
            print(f"  {YELLOW}pending{NC}  {path.name}")
            pending += 1
            continue

        print(f"  {YELLOW}running{NC}  {path.name}")
        wrapped = (
            "BEGIN;\n"
            f"{body}\n"
            "INSERT INTO schema_migrations (name, checksum) VALUES "
            f"('{path.name}', '{checksum}');\n"
            "COMMIT;\n"
        )
        res = _psql(wrapped, container)
        if res.returncode != 0:
            log_err(f"{path.name} failed, nothing committed:\n{res.stderr.strip()}")
            return 1
        pending += 1

    if args.dry_run:
        log_ok(f"{pending} migration(s) would run")
    elif pending:
        log_ok(f"{pending} migration(s) applied")
    else:
        log_ok("database is up to date")
    return 0


def run(args: argparse.Namespace, config: dict) -> int:
    """Entry point the loader dispatches to."""
    return run_cmd(args, config)
