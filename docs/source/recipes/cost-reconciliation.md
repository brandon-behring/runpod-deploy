# Recipe: cost reconciliation across past runs

**Pattern:** read `wall_time_sec`, `gpu_price_per_hour_usd`,
`gpu_price_source`, and `estimated_cost_usd` from past
`runpod_deploy_pull_manifest.json` files to validate that the
`budget.assumed_hourly_rate_usd` you set in YAML is realistic, and to
catch cost drift across runs.

## Why this is a recipe, not a schema feature

Cost-reconciliation analysis is *consumer-domain*: which manifests to
include, how to aggregate, what counts as "drift," and what to do
about it (bump the assumed rate, split the GPU classes into separate
configs, escalate to a quota review) all depend on your project's
budget discipline and tolerance for variance. Those decisions don't
belong in a deployment-primitives library.

What `runpod-deploy` owns is the *capture* of the cost signal: the v2
manifest preserves both the assumed rate (implicit in `cost_cap_usd`
budgeting) and the actual `costPerHr` parsed from `runpodctl pod get`
(`gpu_price_per_hour_usd` with `gpu_price_source: pod_describe`). The
reconciliation is yours to drive.

If your assumed rate is much lower than the captured `costPerHr`, jobs
hit the timeout before reaching their cost cap; if much higher, you're
over-paying for headroom. Comparing the two gives you data to tune
`budget.assumed_hourly_rate_usd` in your YAML configs.

## One-shot inspection of the latest run

```sh
LATEST=$(ls -dt artifacts/runpod/*/ | head -1)
runpod-deploy manifest-summary "$LATEST/runpod_deploy_pull_manifest.json"
```

Look at the `wall_time_sec`, `price_usd/hr`, `est_cost_usd`, and
`cost_cap_usd` lines. If `est_cost_usd` is much lower than
`cost_cap_usd`, the cap is loose; if it bumps against it, you may have
hit the timeout.

## Sweep across many runs (Python)

```python
import json
from pathlib import Path

manifests = list(Path("artifacts/runpod").glob("*/runpod_deploy_pull_manifest.json"))
for path in sorted(manifests):
    m = json.loads(path.read_text())
    if m.get("schema_version") != "v2":
        continue
    if m.get("gpu_price_source") != "pod_describe":
        continue  # skip runs that fell back to assumed_rate
    print(
        f"{m['run_id']:30s}  "
        f"gpu={m['gpu_id']:30s}  "
        f"wall={m['wall_time_sec']:8.0f}s  "
        f"price=${m['gpu_price_per_hour_usd']:.2f}/hr  "
        f"est_cost=${m['estimated_cost_usd']:.2f}  "
        f"final_state={m['pod_final_state']}"
    )
```

This gives you a per-GPU price table over time. If your `assumed_hourly_rate_usd`
is set at $1.65 but H100 runs consistently report $4.18, bump the
assumed rate (which lengthens the implicit timeout) or split the GPUs
into separate configs each with their own assumed rate.

## Detecting failed/killed pods

`pod_final_state` from `runpodctl pod get`'s `desiredStatus` field
distinguishes:

- `EXITED` — clean shutdown after the run (your code finished or
  hit the success marker)
- `RUNNING` — pod still active when manifest was written (means
  `lifecycle.on_*: preserve` and the pod was preserved)
- Anything else (`TERMINATED`, `FAILED`, `STOPPED`) — surfaced as a
  `pod_killed_unexpected` event in `events.jsonl`. Cross-reference
  RunPod console history to find the cause.

When a run shows `failed: true` and `pod_final_state: TERMINATED`,
RunPod killed the pod mid-run — usually quota or capacity. Re-running
on a different DC (multi-DC failover) avoids the same outcome next time.

## What lives where

| Concern | Owner |
|---|---|
| Capturing `costPerHr` from `runpodctl pod get` and persisting it | `runpod-deploy` (`telemetry._extract_price` → manifest `gpu_price_per_hour_usd`) |
| Capturing wall time and computing `estimated_cost_usd` | `runpod-deploy` (`manifest._estimated_cost_usd`) |
| Distinguishing `pod_describe` vs `assumed_rate` price sources | `runpod-deploy` (`gpu_price_source` manifest field) |
| Aggregating across multiple manifests | Your driver (or `runpod_deploy.forensics.walk_run_dirs` + `load_manifest`) |
| Deciding whether observed drift warrants tuning `assumed_hourly_rate_usd` | Your project's cost discipline |
| Filing a cost-anomaly issue when drift exceeds your tolerance | Your release process |

## Anti-pattern to avoid

Don't hard-code cost-tolerance thresholds into the YAML config or wrap
them in deploy-time `validate` rules. Cost drift is a *post-hoc*
analytical concern — what counts as "too much" depends on the project's
budget discipline, which evolves without code releases.

Don't re-derive `estimated_cost_usd` in your driver from
`wall_time_sec * gpu_price_per_hour_usd`; the manifest already
computes it (with proper handling of the `pod_describe` vs
`assumed_rate` price-source fallback) at `manifest._estimated_cost_usd`.
Re-deriving risks divergence when the formula changes.

## See also

- [`multi-config-sweep.md`](multi-config-sweep.md) — the typical
  source of many manifests; pair `manifest-summary --root` after a
  sweep completes.
- [`embed-deploy-metadata.md`](embed-deploy-metadata.md) — the same
  fields the manifest captures (`local_git_sha`, `payload_lockfile`)
  are exposed via the `capture-env` subcommand if you need them in
  your own evals manifest.
- [`local-postprocess-after-run.md`](local-postprocess-after-run.md) —
  walks `<run_dir>` for aggregation; cost reconciliation is one
  flavor of post-processing.
