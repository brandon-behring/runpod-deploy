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

### Prefix Makefile recipes with `uv run` when the dep is a dev-extra

When the consumer's `pyproject.toml` places `runpod-deploy` under
`[project.optional-dependencies] dev` (the recommended location —
suggested by `runpod-deploy validate --scan-consumer` to avoid
polluting production deps with orchestrator tooling), bare
`runpod-deploy` invocations from a Makefile target break with:

```
make: runpod-deploy: No such file or directory
make: *** [Makefile:NN: headline-cloud] Error 127
```

The fix is one word per recipe — prefix every `runpod-deploy` call
with `uv run` so make resolves the executable through the project's
virtualenv:

```makefile
.PHONY: headline-cloud
headline-cloud: audit
	uv run runpod-deploy validate --config configs/runpod/headline.yaml --all
	uv run runpod-deploy run --config configs/runpod/headline.yaml
```

This applies to **every** `runpod-deploy` subcommand invoked from
Makefile (`run`, `validate`, `logs`, `cleanup`, `ls-stale`,
`gpu-list`, `gpu-prices`, `estimate`, `ls-runs`, `compare-runs`,
`events`, `events-query`, `capture-env`, `manifest-summary`, etc).
The `uv run` prefix is harmless when `runpod-deploy` is in
`[project.dependencies]` (uv finds it the same way), so applying it
universally is safe.

If your shell PATH already has the venv's `bin/` directory active
(e.g., `source .venv/bin/activate`), bare `runpod-deploy` works
interactively but still fails inside `make` because `make` doesn't
inherit shell activations. Using `uv run` in the Makefile sidesteps
this.

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
