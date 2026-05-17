# Recipe: pod-Python reproducibility

**Pattern:** pin the pod-side CPython interpreter via
`pod.python_version` so successive pod runs use the exact same
interpreter, closing the third leg of the reproducibility tripod (git
SHA + lockfile hash + interpreter version).

## Why this is a recipe, not a schema feature

`pod.python_version` *is* a schema field — that part is upstream. What
makes the surrounding workflow a recipe is the *integration story*:
how you reconcile this YAML pin with `requires-python` in pyproject,
which patch level vs minor pin you choose for which use case, and how
you couple the pin with manifest provenance for paper-grade
reproducibility claims. Those decisions are consumer-domain and
project-specific.

A YAML that declares `requires-python = ">=3.13"` in pyproject and has
no `.python-version` file can resolve to a different CPython minor
version on successive pod runs (e.g. 3.13 today, 3.14 next month).
Reproducibility claims that hinge on git SHA + HF revision + uv.lock
get a third moving part nobody declared. The fix is below.

## Pattern (YAML)

```yaml
pod:
  image: runpod/pytorch:2.4.0
  datacenters: [EU-RO-1]
  gpu_order: ["NVIDIA H100 80GB HBM3"]
  python_version: "3.13.5"   # exact pin (recommended for canonical sweeps)
```

The orchestrator auto-injects a preflight step:

```sh
uv python install 3.13.5 \
  && cd /workspace/repo \
  && uv python pin 3.13.5
```

`uv python install` is idempotent (uv-managed cache under
`~/.local/share/uv/python/`); subsequent runs of the same pod re-use
the cached interpreter. `uv python pin` writes a `.python-version`
file into the staged project dir so the user's run-body `uv sync`
honors the pin.

## When to use minor vs patch pinning

| Pin | Use case | Trade-off |
|---|---|---|
| `"3.13.5"` (exact patch) | canonical sweeps, paper-publication runs | strongest reproducibility; install cost ~30s first time |
| `"3.13"` (minor only) | dev/smoke loops where patch-level drift is acceptable | uv resolves the latest available 3.13.x; slightly looser pin |

## Why not just rely on `requires-python` in pyproject?

`requires-python = ">=3.13"` is a *constraint*, not a pin — uv picks
the highest interpreter satisfying it. If you want canonical
reproducibility, pair the pyproject constraint with `pod.python_version`
in the runpod-deploy config. The YAML pin is the deploy-domain
declaration of "this is the interpreter we are choosing"; the pyproject
constraint is the package-domain declaration of "this is the floor."

## Coupling with manifest provenance

The pulled run manifest (`runpod_deploy_pull_manifest.json`) records
the local git SHA and the uv.lock hash. Adding `pod.python_version`
to the YAML means the third leg of the reproducibility tripod is also
explicit: declared in the config, pinned via the auto-injected
preflight, surfaced in the manifest via the `name` / `run_id` echo of
the YAML's resolved values.

## Failure mode

If `uv python install` fails (network blip, no such version, uv
missing from the base image), the run aborts at the auto-injected
preflight step — before any user `preflight` commands or run-body
execute. The operator pays ~30s of pod time to surface a fixable
config issue, not a multi-minute mid-run failure with partial
artifacts.

## What lives where

| Concern | Owner |
|---|---|
| Honoring `pod.python_version` and injecting the install/pin preflight | `runpod-deploy run` (`orchestrator._build_python_pin_preflight`) |
| Choosing the exact patch version (`"3.13.5"`) vs minor (`"3.13"`) | Your project (canonical sweeps vs dev loops) |
| Setting `requires-python` floor in `pyproject.toml` | Your project (package-domain constraint) |
| Caching the pulled interpreter (`~/.local/share/uv/python/`) | `uv` (idempotent across pod re-runs) |
| Asserting all shards in a sweep used the same interpreter | Your post-run analysis (read `python_version` echo from each manifest) |

## Anti-pattern to avoid

**Do not rely on `requires-python = ">=3.13"` alone for canonical
reproducibility.** It's a *floor*, not a pin — uv picks the highest
available interpreter satisfying it, which can drift between pod
provisioning runs as `uv python install`'s available-versions list
updates.

**Do not commit a `.python-version` file in the project root that
disagrees with `pod.python_version`.** The auto-injected preflight
writes `.python-version` *into the staged project dir* using the YAML
value, but a pre-existing committed file can confuse reviewers about
which is authoritative. Either commit `.python-version` matching the
YAML, or omit it and let the orchestrator manage it.

## See also

- [`predictions-only-eval.md`](predictions-only-eval.md) — the
  canonical "paper-grade evidence" pattern; pair with this recipe
  for full reproducibility (interpreter pin + per-row predictions +
  git SHA + lockfile hash captured in the manifest).
- [`embed-deploy-metadata.md`](embed-deploy-metadata.md) — the manifest
  already captures `local_git_sha`, `local_git_dirty`, `payload_lockfile`,
  and the pinned `python_version` flows through `ctx.run_id` /
  `provider --name`. `capture-env` exposes the same fields if you
  need them in your own evals manifest.
- [`multi-config-sweep.md`](multi-config-sweep.md) — apply the same
  `python_version` pin across every shard in a sweep; consumers
  reading manifests across runs can assert all shards used the same
  interpreter.
