from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest

from runpod_deploy.cli import main


@pytest.mark.unit
def test_capture_env_emits_json_object_to_stdout(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    project = tmp_path / "proj"
    project.mkdir()
    (project / "uv.lock").write_text("locked")

    responses = iter(["abcdef0123" * 4, "main", ""])  # sha, branch, porcelain (clean)

    def fake_run(args: tuple[str, ...], **_: object) -> subprocess.CompletedProcess[str]:
        return subprocess.CompletedProcess(
            args=args, returncode=0, stdout=next(responses) + "\n", stderr=""
        )

    monkeypatch.setattr("runpod_deploy.metadata.subprocess.run", fake_run)
    rc = main(["capture-env", "--project-root", str(project)])
    captured = capsys.readouterr()

    assert rc == 0
    payload = json.loads(captured.out)
    assert payload["local_git_sha"] == "abcdef0123" * 4
    assert payload["local_git_branch"] == "main"
    assert payload["local_git_dirty"] is False
    assert payload["payload_lockfile"] == "uv.lock"
    assert isinstance(payload["payload_lockfile_sha256"], str)


@pytest.mark.unit
def test_capture_env_emits_nulls_for_non_git_non_lockfile_dir(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    project = tmp_path / "proj"
    project.mkdir()

    def fake_run(args: tuple[str, ...], **_: object) -> subprocess.CompletedProcess[str]:
        return subprocess.CompletedProcess(
            args=args, returncode=128, stdout="", stderr="not a git repository"
        )

    monkeypatch.setattr("runpod_deploy.metadata.subprocess.run", fake_run)
    rc = main(["capture-env", "--project-root", str(project)])
    captured = capsys.readouterr()

    assert rc == 0
    payload = json.loads(captured.out)
    assert payload["local_git_sha"] is None
    assert payload["payload_lockfile"] is None
    assert payload["payload_lockfile_sha256"] is None


@pytest.mark.unit
def test_capture_env_defaults_project_root_to_cwd(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.chdir(tmp_path)

    def fake_run(args: tuple[str, ...], **_: object) -> subprocess.CompletedProcess[str]:
        return subprocess.CompletedProcess(
            args=args, returncode=128, stdout="", stderr="not a git repository"
        )

    monkeypatch.setattr("runpod_deploy.metadata.subprocess.run", fake_run)
    rc = main(["capture-env"])
    captured = capsys.readouterr()

    assert rc == 0
    payload = json.loads(captured.out)
    assert "local_git_sha" in payload
    assert "payload_lockfile" in payload
