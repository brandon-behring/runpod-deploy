"""Command-line interface for runpod-deploy."""

from __future__ import annotations

import argparse
import json
import logging
import shlex
import sys
from collections.abc import Sequence
from dataclasses import replace
from pathlib import Path

from runpod_deploy import preflight
from runpod_deploy.config import build_job_context, load_job_spec, validate_local_paths
from runpod_deploy.orchestrator import run_job
from runpod_deploy.provider import run_json, stop_pod
from runpod_deploy.transport import RemoteRunner

__all__ = ["main"]

logger = logging.getLogger(__name__)


def _configure_logging(level: int = logging.INFO) -> None:
    """Route runpod_deploy DEBUG/INFO to stdout and WARNING/ERROR to stderr."""
    root = logging.getLogger("runpod_deploy")
    for handler in list(root.handlers):
        root.removeHandler(handler)
    root.setLevel(level)
    info_handler = logging.StreamHandler(sys.stdout)
    info_handler.setLevel(level)
    info_handler.addFilter(lambda record: record.levelno < logging.WARNING)
    info_handler.setFormatter(logging.Formatter("%(message)s"))
    warn_handler = logging.StreamHandler(sys.stderr)
    warn_handler.setLevel(logging.WARNING)
    warn_handler.setFormatter(logging.Formatter("%(message)s"))
    root.addHandler(info_handler)
    root.addHandler(warn_handler)


def _verbosity_parser() -> argparse.ArgumentParser:
    """Parent parser supplying --verbose/--quiet to every subcommand."""
    parent = argparse.ArgumentParser(add_help=False)
    group = parent.add_mutually_exclusive_group()
    group.add_argument("--verbose", "-v", action="store_true", help="Show DEBUG output.")
    group.add_argument(
        "--quiet", "-q", action="store_true", help="Suppress INFO; show only warnings/errors."
    )
    return parent


def _level_from_args(args: argparse.Namespace) -> int:
    if getattr(args, "verbose", False):
        return logging.DEBUG
    if getattr(args, "quiet", False):
        return logging.WARNING
    return logging.INFO


def _cmd_validate(args: argparse.Namespace) -> int:
    spec = load_job_spec(args.config)
    ctx = build_job_context(spec, args.config)
    if args.all or args.check_local:
        validate_local_paths(ctx)
    if args.all or args.check_availability:
        preflight.check_gpu_availability(ctx)
    if args.all or args.scan_consumer:
        preflight.scan_consumer_pyproject(ctx)
        preflight.scan_staged_payloads_for_absolute_paths(ctx)
    logger.info(f"ok: {args.config} schema_version={spec.schema_version} job={spec.name}")
    return 0


def _cmd_gpu_list(args: argparse.Namespace) -> int:
    entry = preflight.fetch_datacenter_payload(args.datacenter)
    availability = entry.get("gpuAvailability") or []
    rows: list[tuple[str, str]] = []
    if isinstance(availability, list):
        for item in availability:
            if isinstance(item, dict):
                name = str(item.get("gpuId") or "")
                status = str(item.get("stockStatus") or "").strip()
                if name:
                    rows.append((name, status or "—"))
    tier_rank = {"high": 0, "medium": 1, "low": 2}
    rows.sort(key=lambda row: (tier_rank.get(row[1].lower(), 99), row[0]))
    name_width = max((len(name) for name, _ in rows), default=3)
    logger.info(f"datacenter: {args.datacenter}")
    logger.info(f"{'gpu':<{name_width}}  stock")
    for name, status in rows:
        logger.info(f"{name:<{name_width}}  {status}")
    return 0


def _cmd_run(args: argparse.Namespace) -> int:
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


def _cmd_stop(args: argparse.Namespace) -> int:
    if not args.state_file.exists():
        raise FileNotFoundError(f"state file not found: {args.state_file}")
    payload = json.loads(args.state_file.read_text())
    pod_id = str(payload.get("pod_id") or payload.get("id") or payload.get("podId") or "")
    if not pod_id:
        raise RuntimeError(f"state file has no pod id: {args.state_file}")
    stop_pod(pod_id, dry_run=bool(args.dry_run), state_file=args.state_file)
    return 0


def _cmd_logs(args: argparse.Namespace) -> int:
    spec = load_job_spec(args.config)
    state_file = spec.resolved_state_file
    if not state_file.exists():
        raise FileNotFoundError(f"state file not found: {state_file}")
    state = json.loads(state_file.read_text())
    pod_id = str(state.get("pod_id") or "")
    if not pod_id:
        raise RuntimeError(f"state file has no pod_id: {state_file}")
    payload = run_json(["runpodctl", "pod", "get", pod_id, "-o", "json"])
    ssh_info_raw = payload.get("ssh") if isinstance(payload, dict) else None
    ssh_info = ssh_info_raw if isinstance(ssh_info_raw, dict) else {}
    host = str(ssh_info.get("ip") or "")
    port = int(ssh_info.get("port") or 0)
    if not host or not port:
        raise RuntimeError(f"pod {pod_id} has no SSH info; payload={payload!r}")
    ctx = build_job_context(spec, args.config)
    log_path = ctx.render(spec.run.log_path)
    runner = RemoteRunner(host=host, port=port, ssh_key=spec.ssh.resolved_key_path)
    cmd = f"tail -n {args.lines}"
    if not args.no_follow:
        cmd += " -f"
    cmd += f" {shlex.quote(log_path)}"
    return runner.ssh_stream(cmd)


def main(argv: Sequence[str] | None = None) -> int:
    """CLI entry point."""
    verbosity = _verbosity_parser()
    parser = argparse.ArgumentParser(description="Config-driven RunPod deployment.")
    sub = parser.add_subparsers(dest="command", required=True)

    validate_parser = sub.add_parser("validate", parents=[verbosity], help="Validate a job config.")
    validate_parser.add_argument("--config", type=Path, required=True)
    validate_parser.add_argument(
        "--check-local",
        action="store_true",
        help="Also validate local required_paths against the current filesystem.",
    )
    validate_parser.add_argument(
        "--check-availability",
        action="store_true",
        help="Live-query runpodctl datacenter list and verify configured GPUs.",
    )
    validate_parser.add_argument(
        "--scan-consumer",
        action="store_true",
        help="Scan consumer pyproject.toml + staged payloads for common foot-guns.",
    )
    validate_parser.add_argument(
        "--all",
        action="store_true",
        help="Enable every opt-in check (--check-local, --check-availability, --scan-consumer).",
    )

    run_parser = sub.add_parser("run", parents=[verbosity], help="Run a job config.")
    run_parser.add_argument("--config", type=Path, required=True)
    run_parser.add_argument("--dry-run", action="store_true")
    run_parser.add_argument("--offline-dry-run", action="store_true")
    run_parser.add_argument("--cost-cap-usd", type=float, default=None)
    run_parser.add_argument("--max-runtime-minutes", type=int, default=None)

    stop_parser = sub.add_parser("stop", parents=[verbosity], help="Stop a pod from a state file.")
    stop_parser.add_argument("--state-file", type=Path, required=True)
    stop_parser.add_argument("--dry-run", action="store_true")

    logs_parser = sub.add_parser(
        "logs", parents=[verbosity], help="Live-tail the current pod's run log."
    )
    logs_parser.add_argument("--config", type=Path, required=True)
    logs_parser.add_argument(
        "--lines", type=int, default=200, help="Initial lines to show (default 200)."
    )
    logs_parser.add_argument(
        "--no-follow", action="store_true", help="Print last N lines and exit."
    )

    gpu_list_parser = sub.add_parser(
        "gpu-list",
        parents=[verbosity],
        help="Print GPU availability for one RunPod datacenter.",
    )
    gpu_list_parser.add_argument("--datacenter", type=str, required=True)

    args = parser.parse_args(argv)
    _configure_logging(_level_from_args(args))
    handlers = {
        "validate": _cmd_validate,
        "run": _cmd_run,
        "stop": _cmd_stop,
        "logs": _cmd_logs,
        "gpu-list": _cmd_gpu_list,
    }
    return handlers[args.command](args)


if __name__ == "__main__":
    raise SystemExit(main())
