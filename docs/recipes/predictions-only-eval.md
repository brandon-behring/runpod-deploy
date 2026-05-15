# Recipe: predictions-only-eval

**Pattern:** the GPU pod emits ONLY the per-row predictions
(`predictions_full.parquet` + any trained adapters); all metrics,
bootstrap CIs, paired tests, and calibration fits run **locally on CPU**
after `runpod-deploy run` pulls the parquet back.

## Why

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

```python
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
