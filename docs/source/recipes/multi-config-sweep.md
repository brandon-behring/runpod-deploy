# Recipe: multi-config sweep

**Pattern:** run a set of related configs (e.g., one per LoRA rank, one
per dataset slice, or one per `--var seed=N`) sharing a project root
and a common pre/post-flow.

## Why this is a recipe, not a schema feature

Sweep orchestration is *consumer-domain*: how many shards to run in
parallel, what counts as a transient failure worth retrying, how to
aggregate results across shards, what cost cap applies to the fleet as
a whole — all depend on your project's release cadence and budget
tolerance. None of that is deployment metadata, and any one upstream
choice would be wrong for some consumer.

What `runpod-deploy` owns is the *single-job primitive*: each
`runpod-deploy run` invocation provisions one pod, runs one config,
pulls one set of artifacts, and writes one manifest. Composing those
into a sweep is the consumer's responsibility — typically a bash loop,
a Makefile target, or a Python driver. This recipe documents the
canonical bash patterns, including the bash-semaphore pitfalls that
bite first-time implementers.

## Pattern (sequential bash)

```sh
#!/usr/bin/env bash
set -euo pipefail   # ← pipefail is mandatory; see "Pitfalls" below

CONFIGS=(
  configs/runpod/sweep/r4.yaml
  configs/runpod/sweep/r8.yaml
  configs/runpod/sweep/r16.yaml
)

# One-time pre-flight (audit shared across all configs)
make audit

# One-time deploy metadata snapshot
runpod-deploy capture-env --project-root . > artifacts/sweep_env.json

for config in "${CONFIGS[@]}"; do
  echo "==> $config"
  runpod-deploy validate --config "$config" --all
  runpod-deploy run --config "$config" \
    --cost-cap-usd 5.0 \
    --max-runtime-minutes 60
done

# Post-process all of them at once
uv run python scripts/aggregate_sweep.py --pattern 'artifacts/runpod/*/'
```

## Pattern (parallel bash, bounded concurrency)

For N independent shards (e.g., one `runpod-deploy run` per `--var seed=N`),
use a `wait -n` semaphore. Two non-obvious bash interactions bite this
pattern; both are addressed below.

```sh
#!/usr/bin/env bash
set -euo pipefail   # pipefail is required for `tee` (see "Pitfalls")

MAX_PARALLEL=${MAX_PARALLEL:-2}
SEEDS=(42 43 44 45 46 47)
declare -a FAILED_SEEDS=()

launch_shard() {
  local seed=$1
  # Capture this attempt's stdout to its own log so the failure
  # classifier can read THIS shard's run dir, not a sibling's.
  local stdout_log="/tmp/sweep_attempt_${seed}.log"

  if runpod-deploy run \
       --config configs/runpod/template.yaml \
       --var "seed=${seed}" \
       --print-run-dir \
       --cost-cap-usd 5.0 \
       --max-runtime-minutes 60 \
       2>&1 | tee "$stdout_log"; then
    return 0
  fi

  # Grep the run-dir from `--print-run-dir` output, NOT from `ls -td`
  # (which races against sibling shards in flight; see "Pitfalls").
  local run_dir
  run_dir=$(grep -oE '^RUN_DIR=.*' "$stdout_log" | head -1 | cut -d= -f2-)
  if [ -n "$run_dir" ] && [ -f "$run_dir/events.jsonl" ]; then
    if grep -q '"event": "pod_killed_unexpected"' "$run_dir/events.jsonl"; then
      echo "[shard $seed] transient pod kill, eligible for retry"
      # caller's retry policy handles re-launch
    else
      echo "[shard $seed] non-transient failure; not retrying"
    fi
  fi
  return 1
}

for seed in "${SEEDS[@]}"; do
  # Bounded concurrency: block until a slot frees up.
  # `wait -n` returns the exit code of the finishing job. With `set -e`,
  # a non-zero exit would kill the whole driver — `|| true` suppresses
  # that. Failures are collected per-shard inside `launch_shard` instead.
  while [ "$(jobs -rp | wc -l)" -ge "$MAX_PARALLEL" ]; do
    wait -n 2>/dev/null || true
  done

  launch_shard "$seed" &
done

# Drain remaining jobs. Same `|| true` pattern.
while [ "$(jobs -rp | wc -l)" -gt 0 ]; do
  wait -n 2>/dev/null || true
done

if [ ${#FAILED_SEEDS[@]} -gt 0 ]; then
  echo "Failed seeds: ${FAILED_SEEDS[*]}"
  exit 1
fi
```

## Pattern (Makefile, sequential)

```makefile
SWEEP_CONFIGS := $(wildcard configs/runpod/sweep/*.yaml)

sweep: audit
	@for config in $(SWEEP_CONFIGS); do \
		echo "==> $$config"; \
		runpod-deploy validate --config $$config --all || exit 1; \
		runpod-deploy run --config $$config || exit 1; \
	done
	uv run python scripts/aggregate_sweep.py --pattern 'artifacts/runpod/*/'
```

## CLI overrides for one-off variations

`runpod-deploy run` accepts `--cost-cap-usd`, `--max-runtime-minutes`,
the paired `--gpu-id` + `--datacenter-id`, and `--var KEY=VALUE`
(repeatable) for ad-hoc deviations without editing the YAML:

```sh
# Try the same config on a cheaper GPU as a smoke test:
runpod-deploy run \
  --config configs/runpod/headline.yaml \
  --gpu-id 'NVIDIA RTX 4090' \
  --datacenter-id 'EU-RO-1' \
  --cost-cap-usd 2.0

# Same template, different seed:
runpod-deploy run \
  --config configs/runpod/template.yaml \
  --var seed=42
```

## Pitfalls

The parallel bash pattern above is the *correct* form. Three subtle
interactions explain why the obvious naïve version breaks; if you write
your own driver from scratch, watch for these:

### 1. `set -o pipefail` is mandatory when piping driver output through `tee`

Without `pipefail`, `bash driver.sh | tee log` returns `tee`'s success
exit code (0) even when bash dies mid-script. The pipeline looks
successful and any wrapper (Makefile, CI runner) thinks the sweep
completed. Always include `pipefail` in the driver's `set` line.

### 2. `set -e` + `wait -n` kills the driver on the first failed shard

```sh
# BROKEN — set -e kills the driver when the finishing shard returns non-zero
while [ "$(jobs -rp | wc -l)" -ge "$MAX_PARALLEL" ]; do
  wait -n
done
```

`wait -n` returns the exit code of the finishing background job. With
`set -e` enabled, a non-zero exit from `wait -n` kills the driver
immediately — meaning only 1 of N shards launches before the script
dies silently. Suppress the exit with `2>/dev/null || true` and collect
failures per-shard inside the launcher function instead:

```sh
# FIXED
while [ "$(jobs -rp | wc -l)" -ge "$MAX_PARALLEL" ]; do
  wait -n 2>/dev/null || true
done
```

### 3. `ls -td artifacts/runpod/*` races against sibling shards

`ls -td artifacts/runpod/* | head -1` returns the *newest* run dir at
the moment of inspection. With `MAX_PARALLEL > 1`, several runs are
in-flight concurrently and the newest is whichever sibling started
last — not the failed shard you wanted to inspect. Result: the failure
classifier reads a healthy sibling's `events.jsonl` and misclassifies
the failure mode.

Use `runpod-deploy run --print-run-dir` to emit a machine-parseable
`RUN_DIR=<path>` line on stdout right after run-dir creation; capture
it per-attempt via `tee` to a per-shard log and grep that log (not the
filesystem) for the run dir. This pattern is used in the parallel
example above.

## Notes

- runpod-deploy does not run sweeps in parallel — the pod lifecycle is
  serialized per-invocation. The parallel pattern above is the
  consumer's bash driver, not a runpod-deploy feature.
- Each invocation produces its own `artifacts/runpod/<ts>/` dir,
  so post-processing across the sweep just globs the directory tree.
- For multi-shard cost reconciliation, see
  [`cost-reconciliation.md`](cost-reconciliation.md).

## What lives where

| Concern | Owner |
|---|---|
| Provisioning + running ONE shard (one config, one pod) | `runpod-deploy run` |
| Validating each shard's YAML before billing time | `runpod-deploy validate --all` |
| Iterating over N shards (sequential or parallel) | Your sweep driver (bash loop, Makefile target, Python script) |
| Bounded-concurrency semaphore semantics (`wait -n`, `set -e` interaction) | Your sweep driver (see Pitfalls below) |
| Per-shard retry on transient failures | Your sweep driver (decide what counts as transient) |
| Aggregate cost-cap / wall-time enforcement across shards | Your sweep driver (sum manifest fields; abort if running total exceeds budget) |
| Per-shard `RUN_DIR=...` discovery (avoiding `ls -td` races) | `runpod-deploy run --print-run-dir` |
| Post-sweep aggregation (metrics across all `artifacts/runpod/<ts>/`) | Your post-processing code (consumer-domain) |

## Anti-pattern to avoid

**Do not run more shards in parallel than your local Threadripper can
sustain stable SSH connections to.** Each shard holds an SSH session to
its pod for the duration of the run; the orchestrator's tail loop
polls every `budget.poll_interval_sec`. Saturating local CPU or
filesystem (rsync on large stage trees) causes SSH timeouts that look
like pod failures.

**Do not skip `set -euo pipefail` in the parallel bash pattern.** The
`pipefail` flag is mandatory for `tee` to surface non-zero exit; `-e`
+ `wait -n` interact in a non-obvious way that the Pitfalls section
below explains in detail.

**Do not push aggregate-cost-cap logic into `runpod-deploy`.** It's a
sweep-domain concern; if you need it, sum `estimated_cost_usd` across
manifests in your driver between shard launches and abort before
launching the next. The per-shard `--cost-cap-usd` flag is the only
budget primitive runpod-deploy owns.

## See also

- [`cost-reconciliation.md`](cost-reconciliation.md) — `runpod-deploy
  manifest-summary --root artifacts/runpod` after the sweep prints
  per-run blocks + a `== TOTALS ==` footer (manifest count, failures,
  summed wall_time_sec, summed estimated_cost_usd).
- [`predictions-only-eval.md`](predictions-only-eval.md) — the
  canonical sweep emits ONLY per-row predictions on GPU; metrics +
  bootstrap CIs run locally on CPU after all shards complete.
- [`reproducibility.md`](reproducibility.md) — pair the sweep with
  `pod.python_version: "3.13.5"` so every shard uses the same
  interpreter.
- [`embed-deploy-metadata.md`](embed-deploy-metadata.md) — call
  `runpod-deploy capture-env` once before the sweep loop to snapshot
  the git SHA + lockfile hash for the whole sweep.
- For aggregate forensics:
  `runpod-deploy events-query --filter event=pod_killed_unexpected --since 7d`
  (see [`troubleshooting.md`](../troubleshooting.md) "Forensic recovery").
