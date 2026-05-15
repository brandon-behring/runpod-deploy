#!/usr/bin/env bash
# Forensic example: audit datacenter failover events.
#
# Every time pod.gpu_order × pod.datacenters lookup falls through to a
# different DC (because the configured GPUs were out-of-stock in the
# preferred DC), the orchestrator emits a datacenter_failover event.
# Aggregating these across runs reveals stock patterns:
#  - Which DCs are reliable for which GPU classes?
#  - Which GPU classes routinely fall back to second-choice DCs?
#  - Should pod.datacenters / pod.gpu_order ordering be revised?
#
# Usage:
#   ./dc_failover_audit.sh                  # last 30d, default artifacts/runpod
#   ./dc_failover_audit.sh 90d
#
# Output: JSONL. Useful pipes:
#   ./dc_failover_audit.sh | jq -r '.gpu_id'  | sort | uniq -c | sort -nr
#       # → frequency table of which GPU classes failed over most
#   ./dc_failover_audit.sh | jq -r '.reason' | sort | uniq -c
#       # → reason codes (e.g., '<gpu>' price > cap, 'no stock')
#
# See: docs/troubleshooting.md "Forensic recovery"

set -euo pipefail

SINCE="${1:-30d}"
ROOT="${2:-artifacts/runpod}"

if [ ! -d "$ROOT" ]; then
  echo "==> $ROOT does not exist; nothing to query" >&2
  exit 0
fi

runpod-deploy events-query \
  --root "$ROOT" \
  --filter event=datacenter_failover \
  --since "$SINCE" \
  --json
