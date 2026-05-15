#!/usr/bin/env bash
# Forensic example: aggregate cost + failure stats across a multi-shard sweep.
#
# Pulls every runpod_deploy_pull_manifest.json under artifacts/runpod/
# and prints a per-run summary block plus a == TOTALS == footer with
# manifest count, failure count, summed wall_time_sec, summed
# estimated_cost_usd.
#
# Replaces the prior shell-glob workaround:
#   runpod-deploy manifest-summary 'artifacts/runpod/*/runpod_deploy_pull_manifest.json'
# which only worked because the shell expanded the glob; --root walks
# the tree natively and includes the TOTALS footer.
#
# See: docs/recipes/cost-reconciliation.md

set -euo pipefail

ROOT="${1:-artifacts/runpod}"

if [ ! -d "$ROOT" ]; then
  echo "==> $ROOT does not exist; nothing to reconcile" >&2
  exit 0
fi

runpod-deploy manifest-summary --root "$ROOT"
