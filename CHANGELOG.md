# Changelog

This project follows Semantic Versioning.

## [Unreleased]

## [0.7.9] - 2026-05-16 — Per-module autodoc API reference (Sphinx Phase 2 of 3)

### Added

- **Per-module autodoc API reference**. Six new pages under
  `docs/source/api/` (one per module: `config`, `orchestrator`,
  `provider`, `pricing`, `transport`, `metadata`) plus an `api/index.md`
  overview. Each page uses Sphinx's `autosummary` + `autodoc` to render
  per-symbol stubs from each public function/class's docstring,
  including frozen-dataclass field tables and `__post_init__`-derived
  validation behavior. Stub pages live at
  `docs/source/api/generated/<module>/<symbol>.md` (gitignored;
  regenerated on every build). New "API reference" section in
  `docs/source/index.md` toctree.
- `{ref}` modindex (Python module index) added to the Indices section.

### Changed

- **CI `docs` job now runs a two-pass `sphinx-build`** to absorb
  autosummary's known first-build behavior (stub pages are written
  during pass 1; reference resolution happens during pass 2). Pass 2
  is the strict gate (`-W --keep-going`). `make docs` mirrors the same
  two-pass sequence locally.

## [0.7.8] - 2026-05-16 — Sphinx documentation infrastructure (Phase 1 of 3)

### Added

- **Sphinx documentation infrastructure** (Phase 1 of 3). Builds the
  existing markdown docs into a navigable Sphinx site using
  pydata-sphinx-theme + myst-nb. Run locally with `make docs` (one-shot)
  or `make docs-serve` (live-reload via sphinx-autobuild). All existing
  `docs/*.md`, `docs/recipes/*.md`, and `docs/adr/*.md` have been moved
  to `docs/source/` via `git mv` (history preserved). Per-module
  autodoc API pages follow in Phase 2; GitHub Pages deploy in Phase 3.
- **New `[docs]` optional-dependencies extra**: `sphinx>=7.3`,
  `pydata-sphinx-theme>=0.16`, `myst-nb>=1.1`, `linkify-it-py>=2.0`,
  `sphinx-copybutton>=0.5`, `sphinx-design>=0.6`,
  `sphinx-autodoc-typehints>=2.0`, `sphinx-autobuild>=2024.10.3`.
  Install via `uv pip install -e .[docs]`. `nb_execution_mode = "off"`
  — `jupyter-cache` is a transitive dep of myst-nb but unused since
  there are no executable cells.
- **`docs` CI job** in `.github/workflows/test.yml` runs
  `sphinx-build -b html -W --keep-going` on every PR (strict: warnings
  fail the build; `--keep-going` surfaces every warning in one log for
  faster fix-cycles).
- **`scripts/regen_examples_index.py`** now writes a second output,
  `docs/source/examples.md` (auto-generated standalone Sphinx page),
  alongside the existing `examples/README.md` (markered splice).
  Both files stay in sync from one data source; regenerate via
  `make examples-index`.

### Changed

- `make doctest` and the corresponding CI job now scan `docs/source/`
  (was: `docs/`) for fenced code blocks. `pytest-markdown-docs` skip
  pragmas (` ```python notest `) are preserved as-is.
- `README.md` Docs section links now point at `docs/source/*` paths.
  Docs badge + live URL deferred to Phase 3.

## [0.7.7] - 2026-05-15 — `--scan-consumer` false-positive triage (closes #76, #78, #79)

### Fixed

- **`--scan-consumer` no longer floods output with noise from rsync-excluded
  paths** (#76). `scan_staged_payloads_for_absolute_paths` now honors each
  staging entry's `RsyncPushSpec.effective_excludes` (defaults +
  `excludes` + `excludes_extra`) AND always skips a universal Python-noise
  set (`.venv/`, `.git/`, `.pytest_cache/`, `.ruff_cache/`, `.mypy_cache/`,
  `**/__pycache__/`, `**/*.pyc`) — even when the consumer hasn't set
  `excludes_default: true`. Concrete impact: post_transformers's scan
  output dropped from 3118 lines to the handful of real findings. New
  private helper `_path_matches_rsync_exclude` implements a small subset
  of rsync's filter semantics (trailing `/` for directory-only matches,
  `**/` for any-depth, embedded `/` for root-anchored prefix, basename
  match anywhere otherwise). No new runtime dependency.
- **Optional-dependencies scans now honor what the pod actually installs**
  (#78, #79). Warnings for `runpod-deploy` in
  `[project.optional-dependencies.<name>]` (previously misleading when
  the documented local-orchestration pattern uses a `cloud` extra) and
  for `torch` in any optional group (previously fired even when the
  pod's run-body installed only an unrelated extra) now only emit when
  the optional group's name is actually installed on the pod. The
  scanner parses every `setup[*].command` and `run.body` for
  `uv sync --extra <name>` (and `--all-extras`) invocations; when no
  `uv sync` is detected, optional-extras warnings are suppressed
  entirely (pre-built-image case: no signal that anything beyond
  `[project.dependencies]` reaches the pod). Both `--extra X` and
  `--extra=X` forms are recognized. The `runpod-deploy` warning message
  was also rewritten to call out the specific `--extra <name>` flag
  that installs it, instead of the previous flat "should not ship to
  the pod" wording. `[project.dependencies]` scanning is unchanged.

## [0.7.6] - 2026-05-15 — comparative-gap audit (argcomplete + CodeQL + AGENTS.md + doctest gate)

### Added

- **`pytest-markdown-docs` doctest gate** — fenced Python blocks in
  `docs/`, `README.md`, and `examples/` now execute under `pytest
  --markdown-docs`. New `make doctest` target + dedicated `doctest`
  CI job in `.github/workflows/test.yml` (parallel to `test` /
  `test-base-install` / `test-published-wheel` / `security`; hard-fail).
  Illustrative blocks that reference unrunnable consumer-side imports
  (`torch`, `transformers`) or use `...` placeholders are skipped via
  the plugin's ` ```python notest ` syntax; 5 files patched
  (`docs/extending.md`, three `docs/recipes/*.md`,
  `docs/troubleshooting.md`). The single live doctest currently is the
  JSON snippet in `docs/recipes/cost-reconciliation.md`. Guards against
  doc drift: a copy-paste from any unmarked Python block must literally
  execute.
- New `[project.optional-dependencies].dev` entry:
  `pytest-markdown-docs>=0.9`.
- **`AGENTS.md`** — discoverability shim for non-Claude agents
  (Cursor, Codex, Aider, Copilot Workspace, etc.). Per the emerging
  agents.md convention: ~80-line redirect pointing at `CLAUDE.md` for
  full operational standards, plus a quick-orientation summary of
  the SRP boundary, public-API entry points, key files, test
  invocations, and "what not to propose" callouts. Avoids forcing
  non-Claude agents to ingest the Claude-flavored `CLAUDE.md` in
  full.
- **`DEVELOPING.md`** — local-development reference split out from
  `CONTRIBUTING.md`. Covers environment setup, day-to-day commands,
  test markers, golden-file workflow, debugging conventions, schema
  iteration checklist, and release operations. CONTRIBUTING.md
  becomes the high-level PR-flow + scope-boundary doc (~5 lines
  pointer to DEVELOPING.md for the dev-side details). Separation
  matches modal-labs's pattern.

- **`scripts/regen_examples_index.py` + `make examples-index`** —
  auto-generate the "Per-directory contents" section of
  `examples/README.md` from each example's `README.md` H1 + first
  paragraph. Marker-comment-bracketed (`<!-- begin examples-index -->`
  / `<!-- end examples-index -->`) so the "By use case" table above
  stays human-maintained. Idempotent. Mirrors the SkyPilot pattern.
  Running on this baseline regenerated 8 example entries; 4 of them
  flagged as missing their `README.md` (legacy `examples/` dirs that
  predate the README-per-example convention). Future work: backfill
  those READMEs so the auto-index has consistent descriptions.

- **`argcomplete` shell completion** (opt-in via new `[completion]`
  extra). `pip install runpod-deploy[completion]` + a one-line `eval`
  in shell rc enables Bash/Zsh tab-completion of subcommands + flags.
  Implementation: `PYTHON_ARGCOMPLETE_OK` marker at the top of
  `src/runpod_deploy/cli.py` + a guarded `import argcomplete` block
  before `parser.parse_args`. The base package stays lean — no
  consumer pays the dep cost unless they want completion. Docs:
  README quickstart + CONTRIBUTING.md activation note.
- **`.github/workflows/codeql.yml`** — GitHub's static security
  scanner for Python. Triggers: push to main + pull_request +
  weekly cron (Mon 03:30 UTC, same cadence as dependabot).
  Complements the existing `pip-audit` job (which scans declared
  dependency CVEs) by analyzing our own source code for common
  vulnerability patterns. Query set: `security-and-quality`.
- **pepy.tech downloads badge** in `README.md` (alongside the
  existing 4 badges). Visible install-volume signal.
- **`mypy` pre-push hook** in `.pre-commit-config.yaml`. Local hook
  reusing `.venv/bin/python -m mypy src` for zero version drift with
  `make lint`. Stage: `pre-push` (commit cycles stay fast at
  ~0.1s; push-time gate adds ~1–3s before remote push). Activated
  via `pre-commit install --hook-type pre-push`.
- **`.github/CODEOWNERS`** — auto-review-request for every PR.
  Currently `* @brandon-behring` (solo maintainer); easy to extend
  if/when collaborators arrive.

## [0.7.5] - 2026-05-15 — post-publish polish (discoverability + hello example + wheel CI)

### Added

- **`examples/hello/`** — new "absolute minimum" example. Targets
  first-time consumers right after `pip install runpod-deploy` who
  want to verify the CLI works without registering an SSH key,
  creating a RunPod account, or installing `runpodctl`. Contains a
  20-line `hello.yaml` (smallest valid v2 schema) + a README with a
  30-second walkthrough + a phase-by-phase table of what
  `--offline-dry-run` exercises vs. mocks. Auto-validated by
  `tests/test_config.py::test_examples_are_schema_valid`.
- **`test-published-wheel` CI job** in `.github/workflows/test.yml`.
  Queries `https://pypi.org/pypi/runpod-deploy/json` for the
  latest-published version, installs from PyPI, smoke-imports the
  public API, runs `runpod-deploy --help`, and exercises the new
  `examples/hello/hello.yaml` via `validate` + `run --offline-dry-run`.
  Hard-gates merges; catches "publish succeeded but the wheel is
  broken" regressions. Targets the latest-published version (not the
  in-development `pyproject.toml` version) because version-bump
  commits introduce a version that's not on PyPI until AFTER the
  release workflow runs on the tag push; the in-development surface
  is covered by the existing `test-base-install` job via local source.

### Changed

- **`README.md` Quickstart**: now leads with `pip install runpod-deploy`
  (the published path) instead of `uv pip install -e ".[dev]"` (the
  editable-install path). Mentions the new `examples/hello/hello.yaml`
  for first-time verification. The editable-install + pre-commit setup
  flow moves to `CONTRIBUTING.md` (already there). New "Contributors:
  see CONTRIBUTING.md" pointer added.
- **`docs/quickstart.md`** §1: install step rewritten to lead with
  `pip install runpod-deploy`. §4: now mentions the bundled
  `examples/hello/hello.yaml` as the absolute-minimum walkthrough
  alongside the existing `examples/smoke/a4000_smoke.yaml`.
- **`examples/README.md`**: adds a "First-time, no RunPod account
  needed" row pointing at the new `hello/` example. Marks `hello/`
  as the first stop for new PyPI-installed consumers.

### Added

- **`pyproject.toml` `[project.urls]`**: adds Homepage, Source, Issues,
  Changelog, Documentation, Releases — all linking to the GitHub repo
  + relevant files. Renders in the PyPI sidebar and on
  `pip show runpod-deploy`. Previously the PyPI page had no outbound
  links at all (`home_page: None`, `project_urls: None`).
- **`README.md` badges**: PyPI version, CI status, supported Python
  versions, license. Visible-trust signal for first-time visitors;
  also surfaces "is the latest tag's CI passing?" without navigating
  to Actions.

## [0.7.4] - 2026-05-15 — CI hygiene: node24 actions + dependabot policy + test-isolation fix

### Changed

- **GitHub Actions bumped off Node.js 20** (deadline: 2026-06-02).
  - `actions/checkout`: v5 → v6 (via dependabot PR #60; merged in this cycle).
  - `actions/upload-artifact`: v4 → **v6** (hand-written, replacing dependabot PR #58 which targeted v7). v6 is the first version using `node24` in its `action.yml`.
  - `actions/download-artifact`: v4 → **v7** (hand-written, replacing dependabot PR #59 which targeted v8). v7 is the first version using `node24` in its `action.yml`.
  - Verified per-version via `gh api repos/actions/<action>/contents/action.yml?ref=<tag>`. The release workflow's run page should show **zero** Node.js 20 deprecation annotations after the upgrade.
- **`.github/dependabot.yml`**: added `ignore` rules for
  `version-update:semver-major` on `actions/checkout`,
  `actions/upload-artifact`, and `actions/download-artifact`. Dependabot
  still files minor + patch updates automatically (via the existing
  `actions-minor-patch` group); major bumps now require manual review.
  Encodes "manual review for release-pipeline-critical actions"
  permanently — these actions touch the publish path and majors can
  change behavior (e.g., download-artifact v5's by-ID path semantics)
  or runtime (node20 → node24).

### Fixed

- **`tests/test_provider_subprocess.py` isolation**: this file's tests
  depended on alphabetical test ordering to populate
  `provider._supported_pod_create_flags`'s function-level attribute
  cache via `tests/test_provider.py`. Running the file in isolation
  (`pytest tests/test_provider_subprocess.py`) failed because the
  cache-empty probe consumed the first enqueued `FakeResult`, breaking
  the FIFO contract in `tests/conftest.py::FakeSubprocess`. Added a
  module-scope `_stub_supported_flags_cache` autouse fixture that
  monkeypatches `provider._supported_pod_create_flags` to
  `lambda: frozenset()` for every test in the file. Mirrors the
  per-test pattern at `tests/test_provider.py:410`. Tests now pass
  identically in isolation and as part of `make ci`. Closes the
  known-issue noted in the v0.7.2 CHANGELOG.

## [0.7.3] - 2026-05-15 — hotfix CI gates from v0.7.2

### Fixed

- **`test-base-install` CI job**: the smoke-import block in
  `.github/workflows/test.yml` listed 7 symbols that were *not* in
  fact re-exported from `runpod_deploy/__init__.py`
  (`build_job_context`, `validate_local_paths`, `SecretSpec`,
  `SCHEMA_VERSION`, `STORAGE_NETWORK_VOLUME`, `STORAGE_EPHEMERAL`,
  `DEFAULT_STAGING_EXCLUDES`). Added all 7 to the package-level
  `from runpod_deploy.config import ...` block + the `__all__`
  manifest. Brings the actual re-export surface into agreement with
  what `docs/extending.md` §2 documents as the public API.
- **`security` CI job (`pip-audit`)**: `--disable-pip` is only valid
  with `--requirement <file>` (not with the default venv-audit
  invocation). Removed the flag; the job now runs `uv run pip-audit`
  which audits the resolved venv directly. Result on baseline
  v0.7.2: "No known vulnerabilities found" — green.

### Why this is a same-day hotfix

The v0.7.2 push triggered the test workflow which exposed both
issues. Three pending dependabot PRs (`actions/checkout` v5→v6,
`actions/upload-artifact` v4→v7, `actions/download-artifact` v4→v8)
were also failing on the same two errors; merging this hotfix on
main should auto-clear their CI runs since they rebase against
main.

## [0.7.2] - 2026-05-15 — governance hardening (ported from eval-toolkit + temporalcv)

### Added

- **`.github/PULL_REQUEST_TEMPLATE.md`** — auto-surfaced on every PR.
  Sections for Summary / Testing checklist / Risk level / Documentation
  updates / Linked issues. The Testing checklist includes a "golden
  files reviewed (`tests/fixtures/golden/*.txt`) — only intentional
  changes" line so reviewers don't miss UX-contract drift.
- **`.github/ISSUE_TEMPLATE/`** — three forms: `bug_report.yml`,
  `feature_request.yml`, `config.yml`. The bug form asks for the
  failing lifecycle phase (mapped to `docs/lifecycle.md` §1–8) so
  triage can route quickly. The feature form has an SRP-boundary
  checkbox referencing `docs/extending.md` §3 so out-of-scope
  proposals self-flag at submission. The config router disables
  blank issues + links to `SECURITY.md`, `docs/troubleshooting.md`,
  and `docs/recipes/README.md`.
- **`scripts/audit_raises_sections.py`** + `make audit-docstrings` —
  AST-based audit that walks `src/runpod_deploy/`, finds every
  function with a `Raises:` docstring section, and compares the
  documented exception types against actual `raise X(...)` sites
  in the function body. Reports stale entries (documented but
  never raised) and undeclared entries (raised but not in
  `Raises:`). Currently green: 13 files audited, all matches.
  Catches drift the moment someone adds a `Raises:` section in
  a future PR.
- **Pre-commit `check-added-large-files`** with a 500KB ceiling.
  Catches accidental commits of model weights, datasets, build
  artifacts. Bumpable via `--maxkb=N` if a legitimate large
  fixture is needed.

- **`.github/dependabot.yml`** — weekly grouped dependency updates
  for pip + github-actions ecosystems. Minor + patch updates batch
  into one PR per ecosystem (review-noise control); majors land
  individually for explicit review. Commit-message prefixes:
  `deps:` for pip, `ci:` for actions. Monday cadence so reviews
  surface top-of-week.
- **`SECURITY.md`** — vulnerability disclosure policy. Documents
  supported versions (0.7.x active, 0.6.x critical-only, ≤0.5.x
  unsupported), the disclosure path (email
  `brandon.m.behring@gmail.com`, expected 5-business-day response),
  in-scope vulnerability types (auth, RCE, secrets leakage, path
  traversal), out-of-scope deferrals (`runpodctl` itself, dependency
  CVEs handled by `pip-audit`, consumer code), and security-relevant
  features already in place (Trusted Publishing, secrets handling,
  gitleaks, pip-audit, no-asserts policy).
- **`pip-audit` CI job** (`.github/workflows/test.yml`) — runs
  `pip-audit --disable-pip` against the resolved dev dependency set
  on every push / PR. Advisory mode (no `--strict`); surfaces CVEs
  in the run log + dependabot handles the actual upgrades.
- **`test-base-install` CI job** (`.github/workflows/test.yml`) —
  installs the package with NO extras (`uv pip install .`), then
  smoke-imports every symbol from the public re-export surface
  (`load_job_spec`, `build_job_context`, `run_job`,
  `validate_local_paths`, `JobContext`, `RunpodJobSpec`, `PodSpec`,
  `StorageSpec`, `RsyncPushSpec`, `ArtifactPullSpec`, `SecretSpec`,
  `SCHEMA_VERSION`, `STORAGE_NETWORK_VOLUME`, `STORAGE_EPHEMERAL`,
  `DEFAULT_STAGING_EXCLUDES`) + invokes `runpod-deploy --help`,
  `runpod-deploy run --help`, `runpod-deploy events-query --help`.
  Guards against a future PR accidentally adding `import pytest`
  (or any other dev-extra dep) to `src/runpod_deploy/` and breaking
  consumers who didn't opt into `[dev]`.
- **Ruff `ARG` rule** in `pyproject.toml` `[tool.ruff.lint]`. Catches
  unused function arguments. Surfaces dead-arg code as it appears;
  per-file ignores configured for `tests/**/*.py` (ARG001/002) since
  pytest's autouse + monkeypatch + fixture-injection patterns
  legitimately produce arguments that look unused at static-analysis
  time.

### Removed

- **Dead `ctx: JobContext` argument** from
  `provider._wait_for_pod_ready(pod_id, ctx, *, gpu_id)`. Surfaced
  by the new `ARG` ruff rule. Private helper — no public-API impact.
  Three call sites in `tests/test_provider_subprocess.py` updated
  along with the orchestrator call in `provider.provision_pod`.

### Known issue (pre-existing; not introduced here)

- `tests/test_provider_subprocess.py::test_provision_pod_writes_state_file_and_returns_connection`
  passes when the full suite runs (alphabetical test ordering puts
  `test_provider.py` first, which monkeypatches the
  `_supported_pod_create_flags` cache). In isolation
  (`pytest tests/test_provider_subprocess.py`) it fails because the
  flag-detection probe consumes the first FakeResult from the FIFO
  queue. The bug is latent in `make ci` (the cache populates as a
  side effect of earlier tests) and doesn't affect production
  behavior. A future PR should add a `_supported_pod_create_flags._cached`
  reset/populate fixture to `tests/test_provider_subprocess.py`'s
  module-scope to make the file isolation-safe. Filed as a follow-up.

## [0.7.1] - 2026-05-15 — post-audit cleanup + PyPI publishing workflow

### Added

- **`.github/workflows/release.yml`** — new tag-triggered release
  workflow. On `git push origin v*`, builds the sdist + wheel via
  `python -m build` (hatchling backend) and publishes to PyPI via
  **Trusted Publishing** (OIDC; no API tokens in repo secrets).
  Two-job structure: `build` produces and uploads the artifacts
  (always succeeds), `publish-to-pypi` consumes them via
  `pypa/gh-action-pypi-publish@release/v1` (fails gracefully with
  a clear "trusted publisher not configured" error until the
  PyPI-side setup is done).
- **`docs/release.md`** — new release-process doc covering the
  one-time PyPI Trusted Publishing setup (pending publisher
  registration), cutting a release, failure modes, workflow
  iteration patterns (TestPyPI, branch-test trigger), and the
  "I accidentally pushed a tag" recovery flow.
- **`Makefile`** gains a `build` target wrapping
  `python -m build` so consumers can verify the release-workflow
  build path locally without committing.

- **`examples/README.md`** — new index for the `examples/` tree. Lists
  each example by use case + per-directory contents + the standard
  "how to use an example" recipe (copy → edit → validate → dry-run →
  live). Mirrors the pattern of `docs/recipes/README.md`.
- **`CONTRIBUTING.md`** — new top-level contributor entry-point.
  GitHub auto-surfaces this on PR pages. Short doc pointing at
  `docs/extending.md` §3 for the detailed checklists + the SRP-boundary
  rationale, plus the canonical fork→branch→PR→CI flow.
- **`--dry-run` vs `--offline-dry-run`** distinction now documented in
  both `docs/lifecycle.md` and `docs/config-reference.md` with a
  comparison table. Closes the long-standing gap where the two flags
  existed in argparse but were never explained side-by-side.

### Removed

- Dead `import json` + `_ = json` workaround line in
  `tests/test_integration.py`. The defensive add was stale; no
  `json.*` is referenced in the file body.

## [0.7.0] - 2026-05-15 — edge-case rigor + integration + golden-file contracts

### Added

- **`tests/test_cli_golden.py` + `tests/fixtures/golden/*.txt`** — new
  golden-file snapshot tests locking CLI output stability across 7
  subcommands: `manifest-summary` (single + `--root`), `events-query`
  (default table + `--json`), `ls-runs`, `compare-runs`, `events`.
  Each test invokes the CLI with a deterministic fixture, normalizes
  tmp-path placeholders to `<TMP>` and timestamp leaves to `<TS>`,
  and compares stdout against a checked-in `.txt` golden file. New
  `golden` pytest marker registered. Update mode via
  `pytest tests/test_cli_golden.py --update-goldens` regenerates the
  fixtures; the workflow + safety guidance is documented in
  `docs/extending.md`. Each golden is small (~5–25 lines), diff-friendly
  for review. Catches accidental output-format drift — e.g., a
  refactor of `_format_manifest_summary` that adds/removes a field
  would surface as a golden-file mismatch with a clear regenerate
  pointer.

- **`tests/conftest.py`** — adds the `--update-goldens` pytest option +
  matching `update_goldens` fixture used by `test_cli_golden.py`.

- **`pyproject.toml`** — registers the new `golden` pytest marker
  alongside `unit` / `smoke` / `network`.

- **`tests/test_recipe_examples.py`** — new doc-drift catcher. Walks
  every Markdown file under `docs/`, extracts every ```yaml fenced
  block, and feeds the ones that look like full job configs
  (`schema_version:` at column 0) into `load_job_spec`. Snippets
  (no `schema_version:`) are skipped — they're partial and can't be
  validated without context. Catches the failure mode where a doc
  example silently rots when the schema evolves. 15 parametrized
  tests collected at session start; in v0.7.0, 3 are full configs
  that parse (the annotated minimal in `config-reference.md` and
  the quickstart's example YAML) and 12 are correctly-skipped
  snippets. A deliberately-broken full config in a doc would surface
  with the recipe path + block index + YAML body in the failure
  output.

- **5 new integration tests** in `tests/test_integration.py` exercising
  the full `run_job` lifecycle via `--offline-dry-run`. Catches
  *cross-feature* regressions that per-PR unit tests miss:
  - **I1** — Composed v0.4+v0.5 features in one config: `--var` +
    rendered `name`/`run_id_prefix` + `--print-run-dir` + rendered
    `run.script_path`/`log_path` + `staging.excludes_default` +
    `excludes_extra` + `pod.python_version` auto-inject. Asserts
    every feature's signature in the log/stdout.
  - **I2** — Minimum-viable config (empty setup/staging/preflight/
    artifacts): catches regressions where a feature assumes a
    non-empty list.
  - **I3** — Max-coverage config: every optional field set to a
    non-default; schema-surface smoke test.
  - **`print_run_dir` layout invariant** — RUN_DIR path lives under
    `<project_root>/artifacts/runpod/`. Locks the path-resolution
    contract that all CLIs + drivers depend on.
  - **Module-import sanity** — the integration suite imports cleanly
    without side effects.
  All marked `@pytest.mark.smoke` (runs in default `make test`).

- **8 named-gap regression tests** for edge cases not previously
  exercised across the v0.4 + v0.5 surface:
  - **T1**: `--print-run-dir` line emits on stdout even when `--quiet`
    suppresses logger INFO (uses `sys.stdout.write` directly).
  - **T2**: `provider._build_pod_create_argv` passes the *rendered*
    `ctx.run_id` to `runpodctl pod create --name` — regression at the
    use site for v0.4 PR-C. Without this test, a refactor at
    provider.py:285 could silently un-wire the v0.4 fix.
  - **T3**: `events-query --filter KEY=VALUE` matches numeric event
    fields via `str()` coercion (locks the string-cast comparison
    semantics).
  - **T4**: `events-query` skips malformed lines in `events.jsonl`
    with WARNING; well-formed rows in the same file still emit.
  - **T5**: `events-query --since` drops events with missing or
    unparseable `ts_utc` (rather than treating them as "always in
    window").
  - **T6**: `manifest-summary --root` skips manifests that fail to
    parse with WARNING; well-formed manifests still appear in the
    output and TOTALS reflects only parsed stats.
  - **T7**: `pod.python_version` set + empty `staging` falls back to
    `$HOME` as the pin-target directory without crashing.
  - **T8**: `pod.python_version` validation runs in `__post_init__`
    (pre-render); a YAML with `python_version: "{py_ver}"` is
    rejected at parse time.

## [0.6.0] - 2026-05-15 — consumer-onboarding + reference depth

### Added

- **`examples/v0_5_canonical/canonical_sweep_pinned.yaml`** + companion
  README — realistic sweep config exercising every v0.4 + v0.5 feature
  in one place: rendered `name`/`run_id_prefix` template fields,
  `pod.python_version` interpreter pinning, `staging.excludes_default`
  + `excludes_extra` merge semantics, `run.script_path`/`log_path`/
  `success_marker` template rendering (v0.3.3), multi-DC failover.
  Companion README maps each v0.4/v0.5 field to its CHANGELOG entry +
  doc. Auto-validated by `tests/test_config.py::test_examples_are_schema_valid`.
- **`examples/smoke/a4000_smoke_pinned.yaml`** — drop-in upgrade of
  the existing smoke example demonstrating `python_version` +
  `excludes_default` minimally. Cheap (~$0.05–0.20 on RTX A4000) so
  consumers can exercise v0.5 end-to-end without a paper-grade
  workflow.
- **`examples/forensics/`** — three shell scripts + a README
  cataloging the most common post-run queries:
  `cost_reconciliation_one_sweep.sh` (manifest-summary --root with
  TOTALS), `find_killed_pods.sh` (events-query for
  `pod_killed_unexpected`), `dc_failover_audit.sh` (events-query for
  `datacenter_failover`). Pre-built starting points for consumers
  building their own forensic pipelines.

### Added

- **`docs/recipes/*.md`** all gain a `## See also` section pointing
  at related recipes. Each recipe was previously self-contained;
  consumers now have explicit composition pointers (e.g.,
  `multi-config-sweep` → `cost-reconciliation` + `predictions-only-eval`
  + `reproducibility` + `embed-deploy-metadata`).
- **`docs/recipes/README.md`** gains a "By use case" cross-cut table
  mapping common workflows ("Hyperparameter sweep over seeds",
  "Paper-grade canonical eval", "Save money on big sweeps",
  "Portability across GPU classes", "Post-mortem a failed sweep",
  "Stitch deploy provenance into your own evals manifest",
  "First-time consumer setup") to the 2–4 recipes worth reading
  together for that goal.

### Added

- **`MIGRATION.md`** expanded with a schema-versioning policy
  preamble (additive-vs-bump criteria) and a summary of every
  additive change since `schema_version: 2` (the v0.3.x runtime
  additions, v0.4 YAML field additions for staging + name/prefix
  rendering, v0.4 CLI additions for `--print-run-dir`, v0.5 YAML
  additions for `pod.python_version`, v0.5 CLI additions for
  `events-query` + `manifest-summary --root`). Closes with a "When
  we will bump SCHEMA_VERSION" rubric distinguishing changes that
  warrant a bump (type changes, removal, semantic shifts on
  existing fields) from those that don't (additive optional fields,
  internal-only behavior, new CLI surface).
- **`docs/extending.md`** rewritten from a 23-line stub into a
  three-audience guide: consumers (no-fork CLI/YAML patterns),
  library users (`from runpod_deploy import ...` API surface +
  the don'ts), contributors (SRP boundary, recipe/schema/CLI
  contribution checklists, coding standards summary, golden-file
  update workflow).
- **`docs/config-reference.md`** expanded with an annotated minimal
  config showing every required section + the most common optional
  fields, plus a template-variables explainer (built-ins table,
  custom-variable declaration patterns, CLI `--var` semantics, the
  two-pass rendering chain).

### Added

- **`docs/troubleshooting.md`** — new ~400-line catalog of known
  failure modes organized by lifecycle phase. Consolidates the prior
  `runpod-gotchas.md` content with every CHANGELOG-distilled issue
  from the v0.1.x → v0.5.x cycle (runpodctl flag mismatches, GPU
  stock-out + name validation, SSH key sync nuance, network-volume
  DC pinning, CUDA wheel pinning, rsync-missing-in-base-image,
  secrets-on-ephemeral-storage, flash_attention_2 portability,
  pod_killed_unexpected detection, sweep-driver pitfalls,
  predictions-discipline). Each entry: Symptom → Diagnosis → Fix.
  Includes a "Forensic recovery" section pointing at `events-query`,
  `manifest-summary --root`, `compare-runs`, `ls-runs`, `events`.
  Designed to be the first stop when something breaks.

- **`docs/runpod-gotchas.md`** — converted to a one-page redirect
  pointing at `docs/troubleshooting.md`. Preserves any inbound links
  while consolidating the content.

### Added

- **`docs/lifecycle.md`** — new ~260-line walkthrough of the
  `runpod-deploy run` pipeline, phase by phase: validate → provision →
  SSH wait → setup → stage + secrets + preflight + launch + monitor →
  artifact pull → stop → manifest write. Maps every YAML section to
  its phase + function, documents where v0.4 (`--print-run-dir`,
  `excludes_default`/`excludes_extra`, rendered `name`/`run_id_prefix`)
  and v0.5 (`pod.python_version` auto-injection, `events-query`,
  `manifest-summary --root`) features slot in, plus the failure-flow
  semantics (run_started gating, manifest-always-writes-in-finally).
  Replaces the implicit "read the orchestrator source to understand
  the lifecycle" tax that previously existed.
- **`docs/quickstart.md`** — new ~180-line consumer onboarding doc.
  5-minute walkthrough from `git clone` through prerequisites → install →
  read the example YAML → `validate` → `--offline-dry-run` → live
  RTX A4000 run → forensic inspection. Heavier than the README's
  Quickstart block; intended as the first stop for new consumers.
- **`README.md`** — pointer added linking to `docs/quickstart.md` and
  `docs/lifecycle.md` so new readers find the deeper onboarding path.

## [0.5.0] - 2026-05-15 — forensics + reproducibility (post-V5 backlog completion)

### Added

- **`pod.python_version`** new optional YAML field. When set to a
  string matching `3.MINOR` or `3.MINOR.PATCH` (e.g. `"3.13"` or
  `"3.13.5"`; pre-release suffixes intentionally rejected for
  reproducibility), the orchestrator auto-injects a preflight step
  that runs
  `uv python install <ver> && cd <first-staging-destination> && uv python pin <ver>`.
  Installs the requested CPython interpreter (uv-managed cache, ~30s
  amortized first-pod cost) AND writes `.python-version` into the
  staged project dir so the user's `uv sync` honors the pin.

  Closes the reproducibility footgun where `requires-python = ">=3.13"`
  in pyproject could silently resolve to 3.14 next month, undermining
  the "git SHA + uv.lock = reproducible" claim.

  **Implementation note**: the auto-injection lands at `preflight[0]`
  (NOT `setup[0]`), because setup runs before staging — the
  `.python-version` file must land in the staged project dir, which
  doesn't exist until after `_push_workspace`. This is a slight
  deviation from the initial sketch but is the correctness-preserving
  placement (pin file survives rsync `--delete` because staging is
  already done).

  **Failure mode**: a non-zero exit from the install or pin aborts the
  run before user `preflight` or run-body executes (per
  `check=True` on `ssh_exec`). Surfaces a fixable config issue
  cheaply (~30s of pod time) instead of letting a later `uv sync`
  silently fall back to the base-image interpreter.

  New helper `orchestrator._build_python_pin_preflight(spec)` returns
  an empty tuple when `python_version` is unset (existing YAMLs
  unaffected). 12 new tests in `tests/test_config.py` cover valid
  format acceptance (parametrized over `3.13`, `3.13.5`, `3.14`,
  `3.12.10`) and rejection of malformed/pre-release values; 2 new
  smoke tests in `tests/test_orchestrator.py` assert the injected
  command shape (install + cd + pin) and the no-injection default.
  Schema is additive optional; **no `SCHEMA_VERSION` bump** per
  CLAUDE.md §5. New recipe `docs/recipes/reproducibility.md` +
  `docs/config-reference.md` entry. Closes #24.

- **`runpod-deploy events-query`** new subcommand. Aggregates
  `events.jsonl` rows across every run directory under `--root DIR`
  (defaults to `artifacts/runpod`), optionally filtered by
  `--filter KEY=VALUE` (repeatable, AND-semantics, exact-string match
  on any event field) and/or `--since DURATION` (short-form duration:
  `30s`, `5m`, `1h`, `7d`; events with unparseable `ts_utc` are dropped
  when `--since` is set). Default output is a compact human-readable
  table per event: `[ts_utc] <run_dir_leaf> <event> k=v k=v ...`.
  `--json` opts into JSONL (one row per event with an added `run_dir`
  field). Replaces the prior `grep -q '"event": "pod_killed_unexpected"'
  artifacts/runpod/*/events.jsonl` shell workaround documented in
  several recipes; designed for post-sweep forensic analysis ("which
  DCs failed over most often this month?"). 21 new tests in
  `tests/test_cli_events_query.py` cover the duration / filter parse
  helpers and the end-to-end aggregation, multi-filter AND-semantics,
  --since window, --json JSONL emission, multi-run-dir rglob walk,
  missing-dir fail-fast, and empty/no-match info-log behavior. Two new
  pure helpers exposed for tests: `_parse_duration` and
  `_parse_filter_arg`. Closes #20.

- **`runpod-deploy manifest-summary --root DIR`** mode. The
  `manifest-summary` subcommand gains an optional `--root DIR` argument
  that walks the directory recursively for every
  `runpod_deploy_pull_manifest.json`, prints a per-run summary block
  for each, and finishes with a `== TOTALS ==` footer (manifest count,
  failure count, summed `wall_time_sec`, summed `estimated_cost_usd`).
  The positional `manifest` arg becomes optional and is mutually
  exclusive with `--root`. Composes with the v0.3.0 multi-shard sweep
  output (`artifacts/runpod/<ts>/runpod_deploy_pull_manifest.json`) for
  one-shot cost reconciliation across a sweep:
  `runpod-deploy manifest-summary --root artifacts/runpod`. 6 new
  tests in `tests/test_cli_manifest_summary.py` cover the aggregated
  TOTALS output, the mutually-exclusive arg policy, the missing-dir
  fail-fast, and the empty-dir info-log. Closes #21.

- **`docs/recipes/predictions-only-eval.md`** — new recipe documenting
  the architectural pattern where the GPU pod emits ONLY
  `predictions_full.parquet` + adapters and all metrics / bootstrap CIs
  / paired tests run locally on CPU. Decouples GPU billing cost from
  evaluation cost; bootstrap N=10K–100K becomes ~seconds on a beefy
  local box instead of minutes of billed GPU time per shard. Includes
  a small `test_pod_contract.py` lint pattern consumers can adopt to
  prevent CPU-on-pod regressions. References `prompt-injection-v5`'s
  `configs/runpod/v5_canonical_combined.yaml` as the working
  reference. Closes #22.
- **`docs/recipes/flash-attention-fallback.md`** — new recipe with the
  try/except snippet transformer scorers should use to degrade
  gracefully when the runpod-deploy GPU-failover pool lands the shard
  on a GPU class that doesn't support `flash_attention_2`. Eliminates
  the "works on H100, breaks on A6000" failure mode for `pod.gpu_order`
  lists that span GPU generations. Closes #23.
- **`docs/recipes/README.md`** — index updated with the two new
  recipes.

## [0.4.0] - 2026-05-15 — sweep-recipe correctness + render parity

### Added

- **`staging[*].excludes_default` and `staging[*].excludes_extra`** —
  two new optional YAML keys on each rsync-push entry. Set
  `excludes_default: true` to prepend the hygiene preset
  (`DEFAULT_STAGING_EXCLUDES`: `.git/`, `.venv/`, `.pytest_cache/`,
  `.ruff_cache/`, `.mypy_cache/`, `**/__pycache__/`, `**/*.pyc`) to
  the rsync `--exclude` list. `excludes_extra` is appended after for
  project-specific add-ons (`evals/`, `artifacts/`, `data/`, ...).
  Effective list = defaults (if opted in) + `excludes` + `excludes_extra`.
  Existing YAMLs are unaffected: `excludes_default` defaults to false
  and `excludes_extra` defaults to empty, so the only behavior change
  for pre-existing configs is the addition of `excludes_extra` as a
  recognized key — no schema-version bump required since the field
  is additive and optional. New `RsyncPushSpec.effective_excludes`
  property centralizes the merge logic; `orchestrator._push_workspace`
  uses it. 6 new tests in `tests/test_config.py` cover back-compat,
  defaults-only, defaults+explicit+extras (documented merge order),
  extras-without-defaults, unknown-key strictness, and the contents
  of `DEFAULT_STAGING_EXCLUDES` itself (hygiene-only contract). Doc
  added to `docs/config-reference.md`. Closes #25.

### Fixed

- **`name` and `run_id_prefix` top-level YAML fields now get
  template-variable expansion.** v0.3.3 closed the parity gap for the
  four `run.*` path / marker fields but left these two raw — so a
  YAML with ``name: demo-{seed}`` produced a pod named literally
  `demo-{seed}` (the literal substring survived through
  ``ctx.run_id`` into `runpodctl pod create --name <run_id>` at
  `provider.py:285` and into the manifest). `build_job_context` now
  runs a second-pass render of `spec.name` and `spec.run_id_prefix`
  against the fully-merged variables dict (built-ins + YAML
  `variables:` + CLI `--var`), then updates `variables["job_name"]`
  and `variables["run_id"]` with the rendered values. `spec.name` and
  `spec.run_id_prefix` stay raw on the frozen dataclass (parse
  preserved); the rendered values flow through `ctx.run_id` /
  `ctx.variables`. 2 new regression tests in `tests/test_var_flag.py`
  cover the explicit-prefix case and the `run_id_prefix → name`
  default-inheritance case. Closes #18. Surfaced by
  `prompt-injection-v5` driver work; cosmetic-only (runpodctl accepts
  the literal `{seed}` in pod names) but the inconsistency surprised
  driver authors writing templated YAMLs.

### Added

- **`runpod-deploy run --print-run-dir`** flag. When set, emits a
  single grep-friendly `RUN_DIR=<absolute-path>` line on stdout
  immediately after the run-directory path is resolved (before any
  pod-provisioning). Intended for parallel-sweep drivers that need a
  machine-parseable handle to this attempt's run dir without racing
  `ls -td artifacts/runpod/*` (the prior workaround documented in
  `docs/recipes/multi-config-sweep.md`). Off by default; existing
  consumers parsing stdout are unaffected. `run_job(..., print_run_dir=
  bool)` is the library-level entry. 2 new smoke tests in
  `tests/test_orchestrator.py` cover the flag-on (exactly one line on
  stdout, none on stderr) and flag-absent (no line anywhere) contracts.
  Closes #15 (root-cause portion).

### Fixed

- **`docs/recipes/multi-config-sweep.md`** rewritten with correct
  bounded-concurrency bash pattern. Three pitfalls now explicitly
  called out and addressed in the example: (1) `set -o pipefail` is
  mandatory when piping driver output through `tee` (without it, a
  driver that dies mid-script returns `tee`'s success code and looks
  successful); (2) `wait -n` inside the semaphore loop must be wrapped
  `2>/dev/null || true` to keep `set -e` from killing the driver on the
  first shard failure; (3) `ls -td artifacts/runpod/* | head -1` races
  against in-flight sibling shards at `MAX_PARALLEL > 1` and silently
  misclassifies failure modes — capture the run-dir via per-attempt
  `tee` of `runpod-deploy run --print-run-dir` (added in this release)
  instead. Closes #14 (doc portion), #15 (doc portion), #19. Surfaced
  by `prompt-injection-v5` v0.4 sweep work.



### Fixed

- **`run.script_path` / `run.log_path` / `run.success_marker` /
  `run.failure_markers` now get template-variable expansion.** Previously
  these fields were stored raw and used literally in `orchestrator.py`,
  so a `{seed}` / `{backbone}` placeholder survived as a literal
  substring in pod-side ssh commands and the polling marker — breaking
  multi-shard sweeps that try to disambiguate per-pod script/log paths
  via `--var seed=N`. `MIGRATION.md` had promised template support for
  `run.script_path` and `run.log_path` since v0.2.0 but the wiring was
  missing.

  Fix: render through `ctx.render(...)` at every use site in
  `orchestrator._launch_remote_job` (4 sites: rm-log, ssh-detached
  bash-exec, test-f, success marker), `_monitor_remote_log` (polling
  log line), `_pull_remote_log` (rsync target), and `_log_status_command`
  (grep markers). `run.body` was already rendered; this brings the other
  4 fields into parity.

  1 new regression test (`tests/test_var_flag.py::test_run_path_fields_
  render_cli_variables`) that loads a YAML with `{seed}` in all four
  fields, parses (asserts raw storage), then `ctx.render(...)` expands
  the CLI `--var seed=42` correctly.

  Surfaced by `prompt-injection-v5` v0.2 sweep work: the canonical
  YAML uses `run.script_path: /workspace/run-s{seed}.sh` so parallel
  pods write to disjoint paths. Without this fix, the literal
  `s{seed}` ended up in the pod-side ssh command and the runpod-deploy
  monitor never matched the rendered success marker against the
  rendered log.

  221 tests pass; mypy --strict clean.

## [0.3.2] - 2026-05-14 — runpodctl flag feature-detection

### Fixed

- **`runpodctl` flag feature-detection (closes phantom-flag emission
  bug).** Previously, when a YAML config set `pod.spot: true`,
  `pod.min_vcpu_count`, or `pod.min_memory_gb`, `provider._build_pod_create_argv`
  unconditionally emitted `--spot` / `--min-vcpu-count` / `--min-memory-in-gb`
  flags to `runpodctl pod create`. **None of those flags exist in upstream
  `runpodctl` v2.3.0** (the latest), so any pod-create call with those YAML
  keys set would fail with `{"error":"unknown flag: --min-vcpu-count"}` and
  print the `runpodctl pod create --help` text to stderr.

  Fix: `provider._supported_pod_create_flags()` probes `runpodctl pod
  create --help` once per process, parses the long-form flags, and gates
  emission accordingly. Unsupported flags are now SKIPPED with a clear
  WARNING (`runpodctl pod create does not support --<flag> in the
  locally-installed version; skipping ...`) so the operator can see
  the limitation without the deploy aborting.

  Probe failures (runpodctl missing, --help format change, timeout) are
  treated permissively (empty supported-set → all flags emitted),
  matching pre-v0.3.2 behavior so existing pipelines don't regress on
  unusual hosts.

  3 new tests in `tests/test_provider.py` cover the gated-on / gated-off /
  empty-probe-permissive branches plus a smoke probe against the real
  installed `runpodctl`. The pre-existing
  `test_pod_create_emits_spot_and_min_resources_when_set` was renamed to
  `..._when_supported` and gained a `monkeypatch` of the flag-detection
  helper so it tests the intended contract independent of host runpodctl.

  Surfaced by `prompt-injection-v5` v0.1.0 smoke run on RTX 2000 Ada @
  EU-RO-1: the smoke YAML's `min_vcpu_count: 4` / `min_memory_gb: 16`
  blocked the first invocation; this fix prevents the failure from
  recurring once those keys land in any consumer config.

## [0.3.1] - 2026-05-14 — CLI template variables

### Added — CLI template variables (`--var` + `--vars-file`)

- **`runpod-deploy run --var KEY=VALUE`** (repeatable). Sets a template
  variable for `{KEY}` expansion in any string field of the YAML config
  (`run.body`, `staging.destination`, `secrets.destination`, …). KEY
  must be a valid Python identifier (letters/digits/underscore, not
  starting with a digit); VALUE may be any string, including empty.
  Overrides the YAML `variables:` block on collision.
- **`runpod-deploy run --vars-file PATH`**. JSON object of
  `{KEY: VALUE}` template variables (all string values). Merged with
  `--var` (CLI `--var` wins on collision). Same KEY validation as
  `--var`.
- **`build_job_context(spec, config_path, *, cli_variables=None, ...)`**
  gains the `cli_variables` keyword arg. Values render against the
  built-in variables (`project_root`, `run_id`, …) and any earlier
  YAML / CLI variables, so `--var out_dir={project_root}/seed42`
  expands as expected. Unbound `{name}` references raise `KeyError`
  with the offending variable name.
- **`run_job(..., cli_variables=None)`** passes through to
  `build_job_context`.
- 24 new unit tests in `tests/test_var_flag.py` cover the parse
  helpers (`_parse_var_arg`, `_load_vars_file`, `_merge_cli_variables`)
  and the `build_job_context` plumbing (no vars / YAML override /
  built-in references / chained YAML→CLI references / unbound surface).
  217 tests pass; coverage clean.

**Use case**: parallel multi-seed sweeps in consumer repos (e.g.,
`prompt-injection-v5`) drive one `runpod-deploy run` invocation per
shard with a single shared YAML template:

```sh
runpod-deploy run --config configs/runpod/v5_canonical.yaml \
  --var seed=42 --var backbone=deberta
runpod-deploy run --config configs/runpod/v5_canonical.yaml \
  --var seed=43 --var backbone=deberta
```

Subsumes the prior `multi-config-sweep.md` recipe pattern of N
hand-written near-duplicate YAMLs.

## [0.3.0] - 2026-05-14

### Added (v0.3.0 — pricing intelligence + forensic navigation)

Closes the v0.2.0 deferral on cost intelligence and adds the
"data → answers" tooling for the telemetry v0.2.0 captures.

**Pricing (theme A):**
- New `src/runpod_deploy/pricing.py` — stdlib `urllib.request` POST
  to `https://api.runpod.io/graphql` (auth: `Authorization: Bearer
  $RUNPOD_API_KEY`) for the `gpuTypes` query. On-disk cache at
  `~/.cache/runpod-deploy/prices.json` with a 1-hour TTL — survives
  between CLI invocations.
- `GpuPrice` frozen slotted dataclass with `secure_price`,
  `community_price`, `secure_spot_price`, `community_spot_price`,
  `lowest_price`. `select_price_for_pod(prices, *, gpu_id, cloud_type,
  spot)` helper picks the field given `pod.cloud_type` and `pod.spot`.
- `provider.select_gpu_across_datacenters` gains
  `prices: Mapping[str, float] | None` and `max_gpu_price_usd: float
  | None` params. GPUs above the ceiling are skipped via the existing
  `on_failover` callback (per-GPU event reason
  `"'<gpu>' price $X.XX/hr > $Y.YY/hr cap"`). GPUs missing from the
  prices map are NOT skipped — absent price is "unknown, allow."
- New `runpod-deploy gpu-prices [--cloud-type SECURE|COMMUNITY]
  [--spot] [--no-price-cache]` — sortable price table; exit 1 when
  no prices come back (auth/network gate).
- `gpu-list` gains a `$/hr` column when prices are available; new
  `--cloud-type` / `--spot` / `--no-prices` flags. Falls back to the
  v0.2.x stock-only table when prices unavailable.
- `run` gains `--max-gpu-price <float>`. When set, orchestrator
  fetches prices, builds the per-GPU price map for `pod.gpu_order`
  via `select_price_for_pod`, and threads through to
  `select_gpu_across_datacenters`.
- New `runpod-deploy estimate <config>` — walks the GPU/DC selection
  exactly as `run` would (live `runpodctl datacenter list` + GraphQL
  prices) and prints the predicted spend at `budget.timeout_sec` plus
  the implicit timeout from `cost_cap_usd / price`. Falls back to
  `budget.assumed_hourly_rate_usd` when prices unavailable.

**Forensic navigation (theme B1–B3):**
- New `src/runpod_deploy/forensics.py` — read-only helpers:
  `walk_run_dirs(project_root)`, `load_manifest(path)` (handles v1
  + v2; accepts file or dir), `load_events(run_dir)` (parses
  events.jsonl line-by-line, skipping malformed lines with WARNING).
- New `runpod-deploy ls-runs [--project-root .] [--limit N] [--json]`
  — sortable table of past runs from
  `<root>/artifacts/runpod/*/runpod_deploy_pull_manifest.json`.
- New `runpod-deploy compare-runs <a> <b>` — side-by-side manifest
  diff with `==` for unchanged fields and `→` for changes. Compares
  top-level + `deploy_metadata.*` + per-`artifact[label]` fields.
  Exit 1 when either manifest reports `failed=true` so the command
  can gate CI checks.
- New `runpod-deploy events <run-dir>` — pretty-prints
  `events.jsonl` as a wall-clock timeline anchored at the first
  `ts_utc` (`[+M:SS]` / `[+H:MM:SS]` offset format).

**Deferred to v0.3.0.1** (per the planned roadmap): `metrics`
sparkline + `why-failed` triage classifier — design after using
v0.3.0 forensic navigation against real failures for a few weeks.

### Changed (v0.3.0)

- `select_gpu_across_datacenters` signature is additive (new keyword-
  only `prices` and `max_gpu_price_usd` params with defaults); existing
  callers still work.
- `cli._cmd_gpu_list` output gains an additional `$/hr` column
  conditional on price availability; existing column layout unchanged
  when `--no-prices` is passed or prices unavailable.
- Coverage gate `fail_under` 80 → 81 per CLAUDE.md §13
  (`floor(86.70) − 5`).

### Re-exports

`runpod_deploy.__init__` re-exports `GpuPrice`, `fetch_gpu_prices`,
`select_price_for_pod` for embedded consumers.

## [0.2.0] - 2026-05-14

### Added (v0.2.0 — own deployment primitives, expose recipes)

- **Multi-DC failover.** `pod.datacenters` (list) replaces
  `pod.datacenter_id` (string). New `provider.select_gpu_across_datacenters`
  iterates DCs in YAML order; within each DC iterates `gpu_order`; returns
  the first available `(gpu_id, dc_id)`. `on_failover(failed_dc, next_dc,
  reason)` callback fires per-DC exhaustion; orchestrator emits a
  `datacenter_failover` event into `events.jsonl`. Replaces v4-style manual
  DC rotation when stock evaporates.
- **Spot + min-resource pod knobs.** New `pod.spot: bool`,
  `pod.min_vcpu_count`, `pod.min_memory_gb`. `provider._build_pod_create_argv`
  emits `--spot`, `--min-vcpu-count N`, `--min-memory-in-gb N` when set.
- **TelemetrySpec block.** New `telemetry:` YAML block (all defaults
  enabled): `enabled`, `sample_interval_sec`, `capture_nvidia_smi`,
  `capture_dmesg`, `capture_pod_describe`, `capture_remote_env`,
  `capture_local_git`, `capture_payload_lockfile`.
- **`telemetry.py` module.** `TelemetrySession` owns one-shot snapshots
  (`nvidia_smi_{start,end}.txt`, `pod_describe_{start,end}.json`,
  `pip_freeze.txt`, `remote_env.json`, `dmesg_tail.txt`), background
  sampling thread (~one row per `sample_interval_sec` to `metrics.jsonl`
  with GPU + CPU + host mem + workspace disk), and a structured
  `events.jsonl` of orchestrator decisions (`gpu_selected`,
  `datacenter_failover`, `artifact_pull_*`, `remote_step_*`,
  `pod_killed_unexpected`). Stop-sampling joins with a 10 s timeout
  before abandoning a stuck thread; telemetry must never abort the run.
- **`metadata.py` module.** `capture_local_git(project_root)` and
  `capture_payload_lockfile(project_root)` helpers used by the orchestrator
  (auto-embedded in every manifest under `deploy_metadata`) and by the new
  `runpod-deploy capture-env` subcommand.
- **`runpod-deploy capture-env --project-root <path>`** — emits a JSON
  object with `local_git_sha`, `local_git_dirty`, `local_git_branch`,
  `payload_lockfile`, `payload_lockfile_sha256` to stdout. Lets consumers
  embed deploy metadata in their own evals manifests without a
  `runpod-deploy run` invocation. Replaces hand-rolled
  `GIT_SHA=$(git rev-parse HEAD)` Makefile injection.
- **`runpod-deploy manifest-summary <path>`** — pretty-prints a v1 or v2
  pull manifest as compact key/value lines (job, run id, pod, GPU, DC,
  wall time, captured $/hr price, estimated cost, deploy_metadata block,
  per-artifact status, telemetry files).
- **`runpod-deploy run --gpu-id <id> --datacenter-id <dc>`** — paired
  override that short-circuits GPU/DC selection for one-off runs. Both
  flags must come together; CLI override is logged at INFO and emitted
  as a `gpu_selected` event.
- **Reactive cost capture.** `runpodctl pod get`'s `costPerHr` field
  parsed at `capture_start`; manifest gains `gpu_price_per_hour_usd` +
  `gpu_price_source` (`pod_describe` | `assumed_rate`) +
  `estimated_cost_usd` (`gpu_price × wall_time / 3600`).
- **Pod-kill detection.** `runpodctl pod get`'s `desiredStatus` field
  parsed at `capture_end`; states ∉ `{RUNNING, EXITED}` emit
  `pod_killed_unexpected` event with the observed state and set
  `pod_final_state` in the manifest. Surfaces the v4 "EUR-NO-2 mid-fold-0
  killed by RunPod" failure mode that previously left no forensic trail.
- **Always-pull remote log.** `_pull_artifacts_and_log` rsyncs
  `spec.run.log_path` to `run_dir/run.log` *first*, then iterates
  declared artifacts. Log is pulled even on failure when the run started
  — addresses the v0.1.0 case where remote stdout was lost on RunPod
  pod kills.
- **Per-artifact pull tracking.** `manifest.ArtifactResult` (frozen
  slotted dataclass; status ∈ `success` | `failed` | `skipped`) embedded
  per-artifact in the v2 manifest with `bytes_transferred`,
  `duration_sec`, optional `error`.
- **Optional per-step markers.** `__RUNPOD_STEP_START__name__` /
  `__RUNPOD_STEP_DONE__name__` markers in `run.body` are parsed by
  `_monitor_remote_log` and emitted as `remote_step_started` /
  `remote_step_completed` events. Each unique `(kind, name)` pair
  emitted once via a seen set; consumers compute durations from `ts_utc`
  deltas in `events.jsonl`. Pure opt-in convention; absent markers cause
  no behavior change.
- **`docs/recipes/`** — six markdown recipes (README, local-preflight-then-run,
  local-postprocess-after-run, embed-deploy-metadata, multi-config-sweep,
  cost-reconciliation) documenting the composition patterns consumers
  use to wire `runpod-deploy run` into their pipeline. Single-responsibility
  rationale up-front: runpod-deploy is deployment-primitives; recipes
  show how to compose around it without bloating the schema.
- **`MIGRATION.md`** — two-edit guide (schema_version bump, datacenter_id
  → datacenters list).
- New `__all__` re-exports in `runpod_deploy.__init__`: `TelemetrySpec`,
  `select_gpu_across_datacenters`, `capture_local_git`,
  `capture_payload_lockfile`.

### Changed (v0.2.0)

- **Breaking: SCHEMA_VERSION 1 → 2.** v1 configs hard-fail at load time
  with a clear diagnostic. See `MIGRATION.md` for the two mechanical
  edits per config.
- `provider.select_gpu_for_datacenter` removed; replaced by
  `provider.select_gpu_across_datacenters` returning
  `tuple[gpu_id, datacenter_id]`.
- `provider.provision_pod` and `provider._build_pod_create_argv` now take
  explicit `datacenter_id` keyword args (the loop winner); no longer read
  `spec.pod.datacenter_id`.
- `orchestrator.run_job` rewritten to integrate telemetry + metadata +
  failover (linear ~70-line flow, justified by docstring per CLAUDE.md §8).
  Call order: GPU+DC selection → volume resolution → provision (was
  volume → GPU before).
- `manifest.SCHEMA_VERSION` `"v1"` → `"v2"`; `build_pull_manifest` gains
  keyword-only params with safe defaults so legacy callers continue to
  emit a v2 manifest with `null` placeholders for the new fields.
- `runpod-deploy validate` warns when `storage.mode: network_volume`
  combines with `len(pod.datacenters) > 1`.

## [Unreleased pre-0.2.0 — landed in 0.2.0]

### Added

- New top-level `secrets:` YAML block — stages one file per entry to the pod
  with restrictive perms (default `0600`). Each entry sets exactly one of
  `env: [VAR_NAME, ...]` (orchestrator reads local env vars and writes
  `KEY=value` lines) or `file: /local/path` (orchestrator rsyncs the local
  file). The parent directory is auto-created via `ssh mkdir -p`. Perms are
  enforced via rsync `--chmod=Fnnn` on transfer (works around the global
  `--no-perms` flag). Secret values are never logged at any verbosity. The
  consumer separately declares `remote_env.source_files` to wire the file
  into the run script — auto-sourcing is intentionally left explicit per
  CLAUDE.md §15. Closes #2.
- `transport.rsync_argv` / `RemoteRunner.rsync_push` now accept an optional
  `chmod: str | None = None` parameter used by the secrets pipeline.
- `validate --scan-consumer` now also warns when `torch` is listed in the
  consumer's `[project.dependencies]` or `[project.optional-dependencies]`
  but no `[tool.uv.sources]` entry pins it to a CUDA-specific wheel.
  Points the user at the new `docs/runpod-gotchas.md` section on wheel
  pinning. Quiet when torch is pinned (any `[tool.uv.sources].torch`
  entry suffices) or when torch isn't a dependency. Closes #3.
- New "Pinning torch to a CUDA-compatible wheel" section in
  `docs/runpod-gotchas.md` documenting the `pytorch-cu128` index pattern.
- `runpod-deploy validate --check-availability` — opt-in flag that
  live-queries `runpodctl datacenter list` and verifies every
  `gpu_order` entry against the configured datacenter. Catches name
  typos (e.g. `NVIDIA RTX 4090` vs `NVIDIA GeForce RTX 4090`) with a
  did-you-mean suggestion, warns on empty/unavailable stock, and
  fails-fast if no configured GPU is currently available. Closes #1.
- `runpod-deploy validate --scan-consumer` — opt-in flag that scans
  the consumer's pyproject.toml for `runpod-deploy` listed as a
  runtime dependency (it shouldn't be — pod doesn't need the
  orchestrator), and line-greps staged payloads for hardcoded
  absolute user paths (`/Users/...`, `/home/...`). Closes #4.
- `runpod-deploy validate --all` — enable every opt-in validate check.
- `runpod-deploy gpu-list --datacenter <id>` — print current GPU
  availability for one RunPod datacenter as a sorted table (High →
  Medium → Low → other). Closes part of #1.
- `runpod_deploy.preflight` module — `check_gpu_availability`,
  `fetch_datacenter_payload`, `scan_consumer_pyproject`,
  `scan_staged_payloads_for_absolute_paths`. Not re-exported from
  `runpod_deploy.__init__`; importable for embedded consumers that
  want to run pre-flight checks programmatically.
- `--verbose` / `--quiet` flags on every CLI subcommand. `--verbose` raises
  the log level to `DEBUG` and surfaces a handful of new debug records
  (rsync source/dest, ssh return codes, JSON payload types). `--quiet`
  lowers it to `WARNING` so info chatter is suppressed.
- `runpod-deploy logs --config <path>` — live-tail the current pod's run
  log over SSH. Discovers the pod's host/port from `runpodctl pod get`
  using the pod id persisted in the config's state file. Supports
  `--lines N` (default 200) and `--no-follow` (print and exit instead of
  `tail -f`).
- `transport.RemoteRunner.ssh_stream(command)` — runs a remote command
  with stdout/stderr inherited from the parent process. Used by the new
  `logs` subcommand to stream `tail -f` output in real time.

### Fixed

- `runpod-deploy run` now skips artifact pulls entirely when the run
  script never executed (e.g., setup or preflight commands failed
  before `_launch_remote_job` could start the script). Previously
  each artifact pull ran anyway, emitting rsync `change_dir` /
  `code 23` warnings that buried the real cause-of-failure trace.
  When the script *did* start but then failed, the existing
  diagnostic-noise behavior is preserved — rsync errors are still
  visible because partial artifacts may exist. Closes #5b.

### Changed

- **Breaking:** Minimum Python version bumped from 3.11 to 3.13.
  `requires-python` is now `>=3.13`; classifiers drop 3.11 and 3.12;
  style configs (`black`, `ruff`, `mypy`) target `py313`; CI matrix
  narrowed to `["3.13", "3.14"]`. `.python-version` (pinning 3.13)
  is now tracked. The ruff pre-commit hook id was also renamed from
  the deprecated `ruff` to `ruff-check`. Contributors on older Python
  must upgrade.
- `provider.select_gpu_for_datacenter` raises a richer error when no
  configured GPU is available — appends a `consider switching
  gpu_order to one of:` list naming any available GPUs in the
  datacenter sorted by stock tier (High → Medium → Low). Closes part
  of #1.
- `config.build_job_context` now raises `ValueError` when
  `local.project_root` resolves to `$HOME` exactly. This prevents the
  catastrophic "rsync entire home directory" foot-gun caused by an
  over-counted relative path (e.g. `../../..` from a config one level
  too deep). Closes #5a.
- `print()` calls in `cli.py`, `orchestrator.py`, `provider.py`, and
  `transport.py` migrated to the stdlib `logging` module. CLI output is
  byte-for-byte equivalent under default configuration; library consumers
  can now filter via the `runpod_deploy` logger.
- `transport.print_cmd` renamed to `transport.log_cmd(logger, label, argv)`;
  signature now takes the caller's logger explicitly.
- `run.script_path` and `run.log_path` now accept template variables (e.g.
  `{volume_mount}/script.sh`), matching `artifacts.remote_path` and
  `staging.destination`. Relative paths are still rejected.

### Fixed

- `provider.stop_pod` warning ("failed to stop pod") now routes to stderr
  via `logger.warning`. Previously emitted on stdout, which polluted
  captured CLI output (`runpod-deploy ... | tee log`).

## [0.1.0] - 2026-05-12

### Added

- Initial config-driven RunPod orchestration package.
- Single-job v1 schema.
- CLI for validation, dry-runs, execution, and state-file stop.
- Examples for prompt-injection-v3, prompt-injection-sdd, post_transformers,
  and research-kb.
