# runpod-deploy — Operational Coding Standards

This file is auto-loaded by Claude Code at the repo root. It is the canonical
source of code-style and operational standards for this project. External
readers of the published sdist see the condensed `STYLE.md`; contributors and
Claude work from this file.

Section structure mirrors `eval-toolkit/STYLE.md` so anyone fluent in one
navigates the other; runpod-deploy-specific adaptations are called out
inline.

## 1. Foundational principles

1. **Never fail silently.** Every validation failure raises a stdlib exception
   with a diagnostic message. No silent defaults, no fake/fallback data.
2. **Fail fast at boundaries.** Validate YAML, CLI args, local required paths,
   and subprocess inputs before resource-heavy work (pod creation, SSH).
   Diagnostic messages explain what was expected, what was found, how to fix.
3. **Immutability by default.** Config, value, and result types are frozen
   slotted dataclasses. Functions return new structures; never mutate
   caller-supplied arguments.
4. **Pure-vs-IO separation.** Config parsing, template rendering, argv
   builders, and manifest builders are pure and directly tested. Subprocess,
   SSH, rsync, and filesystem writes stay in thin wrappers (`provider.py`,
   `transport.py`).
5. **Anti-overengineering.** Don't add an abstraction unless a second concrete
   use exists or is concretely planned.

## 2. Tooling

| Tool | Setting |
|---|---|
| Formatter | `black`, line length 100, target `py311` |
| Linter | `ruff` with `select = ["E", "F", "W", "I", "N", "UP", "B", "SIM", "C4"]`, ignore `E501` (Black owns wrapping). **No `N803`/`N806` exclusions** — no math kernels here. |
| Type checker | `mypy` strict (`disallow_untyped_defs`, `disallow_incomplete_defs`, `check_untyped_defs`, `no_implicit_optional`, `warn_redundant_casts`, `warn_unused_ignores`, `warn_no_return`, `strict_equality`, `warn_return_any`, `warn_unused_configs`) |
| Test runner | `pytest` with markers `unit`, `smoke`, `network`; coverage floor `79%` (`fail_under` in `pyproject.toml`) |
| Build backend | `hatchling` |
| Env manager | `uv` (`uv venv` → `.venv/`; `uv pip install -e .[dev]`) |
| Python | `>=3.11` |

Run via `make lint` (= `ruff check + black --check + mypy`), `make test`, and
`make coverage`. CI runs `make ci` (= all three). Do not use `ruff format` —
Black owns formatting.

Optional commit-time guard: `.pre-commit-config.yaml` runs ruff + black + file
hygiene at `git commit` time when contributors opt in via `pre-commit install`.
`make lint` is still the canonical enforcement path (and is the one CI runs).

## 3. Naming

- **Modules**: `snake_case`, lowercase package name `runpod_deploy`.
- **Classes**: `PascalCase` with role-based suffixes used in this repo:
  - `*Spec` — frozen dataclass parsed from YAML config
    (`PodSpec`, `StorageSpec`, `BudgetSpec`, `RunSpec`, …; 13 total in
    `config.py`).
  - **Descriptive names** for value/operation types that are *not* YAML
    config:
    - `JobContext` — resolved template state for one run
    - `PodConnection` — SSH-ready pod connection details
    - `RemoteRunner` — operation wrapper around SSH/rsync
    - `RsyncTransfer` — one rendered rsync transfer
  - `*Error` for exceptions (only `RemoteRunError` today; see §6).
- **Functions**: `snake_case`. Verb prefix is fine when natural
  (`load_job_spec`, `provision_pod`, `validate_local_paths`) but not
  mandatory.
- **Constants**: `UPPER_SNAKE_CASE` at module level
  (`STORAGE_EPHEMERAL`, `STORAGE_NETWORK_VOLUME`, `SCHEMA_VERSION`,
  `DEFAULT_FAILURE_MARKERS`).
- **Private helpers**: leading `_`; not exported via `__all__`.

## 4. Type hints

- Every public function has fully typed parameters and return.
  `disallow_untyped_defs = True` in mypy enforces this.
- Modern syntax: `list[T]`, `X | None`. Use `Optional` only when stylistically
  required.
- `from __future__ import annotations` at the top of every module except
  `__init__.py` (which has no forward refs and doesn't need it). This is the
  existing convention; keep it.
- No `Protocol` section yet — no current seams with multiple concrete
  implementations. Add one if a second concrete impl of `RemoteRunner` or
  similar emerges.

## 5. Dataclasses

1. **`slots=True` always** on repo-owned dataclasses. Catches typos at
   attribute-set time and trims memory.
2. **`frozen=True`** for value/config/result types. Mutable only for
   runtime-state wrappers (`RemoteRunner` and friends are frozen anyway
   because their attributes are bound once at construction).
3. **Validation in `__post_init__`** using stdlib exceptions. See `PodSpec`,
   `StorageSpec`, `BudgetSpec`, etc. in `config.py`.
4. Mutable defaults via `field(default_factory=...)`. Never `field([])` or
   bare `[]`.

## 6. Errors

- **Always `raise`. Always stdlib.** `ValueError` for bad-data inputs,
  `TypeError` for wrong-type inputs, `RuntimeError` for state errors,
  `FileNotFoundError` for missing artifacts, `KeyError` for missing entries.
  **No `Result[T, Error]` patterns** — use raises.
- **No `assert` in `src/runpod_deploy/`.** `assert` is stripped under
  `python -O`. Use `raise ValueError(...)` even for "this should be
  impossible" cases. `assert` in `tests/` is fine and idiomatic.
- **Diagnostic-message rule.** A caller should be able to fix the input
  without reading the function's internals:
  ```python
  raise ValueError(f"pod.container_disk_gb must be > 0, got {self.container_disk_gb}")
  raise RuntimeError(f"volume {volume_name!r} is in {datacenter_id}, expected {expected_datacenter_id}")
  ```
  Use `!r` repr formatting for any embedded value where the user might need
  to see quoting/whitespace (paths, names, IDs).
- **Single custom-exception carve-out: `RemoteRunError`**
  (`transport.py:15-16`). Reserved for remote-execution failure semantics —
  SSH command failed, remote process exited non-zero. The carve-out exists
  because callers in `orchestrator.py` need to distinguish "SSH command
  failed" (transient, recoverable, possibly retried) from "orchestrator state
  error" (`RuntimeError`, fatal). Do **not** expand this taxonomy — any new
  custom exception requires a documented reason.

## 7. Validation boundary

Validate at:

- **YAML loader** (`config.load_job_spec`) — schema, types, value ranges.
- **CLI entry** (`cli.main`) — argparse-level argument constraints.
- **Before resource-heavy operations** — `provider.provision_pod` validates
  before calling `runpodctl pod create`; `transport.RemoteRunner.ssh_exec`
  rejects empty commands before invoking subprocess.

Do **not** re-validate in helpers downstream of those boundaries. Trust is
faster, and the public API has already failed-fast for invalid input.

## 8. Function design

- **Single responsibility.** Two functions doing 80% the same thing → factor
  a helper.
- **Soft 20–50 line guideline.** Long functions are fine when they're
  cohesive (orchestrator's `run_job` is ~45 lines and is the documented soft
  ceiling). Longer is allowed if the function is genuinely linear and a
  docstring explains why.
- **Pure helpers preferred** for parsing, formatting, rendering
  (`config._parse_*`, `manifest._render_artifact`, `provider.build_pod_create_argv`).
- **Don't over-extract.** Three-line helpers used once add cost without
  clarity. Inline them.

## 9. Output channels (CLI + library)

**Target: use `logging` for all `src/runpod_deploy/` output.**

Reason: runpod-deploy will grow embedded consumers (Python programs that
import `run_job` rather than invoke the CLI). `print(..., flush=True)`
hard-codes stdout and breaks those callers' output discipline.

- Status / progress: `logger.info(...)`
- Warnings (e.g., "pod preserved", "optional pull skipped"):
  `logger.warning(...)`
- Errors (before raising): `logger.error(...)` — but in most cases the
  exception's diagnostic message is enough; don't log-and-raise.
- CLI entry (`cli.main`) configures the root logger with a stdout handler so
  the current `tail -f` UX is preserved for direct CLI users.

**Status**: Phase H completed in 698c04a — all `src/runpod_deploy/`
output now uses `logging`. CLI entry (`cli.main`) configures the root
logger to preserve the `tail -f` UX for direct CLI users.

## 10. Imports

Order (enforced by ruff `I`):

1. `__future__` imports (always present except in `__init__.py`)
2. Stdlib
3. Third-party (`yaml` only, currently)
4. First-party (`runpod_deploy.*`)

Local imports inside functions are allowed for:

- Lazy heavy imports (none currently)
- Optional-dep imports (none currently — `yaml` is required)

If you're tempted to do a local import to break a circular dependency, fix
the circular dependency instead.

## 11. Docstrings

- **Module-level docstring**: required for every module. One-line summary of
  what the module owns (e.g., `"""SSH and rsync transport primitives."""`).
- **Public-function docstring**: required for every function declared in
  `__all__`. One-line summary. Add `Raises:` when the function raises stdlib
  exceptions on bad input (`provider.run_json` raises `RuntimeError` on
  non-zero exit; document that).
- **NumPy-style sections optional.** No math kernels here; the long-form
  Parameters/Returns/Examples style isn't needed. A docstring like:
  ```python
  def provision_pod(ctx: JobContext, *, volume_id: str | None, gpu_id: str, dry_run: bool) -> PodConnection:
      """Provision a pod and return SSH connection details."""
  ```
  is the standard.

## 12. Comments

Default: **none**. Comment only when intent is non-obvious from code and
types. Never restate what the code says.

Audit on 2026-05-12 confirmed `src/runpod_deploy/` has zero inline comments.
Preserve that posture.

Examples of legitimate comments (which would be added if needed):

- A workaround for a specific bug ("rsync openrsync on macOS doesn't accept
  `--info=progress2`; see issue #X").
- A subtle invariant ("`last_payload` is rebound on every iteration so the
  timeout error includes the most recent observation, not the empty initial
  dict").
- A non-obvious algorithm choice.

Do not write comments that:

- Restate the code (`# increment counter`).
- Reference the current task or PR (`# fix for ticket-123`) — that belongs in
  the commit message.
- Describe call sites (`# used by orchestrator.run_job`) — that rots.

## 13. Tests

- **Markers**: `unit` (pure contract tests), `smoke` (end-to-end dry-run),
  `network` (live RunPod — opt-in, excluded from default `make test` and CI).
- Default `make test` never provisions a real pod. Live tests are run
  manually with `pytest -m network` after a deliberate decision.
- **Coverage floor**: 79% (`fail_under` in `pyproject.toml`).
- **Coverage-gate policy**: after a substantive test-coverage commit, run
  `make coverage`, observe actual coverage, bump `fail_under` to
  `floor(actual) − 5`. The 5-point buffer absorbs one-line additions without
  nuisance breakage. Documented pattern from Phase F (gate 65 → 71 at 76%
  actual) and Phase G (71 → 79 at 84.62% actual).
- **Operational-lesson policy**: every operational lesson learned from a real
  deploy becomes a regression test before or with the fix that preserves it.
  Example: `test_offline_dry_run_walks_command_shape` pins the offline-mode
  command shape so a change to `orchestrator.run_job`'s branching can't
  silently regress the dry-run output.

## 14. Packaging

- **Semver from v0.1.0.** Public API breaking changes require a major-version
  bump. Currently v0.1.0; treat the surface as alpha.
- **`CHANGELOG.md`** in Keep-a-Changelog format. Add entries under
  `[Unreleased]`.
- **`py.typed` marker** is shipped (`src/runpod_deploy/py.typed`); consumers
  get inline-typed package data.
- Build: `python -m build` produces wheel + sdist via Hatchling. sdist
  includes `STYLE.md`, `README.md`, `CHANGELOG.md`, `LICENSE` (per
  `pyproject.toml` `[tool.hatch.build.targets.sdist]`). **CLAUDE.md is
  deliberately NOT in the sdist** — it's an operational/internal artifact.

## 15. No-go list

- ❌ Pydantic / LangChain / config frameworks. We use plain YAML +
  `__post_init__` validation.
- ❌ Custom exception hierarchies beyond `RemoteRunError`. Any new custom
  exception needs a documented carve-out reason.
- ❌ `Result[T, Error]` patterns. Use `raise`.
- ❌ Thin dependency wrappers (e.g., a class that wraps `subprocess.run` to
  rename two kwargs).
- ❌ `_inplace` mutation suffix — not Pythonic. Mutating functions return
  `None`, say so in the docstring.
- ❌ `from __future__ import annotations` in `__init__.py` — no forward
  refs needed there.
- ❌ Secrets in any committed artifact: configs, examples, tests, logs, docs,
  manifests, fixtures. Configs may reference remote secret files
  (`/workspace/secrets/env`); they must not contain token values.

## 16. Public API discipline

- Every module declares `__all__` (audit confirmed). New modules must do the
  same.
- `runpod_deploy/__init__.py` re-exports the public surface so consumers can
  `from runpod_deploy import load_job_spec, run_job` — matches sklearn/pandas
  convention.
- Private helpers are prefixed with `_` and are **not** re-exported.

---

## Operational addendum (Claude-specific)

These are workflow notes for Claude Code that complement the code rules
above. Not in eval-toolkit's STYLE.md.

### Coverage-gating after test commits

After any commit that materially expands the test suite:

1. `make coverage` — observe actual coverage (the "Total coverage: X%" line).
2. Edit `pyproject.toml` `fail_under` to `floor(actual) − 5`.
3. Bundle the gate bump in the same commit as the test expansion.

This prevents the coverage gate from drifting upward unintentionally and
breaking the next unrelated one-line addition.

### Test-code coupling for subprocess paths

When modifying `provider.py` or `transport.py` in ways that change the
subprocess argv shape (new flags, reordered args, additional `runpodctl`
subcommands), update the matching tests in the same commit:

- `tests/test_provider_subprocess.py` for `provider.py` changes
- `tests/test_transport_subprocess.py` for `transport.py` changes

The `FakeSubprocess` / `FakePopen` fixtures in `tests/conftest.py` are the
seam — orchestrator tests in `tests/test_orchestrator_run_job.py` use them
via `.when(predicate, FakeResult(...))`.

### Local green bar

`make lint && make test && make coverage` must all pass locally before
pushing. CI runs the same three via `make ci` across Python 3.11/3.12/3.13.

### When in doubt

If a rule above doesn't address something, lean on:

1. Whatever the existing code already does (consistency > novelty).
2. eval-toolkit's STYLE.md for unaddressed sections — this repo aims to stay
   structurally aligned.
3. Ask the user before introducing a new pattern.
