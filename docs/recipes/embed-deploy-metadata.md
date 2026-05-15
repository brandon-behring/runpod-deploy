# Recipe: embed deploy metadata in your own artifacts

**Pattern:** when your eval pipeline writes its own `manifest.json` or
`results.json`, embed the local git SHA + lockfile hash via
`runpod-deploy capture-env`. This replaces ad-hoc
`GIT_SHA=$(git rev-parse HEAD)` injection in Makefile targets.

## When you need this

`runpod-deploy run` already embeds `deploy_metadata` in
`runpod_deploy_pull_manifest.json` for any run it manages. You only
need this recipe when:

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

```python
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
