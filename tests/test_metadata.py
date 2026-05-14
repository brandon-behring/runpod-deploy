from __future__ import annotations

import logging
import subprocess
from pathlib import Path

import pytest

from runpod_deploy.metadata import capture_local_git, capture_payload_lockfile


@pytest.mark.unit
def test_capture_local_git_returns_sha_and_branch_for_clean_repo(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    project = tmp_path / "proj"
    project.mkdir()
    sha = "abcdef1234567890" * 2 + "abcd"  # 40 hex chars
    branch = "main"
    porcelain = ""

    responses = iter([sha, branch, porcelain])

    def fake_run(args: tuple[str, ...], **_: object) -> subprocess.CompletedProcess[str]:
        out = next(responses) + "\n"
        return subprocess.CompletedProcess(args=args, returncode=0, stdout=out, stderr="")

    monkeypatch.setattr("runpod_deploy.metadata.subprocess.run", fake_run)
    result = capture_local_git(project)

    assert result == {
        "local_git_sha": sha,
        "local_git_dirty": False,
        "local_git_branch": branch,
    }


@pytest.mark.unit
def test_capture_local_git_marks_dirty_when_porcelain_nonempty(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    project = tmp_path / "proj"
    project.mkdir()
    responses = iter(["sha", "feature/x", " M src/foo.py\n?? new.py"])

    def fake_run(args: tuple[str, ...], **_: object) -> subprocess.CompletedProcess[str]:
        return subprocess.CompletedProcess(
            args=args, returncode=0, stdout=next(responses) + "\n", stderr=""
        )

    monkeypatch.setattr("runpod_deploy.metadata.subprocess.run", fake_run)
    result = capture_local_git(project)

    assert result["local_git_dirty"] is True
    assert result["local_git_branch"] == "feature/x"


@pytest.mark.unit
def test_capture_local_git_returns_null_when_not_a_git_repo(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    project = tmp_path / "proj"
    project.mkdir()

    def fake_run(args: tuple[str, ...], **_: object) -> subprocess.CompletedProcess[str]:
        return subprocess.CompletedProcess(
            args=args,
            returncode=128,
            stdout="",
            stderr="fatal: not a git repository (or any parent up to mount point /)",
        )

    monkeypatch.setattr("runpod_deploy.metadata.subprocess.run", fake_run)
    caplog.set_level(logging.WARNING, logger="runpod_deploy.metadata")
    result = capture_local_git(project)

    assert result == {
        "local_git_sha": None,
        "local_git_dirty": None,
        "local_git_branch": None,
    }
    assert "exited 128" in caplog.text


@pytest.mark.unit
def test_capture_local_git_handles_missing_git_binary(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    project = tmp_path / "proj"
    project.mkdir()

    def fake_run(*_: object, **__: object) -> subprocess.CompletedProcess[str]:
        raise FileNotFoundError("git")

    monkeypatch.setattr("runpod_deploy.metadata.subprocess.run", fake_run)
    caplog.set_level(logging.WARNING, logger="runpod_deploy.metadata")
    result = capture_local_git(project)

    assert result["local_git_sha"] is None
    assert "git not on PATH" in caplog.text


@pytest.mark.unit
def test_capture_local_git_returns_null_when_directory_missing(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    caplog.set_level(logging.WARNING, logger="runpod_deploy.metadata")
    result = capture_local_git(tmp_path / "does-not-exist")

    assert result == {
        "local_git_sha": None,
        "local_git_dirty": None,
        "local_git_branch": None,
    }
    assert "is not a directory" in caplog.text


@pytest.mark.unit
def test_capture_payload_lockfile_prefers_uv_lock_over_requirements(tmp_path: Path) -> None:
    project = tmp_path / "proj"
    project.mkdir()
    (project / "uv.lock").write_text("uv lock contents")
    (project / "requirements.txt").write_text("requirements contents")

    result = capture_payload_lockfile(project)

    assert result["payload_lockfile"] == "uv.lock"
    assert isinstance(result["payload_lockfile_sha256"], str)
    assert len(result["payload_lockfile_sha256"]) == 64  # type: ignore[arg-type]


@pytest.mark.unit
def test_capture_payload_lockfile_falls_back_to_requirements(tmp_path: Path) -> None:
    project = tmp_path / "proj"
    project.mkdir()
    (project / "requirements.txt").write_text("only requirements")

    result = capture_payload_lockfile(project)

    assert result["payload_lockfile"] == "requirements.txt"
    assert isinstance(result["payload_lockfile_sha256"], str)


@pytest.mark.unit
def test_capture_payload_lockfile_hash_is_stable_for_same_content(tmp_path: Path) -> None:
    project_a = tmp_path / "a"
    project_b = tmp_path / "b"
    project_a.mkdir()
    project_b.mkdir()
    (project_a / "uv.lock").write_text("identical contents")
    (project_b / "uv.lock").write_text("identical contents")

    assert (
        capture_payload_lockfile(project_a)["payload_lockfile_sha256"]
        == capture_payload_lockfile(project_b)["payload_lockfile_sha256"]
    )


@pytest.mark.unit
def test_capture_payload_lockfile_returns_null_when_neither_present(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    project = tmp_path / "proj"
    project.mkdir()

    caplog.set_level(logging.WARNING, logger="runpod_deploy.metadata")
    result = capture_payload_lockfile(project)

    assert result == {"payload_lockfile": None, "payload_lockfile_sha256": None}
    assert "no lockfile" in caplog.text
