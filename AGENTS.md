# AGENTS.md

Discoverability shim for non-Claude agents (Cursor, Codex, Aider,
GitHub Copilot Workspace, etc.). Per the emerging `agents.md` convention.

## What this package is

`runpod-deploy` is a **deployment-primitives library** for RunPod GPU
pods. Config-driven YAML → pod lifecycle (provision → stage → run →
pull artifacts → manifest). Single-responsibility, not a workflow
runner — see `[[feedback-runpod-deploy-srp]]` recorded inside
`CLAUDE.md`.

## For the full operational standards

Read **`CLAUDE.md`** at the repo root. It's the canonical doc for
coding conventions, error-handling discipline, dataclass patterns,
test markers, the SRP boundary, and the §1–§16 numbered standards.

The `CLAUDE.md` content is agent-neutral — written for Claude but
applicable to any agent ingesting this codebase. Read sections in
this order if you only have time for some:

1. **§1 (Foundational principles)** — never fail silently, fail fast
   at boundaries, immutability by default.
2. **§5 (Dataclasses)** — `slots=True` + `frozen=True` for all value
   types. Validation in `__post_init__`.
3. **§6 (Errors)** — always `raise` with stdlib exceptions; no
   `Result[T, Error]`; one custom-exception carve-out (`RemoteRunError`).
4. **§15 (No-go list)** — what to never propose.

## For consumers (vs. contributors)

- **Consumer-facing docs**: `README.md`, `docs/quickstart.md`,
  `docs/lifecycle.md`, `docs/config-reference.md`, `docs/troubleshooting.md`,
  `docs/recipes/`.
- **Contributor-facing docs**: `CONTRIBUTING.md` (PR flow) +
  `DEVELOPING.md` (local dev / debugging / golden-file workflow).
- **Schema migrations**: `MIGRATION.md`.

## Quick test invocations

```sh
make lint        # ruff + black + mypy
make test        # pytest (unit + smoke; skips `network`-marker)
make ci          # lint + test + coverage
make doctest     # pytest --markdown-docs (added in v0.7.6+; if absent, skip)
make build       # python -m build (sdist + wheel)
```

## Where the public API lives

- Top-level package: `runpod_deploy` (re-exports the public surface
  via `src/runpod_deploy/__init__.py`).
- Entry-point script: `runpod-deploy` (console-script defined in
  `pyproject.toml`'s `[project.scripts]`, mapping to
  `runpod_deploy.cli:main`).

## Where the heavyweight files are

- `src/runpod_deploy/config.py` — frozen `*Spec` dataclasses (YAML
  schema).
- `src/runpod_deploy/orchestrator.py` — `run_job` linear lifecycle.
- `src/runpod_deploy/provider.py` — `runpodctl` subprocess + GPU/DC
  selection.
- `src/runpod_deploy/transport.py` — SSH + rsync via `subprocess`.
- `src/runpod_deploy/cli.py` — argparse subcommand registry.

## What to NOT propose

- **Workflow-runner features** (e.g., a `run-fleet` subcommand,
  `local_steps` YAML schema). Per `[[feedback-runpod-deploy-srp]]`,
  this stays a deployment-primitives library; sweep orchestration
  belongs in consumer bash/Make/Python.
- **`Result[T, Error]` patterns** — we use `raise`.
- **Thin dependency wrappers** (e.g., a class wrapping
  `subprocess.run` to rename two kwargs).
- **Plugin entry-points** (`runpod_deploy.plugins`). No consumer
  signal; no peer ships one.

## Communication conventions

- Concise > comprehensive. Match the project's
  conventions-over-novelty bias (CLAUDE.md §16 "consistency >
  novelty").
- Cite `file_path:line_number` for code references.
- Don't add comments that restate the code or reference the current
  PR — those belong in commit messages.
