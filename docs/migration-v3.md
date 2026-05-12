# prompt-injection-v3 Migration

The first consumer migration keeps the existing V3 command names as thin
wrappers around `runpod-deploy`.

Planned V3-owned configs:

- `runpod/reviewer.yaml`
- `runpod/v3_1.yaml`
- `runpod/v3_1_ephemeral.yaml`

Expected compatibility commands:

- `uv run reviewer-runpod --dry-run`
- `uv run v3-1-runpod --dry-run --cost-cap-usd 50`
- `uv run v3-1-runpod-ephemeral --dry-run --cost-cap-usd 50`

Direct equivalent:

```bash
uv run runpod-deploy run --config runpod/v3_1_ephemeral.yaml --offline-dry-run
```
