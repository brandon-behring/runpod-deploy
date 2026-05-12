# runpod-deploy — Coding Standards

Public-facing summary of this project's code conventions. The full
operational standards (naming, errors, function design, output channels,
no-go list, etc.) live in `CLAUDE.md` at the repo root and are the canonical
source of truth.

## Foundational principles

1. **Never fail silently.** Validation failures raise stdlib exceptions with
   diagnostic messages.
2. **Fail fast at boundaries.** YAML, CLI args, and local paths are validated
   before resource-heavy work.
3. **Immutability by default.** Config/value/result types are frozen slotted
   dataclasses.
4. **Pure-vs-IO separation.** Pure logic (config parsing, argv builders,
   template rendering, manifests) is directly tested; subprocess/SSH/rsync
   stays in thin wrappers.
5. **Anti-overengineering.** No abstraction without a second concrete use.

## Tooling

| Tool | Setting |
|---|---|
| Formatter | `black`, line length 100 |
| Linter | `ruff` with `select = ["E", "F", "W", "I", "N", "UP", "B", "SIM", "C4"]` |
| Type checker | `mypy` strict |
| Test runner | `pytest` with markers `unit`, `smoke`, `network`; coverage floor 79% |
| Build backend | `hatchling` |
| Env manager | `uv` |
| Python | `>=3.11` |

Run via `make lint`, `make test`, `make coverage`. CI runs `make ci`.

## Public API surface

- Package import name: `runpod_deploy`
- Console script: `runpod-deploy`
- Every module declares `__all__`; private helpers are `_`-prefixed.
- `py.typed` marker ships with the package.

## Security

No secrets in configs, examples, tests, logs, docs, or manifests. Configs may
reference remote secret files (e.g., `/workspace/secrets/env`); they must not
contain token values.

## Full standards

See `CLAUDE.md` in the repository for the complete coding standards,
including naming conventions, error-handling rules, the no-go list, the
single custom-exception carve-out, and the operational addendum.
