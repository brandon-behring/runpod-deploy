# Contributing to runpod-deploy

Thanks for considering a contribution! This file is the entry point.
The deep guide lives in [`docs/extending.md`](docs/extending.md).

## The 30-second version

1. **Read** [`docs/extending.md`](docs/extending.md) §3 ("Contributors") for the SRP boundary, the per-change-type checklists, and the coding standards.
2. **Read** [`CLAUDE.md`](CLAUDE.md) for the full operational standards (frozen slotted dataclasses, stdlib exceptions, no `Result[T, Error]`, etc.).
3. Fork → branch off `main` → make changes → `make ci` green → open a PR.

## What to contribute

| Change type | Doc to read | Files to touch |
|---|---|---|
| **Recipe** (composition pattern) | [`docs/extending.md`](docs/extending.md) §3 "Contributing a recipe" | `docs/recipes/<name>.md` + `docs/recipes/README.md` index |
| **Schema feature** (new YAML field) | [`docs/extending.md`](docs/extending.md) §3 "Contributing a schema feature" | `src/runpod_deploy/config.py` + `_config_parsers.py` + use site + tests + `docs/config-reference.md` + `MIGRATION.md` |
| **CLI subcommand** | [`docs/extending.md`](docs/extending.md) §3 "Contributing a CLI subcommand" | `src/runpod_deploy/cli.py` + `tests/test_cli_<name>.py` + relevant docs |
| **Bug fix** | [`docs/troubleshooting.md`](docs/troubleshooting.md) if the bug is consumer-facing | Wherever the bug lives + regression test |
| **Example YAML** | [`examples/README.md`](examples/README.md) | `examples/<consumer>/<job>.yaml` + companion README if non-obvious |

## Local development

```sh
git clone https://github.com/brandon-behring/runpod-deploy.git
cd runpod-deploy
uv venv
uv pip install -e ".[dev]"
make lint       # ruff + black + mypy strict
make test       # pytest with default markers (unit + smoke)
make coverage   # pytest with coverage report
make ci         # all three; CI parity
```

Optional: `pre-commit install` to run ruff + black + gitleaks at
`git commit` time. `make lint` is the canonical enforcement path.

Optional shell completion (mirrors the [completion] extra documented in
the README quickstart):

```sh
uv pip install -e ".[dev,completion]"
eval "$(register-python-argcomplete runpod-deploy)"   # bash/zsh
```

For permanent activation, append the `eval` line to your `~/.bashrc` or
`~/.zshrc`.

Optional `mypy` at push time (in addition to `make lint`):

```sh
pre-commit install --install-hooks --hook-type pre-push
```

This adds the `mypy src` hook from `.pre-commit-config.yaml`'s
`stages: [pre-push]` block. Commit cycles stay fast (~0.1s); push-time
gate adds ~1–3s before any actual remote push.

## What we won't merge

Per the [single-responsibility boundary](docs/extending.md#3-contributors--the-srp-boundary):

- Features that turn `runpod-deploy` into a workflow runner (e.g., a `local_steps` YAML field that executes consumer code locally).
- `Result[T, Error]` patterns; we use `raise` with stdlib exceptions.
- New thin wrappers around `subprocess.run` or `yaml.safe_load`.
- Schema-version bumps for additive optional fields (see [`MIGRATION.md`](MIGRATION.md) "Schema-versioning policy").

If your idea sits on the borderline, open an issue first and we'll talk it through.

## Code of conduct

Be kind, be specific, and assume good faith. Bug reports + PR comments should describe symptoms and reproduction steps, not just frustrations.
