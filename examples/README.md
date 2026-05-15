# Examples

Working `runpod-deploy` configs and helper scripts you can copy into
your own repo as a starting point.

New consumers: read [`docs/quickstart.md`](../docs/quickstart.md) first
for the 5-minute onboarding walk. Then come back here to pick a
starting config.

## By use case

| Use case | Start with |
|---|---|
| **First-time, no RunPod account needed** | [`hello/hello.yaml`](hello/hello.yaml) — absolute-minimum config; `--offline-dry-run` walks the full lifecycle with no external calls |
| **First-time smoke test** (cheap, fast) | [`smoke/a4000_smoke.yaml`](smoke/a4000_smoke.yaml) — minimal v1-style config, network volume |
| **First-time smoke test with v0.5 features** | [`smoke/a4000_smoke_pinned.yaml`](smoke/a4000_smoke_pinned.yaml) — same workload + `python_version` + `excludes_default` |
| **Paper-grade canonical sweep** | [`v0_5_canonical/canonical_sweep_pinned.yaml`](v0_5_canonical/canonical_sweep_pinned.yaml) + [`v0_5_canonical/README.md`](v0_5_canonical/README.md) — every v0.4/v0.5 feature in one realistic config |
| **GPU benchmark** | [`post_transformers/gpu_benchmark.yaml`](post_transformers/gpu_benchmark.yaml) |
| **GPU embedding pipeline** | [`research-kb/pdf_embed_gpu.yaml`](research-kb/pdf_embed_gpu.yaml) |
| **Eval / prompt-injection workflow** | [`prompt-injection-v3/v3_1_ephemeral.yaml`](prompt-injection-v3/v3_1_ephemeral.yaml), [`prompt-injection-sdd/headline_resume.yaml`](prompt-injection-sdd/headline_resume.yaml) |
| **Post-sweep forensic queries** | [`forensics/`](forensics/) — three shell scripts (cost reconciliation, killed-pod audit, DC failover audit) |

## Per-directory contents

- **`hello/`** — absolute-minimum example for `--offline-dry-run`; targets first-time PyPI-installed consumers who just want to verify the CLI is wired up.
- **`smoke/`** — minimal end-to-end pipelines. RTX A4000 / A4500 / 2000-Ada, EU-RO-1, ~$0.05–0.20.
- **`prompt-injection-v3/`** — full threshold-free study config; A100/H100, ephemeral storage.
- **`prompt-injection-sdd/`** — headline/resume eval; network-volume storage.
- **`research-kb/`** — GPU-accelerated PDF embedding pipeline.
- **`post_transformers/`** — post-transformers GPU benchmark workload.
- **`v0_5_canonical/`** — realistic canonical-sweep config exercising every v0.4 + v0.5 feature (`python_version`, `excludes_default`/`excludes_extra`, rendered `name`/`run_id_prefix`, `--print-run-dir`). See its README for what each field does.
- **`forensics/`** — shell scripts for common post-run queries (`runpod-deploy manifest-summary --root`, `runpod-deploy events-query --filter ...`).

## How to use an example

1. Pick the closest match for your workload.
2. Copy the YAML into your own repo at `configs/runpod/<job>.yaml` (the recommended consumer-owned-config layout — see the repo
   [README](../README.md) "Consumer-owned configs").
3. Edit `local.project_root`, `pod.image`, `pod.gpu_order`, `staging`, `run.body`, and `artifacts` for your workload.
4. `runpod-deploy validate --config configs/runpod/<job>.yaml --all` to confirm it parses + GPU is in stock.
5. `runpod-deploy run --config configs/runpod/<job>.yaml --offline-dry-run` to walk the lifecycle without provisioning.
6. Once happy: `runpod-deploy run --config configs/runpod/<job>.yaml --cost-cap-usd 1.0 --max-runtime-minutes 15` for a live test.

## See also

- [`../docs/quickstart.md`](../docs/quickstart.md) — 5-min onboarding walk.
- [`../docs/lifecycle.md`](../docs/lifecycle.md) — what happens at each phase of `runpod-deploy run`.
- [`../docs/recipes/README.md`](../docs/recipes/README.md) — composition patterns (sweep drivers, cost reconciliation, post-processing, reproducibility, etc.).
- [`../docs/troubleshooting.md`](../docs/troubleshooting.md) — when something breaks.
