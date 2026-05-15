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

> Auto-generated from each example's `README.md` H1 + first paragraph.
> Regenerate via `make examples-index` after editing an example's README
> or adding a new example dir. The "By use case" table above stays
> human-maintained.

<!-- begin examples-index -->

- **[`forensics/`](forensics/)** — _Forensic scripts_. Pre-built shell scripts for common post-run queries. Each is short enough to copy-paste-adapt for a consumer repo; they exist here as runnable references rather than as a library to vendor.
- **[`hello/`](hello/)** — _Hello example_. The smallest valid runpod-deploy config. Intended for first-time consumers right after `pip install runpod-deploy` who want to verify the CLI works **without** registering an SSH key, creating a RunPod account, or installing `runpodctl`.
- **[`post_transformers/`](post_transformers/)** — (no README.md; see the contained `*.yaml` for the config.)
- **[`prompt-injection-sdd/`](prompt-injection-sdd/)** — (no README.md; see the contained `*.yaml` for the config.)
- **[`prompt-injection-v3/`](prompt-injection-v3/)** — (no README.md; see the contained `*.yaml` for the config.)
- **[`research-kb/`](research-kb/)** — (no README.md; see the contained `*.yaml` for the config.)
- **[`smoke/`](smoke/)** — _smoke_. Minimal end-to-end deploy check. Provisions an RTX A4000/A4500/A100 (whichever is in stock) in `EU-RO-1`, mounts the existing `pid-workspace-100gb` network volume, rsyncs a one-line payload, runs `nvidia-smi`, pulls the output, and stops...
- **[`v0_5_canonical/`](v0_5_canonical/)** — _v0.5 canonical sweep example_. `canonical_sweep_pinned.yaml` is a realistic sweep config exercising every v0.4 + v0.5 feature in one place. Copy-paste into your own repo as a starting point for a paper-grade canonical evaluation.

<!-- end examples-index -->

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
