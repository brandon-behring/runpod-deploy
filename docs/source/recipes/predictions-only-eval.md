# Recipe: predictions-only-eval

**Pattern:** the GPU pod emits ONLY the per-row predictions
(`predictions_full.parquet` + any trained adapters); all metrics,
bootstrap CIs, paired tests, and calibration fits run **locally on CPU**
after `runpod-deploy run` pulls the parquet back.

## Why this is a recipe, not a schema feature

The split between "what runs on GPU" and "what runs on CPU" is
*consumer-domain*: which metrics you care about, what bootstrap N is
appropriate for your sample size, whether your calibration fit is
GPU-tractable, and whether you need paired tests between scorer
variants all depend on your evaluation protocol. Baking a metrics
runner into `runpod-deploy` would force one philosophy on every
consumer.

What `runpod-deploy` owns is the *pull*: `artifacts[*]` with
`required: true` ensures the predictions parquet lands locally even on
partial failures, so post-run CPU analysis has a deterministic input.
The CPU-side workflow itself is yours.

Bootstrap N=10K–100K across a multi-slice × multi-scorer matrix is
~minutes of billed GPU time per shard but ~seconds on a beefy local
CPU at higher N. Keeping the GPU pod's job tight (predict + checkpoint
only) shrinks the billed window and decouples the cost of *running the
model* from the cost of *evaluating it*. As a bonus, all metrics
become deterministic re-runs from the parquet without re-spending on
GPU.

Validated end-to-end in `prompt-injection-v5`'s canonical sweep
(`configs/runpod/v5_canonical_combined.yaml`), which is the working
reference.

## Pattern

```yaml
# In the YAML config the pod runs:
run:
  body: |
    cd {remote_repo}
    set -euo pipefail
    uv run python -m piv5.cli.predict \
      --config configs/canonical_{backbone}.yaml \
      --seed {seed} \
      --out evals/v5_canonical_{family}_{backbone}/seed{seed}/predictions_full.parquet
artifacts:
  - label: predictions
    remote_path: "{remote_repo}/evals/v5_canonical_{family}_{backbone}/seed{seed}/predictions_full.parquet"
    local_path: "{project_root}/evals/v5_canonical_{family}_{backbone}/seed{seed}/"
    required: true
```

Then post-run locally (driver-side):

```sh
uv run python -m piv5.cli.merge \
  --root evals/v5_canonical_${family}_${backbone} \
  --bootstrap-resamples 10000 \
  --seed 42
```

## Enforcing the contract

Consumers preventing CPU-on-pod regressions ship a pod-contract lint
test that greps configs for forbidden invocations:

```python notest
# tests/unit/test_pod_contract.py
def test_pod_does_not_run_bootstrap():
    for config in CONFIGS:
        body = yaml.safe_load(config.read_text())["run"]["body"]
        assert "bootstrap" not in body.lower(), (
            f"{config}: bootstrap belongs on the local CPU, not the billed pod"
        )
```

Cheap to maintain; catches accidental regressions during config-template
refactors.

## What lives where

| Concern | Owner |
|---|---|
| Running the model and emitting per-row predictions | Pod (GPU) — your `run.body` invokes your `predict` entry point |
| Pulling `predictions_full.parquet` back to the local run-dir | `runpod-deploy run` (`artifacts[*]` with `required: true`) |
| Bootstrap CIs, paired tests, calibration fits | Your local post-processing (CPU; consumer-domain) |
| Enforcing the "no bootstrap on the pod" contract | Your project's lint / CI (see "Enforcing the contract" above) |
| Deciding which slices / scorers / metrics to compute | Your evaluation protocol |

## Anti-pattern to avoid

**Do not compute bootstrap CIs / paired tests / calibration fits on
the pod.** They're CPU-cheap; making the GPU pod do them shrinks your
billed window for no upside, and (worse) couples re-evaluation cost to
re-provisioning cost. If you find your config doing this during a
template refactor, the lint test above catches it.

**Do not skip the `required: true` flag on the predictions artifact.**
If the pull fails silently (network blip, rsync race), your post-run
metrics target will hit a missing file and you won't know whether the
run succeeded. Marking the predictions parquet `required: true` turns
a missed-pull into a loud failure that re-triggers the run; the few
seconds of extra strictness saves the cost of an unnoticed silent
regression.

## See also

- [`multi-config-sweep.md`](multi-config-sweep.md) — the canonical
  invocation pattern (per-shard pod runs prediction-only; aggregation
  happens locally after all shards complete).
- [`local-postprocess-after-run.md`](local-postprocess-after-run.md) —
  walks the pulled `predictions_full.parquet` for metrics, bootstrap
  CIs, paired tests.
- [`reproducibility.md`](reproducibility.md) — pair with
  `pod.python_version` to lock the interpreter version across the
  sweep; otherwise per-row predictions could shift between shards on
  a 3.13 → 3.14 minor-version bump.
- [`troubleshooting.md`](../troubleshooting.md) "Predictions
  discipline" — the failure mode this pattern prevents (recovering
  per-row scores after pod teardown costs real money).
