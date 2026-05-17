# Migration notes (v0.9 and prompt-injection-v3)

## Lifecycle policy: `stop:` → `lifecycle:` (v0.9)

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

Each field accepts one of three strings:

| value      | runpodctl call      | volume disk after |
| ---------- | ------------------- | ----------------- |
| `preserve` | _(none)_            | continues at full rate (compute + disk) |
| `stop`     | `pod stop <id>`     | **continues at ~$0.10/GB·month indefinitely** |
| `delete`   | `pod delete <id>`   | released |

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

```python
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
