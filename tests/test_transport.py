from __future__ import annotations

from pathlib import Path

import pytest

from runpod_deploy.transport import RemoteRunner, rsync_argv


@pytest.mark.unit
def test_rsync_argv_avoids_owner_group_perm_churn(tmp_path: Path) -> None:
    argv = rsync_argv(
        source="src/",
        destination="root@example:/workspace/project/",
        port=22,
        ssh_key=tmp_path / "id_ed25519",
        excludes=(),
    )

    assert "--no-owner" in argv
    assert "--no-group" in argv
    assert "--no-perms" in argv
    assert "--delete" in argv


@pytest.mark.unit
def test_rsync_argv_can_disable_delete(tmp_path: Path) -> None:
    argv = rsync_argv(
        source="root@example:/workspace/models/",
        destination=str(tmp_path / "models"),
        port=22,
        ssh_key=tmp_path / "id_ed25519",
        excludes=(),
        delete=False,
    )

    assert "--delete" not in argv


@pytest.mark.unit
def test_detached_ssh_uses_f_n_t_flags(tmp_path: Path) -> None:
    runner = RemoteRunner(host="203.0.113.4", port=22022, ssh_key=tmp_path / "id_ed25519")

    argv = runner.ssh_argv("nohup bash run.sh > log 2>&1 < /dev/null", detached=True)

    assert "-f" in argv
    assert "-n" in argv
    assert "-T" in argv
    assert "-tt" not in argv


@pytest.mark.unit
def test_proxy_target_preserves_user_host(tmp_path: Path) -> None:
    runner = RemoteRunner(
        host="pod-token@ssh.runpod.io",
        port=22,
        ssh_key=tmp_path / "id_ed25519",
    )

    assert runner.target == "pod-token@ssh.runpod.io"
