from __future__ import annotations

from pathlib import Path

import pytest

from runpod_deploy.config import SecretSpec, build_job_context, load_job_spec
from runpod_deploy.orchestrator import _stage_secrets
from runpod_deploy.transport import RemoteRunner
from tests.conftest import FakeResult, FakeSubprocess


def _write_config_with_secrets(path: Path, *, secrets_block: str) -> Path:
    path.write_text(f"""
schema_version: 1
name: demo
state_file: {path.parent / "state.json"}
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
  success_marker: ok
  body: |
    echo ok
{secrets_block}
""")
    return path


# ---------- SecretSpec validation ----------


@pytest.mark.unit
def test_secret_spec_rejects_both_env_and_file() -> None:
    with pytest.raises(ValueError, match="must set exactly one of 'env' or 'file'"):
        SecretSpec(
            name="hf",
            destination="/workspace/secrets/env",
            env=("HF_TOKEN",),
            file="~/.hf-token",
        )


@pytest.mark.unit
def test_secret_spec_rejects_neither_env_nor_file() -> None:
    with pytest.raises(ValueError, match="must set exactly one of 'env' or 'file'"):
        SecretSpec(name="hf", destination="/workspace/secrets/env")


@pytest.mark.unit
def test_secret_spec_rejects_invalid_mode() -> None:
    with pytest.raises(ValueError, match="mode must be a 3- or 4-digit octal"):
        SecretSpec(
            name="hf",
            destination="/workspace/secrets/env",
            env=("HF_TOKEN",),
            mode="abc",
        )


@pytest.mark.unit
def test_secret_spec_rejects_invalid_env_identifier() -> None:
    with pytest.raises(ValueError, match="env must contain valid identifiers"):
        SecretSpec(
            name="hf",
            destination="/workspace/secrets/env",
            env=("HF-TOKEN",),
        )


@pytest.mark.unit
def test_secret_spec_rejects_relative_destination() -> None:
    with pytest.raises(ValueError, match="destination must be absolute or a template"):
        SecretSpec(name="hf", destination="secrets/env", env=("HF_TOKEN",))


# ---------- _stage_secrets behavior ----------


@pytest.mark.unit
def test_stage_secrets_env_writes_kv_file_and_pushes(
    fake_subprocess: FakeSubprocess,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("HF_TOKEN", "hf-secret-value")
    monkeypatch.setenv("OTHER", "other-value")
    cfg = _write_config_with_secrets(
        tmp_path / "job.yaml",
        secrets_block=(
            "secrets:\n"
            "  - name: tokens\n"
            "    destination: /workspace/secrets/env\n"
            "    env: [HF_TOKEN, OTHER]\n"
            "    mode: '0640'\n"
        ),
    )
    ctx = build_job_context(load_job_spec(cfg), cfg)
    runner = RemoteRunner(host="1.2.3.4", port=22, ssh_key=tmp_path / "fake-key")
    captured_contents: list[str] = []

    def capture_rsync(argv: list[str]) -> bool:
        if argv and argv[0] == "rsync":
            source_path = argv[-2]
            if Path(source_path).exists():
                captured_contents.append(Path(source_path).read_text())
            return True
        return False

    fake_subprocess.when(capture_rsync, FakeResult())

    _stage_secrets(runner, ctx)

    mkdir_calls = [c for c in fake_subprocess.calls if c and c[0] == "ssh"]
    assert any("mkdir -p /workspace/secrets" in " ".join(c) for c in mkdir_calls)

    rsync_calls = [c for c in fake_subprocess.calls if c and c[0] == "rsync"]
    assert len(rsync_calls) == 1
    assert "--chmod" in rsync_calls[0]
    assert "F640" in rsync_calls[0]
    assert rsync_calls[0][-1] == "root@1.2.3.4:/workspace/secrets/env"

    assert captured_contents == ["HF_TOKEN=hf-secret-value\nOTHER=other-value\n"]


@pytest.mark.unit
def test_stage_secrets_env_missing_var_raises(
    fake_subprocess: FakeSubprocess,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("HF_TOKEN", raising=False)
    cfg = _write_config_with_secrets(
        tmp_path / "job.yaml",
        secrets_block=(
            "secrets:\n"
            "  - name: hf\n"
            "    destination: /workspace/secrets/env\n"
            "    env: [HF_TOKEN]\n"
        ),
    )
    ctx = build_job_context(load_job_spec(cfg), cfg)
    runner = RemoteRunner(host="1.2.3.4", port=22, ssh_key=tmp_path / "fake-key")

    with pytest.raises(KeyError, match="requires env var 'HF_TOKEN'"):
        _stage_secrets(runner, ctx)


@pytest.mark.unit
def test_stage_secrets_file_copies_local_file(
    fake_subprocess: FakeSubprocess, tmp_path: Path
) -> None:
    secret_file = tmp_path / "openai.key"
    secret_file.write_text("sk-fake-token-value\n")
    cfg = _write_config_with_secrets(
        tmp_path / "job.yaml",
        secrets_block=(
            "secrets:\n"
            "  - name: openai\n"
            "    destination: /workspace/secrets/openai\n"
            f"    file: {secret_file}\n"
            "    mode: '0600'\n"
        ),
    )
    ctx = build_job_context(load_job_spec(cfg), cfg)
    runner = RemoteRunner(host="1.2.3.4", port=22, ssh_key=tmp_path / "fake-key")

    _stage_secrets(runner, ctx)

    rsync_calls = [c for c in fake_subprocess.calls if c and c[0] == "rsync"]
    assert len(rsync_calls) == 1
    assert rsync_calls[0][-2] == str(secret_file)
    assert rsync_calls[0][-1] == "root@1.2.3.4:/workspace/secrets/openai"
    assert "F600" in rsync_calls[0]


@pytest.mark.unit
def test_stage_secrets_file_missing_raises(fake_subprocess: FakeSubprocess, tmp_path: Path) -> None:
    cfg = _write_config_with_secrets(
        tmp_path / "job.yaml",
        secrets_block=(
            "secrets:\n"
            "  - name: missing\n"
            "    destination: /workspace/secrets/missing\n"
            f"    file: {tmp_path / 'does-not-exist.key'}\n"
        ),
    )
    ctx = build_job_context(load_job_spec(cfg), cfg)
    runner = RemoteRunner(host="1.2.3.4", port=22, ssh_key=tmp_path / "fake-key")

    with pytest.raises(FileNotFoundError, match="source file not found"):
        _stage_secrets(runner, ctx)
