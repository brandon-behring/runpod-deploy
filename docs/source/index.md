# runpod-deploy

Config-driven RunPod GPU pod orchestration for reusable Python project
deployments. Define the pod, storage, run script, and artifacts as a
single YAML; runpod-deploy provisions, stages, runs, and pulls results
deterministically.

## Get started

```{toctree}
:maxdepth: 2
:caption: Get started

quickstart
lifecycle
config-reference
```

## Recipes

```{toctree}
:maxdepth: 1
:caption: Recipes

recipes/README
recipes/local-preflight-then-run
recipes/local-postprocess-after-run
recipes/embed-deploy-metadata
recipes/multi-config-sweep
recipes/cost-reconciliation
recipes/predictions-only-eval
recipes/flash-attention-fallback
recipes/reproducibility
recipes/forensics-then-cleanup
recipes/stale-pod-audit
recipes/payload-reuse-via-network-volume
```

## Examples

```{toctree}
:maxdepth: 1
:caption: Examples

examples
```

## API reference

```{toctree}
:maxdepth: 1
:caption: API reference

api/index
api/config
api/orchestrator
api/provider
api/pricing
api/transport
api/metadata
```

## Project

```{toctree}
:maxdepth: 1
:caption: Project

extending
troubleshooting
runpod-gotchas
release
migration-v3
adr/0001-config-first
adr/0002-defer-hooks
adr/0003-git-tags
```

## Indices

- {ref}`genindex`
- {ref}`modindex`
- {ref}`search`
