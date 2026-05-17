# Recipe: stock-out diagnostic

**Pattern:** probe `runpod-deploy gpu-list` for the configured datacenters
*before* invoking `runpod-deploy run`, then choose one of four documented
actions when the configured `gpu_order` × `datacenters` matrix is empty
in your target `cloud_type`.

## Why this is a recipe, not a schema feature

Detecting a stock-out is a deploy-domain concern, and `runpod-deploy`
already owns it: `runpod-deploy gpu-list --datacenter <id>` returns
per-GPU availability and price for one datacenter, and
`runpod-deploy validate --check-availability` walks the configured
`gpu_order` across `datacenters` and raises if nothing is stocked.

What is *not* a deploy-domain concern is the **decision** you make once
you've detected the stock-out. Should you wait? Widen the `gpu_order`?
Switch `cloud_type`? Skip this run and ship a follow-up? Those are
consumer-domain calls — they depend on your release cadence, budget,
and how time-sensitive the run is. So the decision tree lives here, as
a recipe, not as a CLI subcommand that pretends to know your priorities.

## Pattern (bash)

Run this as a pre-launch step in your sweep driver. It exits non-zero
when the configured matrix is empty, so the caller can short-circuit
instead of paying the multi-minute retry-with-backoff penalty against
a genuinely empty cluster.

```sh
#!/usr/bin/env bash
set -euo pipefail

CONFIG=${1:-configs/runpod/headline.yaml}

# Cheap path: let runpod-deploy's existing preflight raise on stock-out.
# This walks gpu_order × datacenters and raises if no GPU is stocked.
if runpod-deploy validate --config "$CONFIG" --check-availability; then
  exec runpod-deploy run --config "$CONFIG"
fi

# Diagnostic path: validate said no stock. Print one gpu-list per
# datacenter so the operator can see exactly what IS stocked right now,
# then surface the four-action menu.
echo
echo "==> STOCK-OUT: no GPU in your gpu_order is currently stocked"
echo "    across the configured datacenters in your cloud_type."
echo
echo "    Currently-stocked GPUs per datacenter:"
for dc in $(python -c "import sys, yaml; print(' '.join(yaml.safe_load(open(sys.argv[1]))['pod']['datacenters']))" "$CONFIG"); do
  echo "    --- $dc ---"
  runpod-deploy gpu-list --datacenter "$dc" --no-prices || true
done

cat <<'ACTIONS'

    Recommended actions:
      (a) Wait 15-30 min for inventory to recover, then re-run this script
      (b) Widen `pod.gpu_order` in the config to include GPUs from the
          list above
      (c) Switch to COMMUNITY cloud: add `pod.cloud_type: COMMUNITY` to
          the config (note: SECURE-only constraints like network volumes
          will not work on COMMUNITY)
      (d) Defer this run: skip the version, ship the next one without
          this slice, file a tracking issue noting the stock-out window
ACTIONS

exit 3
```

The `exit 3` is deliberately distinct from `exit 1` (validation failure)
and `exit 2` (CLI usage error), so callers can branch on it. The four
actions map to consumer-domain decisions; (b) and (c) are reversible
config edits, (a) is patience, (d) is a calendar trade-off.

## What lives where

| Concern | Owner |
|---|---|
| Per-datacenter GPU availability + price | `runpod-deploy gpu-list --datacenter <id>` |
| Walking `gpu_order` × `datacenters` and raising on empty intersection | `runpod-deploy validate --check-availability` |
| Pod provisioning + multi-DC failover | `runpod-deploy run` |
| Choosing between wait / widen / switch / defer | Your sweep driver (this recipe) |
| Filing a tracking issue when a stock-out blocks a release | Your release process |

## Anti-pattern to avoid

Do not bake the four-action decision tree into `runpod-deploy` itself.
A future `runpod-deploy autoretry-on-stockout` flag would have to
guess — wait how long? widen to which GPUs? switch only if pricing is
within X%? — and any choice is wrong for some consumer. Keep the policy
in your driver where you can see and tune it.

Similarly, do not parse `gpu-list`'s human-readable output in a
production driver. Today the output is for operators reading a terminal;
if you need machine-readable per-datacenter stock data, prefer
`runpod-deploy validate --check-availability` (which exits non-zero on
empty) over scraping `gpu-list`.

## See also

- [`local-preflight-then-run.md`](local-preflight-then-run.md) — the
  canonical pre-launch pattern; this recipe is a stock-out-specific
  specialization of the same Makefile shape.
- [`multi-config-sweep.md`](multi-config-sweep.md) — most sweep
  drivers call a pre-flight check before the per-config loop; this
  recipe is what that check should look like for stock-out.
