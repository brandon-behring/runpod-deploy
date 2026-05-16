# Release workflow

`runpod-deploy` ships to PyPI via a tag-triggered GitHub Actions
workflow at [`.github/workflows/release.yml`](https://github.com/brandon-behring/runpod-deploy/blob/main/.github/workflows/release.yml).
The flow uses **PyPI Trusted Publishing** (OIDC) so no API tokens
live in repo secrets.

## One-time PyPI setup

Before the first publish succeeds, configure the publisher on PyPI.
This is a manual step, done once per project.

### Option A: Pre-publish (recommended for first release)

If the project name `runpod-deploy` hasn't been claimed on PyPI yet:

1. Sign in to https://pypi.org with the account that will own the
   project.
2. Go to https://pypi.org/manage/account/publishing/.
3. Click **Add a new pending publisher**.
4. Fill in:
   - **PyPI Project Name**: `runpod-deploy`
   - **Owner**: `brandon-behring`
   - **Repository name**: `runpod-deploy`
   - **Workflow filename**: `release.yml`
   - **Environment name**: `pypi`
5. Save. The publisher now exists in "pending" state — the first
   successful workflow run will claim the project name.

### Option B: Post-claim (if `runpod-deploy` is already on PyPI)

If the package already exists on PyPI (e.g., from a manual upload):

1. Sign in as the project maintainer.
2. Go to https://pypi.org/manage/project/runpod-deploy/settings/publishing/.
3. Add a new trusted publisher with the same fields as Option A.

## GitHub-side environment setup

The workflow's `publish-to-pypi` job uses
`environment: name: pypi`. GitHub will auto-create this environment
on first workflow run, but you can also create it explicitly under
**Settings → Environments → New environment** if you want to add
approval gates or restrict the deploying branch.

For our use case (tag-triggered release from `main`-merged commits),
no additional environment protection is needed — the tag itself is
the approval gate.

## Cutting a release

1. Confirm all merged PRs since the previous tag have CHANGELOG entries.
2. Bump `pyproject.toml` `version` and `src/runpod_deploy/__init__.py`
   `__version__`. Match across both.
3. Move CHANGELOG `[Unreleased]` to `[<version>] - YYYY-MM-DD — <theme>`.
4. `make ci` green locally.
5. Commit: `chore: bump to X.Y.Z — <theme>`.
6. Push: `git push origin main`.
7. Tag: `git tag vX.Y.Z -m "vX.Y.Z — <theme>"`.
8. Push tag: `git push origin vX.Y.Z`. **This triggers the release
   workflow.**

Watch the workflow run at
https://github.com/brandon-behring/runpod-deploy/actions. The flow:

- `build` — produces `dist/runpod_deploy-X.Y.Z.tar.gz` (sdist) +
  `runpod_deploy-X.Y.Z-py3-none-any.whl` (wheel). Artifacts uploaded
  to the workflow run.
- `publish-to-pypi` — downloads the artifacts, calls
  `pypa/gh-action-pypi-publish@release/v1` with OIDC. PyPI verifies
  the signed token against the configured trusted publisher.

On success: `runpod-deploy X.Y.Z` appears at
https://pypi.org/project/runpod-deploy/ within ~1 minute.

## Failure modes

- **`Trusted publisher not configured`** — Trusted Publishing wasn't
  set up on PyPI per "One-time PyPI setup" above. The `build` job
  still succeeds; download the sdist + wheel from the workflow run
  artifacts and upload manually via `uv pip install twine && twine
  upload dist/*` if needed.
- **`Version already exists`** — the tagged version was previously
  published. Bump the version and re-tag.
- **`Invalid metadata`** — hatchling produced an invalid sdist.
  Reproduce locally via `uv run python -m build` and inspect.

## Iterating on the workflow

For workflow changes, push to a branch first. The workflow only
triggers on tag push (`v*`), so feature-branch pushes don't trigger
a publish. To test the build path without publishing, you can:

1. Temporarily flip the `on:` trigger to include `pull_request`.
2. Push to a branch; the `build` job runs.
3. Inspect the uploaded `dist/` artifact.
4. Revert the `on:` change before merging.

Or, use TestPyPI: uncomment the `repository-url` line in the
workflow pointing at `https://test.pypi.org/legacy/`. You'll need a
separate Trusted Publisher configured at https://test.pypi.org for
this to succeed.

## Skipping a release

If a tag was pushed by accident, delete it before the workflow
finishes:

```sh
git push --delete origin vX.Y.Z   # remote
git tag -d vX.Y.Z                 # local
```

Cancel the in-progress workflow at the Actions tab. If the
`publish-to-pypi` job already ran, the version is on PyPI and you
must bump to the next version (PyPI doesn't allow re-uploads of the
same version, even after deletion).
