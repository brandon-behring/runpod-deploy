# Recipe: pod-Python reproducibility

**Problem**: a YAML that declares `requires-python = ">=3.13"` in
pyproject and has no `.python-version` file can resolve to a different
CPython minor version on successive pod runs (e.g. 3.13 today, 3.14
next month). Reproducibility claims that hinge on git SHA + HF revision
+ uv.lock get a third moving part nobody declared.

## Fix: pin via `pod.python_version`

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
