"""Apply SQL migrations that the entity schemas cannot express.

DBAL builds each table from its entity definition, but its create-table
template emits columns only. Foreign keys and indexes an entity declares are
never created, and a column it stops declaring is never dropped. Those gaps
are what these files close, so a database rebuilt from scratch ends up
matching one that has been running.

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
    BLUE, GREEN, NC, YELLOW, SCRIPT_DIR, log_err, log_ok, log_warn,
)

MIGRATIONS_DIR = SCRIPT_DIR / "migrations"
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


def run_cmd(args: argparse.Namespace, config: dict) -> int:
    container = getattr(args, "container", None) or POSTGRES_CONTAINER
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
