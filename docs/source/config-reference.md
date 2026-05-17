# Config Reference

The current YAML schema is `schema_version: 2`. The loader is strict:
unknown fields are errors at parse time. See
[`MIGRATION.md`](https://github.com/brandon-behring/runpod-deploy/blob/main/MIGRATION.md) for the schema-versioning policy
and v1 → v2 migration history.

## `runpod-deploy run` invocation modes

| Mode | What runs | Use case |
|---|---|---|
| (default) | Full lifecycle: `runpodctl pod create`, SSH wait, rsync push, remote commands, artifact pull, `runpodctl pod stop`. Real money. | Production runs. |
| `--dry-run` | Read-only externals (`runpodctl datacenter list`, GraphQL pricing if `--max-gpu-price`) **+** all side-effecting commands are mocked + logged. | "Will my config find a GPU in stock right now?" |
| `--offline-dry-run` | **No external calls at all**; synthetic GPU/DC selection + mocked side-effecting commands. Implies `--dry-run`. | CI tests, offline config iteration, validation against the lifecycle without a RunPod account. |

For the per-phase breakdown of what runs in each mode, see
[`lifecycle.md`](lifecycle.md).

## Annotated minimal config

A working v2 config with every required section and the most common
optional fields. Every other field defaults to a sane value (see
sections below for full details).

```yaml
schema_version: 2                     # required (current schema)
name: my-job                          # required; pod's --name is the *rendered* form (v0.4.0)
run_id_prefix: my-job                 # optional; defaults to `name`
state_file: ~/.runpod-my-job-current  # optional; tracks active pod_id for `stop`

local:                                # optional block; controls local validation + paths
  project_root: ../..                 # relative to THIS yaml's directory
  required_paths:                     # validate fails if any are missing locally
    - pyproject.toml

pod:                                  # required block
  image: runpod/pytorch:2.4.0-py3.13-cuda12.4.1-devel-ubuntu22.04
  datacenters: [EU-RO-1, US-CA-2]     # ordered failover list
  gpu_order:                          # ordered failover list
    - NVIDIA H100 80GB HBM3
    - NVIDIA A100-SXM4-80GB
  cloud_type: SECURE                  # SECURE | COMMUNITY (default SECURE; required for network volumes)
  # python_version: "3.13.5"          # OPTIONAL (v0.5.0); see "Pod field: python_version"

storage:                              # required block
  mode: ephemeral                     # ephemeral | network_volume
  volume_gb: 20

ssh:                                  # optional block
  key_path: ~/.ssh/id_ed25519

setup:                                # optional list; runs BEFORE staging
  - command: "which rsync || apt-get install -y rsync"
    timeout_sec: 300

staging:                              # optional list; rsync push local → pod
  - label: source
    source: "{project_root}/"
    destination: "/workspace/repo/"
    excludes_default: true            # v0.4.0: opt in to .git/.venv/caches preset
    excludes_extra: ["evals/", "artifacts/"]

preflight:                            # optional list; runs AFTER staging, BEFORE the run script
  - command: "cd /workspace/repo && uv sync --extra dev"
    timeout_sec: 1800
    with_env: true

run:                                  # required block
  script_path: /workspace/run.sh
  log_path: /workspace/run.log
  success_marker: "[my-job] DONE"
  body: |
    set -euo pipefail
    cd /workspace/repo
    uv run python -m my_package.main

artifacts:                            # optional list; pulled after the run
  - label: results
    remote_path: "/workspace/repo/results/"
    local_path: "{project_root}/results/"
    required: true

stop:                                 # optional block (defaults: both true)
  on_success: true
  on_failure: true
```

## Required top-level fields

- `schema_version: 2`
- `name`
- `pod`
- `storage`
- `run`

Common optional fields:

- `run_id_prefix`
- `state_file`
- `local`
- `ssh`
- `budget`
- `remote_env`
- `setup`
- `preflight`
- `staging`
- `artifacts`
- `stop`
- `variables`

## Template variables

Every string field in the config can reference template variables via
Python `str.format` syntax (`{name}`). Built-ins:

| Variable | What it is | Example use |
|---|---|---|
| `{config_dir}` | Directory containing this YAML file (absolute). | `local.project_root: "{config_dir}/../.."` |
| `{project_root}` | Resolved `local.project_root` (absolute). | `staging.source: "{project_root}/"` |
| `{run_dir}` | This run's local artifacts dir (e.g. `<project_root>/artifacts/runpod/20260515T120000Z`). | `artifacts.local_path: "{run_dir}/data"` |
| `{run_id}` | The rendered prefix + timestamp (`<run_id_prefix>-<ts>`). | (used internally by `runpodctl pod create --name`) |
| `{job_name}` | The rendered `name` field. | `run.body` `echo "starting {job_name}"` |
| `{volume_mount}` | `storage.volume_mount` (defaults `/workspace`). | `run.script_path: "{volume_mount}/run.sh"` |

Custom variables are declared under `variables:` (YAML) or
`--var KEY=VALUE` / `--vars-file PATH` (CLI). YAML and CLI variables
can reference both built-ins and earlier-defined variables (the
rendering is two-pass — see [`recipes/multi-config-sweep.md`](recipes/multi-config-sweep.md)
for the sweep pattern).

```yaml
variables:
  hf_dataset: "anthropic/persuasion"
  data_dir: "{project_root}/data"   # references built-in
  run_label: "{job_name}-{hf_dataset}"  # references built-in + earlier var
```

CLI:

```sh
runpod-deploy run --config foo.yaml \
  --var seed=42 \
  --var out_dir="{project_root}/seed42"  # CLI vars can reference built-ins too
```

CLI `--var` overrides YAML `variables:` on key collision.

## Storage Modes

Network volume:

```yaml
storage:
  mode: network_volume
  volume_name: pid-workspace-100gb
  volume_mount: /workspace
```

Ephemeral volume:

```yaml
storage:
  mode: ephemeral
  volume_gb: 200
  volume_mount: /workspace
```

## Commands

`setup` and `preflight` are lists:

```yaml
preflight:
  - command: "cd {remote_repo} && uv sync --extra dev"
    timeout_sec: 1800
    with_env: true
```

`with_env: true` prepends `remote_env.source_files` and `remote_env.exports`.

### Recommended `remote_env.exports` for uv-driven pods on /workspace

If your `preflight:` or `run.body` runs `uv sync` and your `storage.volume_mount`
is `/workspace` (RunPod's distributed FUSE filesystem), pin uv's write-heavy
working directories to the pod's overlay disk and export `UV_LINK_MODE=copy`.
On FUSE, three distinct uv/HF-Trainer code paths can stall on MooseFS
`F_SETLKW` exclusive-lock acquisition (uv git resolution, uv install-phase
atomic writes, and HF Trainer atomic checkpoint save) — see
[troubleshooting.md "uv sync hangs silently"](troubleshooting.md#uv-sync-hangs-silently-with-venv-partially-populated)
+ the two follow-up sections for failure signatures.

```yaml
remote_env:
  source_files:
    - /workspace/secrets/env       # if you stage secrets via the secrets: block
  exports:
    HF_HOME: /workspace/hf_cache              # FUSE OK — HF caches are read-mostly
    HUGGINGFACE_HUB_CACHE: /workspace/hf_cache
    UV_CACHE_DIR: /root/uv_cache              # overlay disk, NOT FUSE — git ops + atomic writes
    UV_PROJECT_ENVIRONMENT: /root/.venv       # overlay disk, NOT FUSE — install atomic writes
    UV_LINK_MODE: copy                         # defense-in-depth for residual /workspace touchpoints
```

`/root` is the container's overlay disk (verify with `df -hT /root` — type
`overlay`, NOT `fuse`). POSIX locks work normally there. The uv cache and
venv are ephemeral anyway (re-populated each fire); putting them on `/root`
sacrifices nothing.

**If your training framework writes checkpoints** (HF Trainer's `save_strategy`,
PyTorch Lightning's `ModelCheckpoint`, etc.) and the default `output_dir` is
under `/workspace/`, the atomic-save protocol can stall on the same FUSE bug.
Pin checkpoint `output_dir` to `/root/checkpoints/` and rsync back to the
volume as a `run.body` trailer for orchestrator artifact pull. See
[troubleshooting.md "HF Trainer checkpoint save hangs"](troubleshooting.md#hf-trainer-checkpoint-save-hangs-on-fuse-backed-output_dir).

For genuinely separate network-stall symptoms (single wheel download stuck
mid-stream rather than a stalled `stat()`/`flock()`), also add
`UV_HTTP_TIMEOUT: "120"` (defense against Fastly/CDN HTTP stalls) and
optionally `UV_CONCURRENT_DOWNLOADS: "4"` (caps concurrency; default 50
amplifies head-of-line blocking on stalled sockets).

## Pod field: `python_version` (optional, default: unset)

```yaml
pod:
  image: runpod/pytorch:2.4.0
  datacenters: [EU-RO-1]
  gpu_order: ["NVIDIA H100 80GB HBM3"]
  python_version: "3.13.5"   # ← pin via uv
```

When set, the orchestrator auto-injects a preflight step that runs
`uv python install <ver> && cd <first-staging-destination> && uv python pin <ver>`.
This installs the requested CPython interpreter on the pod and writes a
`.python-version` file into the staged project directory so subsequent
`uv sync` invocations honor the pin.

**Format**: `3.MINOR` or `3.MINOR.PATCH` (e.g. `"3.13"` or `"3.13.5"`).
Pre-release suffixes are rejected — the field exists for reproducibility,
not for chasing alphas.

**Failure mode**: a non-zero exit from the install or pin aborts the
run before the user's `preflight` or run-body executes. Surfaces the
issue cheaply (~30s of pod time) rather than letting a later `uv sync`
fall back to the base-image interpreter.

**Why preflight, not setup**: the pin must write `.python-version` into
the staged repo dir, which doesn't exist until after `_push_workspace`
runs. Injecting at preflight[0] is the correctness-preserving placement.

See [`docs/recipes/reproducibility.md`](recipes/reproducibility.md) for
the trade-offs.

## Staging (rsync push)

`staging` is a list of local-to-remote rsync transfers:

```yaml
staging:
  - label: source
    source: "{project_root}/"
    destination: "{remote_repo}/"
    excludes_default: true              # opt in to the hygiene preset
    excludes_extra: ["evals/", "artifacts/"]
    delete: true
```

Per-entry fields:

- `label` (required)
- `source` (required) — local path; template variables rendered
- `destination` (required) — remote path; template variables rendered
- `excludes` (optional) — explicit list of rsync `--exclude` patterns
- `excludes_default` (optional, default `false`) — when `true`, prepend
  the hygiene preset (`.git/`, `.venv/`, `**/__pycache__/`, `**/*.pyc`,
  `.pytest_cache/`, `.ruff_cache/`, `.mypy_cache/`). Saves repeating
  these across configs that share repo conventions.
- `excludes_extra` (optional) — additional patterns appended after
  `excludes_default` + `excludes`. Useful for project-specific add-ons
  like `evals/`, `artifacts/`, `data/`.
- `delete` (optional, default `true`)

The effective `--exclude` list passed to rsync is the concatenation:
`DEFAULT_STAGING_EXCLUDES` (if `excludes_default`) + `excludes` +
`excludes_extra`, in that order. Existing configs that set only
`excludes` are unaffected.

## Artifacts

Artifacts are pulled after a successful run, and best-effort after failure:

```yaml
artifacts:
  - label: models
    remote_path: "{remote_repo}/artifacts/models/"
    local_path: "{project_root}/artifacts/models"
    excludes: ["**/_trainer/checkpoint-*"]
    required: true
    delete: true
```
