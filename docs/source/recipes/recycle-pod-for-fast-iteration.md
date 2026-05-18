# Recipe: recycle a pod for fast iteration

**Pattern:** for workflows you run repeatedly with the same image and
GPU class — daily benchmarks, debug-rerun loops, sweeps — set
`lifecycle.on_success: recycle` so successful runs pause the pod
*and preserve the state-file*. The next `runpod-deploy run` with the
same `state_file:` finds the paused pod, validates compatibility,
and calls `runpodctl pod start <id>` instead of `pod create`. Image
pull and cold-boot are skipped; setup commands re-run (idempotent)
and rsync is incremental.

## When to use this

| Scenario | Use recycle? |
|---|---|
| One-shot run, occasional sweeps | **No** — fresh `delete` default is fine; the storage cost is negligible. |
| Same config, multiple times per week | **Yes** — 3–5 min × N runs saved per week. |
| Iterating on `run.body:` against a heavy image | **Yes** — image cache survives between attempts. |
| Two configs sharing one paused pod | **No** — `state_file:` is per-config; share via network volume instead. |
| `lifecycle.on_failure` | **No** — `recycle` is success-path only; failed pods have potentially corrupted state. |

## Why this is a recipe, not a default

The trade-off is real: a 50 GB pod sitting paused costs ~$0.17/day
(~$5/mo). For one-shot configs that's waste. For a 5×/week workflow
that recovers 30+ minutes of cold-start time per week, it pays off.
Recycle is opt-in.

## Minimum config

```yaml
# foo.yaml
name: my-benchmark
run_id_prefix: my-benchmark
state_file: ~/.runpod-my-benchmark-current   # IMPORTANT: per-config path

pod:
  image: runpod/pytorch:2.4.0-py3.11-cuda12.4.1-devel-ubuntu22.04
  datacenters: [EUR-IS-1]
  gpu_order: [NVIDIA L4]

storage:
  mode: ephemeral
  volume_gb: 50

run:
  script_path: /workspace/run.sh
  log_path: /workspace/run.log
  success_marker: "[my-benchmark] DONE"
  body: |
    echo "[my-benchmark] DONE"

lifecycle:
  on_success: recycle    # ← the only change vs. a regular config
  on_failure: stop
```

The `state_file:` MUST be a path unique to this config. The default
`~/.runpod-deploy-current` would clobber across configs — point this
field at a per-workflow path like `~/.runpod-<workflow-name>-current`.

## Lifecycle walkthrough

### First run (cold)

```bash
runpod-deploy run --config foo.yaml
```

What happens:
1. State-file `~/.runpod-my-benchmark-current` doesn't exist yet → no
   resume attempt.
2. `runpodctl pod create` → image pull (~3 min on cold host) → SSH-ready.
3. `setup:` runs → rsync staging → run script → artifact pull.
4. `lifecycle.on_success: recycle` → `runpodctl pod stop <id>`.
5. State-file written: `{pod_id, gpu_id, image, datacenter_id}`.
6. Manifest shows `pod_resumed: false`.

### Second run (warm)

```bash
runpod-deploy run --config foo.yaml
```

What happens:
1. State-file exists → `try_resume_pod` reads it.
2. `runpodctl pod get <pod_id>` confirms the pod is EXITED and the
   stored image/GPU/datacenter match the current spec.
3. `runpodctl pod start <pod_id>` (no image pull — cache is warm).
4. SSH-ready typically in 30–60 s (vs 3–5 min cold).
5. `setup:` re-runs (idempotent — apt skip, uv venv skip).
6. rsync re-pushes (incremental — only changed bytes).
7. Run script → artifact pull → `pod stop` again.
8. Manifest shows `pod_resumed: true`.

### Image drift

If you bump `pod.image` in the YAML between runs:

```
[recycle] drift detected for pod 'abc123': image: stored='runpod/pytorch:OLD' current='runpod/pytorch:NEW'; deleting stale pod and fresh-creating
```

The stale pod is deleted, state-file is unlinked, and a fresh
`runpodctl pod create` fires. The next run is cold again. Same for
GPU class or datacenter changes.

### Forcing a fresh run on demand

```bash
runpod-deploy run --config foo.yaml --force-fresh
```

Skips the resume attempt for this run only:
- Deletes any stale paused pod referenced by the state-file.
- Unlinks the state-file.
- Provisions a fresh pod via `runpodctl pod create`.

Useful for "did I actually pull the new image?" debugging without
editing YAML.

Equivalent manual recipe: `rm ~/.runpod-my-benchmark-current && runpod-deploy run --config foo.yaml`.

## Hygiene: pair with `ls-stale`

A paused recycle pod shows up in `runpod-deploy ls-stale` like any
other EXITED pod — that's intentional. The audit lists give you
visibility into what you're recycling:

```bash
runpod-deploy ls-stale
```

```
POD_ID           NAME                                         GB    $/day     $/mo
----------------------------------------------------------------------------------
abc12345         my-benchmark-20260517T120000Z                 50     0.17     5.00
def67890         my-other-workflow-20260517T103000Z           100     0.33    10.00
----------------------------------------------------------------------------------
TOTAL: 2 pods, $0.50/day (~$15.00/mo)
```

If a recycle pod has been idle for weeks and you've moved on, just
delete it via `runpod-deploy cleanup --state-file <path> --mode
delete` (or hand-`runpodctl pod delete <id>`).

## When recycle stops paying off

Three signals that a workflow shouldn't be on recycle anymore:

1. **Image drift WARNING fires every run** — your image is rotating
   too fast for the cache to help.
2. **`ls-stale` shows a recycle pod sitting > 30 days unused** —
   you've moved off this workflow; switch to `on_success: delete` and
   `rm` the state-file.
3. **GPU class changes per run** — sweeps that rotate `gpu_order`
   force fresh-create every time anyway.

## What lives where

| Concern | Owner |
|---|---|
| Issuing `runpodctl pod stop` at end-of-run + preserving state-file | `runpod-deploy run` (`provider._cleanup_recycle`) |
| Storing the resume pointer (pod_id + image + GPU + DC) | The state-file at `state_file:` (per-config) |
| Validating that the paused pod still matches the spec (image / GPU / DC drift) | `runpod-deploy run` (`provider.try_resume_pod`) |
| Calling `runpodctl pod start <id>` when validation passes | `runpod-deploy run` (`provider.try_resume_pod`) |
| Forcing a fresh-create regardless of state-file | `runpod-deploy run --force-fresh` |
| Deciding when recycle stops paying off (volume cost vs run frequency) | You (the trade-off above) |
| Pairing with weekly `ls-stale` to catch forgotten paused pods | Your hygiene rotation |

## Anti-pattern to avoid

Don't use `lifecycle.on_success: recycle` on configs you run less than
~3×/week. A 50 GB paused pod costs ~$5/mo idle; the recycle benefit
(saved cold-start time × run frequency) needs to clear that floor.
For low-frequency configs, the default `lifecycle.on_success: delete`
is cheaper.

Don't share one `state_file:` across multiple configs. The state-file
is the resume pointer; if two configs both write to
`~/.runpod-deploy-current` and the second config recycles a pod
provisioned by the first, image / GPU / DC drift detection will fall
through to fresh-create (with a WARNING) — defeating the purpose.
Always give recycled configs unique `state_file:` paths.

## See also

- [`lifecycle.md` §7](../lifecycle.md#7-lifecycle-action-cleanup) —
  the full action table including `recycle`.
- [`payload-reuse-via-network-volume.md`](payload-reuse-via-network-volume.md)
  — orthogonal: use a network volume to share state ACROSS pods
  (e.g., for parallel sweeps). Recycle reuses ONE pod across runs.
- [`troubleshooting.md`](../troubleshooting.md) — diagnosing drift
  WARNINGs and unexpected fresh-creates.
