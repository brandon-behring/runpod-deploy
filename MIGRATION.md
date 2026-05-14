# Migrating configs from v1 to v2 (runpod-deploy 0.2.0)

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
