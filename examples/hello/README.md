# Hello example

The smallest valid runpod-deploy config. Intended for first-time
consumers right after `pip install runpod-deploy` who want to verify
the CLI works **without** registering an SSH key, creating a RunPod
account, or installing `runpodctl`.

## 30-second walkthrough

```bash
pip install runpod-deploy

# Validate the config (parses YAML, checks schema):
runpod-deploy validate --config examples/hello/hello.yaml

# Walk the full lifecycle without any external calls:
runpod-deploy run --config examples/hello/hello.yaml --offline-dry-run
```

Expected output: a log of each phase (`runpodctl pod create --name
hello-<ts> ...`, `ssh-detached`, `rsync-push`, `runpodctl pod stop`)
followed by a clean exit. No money spent; no pod ever provisioned.

## What this exercises

`--offline-dry-run` walks the full
[runpod-deploy lifecycle](../../docs/lifecycle.md) but mocks every
external call:

| Phase | What runs offline | What's mocked |
|---|---|---|
| 1. Validate | YAML parse + schema | — |
| 2. Provision | argv construction | `runpodctl pod create` (logged only) |
| 3. SSH wait | — | skipped (synthetic pod) |
| 4. Setup | argv construction | SSH command invocation |
| 5a. Stage | argv construction | `rsync` |
| 5b. Preflight | argv construction | SSH command invocation |
| 5c. Launch | argv construction | SSH detached invocation |
| 5d. Monitor | — | skipped |
| 6. Pull | — | skipped |
| 7. Stop | argv construction | `runpodctl pod stop` (logged only) |
| 8. Manifest | — | skipped |

The contract: if `hello.yaml` walks cleanly, the runpod-deploy CLI
+ wheel + Python environment are all wired up correctly. A real
deploy would substitute real RunPod credentials, an SSH key, and a
populated `local.project_root` for rsync staging.

## Next steps

| Goal | Where to go |
|---|---|
| First real (cheap) end-to-end deploy | [`examples/smoke/a4000_smoke.yaml`](../smoke/a4000_smoke.yaml) (~$0.05–0.20) |
| Understand each lifecycle phase | [`docs/lifecycle.md`](../../docs/lifecycle.md) |
| Compose with sweep drivers, post-processing, etc. | [`docs/recipes/README.md`](../../docs/recipes/README.md) |
| Failure-mode catalog | [`docs/troubleshooting.md`](../../docs/troubleshooting.md) |
| All config-field documentation | [`docs/config-reference.md`](../../docs/config-reference.md) |
| Realistic canonical sweep config | [`examples/v0_5_canonical/canonical_sweep_pinned.yaml`](../v0_5_canonical/canonical_sweep_pinned.yaml) |
