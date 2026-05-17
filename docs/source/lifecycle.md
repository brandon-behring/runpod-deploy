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
[`src/runpod_deploy/orchestrator.py`](https://github.com/brandon-behring/runpod-deploy/blob/main/src/runpod_deploy/orchestrator.py)
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

Values are never logged. See [issue #2](https://github.com/brandon-behring/runpod-deploy/issues/2) for the
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

## 7. Lifecycle action (cleanup)

After the run completes (or fails), the orchestrator calls
`cleanup_pod(pod_id, action, dry_run, state_file, volume_in_gb)` with
one of three actions, controlled by the YAML `lifecycle:` block:

```yaml
lifecycle:
  on_success: delete    # default — release volume disk on success
  on_failure: stop      # default — preserve for SSH forensics
```

Action semantics:

| action      | runpodctl call         | compute billing | volume disk billing |
| ----------- | ---------------------- | --------------- | ------------------- |
| `preserve`  | _(none)_               | continues at GPU rate | continues at volume rate |
| `stop`      | `pod stop <id>`        | stops           | **continues at ~$0.10/GB·month indefinitely** |
| `delete`    | `pod delete <id>`      | stops           | stops               |

The defaults `on_success: delete` and `on_failure: stop` encode the
operational discipline that prevents storage leaks while preserving
forensic access:

- **Success path** → `delete` releases the volume disk. The run is
  done, all artifacts have been pulled, the manifest is written.
  There is nothing left worth paying storage for.
- **Failure path** → `stop` keeps the pod paused so the operator can
  `runpodctl pod start <id>` later and SSH in for post-mortem. The
  orchestrator emits a multi-line WARNING with the exact release
  command so the operator never has to remember the cleanup syntax:

  ```
  [lifecycle] pod 'abc123' stopped for forensics.
    Volume disk (50 GB) continues billing at ~$0.17/day (~$5.00/mo) until released.
    When done investigating, release with:
        runpod-deploy cleanup --state-file ~/.runpod-deploy-current --mode delete
    Or audit all stale pods:
        runpod-deploy ls-stale
  ```

If you don't want SSH-forensics for failed runs, set
`lifecycle: {on_failure: delete}` to release disk on every run
regardless of outcome.

---

## 7b. Cost discipline: cleaning up after forensics

The `on_failure: stop` default trades a small ongoing storage cost
(~$0.17/day per 50 GB pod) for the option to SSH in after a failure.
This trade-off is only sustainable if you *actually* clean up the
preserved pods. **Stopped pods continue billing the volume disk
indefinitely** at RunPod's $0.10/GB·month preserved-volume rate.

### Why this section exists

On 2026-05-17, this repo had **76 EXITED pods totaling 3,930 GB** —
nothing actively running, but **$1.10/hr (~$26/day, ~$393/month)** of
idle storage burn. The leak existed because `stop_pod` only paused
pods (never deleted them) and operators assumed "stop" meant
"terminated". After releasing those 76 pods, idle burn dropped 110×
to $0.01/hr. The current schema (`lifecycle.on_success: delete` by
default + the failure-path WARNING + `ls-stale` audit + `cleanup
--all-stopped` bulk-release) is the structural fix that prevents the
same gap reopening.

### The forensics-then-cleanup workflow

After a failed run that preserved a pod:

1. **Audit**: `runpod-deploy ls-stale` lists every EXITED pod on the
   account with its volume size and estimated daily/monthly cost,
   plus a TOTAL footer. Read-only; safe to run anytime.

2. **Investigate**: inspect the pulled manifest in
   `artifacts/runpod/<ts>/runpod_pull_manifest.json` for most root-cause
   analysis (most failure modes are visible in the captured logs and
   telemetry without needing SSH). If you do need SSH:
   `runpodctl pod start <id>`, then `runpodctl pod ssh <id>`.

3. **Release** (single pod):
   ```bash
   runpod-deploy cleanup --state-file <path> --mode delete
   ```
   The state file path is logged by the per-run WARNING. The default
   `--mode` is `delete` — you almost always want to release disk
   after forensics. `--mode stop` re-pauses (rarely useful); `--mode
   preserve` is a no-op.

4. **Release** (bulk, after a sweep of failed runs):
   ```bash
   runpod-deploy cleanup --all-stopped         # interactive y/N prompt
   runpod-deploy cleanup --all-stopped --yes   # non-interactive
   ```
   Equivalent to `runpodctl pod list -a --status EXITED -o json | jq
   -r '.[].id' | xargs -I{} runpodctl pod delete {}` but ships in the
   SDK with failure collection (one bad delete doesn't abort the
   rest).

### Recommended hygiene

- Add `runpod-deploy ls-stale` to a weekly cron / CI job to detect
  drift before it becomes a leak. See
  [`recipes/stale-pod-audit.md`](recipes/stale-pod-audit.md).
- When iterating on a workflow that fails repeatedly during
  development, set `lifecycle: {on_failure: delete}` in that config
  so failed runs don't accumulate. Revert to `on_failure: stop` only
  when you genuinely want SSH access on failure.
- For workflows where the staging payload is the slow part of every
  run (large repos, repeated rsyncs), consider switching
  `storage.mode: network_volume` so the volume persists across pods
  and `rsync` is incremental. See
  [`recipes/payload-reuse-via-network-volume.md`](recipes/payload-reuse-via-network-volume.md).

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
