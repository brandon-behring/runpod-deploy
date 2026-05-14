"""Pod-side telemetry: events.jsonl, metrics.jsonl, one-shot snapshots.

Telemetry must never abort a run — every SSH/subprocess call inside a
``TelemetrySession`` swallows exceptions and logs a WARNING. The session
exposes captured pod price (``gpu_price_per_hour_usd``) and final pod
state (``pod_final_state``) for the manifest after ``capture_end`` runs.
"""

from __future__ import annotations

import contextlib
import json
import logging
import subprocess
import threading
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from runpod_deploy.config import TelemetrySpec
from runpod_deploy.transport import RemoteRunner

__all__ = ["TelemetrySession", "start_session"]

logger = logging.getLogger(__name__)

_HEALTHY_POD_STATES = frozenset({"RUNNING", "EXITED"})
_SAMPLE_TIMEOUT_SEC = 30
_DESCRIBE_TIMEOUT_SEC = 30
_JOIN_TIMEOUT_SEC = 10
_DMESG_TAIL_LINES = 200


@dataclass(slots=True)
class TelemetrySession:
    """One pod's telemetry state — captures, samples, events.

    Mutable on purpose (background thread updates fields). Operational
    state, not config: descriptive name, no ``*Spec`` suffix.
    """

    run_dir: Path
    runner: RemoteRunner
    spec: TelemetrySpec
    pod_id: str
    assumed_hourly_rate_usd: float
    dry_run: bool = False

    gpu_price_per_hour_usd: float | None = None
    gpu_price_source: str | None = None
    pod_final_state: str | None = None

    _events_path: Path | None = None
    _metrics_path: Path | None = None
    _stop_event: threading.Event = field(default_factory=threading.Event)
    _thread: threading.Thread | None = None
    _files: list[Path] = field(default_factory=list)

    @property
    def files_written(self) -> list[Path]:
        """Telemetry files emitted into the run directory (relative paths fine)."""
        return list(self._files)

    def emit_event(self, event: str, **fields: object) -> None:
        """Append one JSON line to events.jsonl. Never raises."""
        if self.dry_run or not self.spec.enabled:
            return
        path = self._ensure_events_path()
        record: dict[str, object] = {
            "ts_utc": datetime.now(UTC).isoformat(),
            "event": event,
        }
        record.update(fields)
        try:
            with path.open("a") as fh:
                fh.write(json.dumps(record) + "\n")
        except OSError as exc:
            logger.warning(f"[telemetry] failed to write event {event!r}: {exc}")

    def capture_start(self) -> None:
        """One-shot snapshots before the remote job launches."""
        if self.dry_run or not self.spec.enabled:
            return
        if self.spec.capture_nvidia_smi:
            self._capture_nvidia_smi("start")
        if self.spec.capture_pod_describe:
            self._capture_pod_describe("start")
        if self.spec.capture_remote_env:
            self._capture_remote_env()
            self._capture_pip_freeze()

    def start_sampling(self) -> None:
        """Spawn the background sampling thread."""
        if self.dry_run or not self.spec.enabled:
            return
        if self._thread is not None:
            return
        self._stop_event.clear()
        self._thread = threading.Thread(
            target=self._sample_loop, name="runpod-deploy-telemetry", daemon=True
        )
        self._thread.start()

    def stop_sampling(self) -> None:
        """Signal the sampler to exit; wait up to 10 s before abandoning."""
        if self._thread is None:
            return
        self._stop_event.set()
        self._thread.join(timeout=_JOIN_TIMEOUT_SEC)
        if self._thread.is_alive():
            logger.warning(
                "[telemetry] sampling thread did not exit within "
                f"{_JOIN_TIMEOUT_SEC}s; abandoning"
            )
        self._thread = None

    def capture_end(self) -> None:
        """One-shot snapshots after the remote job ends."""
        if self.dry_run or not self.spec.enabled:
            return
        if self.spec.capture_nvidia_smi:
            self._capture_nvidia_smi("end")
        if self.spec.capture_pod_describe:
            self._capture_pod_describe("end")
        if self.spec.capture_dmesg:
            self._capture_dmesg()

    def _sample_loop(self) -> None:
        # Sample-first then wait so the t=0 row lands immediately, and so
        # stop_sampling() can abandon the thread when an SSH call hangs.
        path = self._ensure_metrics_path()
        while True:
            row: dict[str, object] = {"ts_utc": datetime.now(UTC).isoformat()}
            row.update(self._sample_nvidia_smi())
            row.update(self._sample_cpu_load())
            row.update(self._sample_host_mem())
            row.update(self._sample_workspace_disk())
            try:
                with path.open("a") as fh:
                    fh.write(json.dumps(row) + "\n")
            except OSError as exc:
                logger.warning(f"[telemetry] metrics.jsonl write failed: {exc}")
            if self._stop_event.wait(self.spec.sample_interval_sec):
                return

    def _sample_nvidia_smi(self) -> dict[str, object]:
        out = self._safe_ssh(
            "nvidia-smi --query-gpu=utilization.gpu,memory.used,memory.total,"
            "temperature.gpu,ecc.errors.uncorrected.volatile.total "
            "--format=csv,noheader,nounits"
        )
        if out is None:
            return {}
        first_line = out.strip().splitlines()[0] if out.strip() else ""
        parts = [p.strip() for p in first_line.split(",")]
        if len(parts) < 4:
            return {}
        try:
            return {
                "gpu_util_pct": int(parts[0]),
                "gpu_mem_used_mb": int(parts[1]),
                "gpu_mem_total_mb": int(parts[2]),
                "gpu_temp_c": int(parts[3]),
                "gpu_ecc_errors": int(parts[4]) if len(parts) > 4 and parts[4] else None,
            }
        except ValueError:
            return {}

    def _sample_cpu_load(self) -> dict[str, object]:
        out = self._safe_ssh("top -b -n1 | head -3")
        if not out:
            return {}
        load = _parse_load_avg_1m(out)
        cpu_user, cpu_sys = _parse_cpu_pct(out)
        return {"cpu_load_1m": load, "cpu_user_pct": cpu_user, "cpu_sys_pct": cpu_sys}

    def _sample_host_mem(self) -> dict[str, object]:
        out = self._safe_ssh("free -m | awk 'NR==2{print $3, $2}'")
        if not out:
            return {}
        try:
            used_str, total_str = out.split()[:2]
            return {"host_mem_used_mb": int(used_str), "host_mem_total_mb": int(total_str)}
        except (ValueError, IndexError):
            return {}

    def _sample_workspace_disk(self) -> dict[str, object]:
        out = self._safe_ssh("df -B1 /workspace | awk 'NR==2{print $3, $2}'")
        if not out:
            return {}
        try:
            used_str, total_str = out.split()[:2]
            return {
                "workspace_disk_used_bytes": int(used_str),
                "workspace_disk_total_bytes": int(total_str),
            }
        except (ValueError, IndexError):
            return {}

    def _capture_nvidia_smi(self, suffix: str) -> None:
        out = self._safe_ssh("nvidia-smi", timeout_sec=_SAMPLE_TIMEOUT_SEC)
        if out is None:
            return
        self._write_file(f"nvidia_smi_{suffix}.txt", out)

    def _capture_pod_describe(self, suffix: str) -> None:
        payload = self._safe_runpodctl_pod_get()
        if payload is None:
            return
        self._write_file(f"pod_describe_{suffix}.json", json.dumps(payload, indent=2))
        if suffix == "start":
            self._extract_price(payload)
        if suffix == "end":
            self._extract_final_state(payload)

    def _capture_remote_env(self) -> None:
        uname = self._safe_ssh("uname -a") or ""
        python_version = self._safe_ssh("python --version 2>&1") or ""
        payload = {"remote_uname": uname.strip(), "remote_python_version": python_version.strip()}
        self._write_file("remote_env.json", json.dumps(payload, indent=2))

    def _capture_pip_freeze(self) -> None:
        out = self._safe_ssh("pip freeze", timeout_sec=_SAMPLE_TIMEOUT_SEC)
        if out is None:
            return
        self._write_file("pip_freeze.txt", out)

    def _capture_dmesg(self) -> None:
        out = self._safe_ssh(f"dmesg | tail -n {_DMESG_TAIL_LINES} 2>/dev/null || true")
        if out is None:
            return
        self._write_file("dmesg_tail.txt", out)

    def _extract_price(self, payload: Any) -> None:
        cost = _get_case_insensitive(payload, "costPerHr")
        if isinstance(cost, (int, float)) and cost > 0:
            self.gpu_price_per_hour_usd = float(cost)
            self.gpu_price_source = "pod_describe"
            return
        self.gpu_price_per_hour_usd = self.assumed_hourly_rate_usd
        self.gpu_price_source = "assumed_rate"
        logger.warning(
            f"[telemetry] pod_describe.costPerHr missing or zero (got {cost!r}); "
            f"falling back to assumed_hourly_rate_usd={self.assumed_hourly_rate_usd}"
        )

    def _extract_final_state(self, payload: Any) -> None:
        state = _get_case_insensitive(payload, "desiredStatus")
        state_str = str(state) if state is not None else None
        self.pod_final_state = state_str
        if state_str is not None and state_str not in _HEALTHY_POD_STATES:
            self.emit_event(
                "pod_killed_unexpected",
                state=state_str,
                note="pod final state is not RUNNING or EXITED",
            )

    def _safe_ssh(self, command: str, *, timeout_sec: int = _SAMPLE_TIMEOUT_SEC) -> str | None:
        try:
            result = self.runner.ssh_exec(command, timeout_sec=timeout_sec, check=False)
        except Exception as exc:
            logger.warning(f"[telemetry] ssh failed for {command!r}: {exc}")
            return None
        if result.returncode != 0:
            logger.debug(
                f"[telemetry] ssh exit={result.returncode} for {command!r}; stderr="
                f"{result.stderr[-200:]!r}"
            )
            return None
        return result.stdout

    def _safe_runpodctl_pod_get(self) -> Any:
        argv = ["runpodctl", "pod", "get", self.pod_id, "--include-machine", "-o", "json"]
        try:
            result = subprocess.run(
                argv, capture_output=True, text=True, timeout=_DESCRIBE_TIMEOUT_SEC, check=False
            )
        except (FileNotFoundError, subprocess.TimeoutExpired) as exc:
            logger.warning(f"[telemetry] runpodctl pod get failed: {exc}")
            return None
        if result.returncode != 0:
            logger.warning(
                f"[telemetry] runpodctl pod get exited {result.returncode}: "
                f"{result.stderr[-200:]!r}"
            )
            return None
        try:
            return json.loads(result.stdout)
        except json.JSONDecodeError as exc:
            logger.warning(f"[telemetry] runpodctl pod get JSON decode failed: {exc}")
            return None

    def _write_file(self, name: str, content: str) -> None:
        path = self.run_dir / name
        try:
            self.run_dir.mkdir(parents=True, exist_ok=True)
            path.write_text(content)
        except OSError as exc:
            logger.warning(f"[telemetry] failed to write {name}: {exc}")
            return
        if path not in self._files:
            self._files.append(path)

    def _ensure_events_path(self) -> Path:
        if self._events_path is None:
            self.run_dir.mkdir(parents=True, exist_ok=True)
            self._events_path = self.run_dir / "events.jsonl"
            if self._events_path not in self._files:
                self._files.append(self._events_path)
        return self._events_path

    def _ensure_metrics_path(self) -> Path:
        if self._metrics_path is None:
            self.run_dir.mkdir(parents=True, exist_ok=True)
            self._metrics_path = self.run_dir / "metrics.jsonl"
            if self._metrics_path not in self._files:
                self._files.append(self._metrics_path)
        return self._metrics_path


def start_session(
    *,
    run_dir: Path,
    runner: RemoteRunner,
    spec: TelemetrySpec,
    pod_id: str,
    assumed_hourly_rate_usd: float,
    dry_run: bool = False,
) -> TelemetrySession:
    """Construct a TelemetrySession ready for capture_start()."""
    return TelemetrySession(
        run_dir=run_dir,
        runner=runner,
        spec=spec,
        pod_id=pod_id,
        assumed_hourly_rate_usd=assumed_hourly_rate_usd,
        dry_run=dry_run,
    )


def _get_case_insensitive(payload: Any, key: str) -> Any:
    """Return ``payload[key]`` matching key case-insensitively, or None."""
    if not isinstance(payload, dict):
        return None
    target = key.lower()
    for existing_key, value in payload.items():
        if isinstance(existing_key, str) and existing_key.lower() == target:
            return value
    return None


def _parse_load_avg_1m(top_out: str) -> float | None:
    """Extract the 1-minute load average from `top -b -n1 | head -3` output."""
    for line in top_out.splitlines():
        if "load average" in line:
            tail = line.split("load average:", 1)[-1].strip()
            with contextlib.suppress(ValueError, IndexError):
                return float(tail.split(",")[0].strip())
    return None


def _parse_cpu_pct(top_out: str) -> tuple[float | None, float | None]:
    """Extract user% and sys% from `top -b -n1 | head -3` output."""
    for line in top_out.splitlines():
        if line.startswith("%Cpu(s):") or line.startswith("Cpu(s):"):
            payload = line.split(":", 1)[1]
            user = sys_ = None
            for part in payload.split(","):
                token = part.strip()
                with contextlib.suppress(ValueError, IndexError):
                    if token.endswith("us"):
                        user = float(token.split()[0])
                    elif token.endswith("sy"):
                        sys_ = float(token.split()[0])
            return user, sys_
    return None, None
