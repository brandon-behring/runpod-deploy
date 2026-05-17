# Recipe: forensics, then cleanup

**Pattern:** when a `runpod-deploy run` fails, the default
`lifecycle.on_failure: stop` preserves the pod paused so you can SSH
in for post-mortem. After investigation, release the volume disk
explicitly so it doesn't bill indefinitely.

## Why this is a recipe, not a schema feature

The two halves — forensics and cleanup — are operator workflows, not
configuration. `runpod-deploy` provides the affordances
(`ls-stale`, `cleanup --state-file`, `cleanup --all-stopped`) and an
actionable WARNING per failed run; chaining them into your team's
hygiene practice is a workflow concern.

## The trigger: a per-run WARNING

When a run fails with `lifecycle.on_failure: stop` (the default),
the orchestrator emits a multi-line WARNING ending with the exact
release command:

```
[lifecycle] pod 'abc123' stopped for forensics.
  Volume disk (50 GB) continues billing at ~$0.17/day (~$5.00/mo) until released.
  When done investigating, release with:
      runpod-deploy cleanup --state-file ~/.runpod-deploy-current --mode delete
  Or audit all stale pods:
      runpod-deploy ls-stale
```

Treat this WARNING as a TODO. Until you act on it, the volume disk
is billing.

## Step 1 — Inspect offline (no SSH needed for most diagnoses)

Most failure modes are visible in the artifacts already pulled:

```bash
# What just happened?
runpod-deploy manifest-summary artifacts/runpod/<ts>/runpod_deploy_pull_manifest.json

# Tail the run log
tail -n 200 artifacts/runpod/<ts>/run.log

# Inspect telemetry (GPU mem over time, dmesg, etc.)
ls artifacts/runpod/<ts>/telemetry/
```

`runpod-deploy events` and `events-query` walk the event log for
structured per-step status. Most "why did this fail" questions are
answered without ever logging into the pod.

## Step 2 — SSH only if needed

If the offline inspection isn't enough:

```bash
# Resume the paused pod
runpodctl pod start <pod-id>

# Attach
runpodctl pod ssh <pod-id>
```

The pod retains its `/workspace`, so any state inspection (look at a
`.pyc` file, re-run a single Python expression in the same venv) is
available. When done, exit the SSH session — but **don't forget to
delete the pod**; resuming it puts compute billing back on top of
the storage billing you've already been paying since the failure.

## Step 3 — Release

Once forensics is complete, run the command from the WARNING:

```bash
runpod-deploy cleanup --state-file ~/.runpod-deploy-current --mode delete
```

The default `--mode` is `delete`, so `runpod-deploy cleanup
--state-file <path>` is also sufficient. The state file is unlinked
on success; the pod is gone; volume disk is released.

## Step 4 — Bulk-release after a sweep

If you ran a 50-config sweep and 12 failed, do not chase each one
individually. Run a single bulk command after the sweep:

```bash
# What's still around?
runpod-deploy ls-stale

# Release everything (interactive y/N)
runpod-deploy cleanup --all-stopped

# Or non-interactive (for CI / cron)
runpod-deploy cleanup --all-stopped --yes
```

The bulk path collects failures rather than aborting on the first
delete error, so one transient API hiccup doesn't leave the rest
billing.

## Step 5 — Add hygiene to your weekly rhythm

The leak that motivated this recipe (2026-05-17, 76 stale pods,
$26/day) accumulated over weeks because no one was looking. Wire
`ls-stale` into your regular review:

```bash
# Add to a personal Makefile / Justfile / weekly cron
runpod-deploy-audit:
	runpod-deploy ls-stale
```

Or, for an automated nudge: see
[`recipes/stale-pod-audit.md`](stale-pod-audit.md) for the JSON
output pattern that feeds a Slack ping or GitHub Action.

## Anti-pattern to avoid

Don't set `lifecycle.on_failure: stop` "just in case I want to debug
later" if you don't actually do post-mortems. The default is
`stop` for the case where you *will* SSH in; if your team never
does, set:

```yaml
lifecycle:
  on_success: delete
  on_failure: delete       # opt out of forensics, opt out of storage billing
```

Failed runs still pull artifacts and write the manifest before the
delete, so `runpod-deploy manifest-summary` and the run log are
still available for analysis.
