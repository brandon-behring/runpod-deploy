# The runpod-deploy run lifecycle

What actually happens between `runpod-deploy run --config foo.yaml`
and the artifacts landing in `artifacts/runpod/<ts>/`. This doc maps
every YAML section to its phase, the side effects that happen at each
step, and the inputs/outputs the manifest captures.

The flow is **linear** (no DAG, no retry-in-process) and runs once per
`runpod-deploy run` invocation. For parallel sweeps, the consumer
runs multiple invocations from a bash/Make driver
(see [`recipes/multi-config-sweep.md`](recipes/multi-config-sweep.md)).

---

## Phase overview

```
┌─────────────┐   ┌─────────────┐   ┌────────────┐   ┌───────────┐
│ 1. Validate │ → │ 2. Provision│ → │ 3. SSH wait│ → │ 4. Setup  │
└─────────────┘   └─────────────┘   └────────────┘   └───────────┘
                                                            │
                                                            ▼
┌─────────────┐   ┌─────────────┐   ┌────────────┐   ┌───────────┐
│ 8. Manifest │ ← │ 7. Stop pod │ ← │ 6. Pull    │ ← │ 5. Stage  │
└─────────────┘   └─────────────┘   │  artifacts │   │ + preflight│
                                    └────────────┘   │ + launch  │
                                                     │ + monitor │
                                                     └───────────┘
```

Each phase corresponds to a function in
[`src/runpod_deploy/orchestrator.py`](../src/runpod_deploy/orchestrator.py)
and a YAML config section.

---

## 1. Validate

**Entrypoint**: `runpod-deploy validate --config foo.yaml`
(optionally `--all` for the heavy checks).

What runs:
- `load_job_spec(path)` parses the YAML strictly. Unknown root keys
  raise; missing required fields raise. No template rendering at this
  step (raw values are stored).
- `build_job_context(spec, path)` resolves `local.project_root`
  (relative to the config file's parent dir) and computes the run-dir
  path. Raises if `project_root` resolves to `$HOME` (the v0.1.x typo
  guard from issue #5a).
- `validate_local_paths(ctx)` (when `--check-local` or `--all`):
  verifies each `local.required_paths` entry exists locally.
- `preflight.check_gpu_availability(ctx)` (`--check-availability`):
  live-queries `runpodctl datacenter list` to assert at least one
  `pod.gpu_order` entry is in-stock in `pod.datacenters`. Closes the
  failure mode from issue #1.
- `preflight.scan_consumer_pyproject(ctx)` + `.scan_staged_payloads_for_absolute_paths(ctx)`
  (`--scan-consumer`): scans for `runpod-deploy` declared as a runtime
  dep (issue #4) and `/Users/...` / `/home/...` hardcoded paths in
  staged source.

The `validate` command is purely read-only — no pod is created.

**YAML inputs**: every section.

**Outputs**: exit 0 on pass; raises `ValueError` / `FileNotFoundError`
/ `RuntimeError` with a diagnostic message on failure.

---

## 2. Provision

**Entrypoint**: triggered by `runpod-deploy run` (no separate CLI).

What runs:
- `_capture_deploy_metadata(spec, ctx)`: snapshots local git SHA +
  dirty flag + `uv.lock` hash. Written to the manifest later.
- `_resolve_gpu_id_and_dc(spec, offline, on_failover, max_gpu_price_usd)`
  picks `(gpu_id, datacenter_id)` from `pod.gpu_order` × `pod.datacenters`,
  walking failover events through `on_failover` for telemetry capture.
  Honors `--max-gpu-price <float>` via the GraphQL prices fetched from
  `pricing.fetch_gpu_prices`.
- `provider.provision_pod(ctx, volume_id, gpu_id, datacenter_id, dry_run)`:
  builds the `runpodctl pod create` argv via
  `provider._build_pod_create_argv` (gates `--spot` / `--min-vcpu-count` /
  `--min-memory-in-gb` via the v0.3.2 feature-detection probe) and
  shells out. Returns a `PodConnection` with `host`, `port`, `pod_id`.

The pod's `--name` is set to `ctx.run_id` — which is *rendered*
(v0.4.0 PR-C), so a YAML with `name: demo-{seed}` produces
`demo-42-<ts>` when invoked with `--var seed=42`.

**YAML inputs**: `pod`, `storage`, `budget`, top-level `name` /
`run_id_prefix`.

**Outputs**: provisioned pod with a public SSH port; pod_id stored
in `spec.resolved_state_file` for later `runpod-deploy stop` recovery.

---

## 3. SSH wait

`_wait_for_sshd(runner)` polls the pod's SSH port until ready (default
~10 min timeout). The pod's `runpod/pytorch` base image usually boots
in 30–90 seconds. Failures here raise `RuntimeError` and the pod is
stopped (or preserved if `stop.on_failure: false`).

---

## 4. Setup commands

`_run_commands(runner, ctx, spec.setup, label="setup")` runs each
`setup[*].command` over SSH in order. Each command's stdout is logged
at INFO; non-zero exits raise `RemoteRunError` and abort the run.

Typical contents:
- Install missing system packages (`rsync`, `git`)
- Install `uv` if the base image doesn't include it
- `mkdir -p {remote_repo}` for the staging destination

**YAML inputs**: `setup`, `remote_env` (when `with_env: true` on a
command).

**Note**: setup runs *before* staging. That's why the v0.5
`pod.python_version` pin gets auto-injected at preflight (phase 5),
not setup — it needs the staged project dir to write `.python-version`
into. See [`recipes/reproducibility.md`](recipes/reproducibility.md).

---

## 5. Stage + secrets + preflight + launch + monitor

The "hot path" — five sub-phases that happen back-to-back inside the
`try:` block in `run_job`.

### 5a. Stage secrets

`_stage_secrets(runner, ctx)` walks `spec.secrets`. For each entry:
- `source_env`: reads the named local env var, writes `KEY=value`
  lines to a tempfile, rsyncs to `destination` with `--chmod=F<mode>`.
- `source_file`: rsyncs the local file directly.

Values are never logged. See [issue #2](../examples/) for the
ephemeral-storage motivation.

### 5b. Push workspace

`_push_workspace(runner, ctx)` walks `spec.staging`. For each
`RsyncPushSpec`:
- Renders `source` and `destination` through `ctx.render` (template
  variables expand).
- Computes `effective_excludes`: `DEFAULT_STAGING_EXCLUDES` (when
  `excludes_default: true`) + `excludes` + `excludes_extra`, in that
  order. New in v0.4.0 — see
  [`config-reference.md`](config-reference.md#staging-rsync-push).
- Each pattern in the effective list is also rendered through
  `ctx.render`, so `excludes_extra: ["{job_name}-tmp/"]` works.
- Shells out to `rsync` via `RsyncTransfer`.

### 5c. Preflight commands

`_run_commands(runner, ctx, _build_python_pin_preflight(spec) + spec.preflight, label="preflight")`.

When `pod.python_version` is set (v0.5.0 PR-G), the orchestrator
**auto-prepends a single command** to the preflight tuple:
```
uv python install <ver> && cd <first-staging-destination> && uv python pin <ver>
```
This runs *after* staging (so `.python-version` lands in the staged
project dir) and *before* the user's own preflight commands.

User preflight then runs (typical contents: `uv sync --extra dev`,
data-availability checks, environment fingerprinting).

### 5d. Launch remote job

`_launch_remote_job(runner, ctx)`:
- Writes `run.script_path` on the pod with the rendered `run.body`.
- Detaches the script via `nohup ... &`; the SSH command returns
  immediately so the orchestrator can poll the log without holding
  the connection.
- If `--print-run-dir` was set, emits `RUN_DIR=<ctx.run_dir>` on
  stdout *before* the SSH call (v0.4.0 PR-B). Parallel-sweep drivers
  grep this line to know which `artifacts/runpod/<ts>/` dir belongs
  to this shard.

### 5e. Monitor remote log

`_monitor_remote_log(runner, ctx, tel=tel)` polls the pod's log file
(`run.log_path`) for either:
- `run.success_marker` → run-ok, exit poll.
- Any string in `run.failure_markers` → raise.
- Timeout (`budget.timeout_sec`) → raise.

Telemetry samples (`nvidia-smi`, `pip freeze`) run at the configured
interval throughout the poll.

---

## 6. Artifact pull

After the run script exits (success or failure), `_pull_artifacts_and_log`
walks `spec.artifacts`:
- For each entry: rsync from `remote_path` to `local_path` with
  `excludes` honored.
- `required: true` failures raise; `required: false` failures log a
  WARNING and continue.

The pod's run log (`run.log_path`) is also pulled to
`<run_dir>/run.log` regardless of success/failure (as long as the
run script started — i.e., not preflight-failure).

---

## 7. Stop pod

`stop_pod(pod.pod_id, dry_run, state_file)` is called based on
`stop.on_success` / `stop.on_failure`:
- If true → `runpodctl pod stop <pod_id>`. Pod is terminated; bills
  for the runtime so far.
- If false → log a WARNING (`pod preserved`) so the operator can
  SSH in for post-mortem. Common pattern for failure cases during
  development.

---

## 8. Manifest write

`write_pull_manifest(ctx, failed, pod, datacenter_id, deploy_metadata, artifact_results, telemetry_files, wall_time_sec, gpu_price_per_hour_usd, gpu_price_source, pod_final_state)`
serializes everything to
`<run_dir>/runpod_deploy_pull_manifest.json` (schema v2).

Captured fields:
- **Provenance**: `job_name`, `run_id`, `schema_version=v2`,
  `pod_id`, `gpu_id`, `datacenter_id`, `image`, `storage_mode`.
- **Cost/timing**: `wall_time_sec`, `gpu_price_per_hour_usd`,
  `gpu_price_source` (e.g. `pod_describe`), `estimated_cost_usd`,
  `cost_cap_usd`.
- **Pod final state**: `pod_final_state` (e.g. `EXITED`,
  `pod_killed_unexpected`).
- **Deploy metadata**: `local_git_sha`, `local_git_dirty`,
  `payload_lockfile`.
- **Artifacts**: list of `{label, status, duration_sec, bytes_transferred}`.
- **Telemetry files**: list of telemetry-snapshot filenames.

This manifest is the source of truth for forensic queries
(`runpod-deploy ls-runs`, `manifest-summary`, `compare-runs`,
`events-query`).

---

## Where each YAML section maps

| YAML section | Phase | Function |
|---|---|---|
| `schema_version`, `name`, `run_id_prefix`, `state_file` | All | `build_job_context` |
| `local` | 1 | `validate_local_paths`, `build_job_context` |
| `pod` (incl. `python_version`) | 2 | `provision_pod`, `_build_python_pin_preflight` |
| `storage` | 2 | `resolve_volume`, `provision_pod` |
| `ssh` | 3 | `RemoteRunner` construction |
| `budget` | 2 + 5e | cost cap + monitor timeout |
| `remote_env` | 4 + 5c | `_remote_env_prefix` (when `with_env: true`) |
| `setup` | 4 | `_run_commands(label="setup")` |
| `staging` | 5b | `_push_workspace` |
| `secrets` | 5a | `_stage_secrets` |
| `preflight` | 5c | `_run_commands(label="preflight")` |
| `run` | 5d + 5e | `_launch_remote_job`, `_monitor_remote_log` |
| `artifacts` | 6 | `_pull_artifacts_and_log` |
| `stop` | 7 | `stop_pod` |
| `telemetry` | 5d + 5e | `telemetry.start_session`, `tel.start_sampling()` |
| `variables` (+ `--var` / `--vars-file`) | 1 (resolution) | `build_job_context` two-pass render |

---

## Failure handling

The orchestrator's `try`/`except`/`finally` block is the canonical
failure flow:

- **Exception before `run_started = True`** (phases 3–5c): no
  artifact pulls (the run script never executed). Stop pod per
  `stop.on_failure`. Log a WARNING.
- **Exception after `run_started = True`** (phases 5d/5e/6):
  best-effort artifact pull (suppresses second-order exceptions) +
  `tel.capture_end()`. Stop pod per `stop.on_failure`.
- **Manifest always writes** in the `finally` block (suppressed
  exception during the write itself just logs).

For deeper failure-mode debugging see
[`troubleshooting.md`](troubleshooting.md).

---

## `--dry-run` vs `--offline-dry-run`

Both flags walk the lifecycle without provisioning, but they differ
in whether external read-only queries are made:

| Flag | External calls? | Use case |
|---|---|---|
| `--offline-dry-run` | **None** — no `runpodctl`, no SSH, no rsync. GPU/DC selection uses synthetic sentinels. | CI tests, fast config iteration, validation when you're offline or don't have a RunPod account |
| `--dry-run` | **Read-only only** — `runpodctl datacenter list` is queried so live GPU stock info is reflected; `runpod-deploy gpu-prices` is queried if `--max-gpu-price` is set. Pod create / SSH / rsync are mocked. | "Will this config actually find a GPU in stock right now?" without provisioning |

In code: `--offline-dry-run` implies `dry_run=True` in `run_job`,
and additionally passes `offline=True` to
`_resolve_gpu_id_and_dc` and `_resolve_volume_id`. The CLI gates the
external calls via that `offline` flag.
