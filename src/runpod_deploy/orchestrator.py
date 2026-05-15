"""RunPod single-job orchestration."""

from __future__ import annotations

import contextlib
import logging
import os
import re
import shlex
import sys
import tempfile
import time
from collections.abc import Callable, Mapping
from pathlib import Path

from runpod_deploy import metadata, pricing, telemetry
from runpod_deploy.config import (
    STORAGE_NETWORK_VOLUME,
    CommandSpec,
    JobContext,
    RunpodJobSpec,
    SecretSpec,
    build_job_context,
    validate_local_paths,
)
from runpod_deploy.manifest import ArtifactResult, write_pull_manifest
from runpod_deploy.provider import (
    provision_pod,
    resolve_volume,
    run_json,
    select_gpu_across_datacenters,
    stop_pod,
)
from runpod_deploy.telemetry import TelemetrySession
from runpod_deploy.transport import RemoteRunner, RsyncTransfer

__all__ = ["run_job"]

logger = logging.getLogger(__name__)

_STEP_MARKER_RE = re.compile(r"__RUNPOD_STEP_(START|DONE)__([\w.\-]+)__")


def run_job(
    spec: RunpodJobSpec,
    *,
    config_path: Path | str,
    dry_run: bool = False,
    offline_dry_run: bool = False,
    gpu_id_override: str | None = None,
    datacenter_id_override: str | None = None,
    max_gpu_price_usd: float | None = None,
    cli_variables: Mapping[str, str] | None = None,
    print_run_dir: bool = False,
) -> None:
    """Provision, stage, run, capture telemetry, pull artifacts, and stop one job.

    Linear flow (~70 lines, intentionally past the 50-line soft ceiling
    per CLAUDE.md §8 because the body remains a single straight path):
    metadata capture → GPU/DC selection (with failover) → provision →
    telemetry session start → setup/preflight → launch → monitor (parsing
    optional step markers) → telemetry capture_end → pull log + artifacts
    (always pulls log when run started, even on failure) → stop pod →
    write v2 manifest with all captured fields.

    When ``print_run_dir`` is True, a single ``RUN_DIR=<path>`` line is
    written to ``sys.stdout`` immediately after the run-dir path is
    resolved. Intended for parallel-sweep drivers that need a
    machine-parseable handle without racing ``ls -td``.
    """
    if offline_dry_run:
        dry_run = True
    ctx = build_job_context(spec, config_path, cli_variables=cli_variables)
    if print_run_dir:
        sys.stdout.write(f"RUN_DIR={ctx.run_dir}\n")
        sys.stdout.flush()
    validate_local_paths(ctx)
    _print_budget(spec)
    deploy_metadata = _capture_deploy_metadata(spec, ctx)
    pending_failover: list[dict[str, object]] = []
    if gpu_id_override is not None and datacenter_id_override is not None:
        gpu_id, datacenter_id = gpu_id_override, datacenter_id_override
        logger.info(f"[gpu] CLI override: gpu_id={gpu_id!r} datacenter_id={datacenter_id!r}")
    else:
        gpu_id, datacenter_id = _resolve_gpu_id_and_dc(
            spec,
            offline=offline_dry_run,
            on_failover=_buffer_failover(pending_failover),
            max_gpu_price_usd=max_gpu_price_usd,
        )
    volume_id = _resolve_volume_id(spec, datacenter_id=datacenter_id, offline=offline_dry_run)
    pod = provision_pod(
        ctx,
        volume_id=volume_id,
        gpu_id=gpu_id,
        datacenter_id=datacenter_id,
        dry_run=dry_run,
    )
    runner = RemoteRunner(
        host=pod.host,
        port=pod.port,
        ssh_key=spec.ssh.resolved_key_path,
        dry_run=dry_run,
    )
    tel = telemetry.start_session(
        run_dir=ctx.run_dir,
        runner=runner,
        spec=spec.telemetry,
        pod_id=pod.pod_id,
        assumed_hourly_rate_usd=spec.budget.assumed_hourly_rate_usd,
        dry_run=dry_run,
    )
    for event in pending_failover:
        tel.emit_event("datacenter_failover", **event)
    tel.emit_event("gpu_selected", gpu_id=gpu_id, datacenter_id=datacenter_id)
    failed = False
    run_started = False
    artifact_results: list[ArtifactResult] = []
    wall_start = time.monotonic()
    try:
        _wait_for_sshd(runner)
        tel.capture_start()
        _run_commands(runner, ctx, spec.setup, label="setup")
        _stage_secrets(runner, ctx)
        _push_workspace(runner, ctx)
        _run_commands(
            runner, ctx, _build_python_pin_preflight(spec) + spec.preflight, label="preflight"
        )
        _launch_remote_job(runner, ctx)
        run_started = True
        tel.start_sampling()
        _monitor_remote_log(runner, ctx, tel=tel)
        tel.stop_sampling()
        tel.capture_end()
        artifact_results = _pull_artifacts_and_log(runner, ctx, failed=False, tel=tel)
    except Exception:
        failed = True
        tel.stop_sampling()
        if not dry_run and run_started:
            with contextlib.suppress(Exception):
                artifact_results = _pull_artifacts_and_log(runner, ctx, failed=True, tel=tel)
            with contextlib.suppress(Exception):
                tel.capture_end()
        elif not dry_run:
            logger.warning("[warn] skipping artifact pulls — run script did not execute")
        raise
    finally:
        wall_time_sec = time.monotonic() - wall_start
        should_stop = spec.stop.on_failure if failed else spec.stop.on_success
        if should_stop:
            stop_pod(pod.pod_id, dry_run=dry_run, state_file=spec.resolved_state_file)
        elif not dry_run:
            logger.warning(f"[warn] pod preserved: {pod.pod_id}")
        if not dry_run:
            with contextlib.suppress(Exception):
                write_pull_manifest(
                    ctx,
                    failed=failed,
                    pod=pod,
                    datacenter_id=datacenter_id,
                    deploy_metadata=deploy_metadata,
                    artifact_results=artifact_results,
                    telemetry_files=tel.files_written,
                    wall_time_sec=wall_time_sec,
                    gpu_price_per_hour_usd=tel.gpu_price_per_hour_usd,
                    gpu_price_source=tel.gpu_price_source,
                    pod_final_state=tel.pod_final_state,
                )


def _capture_deploy_metadata(spec: RunpodJobSpec, ctx: JobContext) -> dict[str, object]:
    """Auto-capture local git + payload lockfile metadata pre-provisioning."""
    payload: dict[str, object] = {}
    project_root = Path(ctx.variables["project_root"])
    if spec.telemetry.capture_local_git:
        payload.update(metadata.capture_local_git(project_root))
    if spec.telemetry.capture_payload_lockfile:
        payload.update(metadata.capture_payload_lockfile(project_root))
    return payload


def _buffer_failover(
    pending: list[dict[str, object]],
) -> Callable[[str, str | None, str], None]:
    """Build an on_failover callback that buffers events for later telemetry replay."""

    def callback(failed_dc: str, next_dc: str | None, reason: str) -> None:
        pending.append({"from": failed_dc, "to": next_dc, "reason": reason})
        logger.warning(f"[failover] {failed_dc!r} -> {next_dc!r}: {reason}")

    return callback


def _resolve_volume_id(spec: RunpodJobSpec, *, datacenter_id: str, offline: bool) -> str | None:
    """Resolve the RunPod network-volume id, or None for ephemeral storage."""
    if spec.storage.mode != STORAGE_NETWORK_VOLUME:
        return None
    if offline:
        return "<volume-id>"
    volume_name = spec.storage.volume_name
    if volume_name is None:
        raise ValueError("storage.volume_name is required for network_volume storage")
    volumes = run_json(["runpodctl", "network-volume", "list", "-o", "json"])
    volume_id, _ = resolve_volume(
        volumes,
        volume_name=volume_name,
        expected_datacenter_id=datacenter_id,
    )
    return volume_id


def _resolve_gpu_id_and_dc(
    spec: RunpodJobSpec,
    *,
    offline: bool,
    on_failover: Callable[[str, str | None, str], None] | None = None,
    max_gpu_price_usd: float | None = None,
) -> tuple[str, str]:
    """Pick (gpu_id, datacenter_id) for provisioning across the configured DCs."""
    if offline:
        return spec.pod.gpu_order[0], spec.pod.datacenters[0]
    datacenters_payload = run_json(["runpodctl", "datacenter", "list", "-o", "json"])
    prices_map: dict[str, float] | None = None
    if max_gpu_price_usd is not None:
        gpu_prices = pricing.fetch_gpu_prices()
        prices_map = {}
        for gpu_id in spec.pod.gpu_order:
            price = pricing.select_price_for_pod(
                gpu_prices,
                gpu_id=gpu_id,
                cloud_type=spec.pod.cloud_type,
                spot=spec.pod.spot,
            )
            if price is not None:
                prices_map[gpu_id] = price
    return select_gpu_across_datacenters(
        datacenters_payload,
        datacenters=spec.pod.datacenters,
        gpu_order=spec.pod.gpu_order,
        on_failover=on_failover,
        prices=prices_map,
        max_gpu_price_usd=max_gpu_price_usd,
    )


def _print_budget(spec: RunpodJobSpec) -> None:
    timeout_minutes = spec.budget.timeout_sec / 60
    estimated_spend = spec.budget.assumed_hourly_rate_usd * (timeout_minutes / 60)
    logger.info(
        "[budget] "
        f"cap=${spec.budget.cost_cap_usd:.2f} "
        f"assumed_rate=${spec.budget.assumed_hourly_rate_usd:.2f}/hr "
        f"timeout={timeout_minutes:.1f}m estimated_spend=${estimated_spend:.2f}"
    )
    if estimated_spend > spec.budget.cost_cap_usd + 1e-9:
        raise RuntimeError("configured timeout exceeds cost cap under the assumed hourly rate")


def _wait_for_sshd(runner: RemoteRunner) -> None:
    if runner.dry_run:
        runner.ssh_exec("true", timeout_sec=10)
        return
    delays = (1, 2, 4, 8, 16, 30, 30)
    last_error: Exception | None = None
    for delay in delays:
        try:
            runner.ssh_exec("true", timeout_sec=10, check=True)
            return
        except Exception as exc:
            last_error = exc
            logger.info(f"[ssh] not ready ({type(exc).__name__}); retrying in {delay}s")
            time.sleep(delay)
    raise RuntimeError(f"sshd never became ready; last_error={last_error!r}")


def _build_python_pin_preflight(spec: RunpodJobSpec) -> tuple[CommandSpec, ...]:
    """Return the auto-injected `uv python install + pin` step when `pod.python_version` is set.

    Empty tuple when not set (default; existing YAMLs unaffected).

    Runs as preflight[0] (NOT setup[0]) because the pin must write
    `.python-version` into the staged project directory, which doesn't
    exist until after `_push_workspace`. Slightly later than the
    original "setup[0]" sketch but correctness-preserving — the pin
    file survives rsync `--delete` because staging is already done.

    Failure mode (per the Q4 decision): `check=True` on `ssh_exec`
    raises `RemoteRunError` on non-zero exit, which aborts the run
    before the user's preflight or run-body executes. Surfaces the
    install failure cheaply (~30s of pod time) rather than letting a
    later `uv sync` silently fall back to the base-image interpreter.
    """
    version = spec.pod.python_version
    if version is None:
        return ()
    # Find the first staging entry's destination as the pin target. If no
    # staging is configured, fall back to $HOME (degenerate but valid —
    # the user has no remote repo to pin against; the install alone is
    # still useful for downstream commands that respect $HOME/.python-version).
    pin_target = "$HOME"
    for stage in spec.staging:
        pin_target = stage.destination
        break
    command = (
        f"uv python install {version} "
        f"&& cd {pin_target} "
        f"&& uv python pin {version} "
        f'&& echo "[runpod-deploy] pinned Python {version} at $(pwd)/.python-version"'
    )
    return (CommandSpec(command=command, timeout_sec=300, with_env=False),)


def _run_commands(
    runner: RemoteRunner,
    ctx: JobContext,
    commands: tuple[CommandSpec, ...],
    *,
    label: str,
) -> None:
    for command in commands:
        rendered = ctx.render(command.command)
        if command.with_env:
            rendered = f"{_remote_env_prefix(ctx)} {rendered}"
        logger.info(f"[{label}] {rendered[:120]}")
        result = runner.ssh_exec(rendered, timeout_sec=command.timeout_sec, check=True)
        if result.stdout:
            logger.info(result.stdout)


def _stage_secrets(runner: RemoteRunner, ctx: JobContext) -> None:
    """Stage each `secrets:` entry to the pod with restrictive perms.

    Secret values are never logged. For ``env`` secrets the orchestrator reads
    each named local env var, writes ``KEY=value`` lines to a tempfile, and
    rsyncs it to ``destination`` with ``--chmod=F<mode>``. For ``file`` secrets
    the local file is rsynced directly. The parent directory of ``destination``
    is created via ``mkdir -p`` first.
    """
    for secret in ctx.spec.secrets:
        destination = ctx.render(secret.destination)
        parent_dir = str(Path(destination).parent)
        logger.info(f"[secrets] staging {secret.name!r} -> {destination} (mode={secret.mode})")
        runner.ssh_exec(f"mkdir -p {shlex.quote(parent_dir)}", timeout_sec=30, check=True)
        if secret.env:
            _stage_env_secret(runner, secret, destination=destination)
        elif secret.file is not None:
            rendered = ctx.render(secret.file)
            local_path = Path(rendered).expanduser()
            if not local_path.exists():
                raise FileNotFoundError(
                    f"secret {secret.name!r} source file not found: {local_path}"
                )
            transfer = RsyncTransfer(
                label=f"secret:{secret.name}",
                source=str(local_path),
                destination=destination,
                delete=False,
            )
            runner.rsync_push(transfer, chmod=secret.mode)


def _stage_env_secret(runner: RemoteRunner, secret: SecretSpec, *, destination: str) -> None:
    lines: list[str] = []
    for var in secret.env:
        try:
            value = os.environ[var]
        except KeyError as exc:
            raise KeyError(
                f"secret {secret.name!r} requires env var {var!r}, which is not set in the "
                "local environment"
            ) from exc
        lines.append(f"{var}={value}")
    content = "\n".join(lines) + "\n"
    fd, tmp_name = tempfile.mkstemp(prefix="runpod-secret-", suffix=".env")
    tmp_path = Path(tmp_name)
    try:
        with os.fdopen(fd, "w") as handle:
            handle.write(content)
        tmp_path.chmod(0o600)
        transfer = RsyncTransfer(
            label=f"secret:{secret.name}",
            source=str(tmp_path),
            destination=destination,
            delete=False,
        )
        runner.rsync_push(transfer, chmod=secret.mode)
    finally:
        tmp_path.unlink(missing_ok=True)


def _push_workspace(runner: RemoteRunner, ctx: JobContext) -> None:
    for spec in ctx.spec.staging:
        transfer = RsyncTransfer(
            label=spec.label,
            source=ctx.render(spec.source),
            destination=ctx.render(spec.destination),
            excludes=tuple(ctx.render(exclude) for exclude in spec.effective_excludes),
            delete=spec.delete,
        )
        runner.rsync_push(transfer)


def _launch_remote_job(runner: RemoteRunner, ctx: JobContext) -> None:
    run = ctx.spec.run
    # Render template variables (built-ins + YAML + CLI --var) in all
    # path-like and marker fields. `run.body` is already template-aware;
    # the others gain template support here so a {seed} / {backbone} /
    # {project_root} in run.script_path / log_path is expanded the same
    # way as in run.body or staging paths. See MIGRATION.md §"Behavioral
    # changes".
    payload = ctx.render(run.body)
    script_path = ctx.render(run.script_path)
    log_path = ctx.render(run.log_path)
    create = (
        f"cat > {shlex.quote(script_path)} <<'BASH'\n"
        f"{payload}\n"
        f"BASH\nchmod +x {shlex.quote(script_path)}"
    )
    runner.ssh_exec(create, timeout_sec=60, check=True)
    runner.ssh_exec(f"rm -f {shlex.quote(log_path)}", timeout_sec=30, check=True)
    runner.ssh_exec_detached(
        f"nohup bash {shlex.quote(script_path)} > {shlex.quote(log_path)} 2>&1 < /dev/null"
    )
    for _ in range(20):
        result = runner.ssh_exec(f"test -f {shlex.quote(log_path)}", timeout_sec=10, check=False)
        if result.returncode == 0:
            logger.info(f"[remote] log created: {log_path}")
            return
        time.sleep(1)
    raise RuntimeError(f"remote job did not create {log_path}")


def _monitor_remote_log(
    runner: RemoteRunner, ctx: JobContext, *, tel: TelemetrySession | None = None
) -> None:
    run = ctx.spec.run
    log_path = ctx.render(run.log_path)
    success_marker = ctx.render(run.success_marker)
    deadline = time.time() + ctx.spec.budget.timeout_sec
    logger.info(
        f"[monitor] polling {log_path}; "
        f"timeout={ctx.spec.budget.timeout_sec // 60}m success={success_marker!r}"
    )
    if runner.dry_run:
        runner.ssh_exec(_log_status_command(ctx), timeout_sec=30, check=False)
        logger.info("[dry-run] skipping monitor loop")
        return
    seen_step_markers: set[tuple[str, str]] = set()
    while time.time() < deadline:
        status = runner.ssh_exec(_log_status_command(ctx), timeout_sec=30, check=False)
        stdout = status.stdout.strip()
        if stdout:
            logger.info(stdout[-4000:])
            if tel is not None:
                _emit_step_marker_events(tel, stdout, seen_step_markers)
        if "__RUNPOD_DEPLOY_DONE__" in stdout:
            return
        if "__RUNPOD_DEPLOY_FAIL__" in stdout:
            raise RuntimeError(f"remote log contains failure marker; tail:\n{stdout[-4000:]}")
        time.sleep(ctx.spec.budget.poll_interval_sec)
    raise TimeoutError(
        f"remote job exceeded timeout/cost cap of {ctx.spec.budget.timeout_sec // 60} minutes"
    )


def _emit_step_marker_events(
    tel: TelemetrySession, log_text: str, seen: set[tuple[str, str]]
) -> None:
    """Opt-in `__RUNPOD_STEP_START/DONE__name__` marker parsing.

    Each unique (kind, name) pair is emitted once. Consumers compute
    durations from ts_utc deltas in events.jsonl.
    """
    for match in _STEP_MARKER_RE.finditer(log_text):
        kind, name = match.group(1), match.group(2)
        key = (kind, name)
        if key in seen:
            continue
        seen.add(key)
        event = "remote_step_started" if kind == "START" else "remote_step_completed"
        tel.emit_event(event, name=name)


def _pull_artifacts_and_log(
    runner: RemoteRunner,
    ctx: JobContext,
    *,
    failed: bool,
    tel: TelemetrySession | None = None,
) -> list[ArtifactResult]:
    """Pull the remote run.log first, then declared artifacts; track per-artifact result."""
    _pull_remote_log(runner, ctx, tel=tel)
    results: list[ArtifactResult] = []
    for artifact in ctx.spec.artifacts:
        required = artifact.required and not failed
        if tel is not None:
            tel.emit_event("artifact_pull_started", label=artifact.label)
        start = time.monotonic()
        try:
            runner.rsync_pull(
                remote_path=ctx.render(artifact.remote_path),
                local_path=ctx.render_path(artifact.local_path),
                excludes=tuple(ctx.render(exclude) for exclude in artifact.excludes),
                delete=artifact.delete,
            )
        except Exception as exc:
            duration = time.monotonic() - start
            if tel is not None:
                tel.emit_event(
                    "artifact_pull_failed",
                    label=artifact.label,
                    duration_sec=round(duration, 3),
                    error=str(exc)[:500],
                )
            results.append(
                ArtifactResult(
                    label=artifact.label,
                    status="failed",
                    duration_sec=round(duration, 3),
                    error=str(exc)[:500],
                )
            )
            if required:
                raise
            logger.warning(f"[warn] optional pull skipped for {artifact.remote_path}: {exc}")
            continue
        duration = time.monotonic() - start
        if tel is not None:
            tel.emit_event(
                "artifact_pull_completed",
                label=artifact.label,
                duration_sec=round(duration, 3),
            )
        results.append(
            ArtifactResult(
                label=artifact.label,
                status="success",
                duration_sec=round(duration, 3),
            )
        )
    return results


def _pull_remote_log(
    runner: RemoteRunner, ctx: JobContext, *, tel: TelemetrySession | None = None
) -> None:
    """Rsync the remote run.log_path into run_dir/run.log. Logs WARNING on failure."""
    log_path = ctx.render(ctx.spec.run.log_path)
    try:
        runner.rsync_pull(
            remote_path=log_path,
            local_path=ctx.run_dir,
            excludes=(),
            delete=False,
        )
    except Exception as exc:
        logger.warning(f"[warn] failed to pull remote log {log_path}: {exc}")
        if tel is not None:
            tel.emit_event("remote_log_pull_failed", path=log_path, error=str(exc)[:500])


def _remote_env_prefix(ctx: JobContext) -> str:
    parts: list[str] = []
    for source in ctx.spec.remote_env.source_files:
        rendered = ctx.render(source)
        parts.append(f"[ -f {shlex.quote(rendered)} ] && source {shlex.quote(rendered)} || true")
    for key, value in ctx.spec.remote_env.exports.items():
        parts.append(f"export {key}={shlex.quote(ctx.render(value))}")
    return "; ".join(parts) + (";" if parts else "")


def _log_status_command(ctx: JobContext) -> str:
    run = ctx.spec.run
    success = shlex.quote(ctx.render(run.success_marker))
    log = shlex.quote(ctx.render(run.log_path))
    failure_checks = " || ".join(
        f"grep -F {shlex.quote(ctx.render(marker))} {log} >/dev/null 2>&1"
        for marker in run.failure_markers
    )
    return (
        f"tail -n 80 {log} 2>/dev/null || true; "
        f"grep -F {success} {log} >/dev/null 2>&1 && echo __RUNPOD_DEPLOY_DONE__; "
        f"if {failure_checks}; then echo __RUNPOD_DEPLOY_FAIL__; fi"
    )
