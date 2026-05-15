# Forensic scripts

Pre-built shell scripts for common post-run queries. Each is short
enough to copy-paste-adapt for a consumer repo; they exist here as
runnable references rather than as a library to vendor.

| Script | What it does | When to use |
|---|---|---|
| [`cost_reconciliation_one_sweep.sh`](cost_reconciliation_one_sweep.sh) | Aggregates every `runpod_deploy_pull_manifest.json` under `--root` with a TOTALS footer | After every sweep completes |
| [`find_killed_pods.sh`](find_killed_pods.sh) | JSONL of every `pod_killed_unexpected` event in the time window | Post-mortem: "why did N shards fail?" |
| [`dc_failover_audit.sh`](dc_failover_audit.sh) | JSONL of every `datacenter_failover` event in the time window | Capacity planning: "which DC + GPU combos are reliable?" |

## Common invocations

```sh
# After a sweep:
./cost_reconciliation_one_sweep.sh

# "Which DCs killed pods most this month?"
./find_killed_pods.sh 30d | jq -r '.datacenter_id' | sort | uniq -c | sort -nr

# "Which GPU classes did our failover loop have to bypass most?"
./dc_failover_audit.sh 90d | jq -r '.gpu_id' | sort | uniq -c | sort -nr
```

## See also

- [`docs/troubleshooting.md`](../../docs/troubleshooting.md) "Forensic
  recovery" — full catalog of forensic CLI tools.
- [`docs/recipes/cost-reconciliation.md`](../../docs/recipes/cost-reconciliation.md)
  — the rationale behind tracking `wall_time_sec` +
  `estimated_cost_usd` per run.
- [`docs/recipes/multi-config-sweep.md`](../../docs/recipes/multi-config-sweep.md)
  — the typical source of many runs that benefit from these
  aggregate queries.
