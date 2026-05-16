# RunPod Gotchas

**Moved.** This file's content has been folded into
[`troubleshooting.md`](troubleshooting.md), which catalogs every known
failure mode by phase of the
[`runpod-deploy run` lifecycle](lifecycle.md).

Specifically:

- Operational constraints (network volume requires secure pods,
  rsync not in stock images, ssh-key sync nuance, ...) →
  [`troubleshooting.md`](troubleshooting.md) "Provisioning failures"
  + "Staging failures".
- torch CUDA wheel pinning →
  [`troubleshooting.md`](troubleshooting.md) "Setup failures" →
  "CUDA initialization: NVIDIA driver too old".
- Per-row predictions discipline →
  [`troubleshooting.md`](troubleshooting.md) "Predictions discipline"
  + [`recipes/predictions-only-eval.md`](recipes/predictions-only-eval.md).

Bookmarks to this file still resolve. The link target above is permanent.
