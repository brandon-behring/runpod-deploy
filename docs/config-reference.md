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
