# Migration & schema-versioning policy

This doc covers (1) the versioning policy that governs YAML schema
changes, (2) the canonical v1 → v2 schema migration shipped in
v0.2.0, and (3) a summary of every *additive* change shipped between
schema versions (which require no migration but may want opt-in).

For breaking changes that warrant a schema bump, see "When we will
bump SCHEMA_VERSION" at the bottom.

---

## Schema-versioning policy

The YAML schema is versioned independently of the runpod-deploy
package. The current schema is `schema_version: 2` (introduced in
runpod-deploy 0.2.0).

**Strict loading**: `load_job_spec` enforces the declared
`schema_version` matches exactly. A v1 config loaded by v0.2.0+ raises
`ValueError: schema_version must be 2, got 1` with a clear path to the
required edits.

**Additive changes do NOT bump the schema**: adding an optional field
with a sane default preserves all existing YAMLs. Per CLAUDE.md §5
("Anti-overengineering — don't add an abstraction unless a second
concrete use exists"), we resist schema-version inflation: a field is
additive if (a) it has a falsy default, (b) no existing-YAML semantic
changes when unset, (c) all loader paths produce identical behavior
for old configs.

**Behavioral changes do NOT bump the schema** when they're internal
implementation details that don't alter the YAML contract — e.g.,
v0.3.x's `runpodctl` flag feature-detection, v0.5.0's auto-injection
of the `python_version` preflight step.

**Breaking changes DO bump the schema**: removing a field, renaming
a key, changing a field's type, changing observable semantics for an
existing field. See "When we will bump SCHEMA_VERSION" below.

---

## Migrating configs from v1 to v2 (runpod-deploy 0.2.0)

`runpod-deploy` 0.2.0 bumps the YAML schema from v1 to v2. The strict
loader rejects v1 configs at load time with a clear diagnostic
(`schema_version must be 2, got 1` and/or
`unknown pod keys: ['datacenter_id']`). Two mechanical edits per config
fix it.

## Required edits

### 1. `schema_version`

```diff
-schema_version: 1
+schema_version: 2
```

### 2. `pod.datacenter_id` → `pod.datacenters` (failover list)

```diff
 pod:
   image: runpod/pytorch:...
-  datacenter_id: EU-RO-1
+  datacenters: [EU-RO-1]
   gpu_order:
     - NVIDIA A100-SXM4-80GB
```

For a single DC, the list contains one entry. To opt into multi-DC
failover, append more datacenter ids; runpod-deploy iterates them in
order until a configured GPU has stock:

```yaml
pod:
  datacenters: [EUR-NO-2, US-GA-2, US-CA-2]
  gpu_order:
    - NVIDIA H100 80GB HBM3
```

That's it. Every other field is unchanged.

## Optional new fields

All defaults are sane; omit unless you need them.

```yaml
pod:
  spot: false                 # request spot pricing where available
  min_vcpu_count: 16          # lower bound on provisioned vCPU
  min_memory_gb: 64           # lower bound on host RAM (GB)

telemetry:
  enabled: true                       # default: true
  sample_interval_sec: 30             # default: 30 (>= 5)
  capture_nvidia_smi: true            # nvidia-smi snapshots + sampling row
  capture_dmesg: true                 # dmesg tail at run end
  capture_pod_describe: true          # runpodctl pod get snapshots
  capture_remote_env: true            # uname + python --version + pip freeze
  capture_local_git: true             # local git SHA + dirty + branch
  capture_payload_lockfile: true      # uv.lock | requirements.txt sha256
```

## Behavioral changes (no config edit needed)

These happen automatically once the schema is v2:

- The remote `run.log_path` is **always pulled** to `run_dir/run.log`
  when the run started, even on failure.
- Per-artifact pull outcomes are recorded in the manifest
  (`status` ∈ `success` | `failed` | `skipped`, plus `bytes_transferred`
  and `duration_sec`).
- A v2 manifest gains `deploy_metadata` (git SHA + lockfile hash + remote
  env), `gpu_price_per_hour_usd` (parsed from `runpodctl pod get`'s
  `costPerHr` field), `gpu_price_source` (`pod_describe` |
  `assumed_rate`), `wall_time_sec`, `estimated_cost_usd`, and
  `pod_final_state`.
- A run dir gains `nvidia_smi_{start,end}.txt`,
  `pod_describe_{start,end}.json`, `dmesg_tail.txt`, `pip_freeze.txt`,
  `remote_env.json`, `events.jsonl` (orchestrator events: gpu_selected,
  datacenter_failover, artifact_pull_*, pod_killed_unexpected,
  remote_step_*), and `metrics.jsonl` (periodic GPU/CPU/mem/disk samples).
- `runpod-deploy validate` warns when `storage.mode: network_volume`
  combines with `len(pod.datacenters) > 1` — the volume pins the deploy
  to one DC, so the failover list is effectively single-element.

## New CLI surface

- `runpod-deploy run --gpu-id <id> --datacenter-id <dc>` — paired
  override that short-circuits GPU/DC selection for one-off runs. Both
  flags must come together.
- `runpod-deploy capture-env --project-root <path>` — emits a JSON
  object with the same `local_git_*` and `payload_lockfile_*` fields
  the manifest captures, for embedding in your own evals manifest.
- `runpod-deploy manifest-summary <path>` — pretty-prints any v1 or v2
  pull manifest as compact key/value lines.

## Things that did **not** change

- `runpod-deploy` is still a deployment-primitives library. There is
  **no** `local_steps` / `local_post_steps` schema feature. Compose your
  own pre/post steps in your Makefile around `runpod-deploy run` — see
  `docs/recipes/local-preflight-then-run.md`.
- Mid-run failover / auto-retry is **not** added. A RunPod-killed pod is
  detected (`pod_killed_unexpected` event + `pod_final_state` in
  manifest) and the run fails. Consumers decide whether to re-invoke.
- Preventive `--max-gpu-price` filtering is **not** in v0.2.0.
  `runpodctl gpu list` and `runpodctl datacenter list` expose no
  pricing. Cost reconciliation is reactive (post-provision capture from
  `runpodctl pod get`'s `costPerHr` field). A v0.3.0 may add a thin
  GraphQL client (`https://api.runpod.io/graphql`, `gpuTypes` query,
  `securePrice` / `communityPrice` / `secureSpotPrice` /
  `communitySpotPrice`).

---

## Additive changes since schema_version: 2 (no migration required)

All changes below preserve existing YAMLs. Opt in per-field by setting
the new key; omit to keep prior behavior.

### Runtime CLI (v0.3.x)

- v0.3.0 — pricing intelligence (`gpu-prices`, `--max-gpu-price`,
  `gpu-list` price column), forensic CLIs (`ls-runs`, `compare-runs`,
  `events`, `estimate`), `capture-env`, `manifest-summary`.
- v0.3.1 — `runpod-deploy run --var KEY=VALUE` (repeatable) +
  `--vars-file PATH` (JSON). Template variables injected at the
  ctx.variables layer; chained against built-ins and YAML `variables:`.
- v0.3.2 — `runpodctl` flag feature-detection (probes
  `runpodctl pod create --help` once per process, gates
  `--spot`/`--min-vcpu-count`/`--min-memory-in-gb` emission).
- v0.3.3 — template rendering wired into `run.script_path`,
  `run.log_path`, `run.success_marker`, `run.failure_markers`.

### YAML additions (v0.4)

- **`run.script_path` / `log_path` / `success_marker` / `failure_markers`**
  now template-render (v0.3.3 fix).
- **`name` / `run_id_prefix`** now template-render against the
  fully-merged variable dict — a YAML with `name: demo-{seed}` produces
  `demo-42` as the pod's `--name` when invoked with `--var seed=42`
  (v0.4.0).
- **`staging[].excludes_default: bool = false`** — opt in to the
  hygiene preset (`.git/`, `.venv/`, caches).
- **`staging[].excludes_extra: list[str] = []`** — additional patterns
  appended after `excludes_default` + `excludes`.

### CLI additions (v0.4)

- **`runpod-deploy run --print-run-dir`** — emits `RUN_DIR=<path>`
  to stdout right after run-dir resolution. Intended for
  parallel-sweep drivers needing a machine-parseable run-dir handle.
- **`runpod-deploy run_job(..., print_run_dir=bool)`** — library-level
  kwarg mirroring the CLI flag.

### YAML additions (v0.5)

- **`pod.python_version: str | None = None`** — when set to
  `3.MINOR` or `3.MINOR.PATCH` (pre-release suffixes rejected),
  the orchestrator auto-injects a preflight step that runs
  `uv python install <ver> && cd <staging-destination> && uv python pin <ver>`.

### CLI additions (v0.5)

- **`runpod-deploy events-query`** — aggregates `events.jsonl` across
  run dirs under `--root DIR`. Filter syntax: `--filter KEY=VALUE`
  (repeatable, AND-semantics), `--since DURATION` (`30s`/`5m`/`1h`/`7d`),
  `--json` for JSONL output (default: human table).
- **`runpod-deploy manifest-summary --root DIR`** — walks DIR
  recursively for `runpod_deploy_pull_manifest.json` files; prints a
  per-run summary block plus a `== TOTALS ==` footer (manifest count,
  failure count, summed wall_time_sec, summed estimated_cost_usd).

---

## When we will bump SCHEMA_VERSION

A bump is warranted when:

1. **A field's type changes** — e.g., `pod.gpu_order` going from
   `list[str]` to `list[GpuPriority]` mappings. Old YAMLs break;
   strict-loader raises.
2. **A field is removed** — e.g., dropping `state_file` because the
   orchestrator handles state internally.
3. **A field's semantics change in an observable way for unchanged
   YAMLs** — e.g., changing `stop.on_failure` default from `true` to
   `false`; an unchanged YAML now behaves differently.
4. **A required-field structure changes** — e.g., flattening `pod` +
   `storage` into a single block.

A bump is NOT warranted when:

- New optional field added with falsy default.
- Internal validation gets stricter (catches things that were always
  bugs).
- Orchestrator behavior changes for internal-only reasons (feature
  detection, auto-injection that an existing YAML can't reference).
- New CLI subcommand or flag.

If a bump becomes necessary, the migration doc gets a new section
following the v1→v2 template above (`## Migrating configs from vN to
vN+1`), with required edits + optional new fields + behavioral
changes + things that did NOT change.
