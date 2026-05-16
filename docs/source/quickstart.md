# Quickstart

5 minutes from `git clone` to your first `runpod-deploy run`.

This walks through the one-time host setup, the anatomy of a YAML
config, and the `--offline-dry-run` mental model. For the full pipeline
walk, see [`lifecycle.md`](lifecycle.md).

---

## 0. Prerequisites

- **Python ≥ 3.13** (declared in `pyproject.toml`'s `requires-python`).
- **`uv`** for environment management:
  `curl -LsSf https://astral.sh/uv/install.sh | sh`.
- **`runpodctl`** (the official CLI you're orchestrating around):
  download from [GitHub releases](https://github.com/runpod/runpodctl/releases)
  and put on `$PATH`. Authenticate with
  `runpodctl config --apiKey <key>`.
- **`rsync`** ≥ 3.x on your local machine (macOS ships a 2.x by
  default; install via Homebrew if needed).
- An SSH key registered with RunPod (paste your public key into the
  RunPod web UI → Settings → SSH).

---

## 1. Install runpod-deploy

```bash
pip install runpod-deploy
```

Or with `uv`:

```bash
uv pip install runpod-deploy
```

Verify:

```bash
runpod-deploy --help
```

You should see the subcommand list including `validate`, `run`,
`gpu-list`, `manifest-summary`, `events-query`, ...

> **For contributors**: see [`CONTRIBUTING.md`](https://github.com/brandon-behring/runpod-deploy/blob/main/CONTRIBUTING.md) for
> the editable-install flow (`git clone` + `uv pip install -e ".[dev]"`),
> pre-commit setup, and the contribution guidelines.

---

## 2. Inspect a working example

The repo ships a minimal smoke config:

```bash
cat examples/smoke/a4000_smoke.yaml
```

It's annotated, but the structure is:

```yaml
schema_version: 2          # required; locks the YAML contract
name: smoke                # used as the pod's --name (template-rendered since v0.4.0)
run_id_prefix: smoke
state_file: ~/.runpod-smoke-current   # local file recording the pod_id for `stop`

local:
  project_root: .          # relative to THIS yaml file's directory
  required_paths:          # validate fails if any are missing locally
    - pyproject.toml

pod:
  image: runpod/pytorch:2.4.0-py3.13-cuda12.4.1-devel-ubuntu22.04
  datacenters: [EU-RO-1]   # ordered failover list
  gpu_order:               # ordered failover list
    - NVIDIA RTX A4000
  cloud_type: SECURE
  # python_version: "3.13.5"   # OPTIONAL (v0.5.0); pins via uv

storage:
  mode: ephemeral          # or network_volume
  volume_gb: 20

ssh:
  key_path: ~/.ssh/id_ed25519

setup:                     # commands that run BEFORE staging
  - command: "which rsync || (apt-get update && apt-get install -y rsync)"
    timeout_sec: 300
  - command: "mkdir -p /workspace/smoke"

staging:
  - label: source
    source: "{project_root}/"        # template variables expand
    destination: "/workspace/smoke/"
    excludes_default: true           # v0.4.0 — drops .git, .venv, caches
    # excludes_extra: [evals/]       # additive on top of defaults

run:
  script_path: /workspace/smoke.sh
  log_path: /workspace/smoke.log
  success_marker: "[smoke] DONE"
  body: |
    set -euo pipefail
    nvidia-smi
    echo "[smoke] DONE"

stop:
  on_success: true
  on_failure: true
```

Every section is documented in [`config-reference.md`](config-reference.md).

---

## 3. Validate the config

```bash
runpod-deploy validate --config examples/smoke/a4000_smoke.yaml --all
```

`--all` enables every check: local-paths exist, GPU availability live
in the datacenter, consumer-pyproject scan, hardcoded-paths scan. The
basic `validate` (without `--all`) only checks schema correctness.

---

## 4. Walk the pipeline without provisioning

For an **absolute-minimum** walkthrough that needs no RunPod account or
SSH key registration, use the bundled `hello` example:

```bash
runpod-deploy run --config examples/hello/hello.yaml --offline-dry-run
```

Or use the (more realistic) smoke config:

```bash
runpod-deploy run --config examples/smoke/a4000_smoke.yaml --offline-dry-run
```

`--offline-dry-run` walks the full lifecycle (validate → "provision" →
SSH wait → setup → stage → preflight → launch → monitor → pull →
stop → manifest) but **never** calls `runpodctl`, SSH, or `rsync`.
Each external command is just logged with its argv.

Expected output (abbreviated):

```
runpodctl pod create --name smoke-<ts> --image runpod/pytorch:... --gpus 1 ...
ssh-detached <pod> 'bash /workspace/smoke.sh' (dry-run)
rsync-push:source {project_root}/ → pod:/workspace/smoke/ (dry-run)
runpodctl pod stop <pod> (dry-run)
```

This is the unit test of "does my YAML make sense end-to-end" without
spending money. Use it constantly during config iteration.

---

## 5. Run for real

```bash
runpod-deploy run --config examples/smoke/a4000_smoke.yaml \
  --cost-cap-usd 1.0 \
  --max-runtime-minutes 15
```

This will:
1. `runpodctl pod create ...` — provision an RTX A4000 in EU-RO-1.
2. Wait for SSH (~30–90s).
3. Run `setup` commands (install rsync if missing, mkdir).
4. `rsync` your repo to the pod.
5. Run `preflight` commands (none in this example).
6. Launch `/workspace/smoke.sh` via detached SSH.
7. Poll the remote log for `[smoke] DONE`.
8. Pull `/workspace/smoke.log` back to `artifacts/runpod/<ts>/`.
9. `runpodctl pod stop`.
10. Write `artifacts/runpod/<ts>/runpod_deploy_pull_manifest.json`.

Total time: ~3 minutes. Cost: ~$0.05 at RTX A4000 rates.

If anything goes wrong, the pod is stopped (per `stop.on_failure: true`)
and the failure flow logs a WARNING before the manifest write. Read
[`troubleshooting.md`](troubleshooting.md) for failure-mode diagnostics.

---

## 6. Inspect what just happened

After the run completes:

```bash
# List recent runs as a table
runpod-deploy ls-runs

# Print a single manifest summary
runpod-deploy manifest-summary artifacts/runpod/<ts>/runpod_deploy_pull_manifest.json

# Or aggregate every manifest under artifacts/runpod/ with TOTALS
runpod-deploy manifest-summary --root artifacts/runpod

# Event-by-event timeline
runpod-deploy events artifacts/runpod/<ts>

# Aggregate forensic queries across all runs
runpod-deploy events-query --filter event=gpu_selected --since 7d
runpod-deploy events-query --filter event=pod_killed_unexpected --since 30d --json
```

The manifest captures everything needed for reproducibility: local git
SHA, `uv.lock` hash, GPU id, datacenter, wall time, estimated cost,
artifact transfer status, and (when `pod.python_version` is set) the
pinned interpreter version via the auto-injected preflight step.

---

## 7. Where to go next

- **Your own config**: copy `examples/smoke/a4000_smoke.yaml` into
  your consumer repo at `configs/runpod/<job>.yaml`. The recommended
  layout has `local.project_root: ../..` so the YAML lives at
  `<your-repo>/configs/runpod/<job>.yaml` and `project_root` resolves
  to the consumer repo's root. See README "Consumer-owned configs".

- **Sweeps**: drive multiple `runpod-deploy run` invocations from a
  bash for-loop with `--var seed=42` to template-substitute per shard.
  See [`recipes/multi-config-sweep.md`](recipes/multi-config-sweep.md).

- **Pipeline patterns**: pre-flight checks, post-process aggregation,
  cost reconciliation, predictions-only-on-GPU, GPU-portability
  fallbacks. See [`recipes/README.md`](recipes/README.md).

- **Library usage** (vs CLI): import `from runpod_deploy import run_job`
  and call directly with `cli_variables={"seed": "42"}` and
  `print_run_dir=True`. See [`extending.md`](extending.md).

- **Failures**: when something breaks, [`troubleshooting.md`](troubleshooting.md)
  catalogs the known modes with diagnostics and fixes.

- **Reference**: every YAML field documented in
  [`config-reference.md`](config-reference.md); every CLI flag via
  `runpod-deploy <subcommand> --help`.
