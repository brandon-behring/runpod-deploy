# runpod-deploy Coding Standards

These standards mirror the reusable-library posture used by `eval-toolkit`,
adapted for RunPod orchestration.

## Principles

1. **Fail fast at boundaries.** Validate YAML, CLI arguments, local required
   paths, and subprocess inputs before resource-heavy work.
2. **Separate pure logic from IO.** Config parsing, template rendering, argv
   builders, and manifest builders are pure and directly tested. Subprocess,
   SSH, rsync, and file writes stay in thin wrappers.
3. **No project-name conditionals in core.** Project behavior belongs in
   consumer-owned configs or future versioned hooks.
4. **Immutability by default.** Config/value/result types are frozen slotted
   dataclasses.
5. **No silent fallbacks.** Unknown config fields, missing required paths, and
   unsupported storage modes raise actionable stdlib exceptions.

## Tooling

| Tool | Setting |
|---|---|
| Formatter | `black`, line length 100 |
| Linter | `ruff check`, import sorting enabled, `E501` ignored because Black owns wrapping |
| Type checker | strict `mypy` |
| Test runner | `pytest`; live cloud tests are marked `network` and opt-in only |
| Build backend | `hatchling` |
| Env manager | `uv` |
| Python | `>=3.11` |

Use `make lint`, `make test`, and `make coverage`. Do not use `ruff format`.

## API And Types

- Package import name is `runpod_deploy`.
- Console script is `runpod-deploy`.
- Public modules declare `__all__`; private helpers are prefixed `_`.
- Public functions are fully typed.
- Use `@dataclass(frozen=True, slots=True)` for configs and value objects.
- Mutable runtime wrappers are allowed only for IO/session state.
- Prefer stdlib exceptions. `RemoteRunError` is reserved for remote job failure
  markers and failed remote execution semantics.

## Tests

- Test public contracts first: config validation, CLI dry-runs, `runpodctl`
  argv, SSH/rsync argv, GPU selection, monitor failure markers, stop policy,
  and manifests.
- Default tests never provision a real pod.
- Every RunPod operational lesson becomes a regression test before or with the
  implementation that preserves it.

## Security

- No secrets in configs, examples, tests, logs, docs, or manifests.
- Configs may reference remote secret files such as `/workspace/secrets/env`;
  they must not contain token values.
