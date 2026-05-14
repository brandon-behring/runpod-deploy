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
from typing import Any

from runpod_deploy import forensics, metadata, preflight, pricing
from runpod_deploy.config import (
    STORAGE_NETWORK_VOLUME,
    build_job_context,
    load_job_spec,
    validate_local_paths,
)
from runpod_deploy.orchestrator import run_job
from runpod_deploy.provider import run_json, select_gpu_across_datacenters, stop_pod
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
    if spec.storage.mode == STORAGE_NETWORK_VOLUME and len(spec.pod.datacenters) > 1:
        logger.warning(
            "[validate] storage.mode=network_volume with multiple pod.datacenters: the "
            "network volume pins the deploy to one DC, so the failover list is "
            f"effectively single-element. datacenters={list(spec.pod.datacenters)}"
        )
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
    rows: list[tuple[str, str, float | None]] = []
    prices = _maybe_fetch_prices(force_refresh=False) if not args.no_prices else {}
    if isinstance(availability, list):
        for item in availability:
            if isinstance(item, dict):
                name = str(item.get("gpuId") or "")
                status = str(item.get("stockStatus") or "").strip()
                if name:
                    price = pricing.select_price_for_pod(
                        prices,
                        gpu_id=name,
                        cloud_type=args.cloud_type,
                        spot=bool(args.spot),
                    )
                    rows.append((name, status or "—", price))
    tier_rank = {"high": 0, "medium": 1, "low": 2}
    rows.sort(key=lambda row: (tier_rank.get(row[1].lower(), 99), row[0]))
    name_width = max((len(name) for name, _, _ in rows), default=3)
    has_prices = any(p is not None for _, _, p in rows)
    logger.info(f"datacenter: {args.datacenter}")
    if has_prices:
        cloud_label = f"{args.cloud_type.lower()}{'-spot' if args.spot else ''}"
        logger.info(f"{'gpu':<{name_width}}  stock     $/hr ({cloud_label})")
        for name, status, price in rows:
            price_str = f"${price:.2f}" if price is not None else "—"
            logger.info(f"{name:<{name_width}}  {status:<8}  {price_str}")
    else:
        logger.info(f"{'gpu':<{name_width}}  stock")
        for name, status, _ in rows:
            logger.info(f"{name:<{name_width}}  {status}")
    return 0


def _cmd_gpu_prices(args: argparse.Namespace) -> int:
    prices = _maybe_fetch_prices(force_refresh=bool(args.no_price_cache))
    if not prices:
        logger.warning("[gpu-prices] no prices returned; check RUNPOD_API_KEY and network")
        return 1
    rows: list[tuple[str, float | None]] = []
    for gpu_id, _ in prices.items():
        price = pricing.select_price_for_pod(
            prices, gpu_id=gpu_id, cloud_type=args.cloud_type, spot=bool(args.spot)
        )
        rows.append((gpu_id, price))
    # Sort by price ascending (None last), then gpu_id.
    rows.sort(key=lambda row: (row[1] is None, row[1] or 0.0, row[0]))
    name_width = max((len(name) for name, _ in rows), default=3)
    cloud_label = f"{args.cloud_type.lower()}{'-spot' if args.spot else ''}"
    logger.info(f"{'gpu':<{name_width}}  $/hr ({cloud_label})")
    for name, price in rows:
        price_str = f"${price:.2f}" if price is not None else "—"
        logger.info(f"{name:<{name_width}}  {price_str}")
    return 0


def _maybe_fetch_prices(*, force_refresh: bool) -> dict[str, pricing.GpuPrice]:
    """Fetch prices; return empty dict on any failure (already WARN'd by pricing.py)."""
    return pricing.fetch_gpu_prices(force_refresh=force_refresh)


def _cmd_estimate(args: argparse.Namespace) -> int:
    spec = load_job_spec(args.config)
    datacenters_payload = run_json(["runpodctl", "datacenter", "list", "-o", "json"])
    raw_prices = _maybe_fetch_prices(force_refresh=False)
    prices_map: dict[str, float] = {}
    for gpu_id in spec.pod.gpu_order:
        price = pricing.select_price_for_pod(
            raw_prices,
            gpu_id=gpu_id,
            cloud_type=spec.pod.cloud_type,
            spot=spec.pod.spot,
        )
        if price is not None:
            prices_map[gpu_id] = price
    failover_log: list[str] = []
    try:
        gpu_id, datacenter_id = select_gpu_across_datacenters(
            datacenters_payload,
            datacenters=spec.pod.datacenters,
            gpu_order=spec.pod.gpu_order,
            prices=prices_map or None,
            on_failover=lambda failed, _nxt, reason: failover_log.append(f"  - {failed}: {reason}"),
        )
    except RuntimeError as exc:
        logger.error(f"[estimate] cannot pick a GPU: {exc}")
        for line in failover_log:
            logger.error(line)
        return 1
    selected_price = prices_map.get(gpu_id)
    cloud_label = f"{spec.pod.cloud_type.lower()}{'-spot' if spec.pod.spot else ''}"
    logger.info(f"config:         {args.config}")
    logger.info(f"job:            {spec.name}")
    logger.info(f"selected:       {gpu_id} in {datacenter_id}")
    if selected_price is not None:
        logger.info(f"price source:   graphql ({cloud_label})")
        logger.info(f"$/hr:           ${selected_price:.2f}")
    else:
        logger.info(
            "price source:   assumed_rate (graphql price unavailable; "
            "actual cost will come from pod_describe at deploy time)"
        )
        logger.info(f"$/hr:           ${spec.budget.assumed_hourly_rate_usd:.2f} (assumed)")
    rate_used = (
        selected_price if selected_price is not None else spec.budget.assumed_hourly_rate_usd
    )
    timeout_sec = spec.budget.timeout_sec
    timeout_min = timeout_sec / 60
    spend_at_timeout = rate_used * timeout_sec / 3600
    runtime_at_cap_sec = (spec.budget.cost_cap_usd / rate_used) * 3600 if rate_used > 0 else 0
    runtime_at_cap_min = runtime_at_cap_sec / 60
    logger.info("budget:")
    logger.info(f"  cost_cap_usd:    {spec.budget.cost_cap_usd:.2f}")
    logger.info(f"  assumed_rate:    {spec.budget.assumed_hourly_rate_usd:.2f}/hr")
    logger.info(f"  timeout:         {timeout_sec}s ({timeout_min:.1f} min)")
    logger.info(f"forecast at ${rate_used:.2f}/hr:")
    logger.info(f"  spend at budget.timeout_sec:    ${spend_at_timeout:.2f}")
    logger.info(
        f"  runtime at cost_cap ceiling:    ~{runtime_at_cap_sec:.0f}s ({runtime_at_cap_min:.0f} min)"
    )
    if failover_log:
        logger.info("failover events during selection:")
        for line in failover_log:
            logger.info(line)
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
    if (args.gpu_id is None) != (args.datacenter_id is None):
        raise argparse.ArgumentTypeError("--gpu-id and --datacenter-id must be supplied together")
    run_job(
        spec,
        config_path=args.config,
        dry_run=bool(args.dry_run),
        offline_dry_run=bool(args.offline_dry_run),
        gpu_id_override=args.gpu_id,
        datacenter_id_override=args.datacenter_id,
        max_gpu_price_usd=args.max_gpu_price,
    )
    return 0


def _cmd_ls_runs(args: argparse.Namespace) -> int:
    project_root = Path(args.project_root).resolve()
    run_dirs = forensics.walk_run_dirs(project_root)
    if args.limit is not None:
        run_dirs = run_dirs[-args.limit :]
    rows: list[dict[str, Any]] = []
    for run_dir in run_dirs:
        manifest = forensics.load_manifest(run_dir)
        if manifest is None:
            continue
        rows.append(
            {
                "timestamp": run_dir.name,
                "job": manifest.get("job_name"),
                "pod_id": manifest.get("pod_id"),
                "gpu_id": manifest.get("gpu_id"),
                "datacenter_id": manifest.get("datacenter_id"),
                "wall_time_sec": manifest.get("wall_time_sec"),
                "failed": manifest.get("failed"),
                "estimated_cost_usd": manifest.get("estimated_cost_usd"),
            }
        )
    if args.json:
        sys.stdout.write(json.dumps(rows, indent=2) + "\n")
        return 0
    if not rows:
        logger.info(f"no runs found under {project_root}/artifacts/runpod/")
        return 0
    headers = ["timestamp", "job", "pod_id", "gpu", "dc", "wall_s", "failed", "est_$"]
    table_rows = [
        [
            row["timestamp"],
            str(row["job"] or ""),
            str(row["pod_id"] or ""),
            str(row["gpu_id"] or ""),
            str(row["datacenter_id"] or ""),
            (
                f"{row['wall_time_sec']:.0f}"
                if isinstance(row["wall_time_sec"], (int, float))
                else "—"
            ),
            "Y" if row["failed"] else ("—" if row["failed"] is None else "N"),
            (
                f"${row['estimated_cost_usd']:.2f}"
                if isinstance(row["estimated_cost_usd"], (int, float))
                else "—"
            ),
        ]
        for row in rows
    ]
    widths = [
        max(len(header), max((len(r[i]) for r in table_rows), default=0))
        for i, header in enumerate(headers)
    ]
    fmt = "  ".join(f"{{:<{w}}}" for w in widths)
    logger.info(fmt.format(*headers))
    for r in table_rows:
        logger.info(fmt.format(*r))
    return 0


def _cmd_compare_runs(args: argparse.Namespace) -> int:
    a = forensics.load_manifest(args.a)
    b = forensics.load_manifest(args.b)
    if a is None or b is None:
        return 1
    sys.stdout.write(_format_compare_runs(args.a, args.b, a, b) + "\n")
    return 1 if a.get("failed") or b.get("failed") else 0


_COMPARE_FIELDS: tuple[str, ...] = (
    "schema_version",
    "failed",
    "job_name",
    "gpu_id",
    "datacenter_id",
    "gpu_price_per_hour_usd",
    "gpu_price_source",
    "wall_time_sec",
    "estimated_cost_usd",
    "pod_id",
    "pod_final_state",
    "image",
    "storage_mode",
)
_COMPARE_METADATA_FIELDS: tuple[str, ...] = (
    "local_git_sha",
    "local_git_dirty",
    "local_git_branch",
    "payload_lockfile",
    "payload_lockfile_sha256",
    "remote_python_version",
    "remote_uname",
)


def _format_compare_runs(a_path: Path, b_path: Path, a: dict[str, Any], b: dict[str, Any]) -> str:
    lines = [
        "diff between two manifests:",
        f"  a: {a_path}  ({a.get('job_name')})",
        f"  b: {b_path}  ({b.get('job_name')})",
        "",
    ]
    rows: list[tuple[str, str]] = []
    for field in _COMPARE_FIELDS:
        rows.append((field, _diff_cell(a.get(field), b.get(field))))
    a_meta = a.get("deploy_metadata") or {}
    b_meta = b.get("deploy_metadata") or {}
    if not isinstance(a_meta, dict):
        a_meta = {}
    if not isinstance(b_meta, dict):
        b_meta = {}
    for field in _COMPARE_METADATA_FIELDS:
        rows.append((f"deploy_metadata.{field}", _diff_cell(a_meta.get(field), b_meta.get(field))))
    a_arts = _index_artifacts(a.get("artifacts"))
    b_arts = _index_artifacts(b.get("artifacts"))
    for label in sorted(set(a_arts) | set(b_arts)):
        a_art = a_arts.get(label) or {}
        b_art = b_arts.get(label) or {}
        for field in ("status", "bytes_transferred", "duration_sec"):
            rows.append(
                (
                    f"artifact[{label}].{field}",
                    _diff_cell(a_art.get(field), b_art.get(field)),
                )
            )
    field_width = max(len(f) for f, _ in rows) + 2
    for field, cell in rows:
        lines.append(f"  {field:<{field_width}}{cell}")
    return "\n".join(lines)


def _diff_cell(av: object, bv: object) -> str:
    if av == bv:
        return f"{_render_value(av)} == {_render_value(bv)}"
    return f"{_render_value(av)}  →  {_render_value(bv)}"


def _render_value(v: object) -> str:
    if v is None:
        return "—"
    if isinstance(v, float):
        return f"{v:.2f}" if abs(v) < 1000 else f"{v:.1f}"
    return str(v)


def _index_artifacts(value: object) -> dict[str, dict[str, Any]]:
    if not isinstance(value, list):
        return {}
    out: dict[str, dict[str, Any]] = {}
    for item in value:
        if isinstance(item, dict):
            label = str(item.get("label") or "")
            if label:
                out[label] = item
    return out


def _cmd_events(args: argparse.Namespace) -> int:
    run_dir = Path(args.run_dir)
    if not run_dir.exists():
        raise FileNotFoundError(f"run-dir not found: {run_dir}")
    events = forensics.load_events(run_dir)
    if not events:
        logger.info(f"no events in {run_dir / forensics.EVENTS_FILENAME}")
        return 0
    sys.stdout.write(_format_events_timeline(events) + "\n")
    return 0


def _format_events_timeline(events: list[dict[str, Any]]) -> str:
    """Render events.jsonl rows as a wall-clock timeline anchored at the first ts_utc."""
    from datetime import datetime

    def parse_ts(raw: object) -> datetime | None:
        if not isinstance(raw, str):
            return None
        try:
            return datetime.fromisoformat(raw)
        except ValueError:
            return None

    anchor: datetime | None = None
    for entry in events:
        ts = parse_ts(entry.get("ts_utc"))
        if ts is not None:
            anchor = ts
            break
    out_lines: list[str] = []
    for entry in events:
        ts = parse_ts(entry.get("ts_utc"))
        offset_str = "[+--:--]"
        if anchor is not None and ts is not None:
            delta = (ts - anchor).total_seconds()
            offset_str = _format_offset(delta)
        event_name = str(entry.get("event") or "?")
        fields = " ".join(
            f"{k}={_render_event_value(v)}"
            for k, v in entry.items()
            if k not in {"ts_utc", "event"}
        )
        out_lines.append(f"{offset_str} {event_name} {fields}".rstrip())
    return "\n".join(out_lines)


def _format_offset(seconds: float) -> str:
    sign = "-" if seconds < 0 else "+"
    sec = int(abs(seconds))
    h, rem = divmod(sec, 3600)
    m, s = divmod(rem, 60)
    if h > 0:
        return f"[{sign}{h}:{m:02d}:{s:02d}]"
    return f"[{sign}{m}:{s:02d}]"


def _render_event_value(v: object) -> str:
    if isinstance(v, str) and (" " in v or '"' in v):
        return f'"{v}"'
    return str(v)


def _cmd_capture_env(args: argparse.Namespace) -> int:
    project_root = Path(args.project_root).resolve()
    payload: dict[str, object] = {}
    payload.update(metadata.capture_local_git(project_root))
    payload.update(metadata.capture_payload_lockfile(project_root))
    sys.stdout.write(json.dumps(payload, indent=2) + "\n")
    return 0


def _cmd_manifest_summary(args: argparse.Namespace) -> int:
    path = Path(args.manifest)
    if not path.exists():
        raise FileNotFoundError(f"manifest not found: {path}")
    payload = json.loads(path.read_text())
    sys.stdout.write(_format_manifest_summary(payload) + "\n")
    return 0


def _format_manifest_summary(m: dict[str, object]) -> str:
    """Render a v1/v2 pull manifest as a compact key/value summary."""
    lines = [
        f"job:           {m.get('job_name')}",
        f"run_id:        {m.get('run_id')}",
        f"failed:        {m.get('failed')}",
        f"schema:        {m.get('schema_version')}",
        f"pod_id:        {m.get('pod_id')}",
        f"gpu:           {m.get('gpu_id')}",
        f"datacenter:    {m.get('datacenter_id')}",
        f"image:         {m.get('image')}",
        f"storage:       {m.get('storage_mode')}",
        f"wall_time_sec: {m.get('wall_time_sec')}",
        f"price_usd/hr:  {m.get('gpu_price_per_hour_usd')} ({m.get('gpu_price_source')})",
        f"est_cost_usd:  {m.get('estimated_cost_usd')}",
        f"cost_cap_usd:  {m.get('cost_cap_usd')}",
        f"final_state:   {m.get('pod_final_state')}",
    ]
    metadata_block = m.get("deploy_metadata") or {}
    if isinstance(metadata_block, dict) and metadata_block:
        lines.append("deploy_metadata:")
        for key, value in metadata_block.items():
            lines.append(f"  {key}: {value}")
    artifacts = m.get("artifacts") or []
    if isinstance(artifacts, list) and artifacts:
        lines.append("artifacts:")
        for art in artifacts:
            if not isinstance(art, dict):
                continue
            label = art.get("label")
            status = art.get("status")
            duration = art.get("duration_sec")
            lines.append(f"  - {label}: status={status} duration_sec={duration}")
    telemetry_files = m.get("telemetry_files") or []
    if isinstance(telemetry_files, list) and telemetry_files:
        lines.append("telemetry_files:")
        for name in telemetry_files:
            lines.append(f"  - {name}")
    return "\n".join(lines)


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
    run_parser.add_argument(
        "--gpu-id",
        type=str,
        default=None,
        help="Override pod.gpu_order; must be supplied with --datacenter-id.",
    )
    run_parser.add_argument(
        "--datacenter-id",
        type=str,
        default=None,
        help="Override pod.datacenters; must be supplied with --gpu-id.",
    )
    run_parser.add_argument(
        "--max-gpu-price",
        type=float,
        default=None,
        help="Skip GPUs above this $/hr ceiling during failover loop. "
        "Reads RUNPOD_API_KEY for GraphQL pricing.",
    )

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
        help="Print GPU availability + price for one RunPod datacenter.",
    )
    gpu_list_parser.add_argument("--datacenter", type=str, required=True)
    gpu_list_parser.add_argument(
        "--cloud-type",
        choices=["SECURE", "COMMUNITY"],
        default="SECURE",
        help="Pick price field (default SECURE).",
    )
    gpu_list_parser.add_argument(
        "--spot",
        action="store_true",
        help="Show spot prices instead of on-demand.",
    )
    gpu_list_parser.add_argument(
        "--no-prices",
        action="store_true",
        help="Skip the GraphQL price fetch (offline / no API key available).",
    )

    gpu_prices_parser = sub.add_parser(
        "gpu-prices",
        parents=[verbosity],
        help="Print all GPU prices from RunPod GraphQL gpuTypes (sorted by $/hr).",
    )
    gpu_prices_parser.add_argument(
        "--cloud-type",
        choices=["SECURE", "COMMUNITY"],
        default="SECURE",
        help="Pick price field (default SECURE).",
    )
    gpu_prices_parser.add_argument(
        "--spot", action="store_true", help="Show spot prices instead of on-demand."
    )
    gpu_prices_parser.add_argument(
        "--no-price-cache",
        action="store_true",
        help="Bypass the on-disk price cache and force a fresh GraphQL request.",
    )

    estimate_parser = sub.add_parser(
        "estimate",
        parents=[verbosity],
        help="Predict cost for a config: walks GPU/DC selection with live prices.",
    )
    estimate_parser.add_argument("config", type=Path, help="Path to a job YAML config.")

    ls_runs_parser = sub.add_parser(
        "ls-runs",
        parents=[verbosity],
        help="List past runs from <project_root>/artifacts/runpod/*.",
    )
    ls_runs_parser.add_argument(
        "--project-root",
        type=Path,
        default=Path("."),
        help="Directory containing artifacts/runpod/ (defaults to cwd).",
    )
    ls_runs_parser.add_argument(
        "--limit", type=int, default=None, help="Show only the N most recent runs."
    )
    ls_runs_parser.add_argument(
        "--json", action="store_true", help="Emit machine-readable JSON instead of a table."
    )

    compare_parser = sub.add_parser(
        "compare-runs",
        parents=[verbosity],
        help="Side-by-side diff of two pull manifests; exit 1 on any failed=true.",
    )
    compare_parser.add_argument("a", type=Path, help="First manifest path or run dir.")
    compare_parser.add_argument("b", type=Path, help="Second manifest path or run dir.")

    events_parser = sub.add_parser(
        "events",
        parents=[verbosity],
        help="Pretty-print events.jsonl as a wall-clock timeline.",
    )
    events_parser.add_argument(
        "run_dir", type=Path, help="A run directory containing events.jsonl."
    )

    capture_env_parser = sub.add_parser(
        "capture-env",
        parents=[verbosity],
        help="Print local git + payload lockfile metadata as JSON to stdout.",
    )
    capture_env_parser.add_argument(
        "--project-root",
        type=Path,
        default=Path("."),
        help="Directory to inspect (defaults to cwd).",
    )

    manifest_parser = sub.add_parser(
        "manifest-summary",
        parents=[verbosity],
        help="Pretty-print a runpod_deploy_pull_manifest.json (v1 or v2).",
    )
    manifest_parser.add_argument(
        "manifest", type=Path, help="Path to a runpod_deploy_pull_manifest.json file."
    )

    args = parser.parse_args(argv)
    _configure_logging(_level_from_args(args))
    handlers = {
        "validate": _cmd_validate,
        "run": _cmd_run,
        "stop": _cmd_stop,
        "logs": _cmd_logs,
        "gpu-list": _cmd_gpu_list,
        "gpu-prices": _cmd_gpu_prices,
        "estimate": _cmd_estimate,
        "ls-runs": _cmd_ls_runs,
        "compare-runs": _cmd_compare_runs,
        "events": _cmd_events,
        "capture-env": _cmd_capture_env,
        "manifest-summary": _cmd_manifest_summary,
    }
    return handlers[args.command](args)


if __name__ == "__main__":
    raise SystemExit(main())
