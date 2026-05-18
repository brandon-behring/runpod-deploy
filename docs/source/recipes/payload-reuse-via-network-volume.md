# Recipe: reuse the staging payload via a network volume

**Pattern:** when you run the same workflow repeatedly (a daily
benchmark, a parameter sweep over the same repo), most of each
`runpod-deploy run` is *re-paying* fixed costs: image pull (~2–5
min), `setup:` re-runs (apt install, uv venv), full rsync of the
staging payload (1–5 min for typical repos). Switching the workflow
to `storage.mode: network_volume` lets those costs amortize across
runs — rsync becomes incremental, the image stays cached on the
volume, and the venv survives.

## Why this is a recipe, not a default

The trade-off is real:

- **Network volume**: $0.07/GB·month for the first 1 TB. A 100 GB
  volume sitting idle is ~$7/month. Pinned to one datacenter — if
  the GPU you want is unavailable there, the run waits.
- **Ephemeral**: free when no pod exists. Full rebuild every run.
  Free GPU choice across all of your `pod.datacenters:`.

For a hello-world or smoke config that runs occasionally, ephemeral
wins. For a benchmark you run 5× a week against the same 2 GB repo
with 8 GB of cached venv state, network_volume wins by hours of wall
time.

## Step 1 — Create the volume

```bash
# Pick a datacenter where your GPU type is consistently available.
runpodctl network-volume create \
  --name pid-workspace-100gb \
  --datacenter EU-RO-1 \
  --size 100
```

The volume is empty. RunPod returns an ID; remember the name
(`pid-workspace-100gb`) — your config references it by name, not by
ID.

Audit volumes anytime:

```bash
runpodctl network-volume list
```

## Step 2 — Update the YAML

```yaml
storage:
  mode: network_volume
  volume_name: pid-workspace-100gb       # must match the name above
  volume_mount: /workspace               # default; what your scripts assume

pod:
  # Network volume is pinned to one datacenter; constrain pod placement to match.
  datacenters: [EU-RO-1]
  gpu_order:
    - NVIDIA H100 80GB HBM3
    - NVIDIA A100-SXM4-80GB

lifecycle:
  on_success: delete                     # release compute; volume persists
  on_failure: stop                       # preserve compute too for forensics
```

The `lifecycle.on_success: delete` action releases the *pod's*
compute and its container disk — but the network volume is a
separate, named resource that survives the pod. Across runs, your
`/workspace` is the same filesystem.

## Step 3 — Make the staging incremental

`runpod-deploy` already uses `rsync` for staging, so the second run
of the same workflow only pushes changed bytes. You don't need to
change anything in the `staging:` block — rsync's incremental
behavior happens for free against a persistent destination.

A few hygiene patterns help:

- Keep `staging.excludes_default: true` (project default) so the
  hygiene exclusions like `**/__pycache__/`, `.git/`, `.venv/`,
  `.pytest_cache/` don't fight rsync.
- Add project-specific large-but-stable directories to
  `staging.excludes_extra` if they're populated on the volume some
  other way (e.g., a Hugging Face cache).

## Step 4 — Cache slow setup output on the volume

Your `setup:` commands run on every pod, but if they write to
`/workspace`, their output persists across pods. Two common idioms:

```yaml
setup:
  - command: |
      # uv venv is idempotent; second run is a fast no-op
      if [ ! -d /workspace/.venv ]; then
        uv venv /workspace/.venv --python 3.11
      fi
      source /workspace/.venv/bin/activate
      uv pip install --quiet -e /workspace/repo
    timeout_sec: 300
```

```yaml
setup:
  - command: |
      # Cache the HF model downloads on the volume
      export HF_HOME=/workspace/.cache/huggingface
      mkdir -p $HF_HOME
    timeout_sec: 30
```

After the first run, the venv and the HF cache are warm. Subsequent
runs spend most of `setup:` re-establishing environment variables,
not pulling bytes.

## What this does *not* solve

- **Docker image pull is still per-pod** — the image isn't on the
  volume; it's on the pod's container disk. Image pull is ~30 s for
  a cached image / ~2–5 min for an uncached image. RunPod caches
  popular images at the datacenter level; the `runpod/pytorch:...`
  base used in this repo's examples is usually already cached.
- **`setup:` commands still run** every pod, even if the outputs are
  cached. They must be idempotent; the cost is just the
  short-circuit branches, which is small.

If image-pull + setup re-execution is still the dominant cost, the
right next step is to leave a pod *paused* between runs and resume
it directly. That's `lifecycle.on_success: recycle` — see
[`recipes/recycle-pod-for-fast-iteration.md`](recycle-pod-for-fast-iteration.md).
Recycle reuses ONE pod across runs (saves image-pull + cold-boot);
network volume here reuses a /workspace ACROSS pods (saves rsync +
venv state). They're orthogonal and compose: ephemeral storage +
recycle is the most common combination for "fast iteration on one
workflow"; network volume + delete is the right combo for "share
state across parallel sweep workers".

## What this DOES solve

For a typical benchmark workflow (5 runs/week, 2 GB repo, 8 GB
cached venv, 12 GB HF model):

- First run: ~3 min image pull + ~2 min setup + ~3 min staging + run.
- Second run onward: ~30 s image pull (cached at DC) + ~10 s setup
  (everything cached) + ~5 s staging (rsync says "nothing to do") + run.

That's ~7 minutes saved per run, or ~30 minutes/week. The $7/month
volume cost is recovered if your time is worth more than $0.20/h.

## What lives where

| Concern | Owner |
|---|---|
| Creating / sizing / pinning the network volume to a datacenter | `runpodctl network-volume create` (one-shot, manual) |
| Resolving the volume by name on every run | `runpod-deploy run` (`provider.resolve_volume`) |
| Mounting the volume at `/workspace` on the pod | `runpod-deploy run` (`storage.volume_mount`) |
| Making rsync incremental (delete-aware) | `staging[].delete: false` in YAML |
| Caching slow setup output (venv, model weights, apt caches) | Your `setup:` commands writing under `/workspace/...` |
| Deciding when the cost of an idle volume is worth the speed | You (recipe trade-off table above) |
| Migrating a volume to a different datacenter | Manual — RunPod doesn't move volumes; recreate + rsync |

## Anti-pattern to avoid

Don't pin every project to its own 1 TB volume "just in case". A 1 TB
volume costs ~$70/month idle. Size to the workflow: typical Python
project + cached venv + model weights = 50–100 GB.

Don't share one volume across unrelated workflows by mounting at
`/workspace` and writing into a project-specific subdirectory.
`storage.volume_mount` is shared by every consumer that mounts the
same volume; concurrent runs from different projects will corrupt
each other's setup state. Either give each workflow its own volume,
or pair the share with strict per-run subdirectory isolation enforced
in `run.body:`.

## See also

- [`lifecycle.md` §7b](../lifecycle.md#7b-cost-discipline-cleaning-up-after-forensics)
  — why `lifecycle.on_success: delete` is the default even when the
  volume persists.
- [`config-reference.md`](../config-reference.md) — full
  `storage.mode: network_volume` schema reference.
