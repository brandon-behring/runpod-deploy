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
