# Recipe: flash_attention_2 graceful fallback

**Pattern:** transformer scorers that prefer `flash_attention_2` for
speed must degrade gracefully when the GPU class doesn't support it —
otherwise the same code that runs on H100 / A100 breaks on RTX A6000
or smaller GPUs in the runpod-deploy GPU-failover pool.

## Why this is a recipe, not a schema feature

GPU-class detection and attention-implementation selection are
*consumer-domain* concerns. They depend on the model architecture, the
PyTorch/Transformers version pinned by your project, and what counts as
an acceptable degraded mode for your evaluation. None of that is
deployment metadata.

What `runpod-deploy` owns is the *failover pool*: it picks an available
GPU class from `pod.gpu_order` and provisions it. What attention
implementation your code uses on that GPU is yours to decide. Baking
the try/except into the orchestrator would force one fallback policy
on every consumer; consumers who genuinely need flash-attn-2 (e.g.,
for paper-grade timing comparisons) would have to opt out of the
fallback they didn't ask for.

## Pattern (Python)

```python notest
import torch
from transformers import AutoModel

try:
    encoder = AutoModel.from_pretrained(
        model_id,
        revision=revision,
        attn_implementation="flash_attention_2",
        torch_dtype=torch.bfloat16 if torch.cuda.is_available() else torch.float32,
    )
except (ValueError, ImportError):
    # flash-attention-2 not available on this GPU class; fall back to
    # stock SDPA. Keep dtype + revision the same so determinism survives.
    encoder = AutoModel.from_pretrained(
        model_id,
        revision=revision,
        torch_dtype=torch.bfloat16 if torch.cuda.is_available() else torch.float32,
    )
```

The try/except costs nothing at runtime when flash-attn-2 *is* supported
(the import / construct succeeds on first try) and turns a hard
ValueError into a logged degraded mode on smaller GPUs.

## What lives where

| Concern | Owner |
|---|---|
| Selecting an available GPU class from `pod.gpu_order` | `runpod-deploy` (failover loop in `provider.select_gpu_across_datacenters`) |
| Detecting GPU-class capabilities (FA2 support, SM compute capability) | Your model-loading code |
| Choosing the attention implementation | Your model-loading code |
| Logging which implementation was actually used (per-shard audit) | Your training code (emit a `events-query`-readable event) |
| Aggregating fallback frequency across shards | Your post-run analysis (`events-query` or custom forensics) |

## Anti-pattern to avoid

**Do not let the model-load fail hard when flash-attn-2 isn't
available.** `pod.gpu_order` typically lists several GPU classes
(failover for stock-outs). A sweep may land on an H100 for one shard
and an A6000 for the next. Without the fallback, the second shard
fails at model load with a `ValueError: flash_attention_2 is not
supported`, the orchestrator pulls a stack trace, and the operator
gets a billed failure for a portable-code bug.

**Do not bake the fallback into `runpod-deploy` itself.** The right
choice between flash-attn-2, SDPA, and eager attention depends on
your model + your tolerance for degraded performance. Consumers
running paper-grade timing comparisons may explicitly *want* the
hard-fail so they catch GPU-class drift early; consumers running
production evals want the graceful fallback. Both are legitimate.

## See also

- [`multi-config-sweep.md`](multi-config-sweep.md) — sweeps that
  span GPU classes (the typical case for `pod.gpu_order` with
  multiple entries) hit this exact failure mode without the fallback.
- [`reproducibility.md`](reproducibility.md) — log which attention
  implementation was used per shard for audit purposes; pair with
  `events.emit_event("attn_impl", ...)` from your training code so
  `events-query` can later answer "which shards fell back?".
