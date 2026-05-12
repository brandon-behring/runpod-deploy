# runpod-deploy

`runpod-deploy` is a config-driven RunPod orchestration package for reusable
GPU project deployments. It owns the RunPod mechanics; consumer repos own their
job configs and project commands.

## Quickstart

```bash
uv venv
uv pip install -e ".[dev]"

runpod-deploy validate --config examples/smoke/a4000_smoke.yaml
runpod-deploy run --config examples/smoke/a4000_smoke.yaml --offline-dry-run
```

Optional: enable pre-commit hooks (`pip install pre-commit && pre-commit
install`). `make lint` remains the canonical enforcement path; CI runs it.

`--offline-dry-run` prints the provision/stage/launch/pull/stop command shape
without calling `runpodctl`, SSH, or rsync. For a real end-to-end deploy on a
cheap GPU, see [`examples/smoke/README.md`](examples/smoke/README.md) — it walks
through the per-host setup (SSH key registration, rsync version) once.

## Examples

| Config | What it does |
| --- | --- |
| [`smoke/a4000_smoke.yaml`](examples/smoke/a4000_smoke.yaml) | Minimal nvidia-smi check on RTX A4000/A4500/A100 in EU-RO-1 — cheapest end-to-end pipeline test |
| [`prompt-injection-v3/v3_1_ephemeral.yaml`](examples/prompt-injection-v3/v3_1_ephemeral.yaml) | Full prompt-injection-v3 threshold-free study on A100/H100, ephemeral storage |
| [`prompt-injection-sdd/headline_resume.yaml`](examples/prompt-injection-sdd/headline_resume.yaml) | Headline/resume evaluation, network-volume storage |
| [`research-kb/pdf_embed_gpu.yaml`](examples/research-kb/pdf_embed_gpu.yaml) | GPU-accelerated PDF embedding pipeline |
| [`post_transformers/gpu_benchmark.yaml`](examples/post_transformers/gpu_benchmark.yaml) | post-transformers GPU benchmark workload |

## Model

Version 1 supports one job per YAML file:

- RunPod pod settings: image, datacenter, GPU order, storage mode, cost cap.
- Local staging: rsync pushes from the consumer repo to the pod.
- Remote setup and preflight commands.
- Detached remote run script, success marker, and failure markers.
- Artifact pulls and a reproducibility manifest.

The core is intentionally project-neutral. If a project needs special behavior,
put it in its config or shell commands. Python hooks are reserved for a future
schema version after at least two projects need the same extension point.

## Docs

- [Config reference](docs/config-reference.md)
- [RunPod gotchas](docs/runpod-gotchas.md)
- [Extending guide](docs/extending.md)
- [V3 migration guide](docs/migration-v3.md)
- [Coding standards](STYLE.md)
