"""Command-line interface for runpod-deploy."""

from __future__ import annotations

import argparse
import json
import logging
import sys
from collections.abc import Sequence
from dataclasses import replace
from pathlib import Path

from runpod_deploy.config import build_job_context, load_job_spec, validate_local_paths
from runpod_deploy.orchestrator import run_job
from runpod_deploy.provider import stop_pod

__all__ = ["main"]

logger = logging.getLogger(__name__)


def _configure_logging() -> None:
    """Route runpod_deploy INFO to stdout and WARNING/ERROR to stderr."""
    root = logging.getLogger("runpod_deploy")
    if root.handlers and not all(isinstance(h, logging.NullHandler) for h in root.handlers):
        return
    for handler in list(root.handlers):
        if isinstance(handler, logging.NullHandler):
            root.removeHandler(handler)
    root.setLevel(logging.INFO)
    info_handler = logging.StreamHandler(sys.stdout)
    info_handler.setLevel(logging.INFO)
    info_handler.addFilter(lambda record: record.levelno < logging.WARNING)
    info_handler.setFormatter(logging.Formatter("%(message)s"))
    warn_handler = logging.StreamHandler(sys.stderr)
    warn_handler.setLevel(logging.WARNING)
    warn_handler.setFormatter(logging.Formatter("%(message)s"))
    root.addHandler(info_handler)
    root.addHandler(warn_handler)


def main(argv: Sequence[str] | None = None) -> int:
    """CLI entry point."""
    _configure_logging()
    parser = argparse.ArgumentParser(description="Config-driven RunPod deployment.")
    sub = parser.add_subparsers(dest="command", required=True)

    validate_parser = sub.add_parser("validate", help="Validate a job config.")
    validate_parser.add_argument("--config", type=Path, required=True)
    validate_parser.add_argument(
        "--check-local",
        action="store_true",
        help="Also validate local required_paths against the current filesystem.",
    )

    run_parser = sub.add_parser("run", help="Run a job config.")
    run_parser.add_argument("--config", type=Path, required=True)
    run_parser.add_argument("--dry-run", action="store_true")
    run_parser.add_argument("--offline-dry-run", action="store_true")
    run_parser.add_argument("--cost-cap-usd", type=float, default=None)
    run_parser.add_argument("--max-runtime-minutes", type=int, default=None)

    stop_parser = sub.add_parser("stop", help="Stop a pod from a state file.")
    stop_parser.add_argument("--state-file", type=Path, required=True)
    stop_parser.add_argument("--dry-run", action="store_true")

    args = parser.parse_args(argv)
    if args.command == "validate":
        spec = load_job_spec(args.config)
        ctx = build_job_context(spec, args.config)
        if args.check_local:
            validate_local_paths(ctx)
        logger.info(f"ok: {args.config} schema_version={spec.schema_version} job={spec.name}")
        return 0
    if args.command == "run":
        spec = load_job_spec(args.config)
        if args.cost_cap_usd is not None:
            spec = replace(
                spec,
                budget=replace(spec.budget, cost_cap_usd=float(args.cost_cap_usd)),
            )
        if args.max_runtime_minutes is not None:
            spec = replace(
                spec,
                budget=replace(spec.budget, max_runtime_minutes=int(args.max_runtime_minutes)),
            )
        run_job(
            spec,
            config_path=args.config,
            dry_run=bool(args.dry_run),
            offline_dry_run=bool(args.offline_dry_run),
        )
        return 0
    if args.command == "stop":
        if not args.state_file.exists():
            raise FileNotFoundError(f"state file not found: {args.state_file}")
        payload = json.loads(args.state_file.read_text())
        pod_id = str(payload.get("pod_id") or payload.get("id") or payload.get("podId") or "")
        if not pod_id:
            raise RuntimeError(f"state file has no pod id: {args.state_file}")
        stop_pod(pod_id, dry_run=bool(args.dry_run), state_file=args.state_file)
        return 0
    raise RuntimeError(f"unsupported command: {args.command}")


if __name__ == "__main__":
    raise SystemExit(main())
