# RunPod Gotchas

These are operational constraints learned from prior project runs.

- Network volumes require secure pods. Community pods cannot mount them.
- GPU pods should expose SSH explicitly with `--ports 22/tcp`.
- Omit `--gpu-count` when the count is one; older `runpodctl`/API behavior
  rejected `--gpu-count 1` with an opaque error.
- Wait for both running status and SSH host/port. Running status alone can
  appear before `sshd` is ready.
- Launch long jobs with detached SSH using `ssh -f -n -T`; PTY-based detached
  commands can be killed by SSH session teardown.
- Rsync to RunPod volumes without owner/group/perms to avoid filesystem churn:
  `--no-owner --no-group --no-perms --omit-dir-times`.
- `/workspace` can be a mounted volume. Do not bake project virtualenvs there
  in reusable images; prefer `/opt/...` and set `UV_PROJECT_ENVIRONMENT`.
- Source `/workspace/secrets/env` if present, but never put secrets directly in
  configs or manifests.
