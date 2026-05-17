# Recipe: embed deploy metadata in your own artifacts

**Pattern:** when your eval pipeline writes its own `manifest.json` or
`results.json`, embed the local git SHA + lockfile hash via
`runpod-deploy capture-env`. This replaces ad-hoc
`GIT_SHA=$(git rev-parse HEAD)` injection in Makefile targets.

## Why this is a recipe, not a schema feature

`runpod-deploy run` already embeds `deploy_metadata` in
`runpod_deploy_pull_manifest.json` for any run it manages — that's the
deployment-primitive part. What's *consumer-domain* is your own
artifact manifests: which fields you want, what your evaluation
pipeline writes, how you join the two. `runpod-deploy` exposes the
capture as a standalone CLI (`capture-env`) so your scripts can pull
the same metadata into wherever they want it, without baking your
manifest schema into ours.

Use this recipe when:

- You produce *additional* artifacts that should be pinned to the same
  git SHA / lockfile hash but live in your project's manifest, not
  runpod-deploy's.
- You run consumer-domain pipelines (audits, plot rendering) outside
  `runpod-deploy run` and want them traceable to a state.

## Pattern (Makefile)

```makefile
.PHONY: headline-cloud
headline-cloud:
	runpod-deploy capture-env --project-root . > /tmp/runpod_env.json
	runpod-deploy run \
		--config configs/runpod/headline.yaml
	# Merge runpod-deploy's capture into your own evals manifest:
	uv run python scripts/merge_env_into_evals.py \
		--env-file /tmp/runpod_env.json \
		--evals-manifest evals/headline/manifest.json
```

## Pattern (Python)

```python notest
import json
import subprocess

env = json.loads(
    subprocess.run(
        ["runpod-deploy", "capture-env", "--project-root", "."],
        check=True,
        capture_output=True,
        text=True,
    ).stdout
)
results_manifest = {
    "git_sha": env["local_git_sha"],
    "git_dirty": env["local_git_dirty"],
    "uv_lock_sha256": env["payload_lockfile_sha256"],
    # ... your own fields
}
```

## What `capture-env` emits

```json
{
  "local_git_sha": "abc123...",
  "local_git_dirty": false,
  "local_git_branch": "main",
  "payload_lockfile": "uv.lock",
  "payload_lockfile_sha256": "def456..."
}
```

Each field is `null` (with a WARNING) if the source isn't available
(no git repo, no `uv.lock` or `requirements.txt`). The command never
raises.

## What lives where

| Concern | Owner |
|---|---|
| Capturing git SHA, dirty flag, branch | `runpod-deploy capture-env` (`metadata.capture_local_git`) |
| Capturing lockfile hash + filename | `runpod-deploy capture-env` (`metadata.capture_payload_lockfile`) |
| Embedding metadata in the orchestrator-managed pull manifest | `runpod-deploy run` (automatic, no opt-in needed) |
| Embedding metadata in your own evals/results manifest | Your script (call `capture-env`, parse JSON, merge into your manifest) |
| Defining what fields your manifest schema requires | Your project |

## Anti-pattern to avoid

**Do not hand-roll `git rev-parse HEAD` injection in Makefiles when
`capture-env` exists.** The captured fields are a superset of what
most consumers reach for (SHA + dirty flag + branch + lockfile hash +
lockfile path), they handle the "no git repo" and "no lockfile" cases
gracefully, and they emit the same fields that land in
`runpod_deploy_pull_manifest.json` automatically — so your manifest
stays consistent with runpod-deploy's.

**Do not pin your evals manifest schema to runpod-deploy's manifest
schema.** They're different concerns: ours is deploy-state, yours is
eval-state. Copy the fields you want; don't subclass or re-export.

## See also

- [`cost-reconciliation.md`](cost-reconciliation.md) — the same
  metadata fields are captured into every run's
  `runpod_deploy_pull_manifest.json` automatically; use
  `capture-env` when you need them in *your own* manifest (separate
  from runpod-deploy's).
- [`local-postprocess-after-run.md`](local-postprocess-after-run.md) —
  consumer post-processing scripts often join the `capture-env` JSON
  with the pulled artifacts to build a reproducibility-grade output.
- [`reproducibility.md`](reproducibility.md) — when paired with
  `pod.python_version`, the manifest records the third leg of the
  reproducibility tripod (git SHA + lockfile hash + interpreter pin).
