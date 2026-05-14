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
- `runpodctl doctor`'s `ssh_key.synced_to_cloud: true` does **not** mean your
  local `~/.ssh/id_ed25519` is registered with the account — only that *some*
  ed25519 key is. Pods will fail with `Permission denied (publickey,password)`
  despite the green doctor report. Verify with `runpodctl ssh list-keys` and
  match the pubkey content against `~/.ssh/id_ed25519.pub`; if absent, register
  with `runpodctl ssh add-key --key-file ~/.ssh/id_ed25519.pub` before the next
  pod create. Existing pods will not pick up newly-added keys.
- The RunPod stock `runpod/pytorch:*` images ship without `rsync`. Configs that
  use `staging` or `artifacts` must install it in `setup` before the first
  rsync call, e.g.
  `which rsync >/dev/null 2>&1 || { apt-get update -qq && DEBIAN_FRONTEND=noninteractive apt-get install -y -qq rsync ; }`.

## Pinning torch to a CUDA-compatible wheel

RunPod pods (as of 2026-05) provide NVIDIA drivers supporting CUDA up to 12.8.
Newer torch wheels published to default PyPI can require CUDA 12.9+ and will
fail `torch.cuda.is_available()` despite the GPU being functional. The failure
mode is non-obvious: `nvidia-smi` works, `torch.cuda.is_available()` returns
`False`, and the error message blames the driver — not the wheel.

Pin torch to a CUDA-specific wheel index in the **consumer** `pyproject.toml`:

```toml
[tool.uv]
environments = ["sys_platform == 'linux'"]   # skip macOS resolution churn

[tool.uv.sources]
torch = { index = "pytorch-cu128" }

[[tool.uv.index]]
name = "pytorch-cu128"
url = "https://download.pytorch.org/whl/cu128"
explicit = true
```

When RunPod ships pods with newer drivers, bump the index URL (`cu128` →
`cu129` etc.) and re-run `uv sync` on the pod. `runpod-deploy validate
--scan-consumer` warns when `torch` is in `[project.dependencies]` but has no
corresponding `[tool.uv.sources]` entry.

## Persisting per-row predictions (consumer-repo discipline)

Eval pipelines that ship only summary metrics (PR-AUC, ROC-AUC, recall@FPR at a
small set of pre-baked pinpoints) close off **every downstream analysis** that
needs per-row scores: calibration (ECE / Brier / reliability curves), threshold
sweeps (detection vs verification policies), ROC curves, recall@FPR at
arbitrary pinpoints, paired-bootstrap rung-vs-rung deltas, per-style breakdowns
beyond the original tagger fidelity.

This was a real failure mode in a consumer-repo iteration: the canonical pod
run finished, the summary metrics JSON was pulled, and pod artifacts (including
LoRA checkpoints) were destroyed. Re-running inference to recover scores cost
~80 min on H100 NVL + ~$5. A 2x file-size increase in the artifacts pull would
have prevented this entirely.

**Recommended consumer-repo discipline**:

- Every training/inference run persists per-row predictions alongside summary
  metrics. Suggested layout: `evals/<version>/predictions/<rung>__<fold>__<seed>.parquet`
  with columns `text_hash, y_true, y_score, source, slice`.
- The `runpod-deploy` pull config (typically `artifacts:` block in the run
  YAML) MUST include the `evals/<version>/predictions/` glob so per-row
  artifacts are pulled before pod teardown.
- For LoRA / fine-tuned rungs, also push checkpoints to HF Hub (or S3, etc.)
  before pod teardown. Local pod artifacts are destroyed with the pod.
- An invariant test in the consumer repo can assert that every cell in
  `evals/<version>/results.json` has a corresponding `predictions/` file.

This is consumer-repo discipline, not a `runpod-deploy` feature. But pulling
predictions IS a `runpod-deploy` concern (artifacts pull-pattern), and it's
exactly the kind of gotcha new consumer projects hit. Document it here so it
shows up in `--scan-consumer` reviews of future repos.
