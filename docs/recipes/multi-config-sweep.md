# Recipe: multi-config sweep

**Pattern:** run a set of related configs (e.g., one per LoRA rank, or
one per dataset slice) sequentially, sharing a project root and a
common pre/post-flow.

## Pattern (bash)

```sh
#!/usr/bin/env bash
set -euo pipefail

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

## Pattern (Makefile)

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
and the paired `--gpu-id` + `--datacenter-id` for ad-hoc deviations
without editing the YAML:

```sh
# Try the same config on a cheaper GPU as a smoke test:
runpod-deploy run \
  --config configs/runpod/headline.yaml \
  --gpu-id 'NVIDIA RTX 4090' \
  --datacenter-id 'EU-RO-1' \
  --cost-cap-usd 2.0
```

## Notes

- runpod-deploy does not run sweeps in parallel — the pod lifecycle is
  serialized per-invocation. For parallel sweeps, run multiple
  `runpod-deploy run` processes from your shell driver.
- Each invocation produces its own `artifacts/runpod/<ts>/` dir,
  so post-processing across the sweep just globs the directory tree.
