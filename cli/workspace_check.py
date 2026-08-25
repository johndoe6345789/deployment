"""Preflight: is the assembled workspace the one we think we are deploying?

MetaBuilder is a micro-repo build. Its libraries/, redux/, dbal/ and packages/
trees are not in its git history -- they are mounted in by
.github/scripts/assemble_workspace.py and gitignored. That has two
consequences a deploy has to defend against:

  * `git pull` never updates them, so a deploy can rebuild happily against a
    snapshot assembled weeks ago and report success.
  * an edit made directly in one of those trees is invisible to git, so it can
    look applied locally and never exist anywhere else.

Both fail silently. This turns them into a stopped deploy instead.
"""

from __future__ import annotations

import json
from pathlib import Path

from cli.helpers import PROJECT_ROOT, log_err, log_ok, log_warn

MANIFEST_REL = Path(".github/workspace.json")
LOCK_REL = Path(".workspace-lock.json")


def _metabuilder_root() -> Path | None:
    """The sibling metabuilder checkout, if there is one."""
    candidate = PROJECT_ROOT / "metabuilder"
    return candidate if (candidate / MANIFEST_REL).is_file() else None


def check_workspace(strict: bool = True) -> bool:
    """Compare the assembled trees against the manifest's pins.

    Returns True if the deploy should proceed. `strict=False` downgrades a
    mismatch to a warning, for the case where you knowingly want to ship
    whatever is on disk.
    """
    root = _metabuilder_root()
    if root is None:
        # Nothing to check against; deployment is usable without the sibling.
        return True

    manifest = json.loads((root / MANIFEST_REL).read_text())
    pinned = {r["repo"]: r.get("ref", "") for r in manifest.get("repos", [])}

    lock_path = root / LOCK_REL
    if not lock_path.is_file():
        log_err(
            f"{LOCK_REL} is missing from {root}.\n"
            "  The mounted libraries/, redux/, dbal/ and packages/ trees are\n"
            "  gitignored, so nothing records which commits they came from --\n"
            "  they may be months old. Assemble them before deploying:\n"
            f"    cd {root} && python3 .github/scripts/assemble_workspace.py "
            "--all --pinned --force"
        )
        return not strict

    lock = json.loads(lock_path.read_text())
    assembled = lock.get("repos", {})

    drift: list[str] = []
    for repo, want in sorted(pinned.items()):
        have = assembled.get(repo)
        if have is None:
            drift.append(f"  {repo}: not assembled (manifest pins {want[:7]})")
        elif want and have != want:
            drift.append(f"  {repo}: on disk {have[:7]}, manifest pins {want[:7]}")

    if lock.get("floating"):
        log_warn(
            "workspace was assembled floating (branch heads), so this build is "
            "not reproducible from workspace.json"
        )

    if drift:
        detail = "\n".join(drift)
        message = (
            "assembled workspace does not match workspace.json:\n"
            f"{detail}\n"
            "  Re-assemble to match the pins:\n"
            f"    cd {root} && python3 .github/scripts/assemble_workspace.py "
            "--all --pinned --force\n"
            "  ...or bump the pins if the newer commits are the ones you want."
        )
        if strict:
            log_err(message)
            return False
        log_warn(message)
        return True

    log_ok(
        f"workspace matches workspace.json ({len(assembled)} repo(s), "
        f"assembled {lock.get('assembled_at', 'unknown')})"
    )
    return True
