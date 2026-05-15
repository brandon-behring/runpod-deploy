# Recipe: multi-config sweep

**Pattern:** run a set of related configs (e.g., one per LoRA rank, one
per dataset slice, or one per `--var seed=N`) sharing a project root
and a common pre/post-flow.

`runpod-deploy` does not orchestrate sweeps itself (single-responsibility
boundary — see [`README.md`](README.md)). Consumers drive the loop in
bash, Make, or Python around `runpod-deploy run`.

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
