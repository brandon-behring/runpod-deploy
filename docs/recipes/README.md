# Recipes

Composition patterns for `runpod-deploy`. None of these are schema
features — they're the conventions consumers use to wire `runpod-deploy
run` into a larger pipeline.

## Why recipes instead of schema features

`runpod-deploy` is a **deployment-primitives library**. Its single
responsibility is the pod lifecycle: GPU/DC selection (with failover),
staging, remote execution, telemetry capture, artifact pull, and the
manifest that records what happened.

It does **not** orchestrate consumer-domain steps (audit, plotting,
aggregation). Those stay in your project's Makefile / shell scripts /
Python entry points and call `runpod-deploy run` from inside their own
flow. This keeps `runpod-deploy` decoupled from any one consumer's
domain logic.

## Index

- [`local-preflight-then-run.md`](local-preflight-then-run.md) — Makefile
  pattern: run a local audit (leakage check, fixture re-render, dataset
  validation) then invoke `runpod-deploy run`.
- [`local-postprocess-after-run.md`](local-postprocess-after-run.md) —
  pull artifacts via `runpod-deploy run`, then run plotting / aggregation
  locally over the pulled `artifacts/runpod/<ts>/` directory.
- [`embed-deploy-metadata.md`](embed-deploy-metadata.md) — pipe
  `runpod-deploy capture-env` into your own evals manifest. Replaces
  hand-rolled `git rev-parse HEAD` injection in Makefile targets.
- [`multi-config-sweep.md`](multi-config-sweep.md) — bash for-loop over
  a set of configs that share a `local.project_root`.
- [`cost-reconciliation.md`](cost-reconciliation.md) — read
  `wall_time_sec` and `estimated_cost_usd` from past manifests to
  validate `assumed_hourly_rate_usd` settings and detect drift.
- [`predictions-only-eval.md`](predictions-only-eval.md) — GPU pod
  emits only `predictions_full.parquet` + adapters; metrics /
  bootstrap CIs / paired tests run locally on CPU. Decouples the cost
  of *running* the model from the cost of *evaluating* it.
- [`flash-attention-fallback.md`](flash-attention-fallback.md) —
  transformer scorers degrade gracefully when the GPU class doesn't
  support `flash_attention_2` (portability across the GPU-failover
  pool).
- [`reproducibility.md`](reproducibility.md) — `pod.python_version`
  YAML field + `uv python install/pin` auto-injection to lock the
  CPython interpreter version across sweep runs.
