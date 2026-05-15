# Recipe: flash_attention_2 graceful fallback

**Pattern:** transformer scorers that prefer `flash_attention_2` for
speed must degrade gracefully when the GPU class doesn't support it —
otherwise the same code that runs on H100 / A100 breaks on RTX A6000
or smaller GPUs in the runpod-deploy GPU-failover pool.

## Snippet

```python
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

## Why this matters with runpod-deploy

`pod.gpu_order` typically lists several GPU classes (failover for
stock-outs). A sweep may land on an H100 for one shard and an A6000
for the next. Without the fallback, the second shard fails at model
load with a `ValueError: flash_attention_2 is not supported`, the
orchestrator pulls a stack trace, and the operator gets a billed
failure for a portable-code bug.

The try/except costs nothing at runtime when flash-attn-2 *is*
supported (the import / construct succeeds on first try) and turns
a hard failure into a logged degraded mode on smaller GPUs.
