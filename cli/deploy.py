"""Build + deploy one or more apps with health check polling."""

import argparse
import sys
import time
from cli.helpers import (
    COMPOSE_FILE, GREEN, RED, YELLOW, BLUE, NC,
    container_health, docker_compose, get_buildable_services,
    get_refreshable_services, log_err, log_warn, resolve_services,
    run as run_proc,
)
from cli.workspace_check import check_workspace
from cli.migrate import run_cmd as run_migrations


def run_cmd(args: argparse.Namespace, config: dict) -> int:
    # The libraries this build compiles against are mounted in and gitignored,
    # so a stale tree would otherwise sail through as a green deploy.
    if not check_workspace(strict=not getattr(args, "skip_workspace_check", False)):
        return 1

    buildable = get_buildable_services()
    targets = buildable if args.all else args.apps
    if not targets:
        log_err("Specify app(s) to deploy, or use --all")
        print(f"Available: {', '.join(buildable)}")
        return 1

    services = resolve_services(targets, config)
    if services is None:
        return 1

    print(f"\n{BLUE}{'=' * 43}{NC}")
    print(f"{BLUE}  Deploy: {' '.join(targets)}{NC}")
    print(f"{BLUE}{'=' * 43}{NC}\n")

    # Step 1: Build
    print(f"{YELLOW}[1/3] Building...{NC}")
    build_args = ["--no-cache"] if args.no_cache else []
    result = run_proc(docker_compose("build", *build_args, *services))
    if result.returncode != 0:
        log_err("Build failed")
        return 1

    # Step 2: Deploy
    #
    # --all also refreshes the first-party images this stack pulls rather
    # than builds. Without it a change to one of those repos publishes a new
    # :latest and never arrives: compose keeps the image already on the host,
    # so the deploy is green and the code is old.
    deploying = list(services)
    if args.all:
        refreshable = get_refreshable_services()
        if refreshable:
            print(f"  refreshing pulled images: {', '.join(refreshable)}")
            pull = run_proc(docker_compose("pull", *refreshable))
            if pull.returncode != 0:
                log_warn("Could not pull one or more images; using what is on the host")
            deploying += refreshable

    print(f"\n{YELLOW}[2/3] Deploying...{NC}")
    result = run_proc(docker_compose("up", "-d", "--force-recreate", *deploying))
    if result.returncode != 0:
        log_err("Deploy failed")
        return 1

    # Step 3: Health check
    print(f"\n{YELLOW}[3/3] Waiting for health checks...{NC}")
    all_healthy = True
    for svc in deploying:
        container = f"metabuilder-{svc}"
        sys.stdout.write(f"  {svc}: ")
        sys.stdout.flush()

        status = "unknown"
        for _ in range(30):
            status = container_health(container)
            if status in ("healthy", "unhealthy"):
                break
            time.sleep(2)

        if status == "healthy":
            print(f"{GREEN}healthy{NC}")
        elif status == "unhealthy":
            print(f"{RED}unhealthy{NC}")
            all_healthy = False
        else:
            print(f"{YELLOW}timeout (status: {status}){NC}")
            all_healthy = False

    print()
    if not all_healthy:
        log_warn(f"Some services not healthy — check: docker compose -f {COMPOSE_FILE} ps")
        return 1

    print(f"{GREEN}All services deployed and healthy{NC}")

    # Foreign keys, index changes and dropped columns are not something an
    # entity schema can express, so they arrive here instead. Run once the
    # database is actually up.
    migrated = run_migrations(
        argparse.Namespace(dry_run=False, container=None), config
    )
    if migrated != 0:
        log_err("migrations failed; the stack is up but its schema is behind")
        return 1

    return 0


run = run_cmd
