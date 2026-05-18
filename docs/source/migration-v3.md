# Migration notes (v0.8.2 and prompt-injection-v3)

## Lifecycle policy: `stop:` → `lifecycle:` (v0.8.2)

The YAML `stop:` block is renamed to `lifecycle:` with three-valued
actions instead of booleans, and the defaults change so that
**successful runs release their volume disk by default**.

### Motivation

On 2026-05-17 the repo's RunPod account held 76 stale EXITED pods
totaling 3,930 GB of preserved volume disk — **$1.10/hr (~$26/day,
~$393/month)** of idle storage burn. The leak existed because
`runpodctl pod stop` (which `runpod-deploy` issued under the old
`on_success: true` default) *pauses* a pod but **keeps the volume
disk allocated indefinitely** at RunPod's $0.10/GB·month rate.
Operators reasonably assumed "stop" meant "terminated" — the
documentation at `lifecycle.md:214-222` literally said so. The
schema change makes the action space explicit and the cost trade-off
visible at config-edit time.

### New schema

```yaml
lifecycle:
  on_success: delete       # NEW default — releases volume disk on success
  on_failure: stop         # NEW default — preserves paused pod for SSH forensics
```

Each field accepts one of three strings (plus a fourth on
`on_success` only):

| value      | runpodctl call      | volume disk after |
| ---------- | ------------------- | ----------------- |
| `preserve` | _(none)_            | continues at full rate (compute + disk) |
| `stop`     | `pod stop <id>`     | **continues at ~$0.10/GB·month indefinitely** |
| `delete`   | `pod delete <id>`   | released |
| `recycle`  | `pod stop <id>`     | continues at ~$0.10/GB·month; next run resumes this pod (`on_success` only) |

See [`lifecycle.md` §7](lifecycle.md#7-lifecycle-action-cleanup) for
the full table and [`lifecycle.md` §7b](lifecycle.md#7b-cost-discipline-cleaning-up-after-forensics)
for the cleanup-after-forensics workflow.

### Legacy `stop:` block — bool shim

Existing configs using the old `stop: {on_success: bool, on_failure: bool}`
block continue to parse; a single `[deprecated]` WARNING is emitted
per parse. The shim maps:

| old form                       | new equivalent                |
| ------------------------------ | ----------------------------- |
| `stop.on_success: true`        | `lifecycle.on_success: delete` |
| `stop.on_success: false`       | `lifecycle.on_success: preserve` |
| `stop.on_failure: true`        | `lifecycle.on_failure: stop` |
| `stop.on_failure: false`       | `lifecycle.on_failure: preserve` |

A config that sets **both** `lifecycle:` and `stop:` is rejected with
a clear `ValueError`. The bool shim will be removed in a future
minor release; migrate at your leisure.

### CLI changes

| old command                                          | new command                                                 |
| ---------------------------------------------------- | ----------------------------------------------------------- |
| `runpod-deploy stop --state-file <path>`             | `runpod-deploy cleanup --state-file <path> --mode stop`     |
| _(no equivalent — was a manual `xargs` invocation)_  | `runpod-deploy cleanup --all-stopped [--yes]`               |
| _(no equivalent)_                                    | `runpod-deploy ls-stale [--json]`                           |

The `stop` subcommand remains as a deprecated alias.

### Python API changes (breaking for direct importers)

```python notest
# Before
from runpod_deploy import StopPolicySpec
from runpod_deploy.provider import stop_pod

# After
from runpod_deploy import LifecyclePolicySpec, LIFECYCLE_ACTIONS, StalePod
from runpod_deploy.provider import cleanup_pod, list_stale_pods, bulk_delete_pods
```

`RunpodJobSpec.stop` is renamed to `RunpodJobSpec.lifecycle`.

### What you need to do

1. **Now**: nothing required — your existing configs and any
   in-flight runs continue to work via the bool shim. Watch the
   `[deprecated]` warnings to gauge your migration backlog.
2. **Next sweep / next config edit**: rename the `stop:` block to
   `lifecycle:` and replace booleans with string values. The
   migration is mechanical; the table above is the full mapping.
3. **Audit**: run `runpod-deploy ls-stale` to find any historical
   pods that the old code left behind; bulk-release with
   `runpod-deploy cleanup --all-stopped --yes`.
4. **Hygiene**: wire `runpod-deploy ls-stale` into a weekly cron or
   CI job to detect drift. See
   [`recipes/stale-pod-audit.md`](recipes/stale-pod-audit.md).

---

## prompt-injection-v3 Migration

This document walks `prompt-injection-v3` consumers through replacing
v3's hand-rolled deploy commands (`uv run reviewer-runpod`,
`uv run v3-1-runpod`, `uv run v3-1-runpod-ephemeral`) with thin
wrappers around `runpod-deploy run`.

If you're migrating a different consumer (e.g., a fresh project), skip
this doc and go straight to [`quickstart.md`](quickstart.md).

## Why migrate

`prompt-injection-v3` (the project) pre-dates `runpod-deploy` (the
tool). The v3-era deploy scripts were hand-rolled bash that
duplicated GPU/DC failover, staging, and artifact-pull logic. Every
sweep maintenance change required editing six different scripts in
parallel.

`runpod-deploy` absorbs those primitives:

- **GPU/DC failover** — `pod.gpu_order` + `pod.datacenters` iterate
  the matrix automatically; v3 had to encode this in bash per script.
- **Staging excludes** — `staging[].excludes_default` + standard
  rsync excludes replace the `--exclude` flag stacks v3 maintained
  inline.
- **Cost capping** — `budget.cost_cap_usd` enforces both
  per-invocation budget *and* derives the implicit runtime ceiling;
  v3 had cost caps only via `timeout` on `runpodctl pod create`.
- **Deploy metadata capture** — git SHA + lockfile hash land in
  `runpod_deploy_pull_manifest.json` automatically; v3 hand-rolled
  `GIT_SHA=$(git rev-parse HEAD)` injection.
- **Artifact pull manifest** — `runpod_deploy_pull_manifest.json`
  records what was pulled, when, with what cost; v3 had ad-hoc
  `pulled_log.txt`.

The migration is mechanical: each v3 deploy command becomes a YAML
config + a Makefile target that invokes `runpod-deploy run`.

## One-time setup

In the `prompt-injection-v3` repo:

```sh
# Add runpod-deploy as an optional dependency
# (in pyproject.toml's [project.optional-dependencies.cloud]):
#   cloud = ["runpod-deploy>=0.8.1"]
uv sync --extra cloud

# runpod-deploy is now at .venv/bin/runpod-deploy
.venv/bin/runpod-deploy --help
```

This is the recommended "consumer-owned configs" pattern (see the
runpod-deploy README's "Consumer-owned configs" section).

## Per-job migration

### Step 1: write the YAML config

Create `configs/runpod/<job-name>.yaml` in your v3 repo. Use
[`quickstart.md`](quickstart.md) as the template; reference
[`config-reference.md`](config-reference.md) for field semantics.

The v3-era environment variables and command-line flags map to YAML
sections as follows:

| v3 hand-rolled | runpod-deploy YAML |
|---|---|
| `--gpu-type`, `--gpu-type-fallback` | `pod.gpu_order` (ordered list) |
| `--datacenter`, `--datacenter-fallback` | `pod.datacenters` (ordered list) |
| `--cost-cap-usd` (per-script) | `budget.cost_cap_usd` |
| `--timeout-minutes` | `budget.max_runtime_minutes` |
| `--cloud-type` | `pod.cloud_type` (`SECURE` or `COMMUNITY`) |
| Hand-rolled `rsync --exclude=foo` | `staging[].excludes_extra: [foo]` |
| Hand-rolled `git rev-parse HEAD` | Auto-captured in manifest |
| Inline bash run script | `run.body` (multi-line YAML string) |

### Step 2: validate

```sh
runpod-deploy validate --config configs/runpod/<job-name>.yaml --all
```

The `--all` flag runs every opt-in check: schema validation, local
path existence, GPU availability against the configured datacenters,
consumer pyproject scan. Fix anything it flags before paying for a
pod.

### Step 3: dry-run

```sh
runpod-deploy run --config configs/runpod/<job-name>.yaml --offline-dry-run
```

`--offline-dry-run` walks the command shape without hitting the
network — no `runpodctl` calls, no SSH, no rsync. Confirms the
orchestrator state machine accepts your config end-to-end.

### Step 4: real run

```sh
runpod-deploy run --config configs/runpod/<job-name>.yaml
```

On success, your artifacts land under `artifacts/runpod/<timestamp>/`
along with `runpod_deploy_pull_manifest.json`. The pod is stopped
automatically per `stop.on_success: true`.

### Step 5: keep the v3 command name (optional)

If you want `uv run reviewer-runpod` to keep working as a thin shim,
add a one-line wrapper to `pyproject.toml`:

```toml
[project.scripts]
reviewer-runpod = "your_v3_module.cli:reviewer_runpod_main"
```

Where `reviewer_runpod_main` is a 3-line Python function that calls
`subprocess.run(["runpod-deploy", "run", "--config", "runpod/reviewer.yaml", *sys.argv[1:]])`.
This lets you keep your existing tooling (`uv run reviewer-runpod
--dry-run`) while the underlying execution is delegated.

## Regression testing

Before retiring the old v3 hand-rolled deploy scripts, run both in
parallel for one billing cycle:

1. Run the v3 hand-rolled script: `uv run reviewer-runpod`. Note
   pod-id, wall time, cost.
2. Run the runpod-deploy equivalent:
   `runpod-deploy run --config runpod/reviewer.yaml`. Note pod-id,
   wall time, cost.
3. Compare the pulled artifacts byte-for-byte (`diff -r artifacts/v3-script-output/ artifacts/runpod/<ts>/`).

If the artifacts diverge, do NOT retire the v3 script until you've
diagnosed the cause. Common causes: missing files in `staging[]`
(check `excludes_default` semantics), different environment variables
(check `remote_env.exports` + `secrets`), or different `gpu_order`
producing different GPU classes per shard.

## Backwards-compat timeline

- **v3.x with hand-rolled scripts**: keep working as-is. No
  runpod-deploy dependency.
- **v3.x with runpod-deploy >= 0.8.1**: add the wrapper per Step 5;
  both invocation styles work side-by-side.
- **v4.x (planned)**: hand-rolled scripts removed; runpod-deploy is
  the only path. Migration deadline TBD; will be announced in v3's
  CHANGELOG when set.

## See also

- [`quickstart.md`](quickstart.md) — the canonical onboarding path
  for fresh consumers.
- [`config-reference.md`](config-reference.md) — full YAML schema.
- [`extending.md`](extending.md) — the three-tier extension story
  (consumers / library users / contributors).
- [`recipes/local-preflight-then-run.md`](recipes/local-preflight-then-run.md) —
  the canonical "audit then deploy" pattern; replaces ad-hoc pre-run
  hooks in v3-era scripts.
