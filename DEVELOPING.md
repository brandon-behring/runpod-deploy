# Developing runpod-deploy

Local development reference for contributors who have already read
[`CONTRIBUTING.md`](CONTRIBUTING.md) for the PR-flow + scope-boundary
rules. This doc covers: environment setup, day-to-day commands,
golden-file workflow, debugging conventions, and release operations.

For coding standards (frozen dataclasses, stdlib exceptions,
`raise`-not-Result, etc.), the canonical doc is `CLAUDE.md` §1–§16.

---

## Environment setup

```sh
git clone https://github.com/brandon-behring/runpod-deploy.git   # (or fork URL)
cd runpod-deploy
uv venv
uv pip install -e ".[dev]"
# Optional: also install [completion] for shell tab-completion
uv pip install -e ".[dev,completion]"
```

Activate the venv as needed: `source .venv/bin/activate`.

### Pre-commit hooks (optional but recommended)

```sh
pre-commit install                          # commit-time hooks (ruff/black/yaml/toml)
pre-commit install --hook-type pre-push     # adds mypy at push time
```

The commit-time hooks run on every `git commit`; the push-time hooks
run on every `git push`. Both gates also run in CI (`.github/workflows/test.yml`),
so failing to install pre-commit just delays the feedback.

---

## Day-to-day commands

```sh
make lint              # ruff check + black --check + mypy strict
make format            # black + ruff check --fix
make test              # pytest (unit + smoke; skips `network`-marker)
make test-unit         # pytest -m unit
make test-smoke        # pytest -m smoke
make coverage          # pytest with coverage report
make ci                # lint + test + coverage (matches test.yml)
make doctest           # pytest --markdown-docs docs/ README.md examples/
                       # (when v0.7.6+; markdown doctest gate)
make build             # python -m build → dist/{sdist,wheel}
make audit-docstrings  # AST check: Raises: sections match raise sites
make examples-index    # regenerate examples/README.md per-dir bullets
make clean             # rm caches + dist + __pycache__
```

---

## Test markers

Each test is tagged with exactly one marker (configured in
`pyproject.toml` `[tool.pytest.ini_options]`):

| Marker | What it means | When it runs |
|---|---|---|
| `unit` | Pure contract tests (no subprocess, no SSH, no rsync) | Always |
| `smoke` | End-to-end `--offline-dry-run` lifecycle walk | Always |
| `network` | Live RunPod calls | Manual via `pytest -m network` |
| `golden` | Golden-file CLI snapshot tests | Always |

```sh
pytest -m unit -v
pytest -m smoke -v
pytest -m network -v        # opt-in; needs runpodctl + RunPod API key
pytest -m golden -v
```

---

## Golden-file workflow

The golden-file tests in `tests/test_cli_golden.py` lock CLI output
stability. Files live under `tests/fixtures/golden/*.txt`. When you
intentionally change a CLI's output format:

```sh
pytest tests/test_cli_golden.py --update-goldens
git diff tests/fixtures/golden/   # eyeball every line
git add tests/fixtures/golden/*.txt
```

Review the diff carefully — these files are the UX contract.
Accidentally regenerating them masks real regressions.

---

## Debugging

### Inspect what the orchestrator does without provisioning

`--offline-dry-run` walks the entire `run_job` lifecycle but never
calls `runpodctl`, SSH, or rsync. Every external command is logged
with its argv. Use this constantly when iterating on YAML configs.

```sh
runpod-deploy run --config examples/hello/hello.yaml --offline-dry-run
```

For DEBUG-level logging:

```sh
runpod-deploy run --verbose --config <yaml>
```

### Local CLI without `pip install`

```sh
.venv/bin/runpod-deploy --help            # uses local source via editable install
PYTHONPATH=src python -m runpod_deploy.cli --help    # alternative
```

### Subprocess mocks for provider/transport tests

`tests/conftest.py` provides `FakeSubprocess` and `FakePopen` fixtures.
Provider tests pre-stub the `_supported_pod_create_flags` cache via a
module-scope autouse fixture in `tests/test_provider_subprocess.py`;
mirror that pattern when adding tests that exercise `provision_pod`.

### Schema iteration

When changing a `*Spec` dataclass in `config.py`:

1. Update the dataclass + `__post_init__` validation.
2. Update the matching `_parse_*` in `_config_parsers.py` (add to
   `_check_keys` allowed set + extract value).
3. Update `docs/source/config-reference.md`.
4. Add a unit test in `tests/test_config.py`.
5. Add an integration test in `tests/test_orchestrator.py` for the
   use-site behavior (via `--offline-dry-run`).
6. Add a CHANGELOG entry.
7. If breaking, bump `SCHEMA_VERSION` + update
   `docs/source/migration-v3.md`.

### Lifecycle / cost-affecting changes — doc-code sync is a release blocker

The 2026-05-17 leak (76 stale pods, 3,930 GB, $26/day) was caused by
`docs/source/lifecycle.md` documenting behavior the code never
implemented — "Pod is terminated; bills for the runtime so far" was
false; `runpodctl pod stop` only paused. Doc-code drift on
cost-affecting paths is a silent operational hazard, not a
follow-up.

When changing the lifecycle path (`provider.cleanup_pod`, anything
that calls `runpodctl pod stop` / `pod delete`, the `lifecycle:` YAML
block, the per-run cleanup WARNING), update **in the same commit**:

1. `docs/source/lifecycle.md` — the three-action table in §7 and
   the "Cost discipline" §7b.
2. `docs/source/troubleshooting.md` — the "Cost / cleanup" section
   entries.
3. `docs/source/config-reference.md` — the `lifecycle:` block
   reference.
4. `CHANGELOG.md` — Added/Changed/Fixed/Deprecated entries with the
   cost impact spelled out.
5. The load-bearing regression tests in
   `tests/test_provider_subprocess.py`
   (`test_cleanup_pod_delete_calls_runpodctl_pod_delete_and_unlinks_state`,
   `test_cleanup_pod_stop_logs_actionable_cleanup_command_with_cost_estimate`)
   — these are designed to fail loudly if cleanup behavior or the
   operator-facing WARNING regresses.

`make docs` is run in CI as a strict build (`-W --keep-going`);
broken cross-references will block the merge.

---

## Release operations

See [`docs/release.md`](docs/release.md) for the canonical release
flow (Trusted Publishing, TestPyPI dry-run, tag-triggered workflow).

Short version:

```sh
# 1. Update version in 3 places (pyproject.toml, src/runpod_deploy/__init__.py)
# 2. Move CHANGELOG.md [Unreleased] → [X.Y.Z] with theme + date
# 3. Commit:
git commit -m "chore: bump to X.Y.Z — <theme>"
git push origin main
# 4. Tag + push (triggers release.yml):
git tag vX.Y.Z -m "vX.Y.Z — <theme>"
git push origin vX.Y.Z
# 5. Watch the workflow:
gh run watch
# 6. Once green, GitHub release page auto-exists from tag;
#    backfill notes via:
scripts/backfill_releases.sh vX.Y.Z
```

---

## What lives where

```
src/runpod_deploy/
  config.py           # frozen *Spec dataclasses (YAML schema)
  _config_parsers.py  # YAML → *Spec parsers
  orchestrator.py     # run_job — linear lifecycle (provision → stage → run → pull → manifest)
  provider.py         # runpodctl subprocess + GPU/DC selection
  transport.py        # SSH + rsync via subprocess
  cli.py              # argparse subcommand registry + handlers
  manifest.py         # write_pull_manifest (the v2 manifest schema)
  telemetry.py        # pod-side run instrumentation (events.jsonl, metrics.jsonl)
  forensics.py        # post-run manifest/events readers
  metadata.py         # local-side capture (git SHA, lockfile hash)
  pricing.py          # GraphQL pricing fetch + cache
  preflight.py        # validate-time checks (GPU availability, consumer pyproject scan)

tests/
  conftest.py         # FakeSubprocess + FakePopen + --update-goldens fixture
  test_<module>.py    # per-module unit tests
  test_cli_golden.py  # CLI output snapshot tests + tests/fixtures/golden/*.txt
  test_integration.py # composed v0.4+v0.5 feature smoke
  test_recipe_examples.py  # markdown-block schema validator

docs/                 # consumer-facing
  quickstart.md, lifecycle.md, config-reference.md, extending.md,
  troubleshooting.md, release.md, recipes/

examples/             # consumer-copyable configs
  hello/, smoke/, v0_5_canonical/, forensics/, ...

scripts/              # operational utilities (run rarely; not on the import path)
  backfill_releases.sh, regen_examples_index.py, audit_raises_sections.py
```

---

## See also

- [`CONTRIBUTING.md`](CONTRIBUTING.md) — PR flow + scope boundary.
- [`CLAUDE.md`](CLAUDE.md) — canonical operational standards.
- [`AGENTS.md`](AGENTS.md) — entry-point for non-Claude agents.
- [`docs/extending.md`](docs/extending.md) — public API reference.
