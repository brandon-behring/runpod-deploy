# Troubleshooting

When something goes wrong. Each entry: **Symptom** (what you see) →
**Diagnosis** (what's happening underneath) → **Fix** (what to change).

Organized by phase of the lifecycle. Cross-reference
[`lifecycle.md`](lifecycle.md) for the full pipeline; this doc is
strictly "things have broken, what now."

---

## Provisioning failures

### `runpodctl pod create` fails with `unknown flag: --min-vcpu-count`

**Symptom**: pod create errors with
`{"error":"unknown flag: --min-vcpu-count"}` (or `--spot`, or
`--min-memory-in-gb`).

**Diagnosis**: your installed `runpodctl` version doesn't support the
flag. v0.3.2 added feature-detection so unsupported flags are *skipped*
with a WARNING rather than emitted blindly, but if you're on the old
runpod-deploy and a fresh runpodctl install you can still hit this.

**Fix**: upgrade to runpod-deploy ≥ v0.3.2. The probe parses
`runpodctl pod create --help` once per process; unsupported flags log
`runpodctl pod create does not support --<flag> in the locally-installed
version; skipping ...` and the pod still launches.

If a flag is essential for your workload (e.g., `--spot`), upgrade
`runpodctl` itself — `runpodctl version` to check, then
download a newer release.

---

### `no configured GPU is available` post-provision

**Symptom**: the orchestrator emits
`RuntimeError: no configured GPU is available in EU-RO-1; observed={...}`
after the pod create call but before SSH waits.

**Diagnosis**: one of two things:
1. **Name mismatch** — your YAML's `gpu_order` lists `NVIDIA RTX 4090`,
   but the actual RunPod API name is `NVIDIA GeForce RTX 4090`. The
   live datacenter dict doesn't have your key.
2. **Real stock-out** — every entry in `pod.gpu_order` is empty-stock
   in every datacenter in `pod.datacenters`.

**Fix**:
- Run `runpod-deploy validate --check-availability` (or `--all`)
  before `run` — it surfaces the mismatch + stock state upfront.
- Use `runpod-deploy gpu-list --datacenter EU-RO-1` to see exact
  names + current stock + per-hour prices.
- Widen `pod.gpu_order` to span more classes (the failover walks
  them in order); widen `pod.datacenters` for DC-level stock-out
  resilience.

---

### `Permission denied (publickey,password)` on SSH

**Symptom**: pod creates, but `_wait_for_sshd` retries indefinitely
or fails with auth errors.

**Diagnosis**: `runpodctl doctor`'s `ssh_key.synced_to_cloud: true`
only means *some* ed25519 key is synced — not necessarily your local
`~/.ssh/id_ed25519`. The pod's `authorized_keys` is populated from
the account-wide registered keys, and existing pods don't pick up
newly-added keys.

**Fix**:
- `runpodctl ssh list-keys` and match the pubkey content against
  `cat ~/.ssh/id_ed25519.pub`.
- If absent: `runpodctl ssh add-key --key-file ~/.ssh/id_ed25519.pub`,
  then **stop the current pod** and `runpod-deploy run` again. New
  pods get the updated keys.

---

### Network volume not mountable

**Symptom**: pod creation succeeds but no `/workspace/` directory.

**Diagnosis**: `storage.mode: network_volume` requires
`pod.cloud_type: SECURE`. Community pods can't mount network volumes.
Also, network volumes pin the pod to *one* datacenter — failover
across `pod.datacenters` is effectively single-element when you're
using a network volume.

**Fix**:
- Switch to `cloud_type: SECURE`, OR
- Switch to `storage.mode: ephemeral` and stage your data via
  `staging:` instead.
- `runpod-deploy validate` warns when `network_volume` is paired
  with `len(pod.datacenters) > 1`.

---

## Staging failures

### `Distribution not found at: file:///workspace/runpod-deploy`

**Symptom**: pod-side `uv sync` errors trying to install
`runpod-deploy` as a dep.

**Diagnosis**: the consumer pyproject lists `runpod-deploy` in
`[project.dependencies]` (often with `[tool.uv.sources]` pointing
at a local path). But `runpod-deploy` is a **local-only orchestrator**
— the pod runs the consumer's code, not the orchestrator. The pod
doesn't need it.

**Fix**:
- Remove `runpod-deploy` from `[project.dependencies]` and any
  matching `[tool.uv.sources]` entry in the consumer pyproject.
- `runpod-deploy validate --scan-consumer` (or `--all`) catches
  this statically before the pod runs.

---

### `FileNotFoundError: /Users/<name>/...` on pod

**Symptom**: pod runs, but immediately fails reading a file at
a path like `/Users/brandonbehring/foo/bar.yaml`.

**Diagnosis**: consumer code has hardcoded a local absolute path.
Works on the dev machine; breaks on every pod.

**Fix**:
- Refactor to use `Path(__file__).parent / "..."` or an explicit
  `staging:` entry that pushes the data file under `{remote_repo}`.
- `runpod-deploy validate --scan-consumer` (or `--all`) greps the
  staged payload for `/Users/`, `/home/`, `C:\Users\` patterns and
  WARNs before the pod runs.

---

### `project_root resolved to $HOME — this would stage your entire home directory`

**Symptom**: `validate` raises `ValueError: project_root resolved to
$HOME (...)`.

**Diagnosis**: `local.project_root: ../../..` (one `..` too many)
when the YAML lives at `<consumer>/configs/runpod/<job>.yaml`. The
correct value is `../..` — one to escape `runpod/`, one to escape
`configs/`.

**Fix**:
- Set `local.project_root: ../..` for the standard
  `<repo>/configs/runpod/<job>.yaml` layout.
- The guard prevents a catastrophic
  `rsync -a $HOME/ pod:/workspace/repo/` from running.

---

### Stock `runpod/pytorch:*` images have no `rsync`

**Symptom**: first staging step errors with `bash: rsync: command not found`.

**Diagnosis**: RunPod's stock PyTorch images ship without `rsync`.
runpod-deploy uses `rsync --info=progress2` for the staging push;
if the binary is missing the SSH command fails.

**Fix**: install rsync in a `setup:` command before any staging:

```yaml
setup:
  - command: |
      which rsync >/dev/null 2>&1 || {
        apt-get update -qq && \
        DEBIAN_FRONTEND=noninteractive apt-get install -y -qq rsync
      }
    timeout_sec: 300
```

---

### Default rsync excludes silently drop data files

**Symptom**: pod-side code looks for `evals/` or `artifacts/` data,
file not found.

**Diagnosis**: `staging[].excludes_default: true` (v0.4.0) adds the
hygiene preset (`.git/`, `.venv/`, caches). It does NOT exclude
`evals/`, `artifacts/`, or data dirs — but if you ALSO set
`excludes_extra: ["evals/", "artifacts/"]` you'll drop those.

**Fix**: review the merged exclude list at the entry's
`effective_excludes` property. Move data dirs out of `excludes_extra`
or use a stricter glob (`evals/tmp/` instead of `evals/`).

---

## Setup failures

### `CUDA initialization: NVIDIA driver too old`

**Symptom**: pod runs, `nvidia-smi` works, but
`torch.cuda.is_available()` returns False with
`UserWarning: CUDA initialization: The NVIDIA driver on your system is too old`.

**Diagnosis**: `uv sync` installed a torch wheel that requires a newer
CUDA than the pod's driver provides. As of 2026-05, RunPod ships
drivers supporting CUDA up to 12.8; default PyPI torch wheels may
require CUDA 12.9+.

**Fix**: pin torch to a CUDA-specific wheel index in the **consumer**
`pyproject.toml`:

```toml
[tool.uv]
environments = ["sys_platform == 'linux'"]

[tool.uv.sources]
torch = { index = "pytorch-cu128" }

[[tool.uv.index]]
name = "pytorch-cu128"
url = "https://download.pytorch.org/whl/cu128"
explicit = true
```

When RunPod ships pods with newer drivers, bump the index URL.

---

### `uv python install` fails on the pod

**Symptom**: with `pod.python_version` set (v0.5.0), the auto-injected
preflight step exits non-zero. The run aborts before user preflight.

**Diagnosis** (per the v0.5.0 PR-G "fail-fast" decision): one of
- `uv` itself isn't installed on the base image (most likely — install
  it in your `setup:` before the python_version pin tries to use it).
- Network blip during the interpreter download.
- The requested version doesn't exist (e.g., `python_version: "3.99"`).

**Fix**:
- Ensure `setup:` includes `curl -LsSf https://astral.sh/uv/install.sh | sh`
  before staging happens.
- Run `uv python list` locally to confirm the version string exists.
- For transient network failures, simply retry the `runpod-deploy run`.

---

## Run failures

### Secrets unavailable on ephemeral pods

**Symptom**: pod runs, code that needs `HF_TOKEN` or `OPENAI_API_KEY`
exits with auth errors. `network_volume` configs work; `ephemeral`
configs don't.

**Diagnosis**: pre-v0.2.x patterns staged secrets to
`/workspace/secrets/env` on the network volume. With ephemeral storage
the volume is fresh every run, so the secret file isn't there.

**Fix**: use the explicit `secrets:` block (shipped in the v0.2.x
cycle):

```yaml
secrets:
  - name: hf
    source_env: HF_TOKEN           # read from your local env var
    destination: /workspace/secrets/env
    var_name: HF_TOKEN
    mode: "0600"
```

The orchestrator reads the named local env var, writes
`HF_TOKEN=value` to a tempfile, and rsyncs it to the pod with restrictive
perms. Never logged. See [`config-reference.md`](config-reference.md).

---

### `ValueError: flash_attention_2 is not supported`

**Symptom**: transformer scorer loads cleanly on H100; fails on
A6000 / RTX A4000 with this error.

**Diagnosis**: `flash_attention_2` isn't supported across all GPU
generations. With `pod.gpu_order` listing multiple classes (the
recommended pattern for stock-out resilience), some shards land on
GPUs that don't support it.

**Fix**: wrap the model load with a try/except per
[`recipes/flash-attention-fallback.md`](recipes/flash-attention-fallback.md):

```python
try:
    encoder = AutoModel.from_pretrained(
        model_id, attn_implementation="flash_attention_2", ...
    )
except (ValueError, ImportError):
    encoder = AutoModel.from_pretrained(model_id, ...)
```

---

### Pod killed mid-run; manifest shows `pod_final_state=pod_killed_unexpected`

**Symptom**: the run script started, ran for a while, then was killed.
The manifest's `pod_final_state` is `pod_killed_unexpected` rather
than `EXITED`.

**Diagnosis**: RunPod-side kill (OOM, host issue, spot-pod preemption,
or quota). Telemetry's pod-kill detector caught it and recorded the
state.

**Fix**:
- For OOM: scale `pod.container_disk_gb`, scale model precision,
  or pick a higher-VRAM GPU class.
- For spot preemption: drop `pod.spot: true` (if you opted in).
- For host issues: retry. The sweep recipe pattern handles this with
  exponential backoff
  ([`recipes/multi-config-sweep.md`](recipes/multi-config-sweep.md)).
- To investigate across many runs:
  `runpod-deploy events-query --filter event=pod_killed_unexpected --since 30d --json`.

---

## Sweep-driver failures

### Driver appears to "exit cleanly" but only 1 of N shards launched

**Symptom**: `bash driver.sh | tee log` exits 0, but `log` shows the
driver died mid-script after launching the first shard. The
`tee`-fronted pipeline returned `tee`'s success code, masking the
bash failure.

**Diagnosis**: `pipefail` was missing from the `set` line. Without
it, the pipeline's exit code is `tee`'s, not `bash`'s.

**Fix**: every sweep-driver header must include `pipefail`:

```sh
set -euo pipefail   # ← all three; -e + -u + -o pipefail
```

See [`recipes/multi-config-sweep.md`](recipes/multi-config-sweep.md)
"Pitfalls" §1.

---

### `wait -n` + `set -e` kills the driver on the first failed shard

**Symptom**: parallel sweep launches the first failure, then the
driver dies before subsequent shards run.

**Diagnosis**: `wait -n` returns the exit code of the finishing
background job. With `set -e`, a non-zero exit from `wait -n` kills
the script immediately.

**Fix**: wrap `wait -n` to suppress its exit code; collect failures
per-shard inside the launcher function instead:

```sh
while [ "$(jobs -rp | wc -l)" -ge "$MAX_PARALLEL" ]; do
  wait -n 2>/dev/null || true
done
```

See [`recipes/multi-config-sweep.md`](recipes/multi-config-sweep.md)
"Pitfalls" §2 for the full corrected pattern.

---

### `ls -td artifacts/runpod/* | head -1` returns the wrong shard's run-dir

**Symptom**: failure classifier reads a healthy sibling's
`events.jsonl` and misclassifies a transient pod-kill as a
non-retryable training failure.

**Diagnosis**: at `MAX_PARALLEL > 1`, multiple `runpod-deploy run`
invocations write concurrent `artifacts/runpod/<ts>/` dirs. `ls -td`
returns whichever sibling started last — racing the failed shard
you wanted to inspect.

**Fix**: use `runpod-deploy run --print-run-dir` (v0.4.0 PR-B) which
emits a single `RUN_DIR=<absolute-path>` line on stdout. Capture
per-attempt stdout via `tee` and grep for the line:

```sh
local stdout_log="/tmp/sweep_attempt_${seed}.log"
if runpod-deploy run --print-run-dir ... 2>&1 | tee "$stdout_log"; then
  return 0
fi
local this_run_dir
this_run_dir=$(grep -oE '^RUN_DIR=.*' "$stdout_log" | head -1 | cut -d= -f2-)
```

See [`recipes/multi-config-sweep.md`](recipes/multi-config-sweep.md)
"Pitfalls" §3.

---

## Forensic recovery

When something failed and you want to know what — these are the tools.

### "Which DCs failed over most often this month?"

```sh
runpod-deploy events-query --filter event=datacenter_failover --since 30d --json
```

### "Show me every pod killed unexpectedly in the last week"

```sh
runpod-deploy events-query --filter event=pod_killed_unexpected --since 7d --json
```

### "What did this specific run do, minute by minute?"

```sh
runpod-deploy events artifacts/runpod/20260515T120000Z
```

### "Aggregate cost + failure rate across a multi-shard sweep"

```sh
runpod-deploy manifest-summary --root artifacts/runpod
```

Outputs per-run summaries plus a `== TOTALS ==` footer with the
manifest count, failure count, summed wall time, summed estimated cost.

### "Compare two runs side-by-side"

```sh
runpod-deploy compare-runs artifacts/runpod/20260515T120000Z \
                           artifacts/runpod/20260515T130000Z
```

Exit 1 if either manifest has `failed: true` — pairs well with CI
gating in driver scripts.

### "List recent runs"

```sh
runpod-deploy ls-runs --limit 20
```

Pulled-back-to-local table of recent run-dir manifests with
pod_id, GPU, datacenter, wall time, failure flag, estimated cost.

---

## Predictions discipline (consumer-side gotcha)

This isn't a runpod-deploy bug — it's a recurring pattern in
consumer-repo design that costs real money when missed.

**Symptom**: post-hoc you want to recompute a metric, ECE/Brier
calibration, or paired-bootstrap delta. The eval pipeline only pulled
summary metrics. You have to re-run inference on a fresh pod (~$5,
~30–80 min).

**Diagnosis**: only summary metrics (PR-AUC, ROC-AUC, recall@FPR at
fixed pinpoints) were persisted. Per-row predictions / `y_score` were
generated, used, and discarded with the pod.

**Fix**: persist per-row predictions alongside summary metrics. The
pattern is documented in
[`recipes/predictions-only-eval.md`](recipes/predictions-only-eval.md).
Pull the parquet via `artifacts:` before pod teardown:

```yaml
artifacts:
  - label: predictions
    remote_path: "{remote_repo}/evals/v5_canonical/predictions/"
    local_path: "{project_root}/evals/v5_canonical/predictions/"
    required: true
```

For trained adapters / LoRA checkpoints, also push to HF Hub before
pod teardown — local pod artifacts are destroyed with the pod.

---

## Still stuck?

- Re-run with `--verbose` to see DEBUG output:
  `runpod-deploy run --verbose --config foo.yaml`
- Use `--offline-dry-run` to walk the lifecycle without provisioning;
  catches config issues for free.
- Inspect the manifest: `runpod-deploy manifest-summary <run-dir>/...json`
  for the full reproducibility record.
- Reach the maintainer with the run-dir tarball
  (`tar czf rundir.tgz artifacts/runpod/<ts>/`).
