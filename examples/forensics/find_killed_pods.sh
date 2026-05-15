#!/usr/bin/env bash
# Forensic example: find every pod killed unexpectedly in the last N days.
#
# The pod_killed_unexpected event is emitted by telemetry when
# `runpodctl pod get` returns a final state other than EXITED — i.e.,
# the pod was killed mid-run by RunPod (OOM, host issue, spot
# preemption, quota). This script aggregates them across all runs
# under --root.
#
# Usage:
#   ./find_killed_pods.sh                    # last 7 days, default artifacts/runpod
#   ./find_killed_pods.sh 30d                # last 30 days
#   ./find_killed_pods.sh 7d /other/path     # custom --root
#
# Output: JSONL (one row per event with run_dir field). Pipe to jq for
# further filtering, e.g.:
#   ./find_killed_pods.sh 30d | jq '.datacenter_id' | sort | uniq -c
# tells you which datacenters had the most kills.
#
# See: docs/troubleshooting.md "Forensic recovery"

set -euo pipefail

SINCE="${1:-7d}"
ROOT="${2:-artifacts/runpod}"

if [ ! -d "$ROOT" ]; then
  echo "==> $ROOT does not exist; nothing to query" >&2
  exit 0
fi

runpod-deploy events-query \
  --root "$ROOT" \
  --filter event=pod_killed_unexpected \
  --since "$SINCE" \
  --json
