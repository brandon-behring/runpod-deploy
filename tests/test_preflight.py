from __future__ import annotations

import json
import logging
import textwrap
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
    staging_excludes_default: bool = False,
    staging_excludes_extra: tuple[str, ...] = (),
    run_body: str = 'echo "[demo] DONE"',
    setup_commands: tuple[str, ...] = (),
) -> Path:
    staging_block = ""
    if staging_source is not None:
        opts: list[str] = []
        if staging_excludes_default:
            opts.append("    excludes_default: true")
        if staging_excludes_extra:
            extras = "\n".join(f"      - {p}" for p in staging_excludes_extra)
            opts.append(f"    excludes_extra:\n{extras}")
        opts_block = ("\n" + "\n".join(opts)) if opts else ""
        staging_block = f"""
staging:
  - label: code
    source: {staging_source}
    destination: /workspace/code{opts_block}
"""
    setup_block = ""
    if setup_commands:
        items = "\n".join(f'  - command: "{c}"' for c in setup_commands)
        setup_block = f"\nsetup:\n{items}\n"
    indented_body = textwrap.indent(run_body, "    ")
    path.write_text(f"""
schema_version: 2
name: demo
run_id_prefix: demo
state_file: {state_file}
pod:
  image: runpod/pytorch:2.4.0-py3.11-cuda12.4.1-devel-ubuntu22.04
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
{indented_body}
{staging_block}{setup_block}""")
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
schema_version: 2
name: demo
state_file: {tmp_path / "state.json"}
pod:
  image: runpod/pytorch
  datacenters: [EU-RO-1]
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


# ---------- regression: #76 — scan respects staging excludes ----------


@pytest.mark.unit
def test_scan_staged_payloads_skips_universal_noise(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    """Files inside .venv/, .mypy_cache/, etc. are always skipped (closes #76)."""
    src_dir = tmp_path / "src"
    src_dir.mkdir()
    venv_pkg = src_dir / ".venv" / "lib" / "python3.13" / "site-packages"
    venv_pkg.mkdir(parents=True)
    (venv_pkg / "foo.py").write_text('CACHE = "/Users/ali/.cache/uv"\n')
    mypy_cache = src_dir / ".mypy_cache" / "3.13"
    mypy_cache.mkdir(parents=True)
    (mypy_cache / "meta.json").write_text('{"path": "/home/srush/work/foo.py"}\n')
    ctx = _build_ctx(tmp_path, staging_source="./src")
    caplog.set_level(logging.WARNING, logger="runpod_deploy.preflight")

    preflight.scan_staged_payloads_for_absolute_paths(ctx)

    assert not any("scan" in r.message for r in caplog.records)


@pytest.mark.unit
def test_scan_staged_payloads_skips_consumer_excludes_extra(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    """Paths in excludes_extra are skipped via push.effective_excludes (closes #76)."""
    src_dir = tmp_path / "src"
    src_dir.mkdir()
    refs = src_dir / "experiments" / "refs"
    refs.mkdir(parents=True)
    (refs / "third_party_clone.py").write_text('PATH = "/home/ali/work/proj"\n')
    ctx = _build_ctx(
        tmp_path,
        staging_source="./src",
        staging_excludes_extra=("experiments/refs/",),
    )
    caplog.set_level(logging.WARNING, logger="runpod_deploy.preflight")

    preflight.scan_staged_payloads_for_absolute_paths(ctx)

    assert not any("scan" in r.message for r in caplog.records)


@pytest.mark.unit
def test_scan_staged_payloads_still_flags_real_findings(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    """Files OUTSIDE excluded directories still get warnings (signal preserved)."""
    src_dir = tmp_path / "src"
    src_dir.mkdir()
    # noise inside .venv → should be ignored
    venv = src_dir / ".venv" / "lib"
    venv.mkdir(parents=True)
    (venv / "noise.py").write_text('PATH = "/Users/x/cache"\n')
    # real finding in a non-excluded file
    (src_dir / "loader.py").write_text('PATH = "/Users/x/data.yaml"\n')
    ctx = _build_ctx(tmp_path, staging_source="./src")
    caplog.set_level(logging.WARNING, logger="runpod_deploy.preflight")

    preflight.scan_staged_payloads_for_absolute_paths(ctx)

    messages = [r.message for r in caplog.records]
    assert any("loader.py:1" in m for m in messages)
    assert not any("noise.py" in m for m in messages)


# ---------- regression: #78 + #79 — optional-extras gated by run-body ----------


@pytest.mark.unit
def test_scan_consumer_pyproject_silent_for_unused_optional_extra(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    """runpod-deploy in [optional-deps.cloud] is silent when --extra cloud not installed (closes #78)."""
    (tmp_path / "pyproject.toml").write_text("""
[project]
name = "consumer"
version = "0.1.0"
dependencies = ["eval-toolkit"]

[project.optional-dependencies]
cloud = ["runpod-deploy>=0.7.5"]
""")
    ctx = _build_ctx(tmp_path, run_body="uv sync --extra dev --extra gpu\necho ok")
    caplog.set_level(logging.WARNING, logger="runpod_deploy.preflight")

    preflight.scan_consumer_pyproject(ctx)

    assert not any("runpod-deploy" in r.message for r in caplog.records)


@pytest.mark.unit
def test_scan_consumer_pyproject_warns_for_used_optional_extra(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    """Signal preserved when run-body DOES install the extra."""
    (tmp_path / "pyproject.toml").write_text("""
[project]
name = "consumer"
version = "0.1.0"
dependencies = ["eval-toolkit"]

[project.optional-dependencies]
cloud = ["runpod-deploy>=0.7.5"]
""")
    ctx = _build_ctx(tmp_path, run_body="uv sync --extra cloud\necho ok")
    caplog.set_level(logging.WARNING, logger="runpod_deploy.preflight")

    preflight.scan_consumer_pyproject(ctx)

    messages = " ".join(r.message for r in caplog.records)
    assert "runpod-deploy" in messages
    assert "[project.optional-dependencies.cloud]" in messages


@pytest.mark.unit
def test_scan_consumer_pyproject_silent_when_no_uv_sync(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    """Pre-built-image case: no uv sync = no signal = no optional-extras warnings (closes #79)."""
    (tmp_path / "pyproject.toml").write_text("""
[project]
name = "consumer"
version = "0.1.0"
dependencies = ["eval-toolkit"]

[project.optional-dependencies]
torch = ["torch>=2.0", "transformers>=4.40"]
""")
    ctx = _build_ctx(tmp_path)  # default run.body has no `uv sync`
    caplog.set_level(logging.WARNING, logger="runpod_deploy.preflight")

    preflight.scan_consumer_pyproject(ctx)

    assert not any("torch" in r.message and r.levelname == "WARNING" for r in caplog.records)


@pytest.mark.unit
def test_scan_consumer_pyproject_warns_when_all_extras(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    """`uv sync --all-extras` installs everything, so torch in any optional group warns."""
    (tmp_path / "pyproject.toml").write_text("""
[project]
name = "consumer"
version = "0.1.0"
dependencies = ["eval-toolkit"]

[project.optional-dependencies]
torch = ["torch>=2.0"]
""")
    ctx = _build_ctx(tmp_path, run_body="uv sync --all-extras\necho ok")
    caplog.set_level(logging.WARNING, logger="runpod_deploy.preflight")

    preflight.scan_consumer_pyproject(ctx)

    messages = " ".join(r.message for r in caplog.records)
    assert "torch" in messages
    assert "pytorch-cu128" in messages


# ---------- regression: install-extras parser ----------


@pytest.mark.unit
def test_parsed_install_extras_finds_setup_commands(tmp_path: Path) -> None:
    """Setup-block commands are also parsed for `uv sync --extra X`."""
    ctx = _build_ctx(
        tmp_path,
        setup_commands=("uv sync --extra cloud",),
    )
    parsed = preflight._parsed_install_extras(ctx.spec)
    assert parsed.has_uv_sync is True
    assert parsed.named_extras == frozenset({"cloud"})
    assert parsed.all_extras is False


@pytest.mark.unit
def test_parsed_install_extras_handles_equals_form(tmp_path: Path) -> None:
    """Both `--extra X` and `--extra=X` forms are recognized."""
    ctx = _build_ctx(tmp_path, run_body="uv sync --extra=dev --extra gpu")
    parsed = preflight._parsed_install_extras(ctx.spec)
    assert parsed.has_uv_sync is True
    assert parsed.named_extras == frozenset({"dev", "gpu"})


# ---------- regression: path matcher ----------


@pytest.mark.unit
def test_path_matches_rsync_exclude_directory_anywhere() -> None:
    """`.venv/` matches any path inside a `.venv` directory at any depth."""
    patterns = (".venv/",)
    assert preflight._path_matches_rsync_exclude(Path(".venv/lib/foo.py"), patterns)
    assert preflight._path_matches_rsync_exclude(Path("nested/.venv/x.py"), patterns)
    assert not preflight._path_matches_rsync_exclude(Path("src/foo.py"), patterns)


@pytest.mark.unit
def test_path_matches_rsync_exclude_glob() -> None:
    """`**/*.pyc` matches any file ending in `.pyc` at any depth."""
    patterns = ("**/*.pyc",)
    assert preflight._path_matches_rsync_exclude(Path("foo.pyc"), patterns)
    assert preflight._path_matches_rsync_exclude(Path("a/b/c.pyc"), patterns)
    assert not preflight._path_matches_rsync_exclude(Path("foo.py"), patterns)


@pytest.mark.unit
def test_path_matches_rsync_exclude_prefix() -> None:
    """`experiments/refs/` is root-anchored — matches at the source root only."""
    patterns = ("experiments/refs/",)
    assert preflight._path_matches_rsync_exclude(Path("experiments/refs/x.py"), patterns)
    assert not preflight._path_matches_rsync_exclude(Path("other/experiments/refs/x.py"), patterns)
