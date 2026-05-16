# API reference

Public API for `runpod-deploy`. Six modules:

| Module | Role | Public surface |
|---|---|---|
| [`runpod_deploy.config`](config.md) | YAML config schema + loader | 15 frozen `*Spec` dataclasses, 4 constants, 3 functions (`load_job_spec`, `build_job_context`, `validate_local_paths`) |
| [`runpod_deploy.orchestrator`](orchestrator.md) | The `run_job` entry point that ties everything together | `run_job` |
| [`runpod_deploy.provider`](provider.md) | `runpodctl`-backed pod provisioning + GPU selection | `PodConnection`, `resolve_volume`, `select_gpu_across_datacenters` |
| [`runpod_deploy.pricing`](pricing.md) | GPU price catalog + selection | `GpuPrice`, `fetch_gpu_prices`, `select_price_for_pod` |
| [`runpod_deploy.transport`](transport.md) | SSH + rsync primitives | `RemoteRunner`, `RemoteRunError`, `rsync_argv` |
| [`runpod_deploy.metadata`](metadata.md) | Reproducibility-manifest capture helpers | `capture_local_git`, `capture_payload_lockfile` |

All public symbols listed above are also re-exported from `runpod_deploy.__all__`, so they can be imported directly:

```python notest
from runpod_deploy import load_job_spec, build_job_context, run_job
```

Per [`CLAUDE.md`](https://github.com/brandon-behring/runpod-deploy/blob/main/CLAUDE.md) §5, all dataclasses are **frozen + slotted**; their constructors validate via `__post_init__` and raise stdlib exceptions (`ValueError`, `TypeError`, `RuntimeError`) on bad input.

```{toctree}
:maxdepth: 1
:hidden:

config
orchestrator
provider
pricing
transport
metadata
```
