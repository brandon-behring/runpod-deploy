"""RunPod single-job orchestration."""

from __future__ import annotations

import contextlib
import logging
import shlex
import time
from pathlib import Path

from runpod_deploy.config import (
    STORAGE_NETWORK_VOLUME,
    CommandSpec,
    JobContext,
    RunpodJobSpec,
    build_job_context,
    validate_local_paths,
)
from runpod_deploy.manifest import write_pull_manifest
from runpod_deploy.provider import (
    PodConnection,
    provision_pod,
    resolve_volume,
    run_json,
    select_gpu_for_datacenter,
    stop_pod,
)
from runpod_deploy.transport import RemoteRunner, RsyncTransfer

__all__ = ["run_job"]

logger = logging.getLogger(__name__)


def run_job(
    spec: RunpodJobSpec,
    *,
    config_path: Path | str,
    dry_run: bool = False,
    offline_dry_run: bool = False,
) -> None:
    """Provision, stage, run, pull artifacts, and stop one RunPod job."""
    if offline_dry_run:
        dry_run = True
    ctx = build_job_context(spec, config_path)
    validate_local_paths(ctx)
    _print_budget(spec)
    volume_id = _resolve_volume_id(spec, offline=offline_dry_run)
    gpu_id = _resolve_gpu_id(spec, offline=offline_dry_run)
    pod = provision_pod(ctx, volume_id=volume_id, gpu_id=gpu_id, dry_run=dry_run)
    runner = RemoteRunner(
        host=pod.host,
        port=pod.port,
        ssh_key=spec.ssh.resolved_key_path,
        dry_run=dry_run,
    )
    failed = False
    try:
        _wait_for_sshd(runner)
        _run_commands(runner, ctx, spec.setup, label="setup")
        _push_workspace(runner, ctx)
        _run_commands(runner, ctx, spec.preflight, label="preflight")
        _launch_remote_job(runner, ctx)
        _monitor_remote_log(runner, ctx)
        _pull_artifacts(runner, ctx, failed=False, pod=pod)
    except Exception:
        failed = True
        if not dry_run:
            with contextlib.suppress(Exception):
                _pull_artifacts(runner, ctx, failed=True, pod=pod)
        raise
    finally:
        should_stop = spec.stop.on_failure if failed else spec.stop.on_success
        if should_stop:
            stop_pod(pod.pod_id, dry_run=dry_run, state_file=spec.resolved_state_file)
        elif not dry_run:
            logger.warning(f"[warn] pod preserved: {pod.pod_id}")


def _resolve_volume_id(spec: RunpodJobSpec, *, offline: bool) -> str | None:
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
        expected_datacenter_id=spec.pod.datacenter_id,
    )
    return volume_id


def _resolve_gpu_id(spec: RunpodJobSpec, *, offline: bool) -> str:
    """Pick the GPU id for provisioning, falling back to the first preference offline."""
    if offline:
        return spec.pod.gpu_order[0]
    datacenters = run_json(["runpodctl", "datacenter", "list", "-o", "json"])
    return select_gpu_for_datacenter(
        datacenters,
        datacenter_id=spec.pod.datacenter_id,
        gpu_order=spec.pod.gpu_order,
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


def _push_workspace(runner: RemoteRunner, ctx: JobContext) -> None:
    for spec in ctx.spec.staging:
        transfer = RsyncTransfer(
            label=spec.label,
            source=ctx.render(spec.source),
            destination=ctx.render(spec.destination),
            excludes=tuple(ctx.render(exclude) for exclude in spec.excludes),
            delete=spec.delete,
        )
        runner.rsync_push(transfer)


def _launch_remote_job(runner: RemoteRunner, ctx: JobContext) -> None:
    run = ctx.spec.run
    payload = ctx.render(run.body)
    create = (
        f"cat > {shlex.quote(run.script_path)} <<'BASH'\n"
        f"{payload}\n"
        f"BASH\nchmod +x {shlex.quote(run.script_path)}"
    )
    runner.ssh_exec(create, timeout_sec=60, check=True)
    runner.ssh_exec(f"rm -f {shlex.quote(run.log_path)}", timeout_sec=30, check=True)
    runner.ssh_exec_detached(
        f"nohup bash {shlex.quote(run.script_path)} > {shlex.quote(run.log_path)} 2>&1 < /dev/null"
    )
    for _ in range(20):
        result = runner.ssh_exec(
            f"test -f {shlex.quote(run.log_path)}", timeout_sec=10, check=False
        )
        if result.returncode == 0:
            logger.info(f"[remote] log created: {run.log_path}")
            return
        time.sleep(1)
    raise RuntimeError(f"remote job did not create {run.log_path}")


def _monitor_remote_log(runner: RemoteRunner, ctx: JobContext) -> None:
    run = ctx.spec.run
    deadline = time.time() + ctx.spec.budget.timeout_sec
    logger.info(
        f"[monitor] polling {run.log_path}; "
        f"timeout={ctx.spec.budget.timeout_sec // 60}m success={run.success_marker!r}"
    )
    if runner.dry_run:
        runner.ssh_exec(_log_status_command(ctx), timeout_sec=30, check=False)
        logger.info("[dry-run] skipping monitor loop")
        return
    while time.time() < deadline:
        status = runner.ssh_exec(_log_status_command(ctx), timeout_sec=30, check=False)
        stdout = status.stdout.strip()
        if stdout:
            logger.info(stdout[-4000:])
        if "__RUNPOD_DEPLOY_DONE__" in stdout:
            return
        if "__RUNPOD_DEPLOY_FAIL__" in stdout:
            raise RuntimeError(f"remote log contains failure marker; tail:\n{stdout[-4000:]}")
        time.sleep(ctx.spec.budget.poll_interval_sec)
    raise TimeoutError(
        f"remote job exceeded timeout/cost cap of {ctx.spec.budget.timeout_sec // 60} minutes"
    )


def _pull_artifacts(
    runner: RemoteRunner,
    ctx: JobContext,
    *,
    failed: bool,
    pod: PodConnection | None,
) -> None:
    for artifact in ctx.spec.artifacts:
        required = artifact.required and not failed
        try:
            runner.rsync_pull(
                remote_path=ctx.render(artifact.remote_path),
                local_path=ctx.render_path(artifact.local_path),
                excludes=tuple(ctx.render(exclude) for exclude in artifact.excludes),
                delete=artifact.delete,
            )
        except Exception as exc:
            if required:
                raise
            logger.warning(f"[warn] optional pull skipped for {artifact.remote_path}: {exc}")
    if not runner.dry_run:
        write_pull_manifest(ctx, failed=failed, pod=pod)


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
    success = shlex.quote(run.success_marker)
    log = shlex.quote(run.log_path)
    failure_checks = " || ".join(
        f"grep -F {shlex.quote(marker)} {log} >/dev/null 2>&1" for marker in run.failure_markers
    )
    return (
        f"tail -n 80 {log} 2>/dev/null || true; "
        f"grep -F {success} {log} >/dev/null 2>&1 && echo __RUNPOD_DEPLOY_DONE__; "
        f"if {failure_checks}; then echo __RUNPOD_DEPLOY_FAIL__; fi"
    )
