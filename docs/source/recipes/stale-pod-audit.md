# Recipe: weekly stale-pod audit

**Pattern:** wire `runpod-deploy ls-stale` into your regular hygiene
rotation so storage drift is caught early — before it becomes a leak
like the 2026-05-17 incident (76 stale pods, 3,930 GB,
$26/day).

## Why this is a recipe, not a schema feature

`runpod-deploy ls-stale` is read-only and idempotent. Scheduling it
is an operator concern; the SDK exposes the JSON output so any
ergonomic — cron, GitHub Action, Slack ping, terminal alias —
composes on top.

## Option 1 — Terminal alias / Makefile target

The minimum-friction version. Read the table, decide whether to
release.

```bash
# ~/.zshrc or your project Makefile
alias stale='runpod-deploy ls-stale'
```

Or:

```makefile
.PHONY: audit
audit:
	runpod-deploy ls-stale
```

## Option 2 — Weekly cron with email

For solo developers who want a passive nudge:

```cron
# Every Monday 09:00 UTC — email the inventory if non-empty
0 9 * * 1 cd ~/projects/runpod-deploy && \
  out=$(.venv/bin/runpod-deploy ls-stale) && \
  [ "$out" != "No stale (EXITED) pods." ] && \
  echo "$out" | mail -s "[runpod-deploy] stale pods" you@example.com
```

The `--json` mode is suitable for parsing if you want to add a
threshold ("only alert if total > $5/day"):

```bash
runpod-deploy ls-stale --json | jq '
  [.[].estimated_daily_cost_usd] | add
  | if . > 5 then "ALERT: $\(.)/day" else "ok" end
'
```

## Option 3 — GitHub Action (CI-native)

If you'd rather the audit live in version control:

```yaml
# .github/workflows/runpod-stale-audit.yml
name: runpod-stale-audit
on:
  schedule:
    - cron: '0 9 * * 1'   # Mondays 09:00 UTC
  workflow_dispatch: {}

jobs:
  audit:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: astral-sh/setup-uv@v3
      - run: uv pip install -e .[dev] runpodctl
      - env:
          RUNPOD_API_KEY: ${{ secrets.RUNPOD_API_KEY }}
        run: |
          out=$(.venv/bin/runpod-deploy ls-stale)
          echo "$out"
          if [ "$out" != "No stale (EXITED) pods." ]; then
            echo "::warning::Stale pods detected"
            # Optional: post to Slack
            curl -X POST -H 'Content-type: application/json' \
              --data "{\"text\":\"runpod-deploy stale-pod alert:\n\`\`\`\n$out\n\`\`\`\"}" \
              ${{ secrets.SLACK_WEBHOOK_URL }}
          fi
```

The job is read-only — `ls-stale` never deletes anything. Deciding
*whether* to release is still a human judgment call (a pod kept
around deliberately for SSH-forensics should not be auto-deleted).

## Option 4 — Pair with a release threshold (auto-cleanup)

If you don't care about preserving paused pods after a window —
e.g., you know any pod that's been EXITED for >7 days is safe to
release — you can pair `ls-stale --json` with `cleanup --all-stopped`:

```bash
# Delete everything that's been stopped >7 days
stale_old=$(runpod-deploy ls-stale --json | jq '[.[] | select(.age_hours > 168)]')
count=$(echo "$stale_old" | jq 'length')
if [ "$count" -gt 0 ]; then
  echo "Releasing $count pods older than 7 days"
  echo "$stale_old" | jq -r '.[].pod_id' | xargs -I{} runpodctl pod delete {}
fi
```

This pattern is intentionally not a CLI subcommand — the threshold
and policy are too consumer-specific to ship in the SDK. The
ingredients (`ls-stale --json`, `pod delete`) compose into whatever
hygiene rule fits your team.

## What "stale" means

`ls-stale` reports every pod in the `EXITED` status, regardless of
how it got there:

- A successful run with `lifecycle.on_success: stop` → EXITED.
- A failed run with `lifecycle.on_failure: stop` (the default) →
  EXITED.
- A manually-stopped pod (`runpodctl pod stop`) → EXITED.

All three cases share the same cost characteristic: volume disk is
billing until you call `runpodctl pod delete`. The audit treats them
uniformly because the cost concern is uniform.

## See also

- [`forensics-then-cleanup.md`](forensics-then-cleanup.md) — the
  one-failed-pod workflow.
- [`lifecycle.md` §7b](../lifecycle.md#7b-cost-discipline-cleaning-up-after-forensics)
  — the cost-discipline narrative and the 2026-05-17 backstory.
