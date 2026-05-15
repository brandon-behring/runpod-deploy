# Config Reference

Version 1 is a strict single-job YAML schema. Unknown fields are errors.

Required top-level fields:

- `schema_version: 1`
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

Template variables are rendered with Python `str.format`. Built-ins:

- `{config_dir}`
- `{project_root}`
- `{run_dir}`
- `{run_id}`
- `{job_name}`
- `{volume_mount}`

Project-specific variables can be declared under `variables`.

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
