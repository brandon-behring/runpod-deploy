from __future__ import annotations

import json
import logging
from pathlib import Path

import pytest

from runpod_deploy import preflight
from runpod_deploy.config import build_job_context, load_job_spec
from tests.conftest import FakeResult, FakeSubprocess


def _write_min_config(
    path: Path,
    *,
    state_file: Path,
    staging_source: str | None = None,
) -> Path:
    staging_block = ""
    if staging_source is not None:
        staging_block = f"""
staging:
  - label: code
    source: {staging_source}
    destination: /workspace/code
"""
    path.write_text(f"""
schema_version: 1
name: demo
run_id_prefix: demo
state_file: {state_file}
pod:
  image: runpod/pytorch:2.4.0-py3.11-cuda12.4.1-devel-ubuntu22.04
  datacenter_id: EU-RO-1
  gpu_order:
    - NVIDIA RTX A4000
storage:
  mode: ephemeral
  volume_gb: 20
run:
  script_path: /workspace/demo.sh
  log_path: /workspace/demo.log
  success_marker: "[demo] DONE"
  body: |
    echo "[demo] DONE"
{staging_block}""")
    return path


def _build_ctx(tmp_path: Path, **kwargs: object) -> object:
    cfg = _write_min_config(tmp_path / "job.yaml", state_file=tmp_path / "state.json", **kwargs)
    return build_job_context(load_job_spec(cfg), cfg)


def _dc_payload(*entries: dict[str, object]) -> str:
    return json.dumps(list(entries))


# ---------- check_gpu_availability ----------


@pytest.mark.unit
def test_check_gpu_availability_happy_path(fake_subprocess: FakeSubprocess, tmp_path: Path) -> None:
    fake_subprocess.enqueue(
        FakeResult(
            stdout=_dc_payload(
                {
                    "id": "EU-RO-1",
                    "gpuAvailability": [
                        {"gpuId": "NVIDIA RTX A4000", "stockStatus": "High"},
                    ],
                }
            )
        )
    )
    ctx = _build_ctx(tmp_path)
    preflight.check_gpu_availability(ctx)


@pytest.mark.unit
def test_check_gpu_availability_suggests_close_match_on_typo(
    fake_subprocess: FakeSubprocess,
    tmp_path: Path,
    caplog: pytest.LogCaptureFixture,
) -> None:
    fake_subprocess.enqueue(
        FakeResult(
            stdout=_dc_payload(
                {
                    "id": "EU-RO-1",
                    "gpuAvailability": [
                        {"gpuId": "NVIDIA RTX A4000", "stockStatus": "High"},
                        {"gpuId": "NVIDIA RTX A5000", "stockStatus": "Low"},
                    ],
                }
            )
        )
    )
    cfg = tmp_path / "job.yaml"
    cfg.write_text(f"""
schema_version: 1
name: demo
state_file: {tmp_path / "state.json"}
pod:
  image: runpod/pytorch
  datacenter_id: EU-RO-1
  gpu_order:
    - NVIDIA RTX A4OOO
storage:
  mode: ephemeral
  volume_gb: 20
run:
  script_path: /workspace/demo.sh
  log_path: /workspace/demo.log
  success_marker: ok
  body: |
    echo ok
""")
    ctx = build_job_context(load_job_spec(cfg), cfg)
    caplog.set_level(logging.ERROR, logger="runpod_deploy.preflight")

    with pytest.raises(RuntimeError, match="no configured GPU"):
        preflight.check_gpu_availability(ctx)

    messages = " ".join(record.message for record in caplog.records)
    assert "did you mean" in messages
    assert "NVIDIA RTX A4000" in messages or "NVIDIA RTX A5000" in messages


@pytest.mark.unit
def test_check_gpu_availability_raises_when_all_unavailable(
    fake_subprocess: FakeSubprocess, tmp_path: Path
) -> None:
    fake_subprocess.enqueue(
        FakeResult(
            stdout=_dc_payload(
                {
                    "id": "EU-RO-1",
                    "gpuAvailability": [
                        {"gpuId": "NVIDIA RTX A4000", "stockStatus": ""},
                    ],
                }
            )
        )
    )
    ctx = _build_ctx(tmp_path)

    with pytest.raises(RuntimeError, match="no configured GPU is currently available"):
        preflight.check_gpu_availability(ctx)


@pytest.mark.unit
def test_check_gpu_availability_warns_when_all_low(
    fake_subprocess: FakeSubprocess,
    tmp_path: Path,
    caplog: pytest.LogCaptureFixture,
) -> None:
    fake_subprocess.enqueue(
        FakeResult(
            stdout=_dc_payload(
                {
                    "id": "EU-RO-1",
                    "gpuAvailability": [
                        {"gpuId": "NVIDIA RTX A4000", "stockStatus": "Low"},
                    ],
                }
            )
        )
    )
    ctx = _build_ctx(tmp_path)
    caplog.set_level(logging.WARNING, logger="runpod_deploy.preflight")

    preflight.check_gpu_availability(ctx)

    assert any("Low stock" in r.message for r in caplog.records)


@pytest.mark.unit
def test_check_gpu_availability_raises_when_datacenter_missing(
    fake_subprocess: FakeSubprocess, tmp_path: Path
) -> None:
    fake_subprocess.enqueue(FakeResult(stdout=_dc_payload({"id": "US-MO-1"})))
    ctx = _build_ctx(tmp_path)

    with pytest.raises(RuntimeError, match="datacenter 'EU-RO-1' not found"):
        preflight.check_gpu_availability(ctx)


# ---------- scan_consumer_pyproject ----------


@pytest.mark.unit
def test_scan_consumer_pyproject_warns_on_runtime_dependency(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    (tmp_path / "pyproject.toml").write_text("""
[project]
name = "consumer"
version = "0.1.0"
dependencies = [
  "eval-toolkit",
  "runpod-deploy",
]
[tool.uv.sources]
runpod-deploy = { path = "../runpod-deploy", editable = true }
""")
    ctx = _build_ctx(tmp_path)
    caplog.set_level(logging.WARNING, logger="runpod_deploy.preflight")

    preflight.scan_consumer_pyproject(ctx)

    messages = " ".join(r.message for r in caplog.records)
    assert "[project.dependencies]" in messages
    assert "[tool.uv.sources]" in messages


@pytest.mark.unit
def test_scan_consumer_pyproject_skips_when_absent(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    ctx = _build_ctx(tmp_path)
    caplog.set_level(logging.INFO, logger="runpod_deploy.preflight")

    preflight.scan_consumer_pyproject(ctx)

    messages = " ".join(r.message for r in caplog.records)
    assert "no pyproject.toml" in messages
    assert not any(r.levelname == "WARNING" for r in caplog.records)


@pytest.mark.unit
def test_scan_consumer_pyproject_warns_on_unpinned_torch(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    (tmp_path / "pyproject.toml").write_text("""
[project]
name = "consumer"
version = "0.1.0"
dependencies = ["torch>=2.0.0"]
""")
    ctx = _build_ctx(tmp_path)
    caplog.set_level(logging.WARNING, logger="runpod_deploy.preflight")

    preflight.scan_consumer_pyproject(ctx)

    messages = " ".join(r.message for r in caplog.records)
    assert "torch" in messages
    assert "pytorch-cu128" in messages
    assert "runpod-gotchas.md" in messages


@pytest.mark.unit
def test_scan_consumer_pyproject_quiet_when_torch_pinned(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    (tmp_path / "pyproject.toml").write_text("""
[project]
name = "consumer"
version = "0.1.0"
dependencies = ["torch>=2.0.0"]
[tool.uv.sources]
torch = { index = "pytorch-cu128" }
""")
    ctx = _build_ctx(tmp_path)
    caplog.set_level(logging.WARNING, logger="runpod_deploy.preflight")

    preflight.scan_consumer_pyproject(ctx)

    torch_warnings = [
        r for r in caplog.records if "torch" in r.message and r.levelname == "WARNING"
    ]
    assert torch_warnings == []


@pytest.mark.unit
def test_scan_consumer_pyproject_does_not_match_torchvision(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    (tmp_path / "pyproject.toml").write_text("""
[project]
name = "consumer"
version = "0.1.0"
dependencies = ["torchvision>=0.15.0", "torchaudio"]
""")
    ctx = _build_ctx(tmp_path)
    caplog.set_level(logging.WARNING, logger="runpod_deploy.preflight")

    preflight.scan_consumer_pyproject(ctx)

    assert not any("torch" in r.message and r.levelname == "WARNING" for r in caplog.records)


@pytest.mark.unit
def test_scan_consumer_pyproject_clean_is_silent(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    (tmp_path / "pyproject.toml").write_text("""
[project]
name = "consumer"
version = "0.1.0"
dependencies = ["eval-toolkit"]
""")
    ctx = _build_ctx(tmp_path)
    caplog.set_level(logging.WARNING, logger="runpod_deploy.preflight")

    preflight.scan_consumer_pyproject(ctx)

    assert not any(r.levelname == "WARNING" for r in caplog.records)


# ---------- scan_staged_payloads_for_absolute_paths ----------


@pytest.mark.unit
def test_scan_staged_payloads_flags_macos_user_path(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    src_dir = tmp_path / "src"
    src_dir.mkdir()
    (src_dir / "loader.py").write_text(
        'PATH = "/Users/brandonbehring/data/probe.yaml"\nprint(PATH)\n'
    )
    ctx = _build_ctx(tmp_path, staging_source="./src")
    caplog.set_level(logging.WARNING, logger="runpod_deploy.preflight")

    preflight.scan_staged_payloads_for_absolute_paths(ctx)

    messages = " ".join(r.message for r in caplog.records)
    assert "loader.py:1" in messages
    assert "/Users/brandonbehring/" in messages
