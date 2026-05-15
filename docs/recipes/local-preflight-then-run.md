# Recipe: local pre-flight, then `runpod-deploy run`

**Pattern:** run consumer-domain checks (leakage audits, dataset
validation, lockfile resolution, CPU-only fixtures) on the local
machine *before* paying for a GPU pod. If pre-flight fails, no pod is
provisioned and no cost is incurred.

## Why this is a recipe, not a schema feature

`runpod-deploy` does not execute consumer code locally. There is no
`local_steps` block in the YAML — `runpod-deploy` only owns the pod
lifecycle. Pre-flight steps live in your project's Makefile, where
they're already typed, tested, and discoverable.

## Pattern (Makefile)

```makefile
.PHONY: audit headline-cloud
audit:
	uv run python -m mypipeline.audit \
		--check-leakage \
		--check-dedup

headline-cloud: audit
	runpod-deploy validate --config configs/runpod/headline.yaml --all
	runpod-deploy run --config configs/runpod/headline.yaml
```

Now `make headline-cloud` runs the audit first (using the local
Threadripper / laptop), only invokes `runpod-deploy run` if the audit
passes, and `runpod-deploy validate --all` does its own pre-flight on
the YAML before any subprocess fires.

## What lives where

| Concern                                                | Owner               |
|--------------------------------------------------------|---------------------|
| Schema validation, GPU/DC availability, payload scan    | `runpod-deploy validate` |
| Leakage audit, dedup audit, fixture freshness checks    | Your Makefile / pipeline |
| Lockfile resolution (`uv lock`, `uv sync`)              | Your Makefile (run once locally) |
| Pod provisioning, staging, run, telemetry, manifest     | `runpod-deploy run` |

## Anti-pattern to avoid

Don't push CPU-only steps onto the pod just because they're "part of
the run." Setup (`apt-get install rsync`, `uv sync`, model warmup) and
dataset prep run faster on your local box and don't need GPU minutes.

## See also

- [`local-postprocess-after-run.md`](local-postprocess-after-run.md) —
  the sibling pattern for post-run CPU steps.
- [`multi-config-sweep.md`](multi-config-sweep.md) — the sweep
  driver's `make audit` invocation is the canonical sweep-level
  preflight call.
- [`embed-deploy-metadata.md`](embed-deploy-metadata.md) — pair
  the local preflight with `capture-env` to snapshot the
  reproducibility tripod fields once per sweep.
