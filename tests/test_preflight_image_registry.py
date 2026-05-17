from __future__ import annotations

import io
import logging
import urllib.error
from pathlib import Path
from typing import Any
from unittest.mock import patch

import pytest

from runpod_deploy import preflight
from runpod_deploy.config import build_job_context, load_job_spec
from runpod_deploy.preflight import _check_docker_hub_tag, _DockerImageRef, _parse_docker_image


@pytest.fixture(autouse=True)
def _clear_registry_cache() -> None:
    preflight._REGISTRY_CHECK_CACHE.clear()


# ---------- _parse_docker_image ----------


@pytest.mark.unit
def test_parse_docker_image_owner_image_tag() -> None:
    ref = _parse_docker_image("runpod/pytorch:1.0.3-cu1281-torch290-ubuntu2204")
    assert ref == _DockerImageRef(
        owner="runpod", image="pytorch", tag="1.0.3-cu1281-torch290-ubuntu2204"
    )


@pytest.mark.unit
def test_parse_docker_image_library_image_tag() -> None:
    assert _parse_docker_image("python:3.11") == _DockerImageRef(
        owner="library", image="python", tag="3.11"
    )


@pytest.mark.unit
def test_parse_docker_image_no_tag_defaults_to_latest() -> None:
    assert _parse_docker_image("runpod/pytorch") == _DockerImageRef(
        owner="runpod", image="pytorch", tag="latest"
    )


@pytest.mark.unit
def test_parse_docker_image_library_no_tag_defaults_to_latest() -> None:
    assert _parse_docker_image("python") == _DockerImageRef(
        owner="library", image="python", tag="latest"
    )


@pytest.mark.unit
@pytest.mark.parametrize(
    "image",
    [
        "ghcr.io/owner/repo:tag",
        "quay.io/owner/repo:tag",
        "registry.example.com:5000/owner/repo:tag",
    ],
)
def test_parse_docker_image_non_docker_hub_returns_none(image: str) -> None:
    assert _parse_docker_image(image) is None


@pytest.mark.unit
@pytest.mark.parametrize("image", ["", ":tag", "runpod/foo/bar:tag"])
def test_parse_docker_image_malformed_returns_none(image: str) -> None:
    assert _parse_docker_image(image) is None


# ---------- _check_docker_hub_tag ----------


class _FakeResponse:
    def __init__(self, code: int) -> None:
        self._code = code

    def __enter__(self) -> _FakeResponse:
        return self

    def __exit__(self, *args: object) -> None:
        return None

    def getcode(self) -> int:
        return self._code


def _fake_response(code: int) -> Any:
    return _FakeResponse(code)


@pytest.mark.unit
def test_check_docker_hub_tag_returns_ok_on_200() -> None:
    ref = _DockerImageRef(owner="runpod", image="pytorch", tag="1.0.3")
    with patch("urllib.request.urlopen", return_value=_fake_response(200)):
        status, detail = _check_docker_hub_tag(ref)
    assert status == "ok"
    assert detail is None


@pytest.mark.unit
def test_check_docker_hub_tag_returns_missing_on_404() -> None:
    ref = _DockerImageRef(owner="runpod", image="pytorch", tag="phantom")
    err = urllib.error.HTTPError("u", 404, "Not Found", {}, io.BytesIO(b""))  # type: ignore[arg-type]
    with patch("urllib.request.urlopen", side_effect=err):
        status, detail = _check_docker_hub_tag(ref)
    assert status == "missing"
    assert "404" in (detail or "")


@pytest.mark.unit
def test_check_docker_hub_tag_returns_unknown_on_500() -> None:
    ref = _DockerImageRef(owner="runpod", image="pytorch", tag="1.0.3")
    err = urllib.error.HTTPError("u", 500, "Server Error", {}, io.BytesIO(b""))  # type: ignore[arg-type]
    with patch("urllib.request.urlopen", side_effect=err):
        status, _ = _check_docker_hub_tag(ref)
    assert status == "unknown"


@pytest.mark.unit
def test_check_docker_hub_tag_returns_unknown_on_network_error() -> None:
    ref = _DockerImageRef(owner="runpod", image="pytorch", tag="1.0.3")
    with patch("urllib.request.urlopen", side_effect=urllib.error.URLError("offline")):
        status, detail = _check_docker_hub_tag(ref)
    assert status == "unknown"
    assert "offline" in (detail or "")


@pytest.mark.unit
def test_check_docker_hub_tag_returns_unknown_on_timeout() -> None:
    ref = _DockerImageRef(owner="runpod", image="pytorch", tag="1.0.3")
    with patch("urllib.request.urlopen", side_effect=TimeoutError("slow")):
        status, _ = _check_docker_hub_tag(ref)
    assert status == "unknown"


# ---------- check_image_registry (end-to-end on JobContext) ----------


def _write_min_config(path: Path, *, state_file: Path, image: str) -> Path:
    path.write_text(f"""
schema_version: 2
name: demo
run_id_prefix: demo
state_file: {state_file}
pod:
  image: {image}
  datacenters: [EU-RO-1]
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
""")
    return path


def _build_ctx(tmp_path: Path, *, image: str) -> object:
    cfg = _write_min_config(tmp_path / "job.yaml", state_file=tmp_path / "state.json", image=image)
    return build_job_context(load_job_spec(cfg), cfg)


@pytest.mark.unit
def test_check_image_registry_logs_ok_on_200(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    ctx = _build_ctx(tmp_path, image="runpod/pytorch:1.0.3")
    with (
        caplog.at_level(logging.INFO, logger="runpod_deploy.preflight"),
        patch("urllib.request.urlopen", return_value=_fake_response(200)),
    ):
        preflight.check_image_registry(ctx)  # type: ignore[arg-type]
    assert any(
        "ok:" in r.message and "runpod/pytorch:1.0.3" in r.message
        for r in caplog.records
        if r.levelno == logging.INFO
    )


@pytest.mark.unit
def test_check_image_registry_warns_on_404(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    ctx = _build_ctx(tmp_path, image="runpod/pytorch:phantom")
    err = urllib.error.HTTPError("u", 404, "Not Found", {}, io.BytesIO(b""))  # type: ignore[arg-type]
    with (
        caplog.at_level(logging.WARNING, logger="runpod_deploy.preflight"),
        patch("urllib.request.urlopen", side_effect=err),
    ):
        preflight.check_image_registry(ctx)  # type: ignore[arg-type]
    warnings = [r for r in caplog.records if r.levelno == logging.WARNING]
    assert warnings, "expected a WARNING for the phantom tag"
    msg = warnings[0].message
    assert "does NOT exist" in msg
    assert "image-pull-backoff" in msg
    assert "--skip-registry-check" in msg


@pytest.mark.unit
def test_check_image_registry_logs_info_on_network_error(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    ctx = _build_ctx(tmp_path, image="runpod/pytorch:1.0.3")
    with (
        caplog.at_level(logging.INFO, logger="runpod_deploy.preflight"),
        patch("urllib.request.urlopen", side_effect=urllib.error.URLError("offline")),
    ):
        preflight.check_image_registry(ctx)  # type: ignore[arg-type]
    infos = [r for r in caplog.records if r.levelno == logging.INFO]
    assert any("could not verify" in r.message for r in infos)
    assert not any(r.levelno == logging.WARNING for r in caplog.records)


@pytest.mark.unit
def test_check_image_registry_skips_non_docker_hub(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    ctx = _build_ctx(tmp_path, image="ghcr.io/owner/repo:tag")
    with (
        caplog.at_level(logging.INFO, logger="runpod_deploy.preflight"),
        patch("urllib.request.urlopen") as urlopen,
    ):
        preflight.check_image_registry(ctx)  # type: ignore[arg-type]
    urlopen.assert_not_called()
    assert any("not on Docker Hub" in r.message for r in caplog.records)


@pytest.mark.unit
def test_check_image_registry_caches_per_image(tmp_path: Path) -> None:
    ctx = _build_ctx(tmp_path, image="runpod/pytorch:1.0.3")
    with patch("urllib.request.urlopen", return_value=_fake_response(200)) as urlopen:
        preflight.check_image_registry(ctx)  # type: ignore[arg-type]
        preflight.check_image_registry(ctx)  # type: ignore[arg-type]
        preflight.check_image_registry(ctx)  # type: ignore[arg-type]
    assert urlopen.call_count == 1


# ---------- CLI wiring ----------


def _write_cli_config(path: Path, *, image: str) -> Path:
    path.write_text(f"""
schema_version: 2
name: demo
run_id_prefix: demo
local:
  project_root: .
  required_paths:
    - pyproject.toml
pod:
  image: {image}
  datacenters: [US-MD-1]
  gpu_order:
    - NVIDIA A100-SXM4-80GB
storage:
  mode: ephemeral
  volume_gb: 20
run:
  script_path: /workspace/demo.sh
  log_path: /workspace/demo.log
  success_marker: "[demo] DONE"
  body: |
    echo "[demo] DONE"
""")
    return path


@pytest.mark.unit
def test_cli_validate_check_image_registry_invokes_check(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    from runpod_deploy.cli import main

    (tmp_path / "pyproject.toml").write_text("[project]\nname='demo'\n")
    cfg = _write_cli_config(tmp_path / "job.yaml", image="runpod/pytorch:1.0.3")
    caplog.set_level(logging.INFO, logger="runpod_deploy.preflight")
    with patch("urllib.request.urlopen", return_value=_fake_response(200)):
        rc = main(["validate", "--config", str(cfg), "--check-image-registry"])
    assert rc == 0
    assert any("[image-registry] ok" in r.message for r in caplog.records)


@pytest.mark.unit
def test_cli_validate_skip_registry_check_suppresses_under_all(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    from runpod_deploy.cli import main

    (tmp_path / "pyproject.toml").write_text("[project]\nname='demo'\n")
    cfg = _write_cli_config(tmp_path / "job.yaml", image="runpod/pytorch:phantom")
    caplog.set_level(logging.INFO, logger="runpod_deploy.preflight")
    err = urllib.error.HTTPError("u", 404, "Not Found", {}, io.BytesIO(b""))  # type: ignore[arg-type]
    with (
        patch("urllib.request.urlopen", side_effect=err) as urlopen,
        patch("runpod_deploy.preflight.check_gpu_availability"),
        patch("runpod_deploy.cli.validate_local_paths"),
    ):
        rc = main(
            [
                "validate",
                "--config",
                str(cfg),
                "--all",
                "--skip-registry-check",
            ]
        )
    assert rc == 0
    urlopen.assert_not_called()
    assert not any("[image-registry]" in r.message for r in caplog.records)
