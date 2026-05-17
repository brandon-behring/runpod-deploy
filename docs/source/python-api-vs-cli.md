# Python API vs. CLI: when to use which

`runpod-deploy` ships two interfaces over the same orchestration logic:

- **CLI**: `runpod-deploy run --config <yaml>` — the primary,
  documented happy path. Both known consumers today use this
  exclusively.
- **Python API**: `from runpod_deploy import run_job, load_job_spec,
  walk_run_dirs, ...` — a curated re-export surface for embedded use.

This page tells you when to choose which.

## Default: use the CLI

For most workflows, the CLI wins:

- **Subprocess overhead is negligible** against GPU pod runtime. One
  `runpod-deploy run` invocation costs ~50ms of process spawn vs.
  minutes-to-hours of billed GPU time. The Python API isn't faster in
  any meaningful sense.
- **The CLI is the documented happy path.** [`quickstart.md`](quickstart.md),
  [`config-reference.md`](config-reference.md), and every recipe in
  [`recipes/`](recipes/README.md) lead with CLI patterns. Following
  the docs by example is the lowest-friction onboarding.
- **Both current consumers use the CLI exclusively.** That's where the
  battle-tested patterns live. Hand-rolling a Python orchestrator means
  re-discovering edge cases the CLI has already absorbed.
- **CLI output is human-debuggable.** `runpod-deploy run` writes
  structured logs to stdout/stderr; you can `tail -f` them or wire
  them into a Makefile target. Python API failures need a debugger or
  `traceback.print_exc()`.

If your use case isn't in the four below, default to the CLI.

## Use the Python API when…

### 1. You're analyzing past runs across many manifests

**Strongest use case.** When you have a directory of
`artifacts/runpod/<ts>/` results and need to walk them all to compute
something (aggregate cost per GPU class, failure rates per datacenter,
wall-time distributions), use the forensics functions:

```python notest
from runpod_deploy import walk_run_dirs, load_manifest, load_events

project_root = Path(".")
for run_dir in walk_run_dirs(project_root):
    manifest = load_manifest(run_dir)
    if manifest is None:
        continue  # malformed or missing manifest; load_manifest already WARN'd
    if manifest.get("failed"):
        events = load_events(run_dir)
        print(f"{manifest['run_id']}: failed; {len(events)} events captured")
```

This beats hand-rolling `json.loads()` + path-walking in bash because
the helpers handle the "malformed manifest" and "missing events.jsonl"
cases gracefully (WARN + skip rather than crash).

See [`recipes/python-api-for-forensics.md`](recipes/python-api-for-forensics.md)
for the full pattern.

### 2. You're building dynamic configs beyond what `--var KEY=VALUE` expresses

CLI `--var` and `--vars-file` cover most parametric sweeps. But some
workflows need *computed* config fields — a Bayesian hyperparameter
optimizer that varies `gpu_order` based on prior results, or a CI
gate that loads a YAML and asserts on the parsed structure. For those,
build the spec in Python:

```python notest
from runpod_deploy import load_job_spec, run_job, replace

spec = load_job_spec("configs/runpod/template.yaml")

# Computed config: vary gpu_order based on a Bayesian optimizer's
# current belief about which GPU class is most cost-effective.
recommended_gpu_class = bayesian_optimizer.suggest()
spec = replace(spec, pod=replace(spec.pod, gpu_order=(recommended_gpu_class,)))

run_job(spec, config_path="configs/runpod/template.yaml")
```

The `*Spec` dataclasses are frozen — use `dataclasses.replace` (or
`runpod_deploy.replace` if re-exported) for mutation.

### 3. You're estimating cost before any pod is provisioned

Dashboards, CI gates, or budget tools that want to predict spend
without subprocess overhead can call the GraphQL pricing layer
directly:

```python notest
from runpod_deploy import fetch_gpu_prices, select_price_for_pod

prices = fetch_gpu_prices()  # cached for 1h
h100_secure = select_price_for_pod(
    prices, gpu_id="NVIDIA H100 80GB HBM3", cloud_type="SECURE", spot=False
)
print(f"H100 SECURE on-demand: ${h100_secure:.2f}/hr")
```

The CLI's `gpu-prices` subcommand provides the same data; use it when
you need a human-readable table. Use the Python API when you're
feeding the prices into further computation.

### 4. You're embedding RunPod orchestration in a larger Python platform

If you're building a web UI ("Deploy to RunPod" button), a multi-cloud
orchestrator that routes jobs to one of several backends, or a Jupyter
notebook driving experiments interactively, `run_job()` is the right
seam:

```python notest
from runpod_deploy import load_job_spec, run_job

def deploy_user_job(yaml_path: Path) -> None:
    """One backend of a multi-cloud orchestrator's runpod adapter."""
    spec = load_job_spec(yaml_path)
    run_job(spec, config_path=yaml_path)  # raises on failure
```

This is the in-process equivalent of `subprocess.run(["runpod-deploy",
"run", "--config", str(yaml_path)])`, with the advantages that (a)
exceptions propagate as Python exceptions (catchable), (b) you can
intercept telemetry events programmatically by patching the orchestrator,
and (c) you avoid the subprocess fork.

## Do NOT use the Python API for…

### *In-process parallel sweeps*

The documented bash pattern in
[`recipes/multi-config-sweep.md`](recipes/multi-config-sweep.md)
with `wait -n` semaphore is simpler than a Python equivalent and
wins on observability (each shard's stdout/stderr is naturally
separated). Subprocess overhead is negligible vs. GPU runtime; you
gain nothing from in-process parallelism.

### *Direct construction of `PodConnection`, `RemoteRunner`, or `select_gpu_across_datacenters`*

These are low-level orchestration plumbing surfaces. The orchestrator
wraps them in `run_job()`. Consumers almost never need to call them
directly; if you find yourself reaching for them, you're probably
re-implementing functionality `run_job()` already provides.

If you have a genuine use case for the low-level surfaces, file an
issue describing the workflow — there may be a higher-level seam
worth adding instead.

## See also

- [`extending.md`](extending.md) — the three-tier extension story
  (consumers / library users / contributors); §2 covers the same
  Python API surface in reference form.
- [`recipes/python-api-for-forensics.md`](recipes/python-api-for-forensics.md) —
  worked example of use case #1 (multi-manifest forensics).
- [`recipes/multi-config-sweep.md`](recipes/multi-config-sweep.md) —
  the recommended CLI-and-bash pattern for parallel sweeps (why
  the Python API is NOT recommended here).
