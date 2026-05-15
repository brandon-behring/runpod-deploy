# v0.5 canonical sweep example

`canonical_sweep_pinned.yaml` is a realistic sweep config exercising
every v0.4 + v0.5 feature in one place. Copy-paste into your own repo
as a starting point for a paper-grade canonical evaluation.

## What each v0.4/v0.5 field demonstrates

| Field | Feature | Doc |
|---|---|---|
| `name: canonical-{backbone}-s{seed}` | v0.4 — rendered through `ctx.run_id` into `runpodctl pod create --name` | [PR-C / #18](../../CHANGELOG.md) |
| `run_id_prefix: canonical-{backbone}` | v0.4 — same parity fix | same |
| `pod.python_version: "3.13.5"` | v0.5 — auto-injects `uv python install + pin` at preflight[0] | [`recipes/reproducibility.md`](../../docs/recipes/reproducibility.md) |
| `staging.excludes_default: true` | v0.4 — hygiene preset (.git, .venv, caches, __pycache__) | [`config-reference.md`](../../docs/config-reference.md) |
| `staging.excludes_extra: [evals/, ...]` | v0.4 — additive consumer-specific exclusions | same |
| `run.script_path: "...-{backbone}-s{seed}.sh"` | v0.3.3 — template rendering at use site | [v0.3.3 CHANGELOG](../../CHANGELOG.md) |
| `--print-run-dir` (CLI) | v0.4 — `RUN_DIR=<path>` line on stdout for parallel-sweep drivers | [PR-B / #15](../../CHANGELOG.md) |
| `--var seed=42` (CLI) | v0.3.1 — template-variable injection | [v0.3.1 CHANGELOG](../../CHANGELOG.md) |

## How to invoke

### Single shard, offline-dry-run (free, no provisioning)

```sh
runpod-deploy run --config examples/v0_5_canonical/canonical_sweep_pinned.yaml \
  --var seed=42 --var backbone=deberta \
  --offline-dry-run
```

### Single shard, live

```sh
runpod-deploy run --config examples/v0_5_canonical/canonical_sweep_pinned.yaml \
  --var seed=42 --var backbone=deberta \
  --print-run-dir \
  --cost-cap-usd 2.0 --max-runtime-minutes 60
```

The `--print-run-dir` flag emits a single `RUN_DIR=<path>` line on
stdout right after the run-dir is resolved — parallel-sweep drivers
grep this line per attempt instead of racing `ls -td`.

### Full sweep (3 seeds × 2 backbones = 6 shards)

See [`docs/recipes/multi-config-sweep.md`](../../docs/recipes/multi-config-sweep.md)
for the bounded-concurrency bash driver that wraps this YAML. The
sweep driver uses this exact config with `--var seed=N --var backbone=X`
per shard.

## After the sweep

```sh
# Per-shard summaries + TOTALS footer:
runpod-deploy manifest-summary --root artifacts/runpod

# Forensic audit:
runpod-deploy events-query --filter event=pod_killed_unexpected --since 30d --json
runpod-deploy events-query --filter event=datacenter_failover --since 30d

# CPU-side metrics + bootstrap CIs:
uv run python -m my_pkg.merge \
  --root evals/canonical_deberta \
  --bootstrap-resamples 10000 \
  --seed 42
```

See [`docs/recipes/predictions-only-eval.md`](../../docs/recipes/predictions-only-eval.md)
for the architectural rationale: GPU pod emits only `predictions_full.parquet`;
all metrics, bootstrap CIs, paired tests run locally on CPU after pull.

## What this YAML is NOT

- It's a **template** — `my_pkg.predict` is a stand-in. Replace with
  your own training/inference module.
- It assumes `staging.excludes_extra` skips `tests/` and `docs/` —
  appropriate for a canonical-eval workflow that doesn't need those
  on the pod. Tune for your use case.
- It uses `storage.mode: ephemeral` — fresh volume per pod. Switch
  to `network_volume` if you need cross-pod data persistence (and
  remember network volumes pin the deploy to a single DC).
