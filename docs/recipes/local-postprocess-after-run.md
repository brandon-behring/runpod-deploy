# Recipe: pull artifacts, then post-process locally

**Pattern:** `runpod-deploy run` writes pulled artifacts under
`{project_root}/artifacts/runpod/<timestamp>/`. Plotting, aggregation,
and report rendering happen *after* the run on the local machine, where
they're cheap and parallelizable. The pulled `runpod_deploy_pull_manifest.json`
tells you exactly which run dir to point at.

## Why this is a recipe, not a schema feature

`runpod-deploy` does not run plot scripts or k-fold aggregations.
Those are consumer-domain — they belong in your project's Makefile or
Python entry points, where they're typed and testable.

## Pattern (Makefile)

```makefile
.PHONY: headline-cloud headline-plots
headline-cloud:
	runpod-deploy run --config configs/runpod/headline.yaml

# Find the most recent run dir and render plots from it
LATEST_RUN_DIR := $(shell ls -dt artifacts/runpod/*/ | head -1)

headline-plots:
	uv run python scripts/render_plots.py --run-dir $(LATEST_RUN_DIR)
	runpod-deploy manifest-summary $(LATEST_RUN_DIR)/runpod_deploy_pull_manifest.json
```

`make headline-cloud headline-plots` chains them; or run them
separately if you want to inspect artifacts before plotting.

## Inspecting what came back

```sh
runpod-deploy manifest-summary artifacts/runpod/20260514T120000Z/runpod_deploy_pull_manifest.json
```

Prints job name, run id, pod id, GPU, datacenter, wall time, captured
$/hr price, estimated cost, deploy metadata (git SHA + lockfile hash),
per-artifact pull status, and the list of telemetry files. Useful as a
"did this run succeed" gate at the top of post-processing scripts.

## Forensic deep-dive

Each run dir also contains:
- `run.log` — full remote stdout/stderr (always pulled when the run
  started, even on failure)
- `events.jsonl` — orchestrator events (gpu selection, datacenter
  failover, artifact pull start/complete/fail, pod kill detection,
  optional `__RUNPOD_STEP_*__` markers)
- `metrics.jsonl` — periodic GPU/CPU/mem/disk samples (~one row per
  `telemetry.sample_interval_sec`)
- `nvidia_smi_{start,end}.txt`, `pod_describe_{start,end}.json`,
  `dmesg_tail.txt`, `pip_freeze.txt`, `remote_env.json`

Walk these in your own analysis script when you need to reconstruct
*why* a run behaved a certain way.

## See also

- [`local-preflight-then-run.md`](local-preflight-then-run.md) —
  the sibling pattern for pre-run audits; the same Makefile target
  often wires both.
- [`predictions-only-eval.md`](predictions-only-eval.md) — the
  canonical case for pulling per-row outputs and doing all metrics
  CPU-side.
- [`cost-reconciliation.md`](cost-reconciliation.md) — reads
  `runpod_deploy_pull_manifest.json` for cost/wall-time per run;
  pair with the artifact analysis above.
- For aggregate forensics across many runs:
  `runpod-deploy events-query` and `manifest-summary --root` (see
  [`troubleshooting.md`](../troubleshooting.md) "Forensic recovery").
