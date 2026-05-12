# runpod-deploy

`runpod-deploy` is a config-driven RunPod orchestration package for reusable
GPU project deployments. It owns the RunPod mechanics; consumer repos own their
job configs and project commands.

## Quickstart

```bash
cd /home/brandon_behring/Claude/runpod-deploy
uv venv
uv pip install -e ".[dev]"

runpod-deploy validate --config examples/prompt-injection-v3/v3_1_ephemeral.yaml
runpod-deploy run --config examples/prompt-injection-v3/v3_1_ephemeral.yaml --offline-dry-run
```

`--offline-dry-run` prints the provision/stage/launch/pull/stop command shape
without calling `runpodctl`, SSH, or rsync.

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
