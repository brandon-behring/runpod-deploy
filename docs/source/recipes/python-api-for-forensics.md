# Recipe: multi-manifest forensics via the Python API

**Pattern:** walk a directory of past `artifacts/runpod/<ts>/` results,
load each `runpod_deploy_pull_manifest.json` and `events.jsonl` with
type-checked access, and aggregate or report on whatever cross-run
question you have.

## Why this is a recipe, not a schema feature

Cross-run analysis is *consumer-domain*: which manifests to include,
how to aggregate (sum, mean, median, percentiles), what counts as a
"failure" worth investigating, and what to do with the result (cost
report, sweep dashboard, regression alert) all depend on your
project's analytics needs. None of that is deployment metadata.

What `runpod-deploy` owns is the *structured access*: `walk_run_dirs`
yields run-dir paths in deterministic order, `load_manifest` returns a
typed dict from the manifest JSON (or `None` with a WARNING on
malformed files), and `load_events` parses `events.jsonl` line by line
(skipping malformed lines with WARNING). The aggregation is yours to
drive.

This recipe is the **strongest Python-API use case** in `runpod-deploy`
(see [`python-api-vs-cli.md`](../python-api-vs-cli.md)). The
forensics surface is graceful by design — every helper handles
missing/malformed inputs without crashing — which beats hand-rolling
`json.loads()` + `Path.glob()` in bash for any non-trivial analysis.

## Pattern (Python)

```python notest
from pathlib import Path

from runpod_deploy import load_events, load_manifest, walk_run_dirs

project_root = Path(".")

# Question: what's the median wall-time per GPU class across all runs?
by_gpu: dict[str, list[float]] = {}
for run_dir in walk_run_dirs(project_root):
    manifest = load_manifest(run_dir)
    if manifest is None:
        continue  # load_manifest already logged a WARNING
    gpu_id = manifest.get("gpu_id")
    wall_time = manifest.get("wall_time_sec")
    if gpu_id is None or wall_time is None:
        continue
    by_gpu.setdefault(gpu_id, []).append(float(wall_time))

for gpu_id, times in sorted(by_gpu.items()):
    times.sort()
    median = times[len(times) // 2]
    print(f"{gpu_id:30s}  n={len(times):3d}  median={median:.0f}s")
```

For event-stream analysis (when a manifest answer isn't enough):

```python notest
# Question: which runs hit a datacenter_failover event, and why?
for run_dir in walk_run_dirs(project_root):
    events = load_events(run_dir)
    failovers = [e for e in events if e.get("event") == "datacenter_failover"]
    if failovers:
        manifest = load_manifest(run_dir)
        run_id = manifest.get("run_id") if manifest else run_dir.name
        for ev in failovers:
            print(f"{run_id}: failover {ev['from']!r} → {ev['to']!r}: {ev['reason']}")
```

## What lives where

| Concern | Owner |
|---|---|
| Walking the project's `artifacts/runpod/*` directory tree | `runpod_deploy.forensics.walk_run_dirs` |
| Loading + parsing one manifest JSON (with malformed-file tolerance) | `runpod_deploy.forensics.load_manifest` |
| Parsing one `events.jsonl` line-by-line (skipping malformed lines) | `runpod_deploy.forensics.load_events` |
| Deciding which runs to include (filter by date, GPU class, etc.) | Your driver |
| Aggregation logic (sum, mean, median, percentiles, joins) | Your driver |
| Output format (text table, JSON report, pandas DataFrame) | Your driver |
| Writing the aggregated result somewhere (CSV, dashboard, alert) | Your driver |

## Anti-pattern to avoid

**Do not hand-roll `json.loads(path.read_text())` + `Path.glob()` for
multi-run analysis.** The forensics helpers exist precisely so you
don't have to. Hand-rolling means you'll re-discover the malformed-file
edge cases the helpers already handle (missing files, partial JSON,
empty events.jsonl), and your code will silently break or noisily
crash on the first weird manifest it hits.

**Do not assume every run has every field.** Manifests evolve between
schema versions; `manifest.get("gpu_price_per_hour_usd")` may be
`None` for runs predating v0.5.0 even on a successful run. Guard with
`.get()` + `is None` checks, not `manifest["field"]`.

**Do not use the Python API for live monitoring.** `walk_run_dirs`
gives you a snapshot at call time; for live sweep observability use
`runpod-deploy logs` (live-tail the pod log) or
`runpod-deploy events-query` (live event-stream filtering).

## See also

- [`../python-api-vs-cli.md`](../python-api-vs-cli.md) — the full
  decision criterion for choosing Python over CLI.
- [`../extending.md`](../extending.md) — §2 lists the full Python API
  surface; this recipe is one of four documented use cases.
- [`cost-reconciliation.md`](cost-reconciliation.md) — the CLI-driven
  cost-analysis pattern; consumers preferring CLI over Python API
  should follow that recipe instead.
- [`local-postprocess-after-run.md`](local-postprocess-after-run.md) —
  single-run post-processing (the CLI equivalent of this recipe for
  one run; this recipe scales to N runs).
