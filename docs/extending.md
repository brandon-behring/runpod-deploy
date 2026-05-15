# Extending runpod-deploy

Three audiences:

1. **Consumers** using runpod-deploy from their own repo (the common
   case). You shouldn't need to fork or patch — the YAML schema +
   `--var` / `--vars-file` cover almost every config-driven
   variation, and recipes (`docs/recipes/`) cover composition with
   your own pre/post pipeline.
2. **Library users** importing `from runpod_deploy import run_job`
   into Python code (e.g., to wrap it inside a notebook or test).
3. **Contributors** adding a new feature, recipe, or PR to this repo.

---

## 1. Consumers — the no-fork path

### Vary one thing at a time → `--var KEY=VALUE`

```sh
runpod-deploy run --config configs/runpod/template.yaml \
  --var seed=42 --var backbone=deberta --print-run-dir
```

KEY must be a valid Python identifier. VALUE is any string. Repeat
`--var` to set multiple. CLI `--var` overrides any matching key in
the YAML's `variables:` block.

### Vary many things → `--vars-file PATH`

```sh
runpod-deploy run --config configs/runpod/template.yaml \
  --vars-file configs/runpod/sweep_seed42.json
```

PATH is a JSON object `{KEY: VALUE}` (all string values). CLI `--var`
takes precedence over `--vars-file` entries on collision.

### Per-shard cost cap + max runtime

```sh
runpod-deploy run --config foo.yaml --cost-cap-usd 5.0 --max-runtime-minutes 60
```

Both override the YAML's `budget.cost_cap_usd` and
`budget.max_runtime_minutes`.

### Pair GPU + DC for one-off runs

```sh
runpod-deploy run --config foo.yaml \
  --gpu-id 'NVIDIA RTX 4090' --datacenter-id EU-RO-1
```

Short-circuits `pod.gpu_order` and `pod.datacenters` selection. Both
flags must come together (validated at CLI parse time). Useful for
"try this GPU class as a smoke test" without editing the YAML.

### Filter GPUs by price

```sh
runpod-deploy run --config foo.yaml --max-gpu-price 4.50
```

Skips GPUs above $4.50/hr during the failover loop. Reads
`RUNPOD_API_KEY` for the GraphQL price fetch.

---

## 2. Library users — `from runpod_deploy import ...`

Public API surface (re-exported from `__init__.py`):

| Symbol | What it is |
|---|---|
| `load_job_spec(path)` | Parses + validates a YAML config file. Returns a frozen `RunpodJobSpec`. Raises `ValueError` / `FileNotFoundError` / `KeyError` / `TypeError` on bad input. |
| `build_job_context(spec, config_path, *, cli_variables=None, timestamp=None)` | Resolves template variables and computes the run-dir path. Returns a frozen `JobContext` with `render(value)` and `render_path(value, base=...)`. |
| `validate_local_paths(ctx)` | Verifies each `local.required_paths` entry exists. Raises `FileNotFoundError` with the missing list. |
| `run_job(spec, *, config_path, dry_run=False, offline_dry_run=False, gpu_id_override=None, datacenter_id_override=None, max_gpu_price_usd=None, cli_variables=None, print_run_dir=False)` | Full lifecycle (provision → stage → preflight → run → pull → stop → manifest). All side-effecting calls. Raises on failure (after the `finally`-block manifest write). |
| `RunpodJobSpec`, `JobContext`, `PodSpec`, `StorageSpec`, `RunSpec`, ... (frozen dataclasses) | Type-hint / pattern-match targets. Constructed via parsers; consumers should treat as read-only. |
| `select_gpu_across_datacenters`, `provision_pod`, `stop_pod` | Lower-level orchestration primitives (rarely needed; the orchestrator wraps them). |
| `pricing.fetch_gpu_prices(force_refresh=False)` | GraphQL pricing fetch. Returns `dict[str, GpuPrice]`. |

### Pattern: composing with a Python driver

```python notest
from runpod_deploy import load_job_spec, run_job

spec = load_job_spec("configs/runpod/template.yaml")

for seed in [42, 43, 44]:
    run_job(
        spec,
        config_path="configs/runpod/template.yaml",
        cli_variables={"seed": str(seed)},
        print_run_dir=True,
    )
```

This is the in-process equivalent of the bash sweep recipe. Failures
raise; the caller decides retry/skip.

### What you should NOT do

- **Do not mutate `RunpodJobSpec` / `JobContext`** — they're frozen
  dataclasses. Construct new instances via `dataclasses.replace` if
  you need to alter a field (the CLI does this for budget overrides).
- **Do not import private helpers** (anything prefixed with `_`).
  They're not part of the public API and may change without notice.
- **Do not catch `RemoteRunError` to swallow it** — it's the
  carve-out for "SSH command failed" semantics. Catching means you've
  decided to handle a transient pod-side failure, which is your
  retry decision to make.

---

## 3. Contributors — the SRP boundary

runpod-deploy is a **deployment-primitives library**. Its single
responsibility is the pod lifecycle: GPU/DC selection, staging,
remote execution, telemetry, artifact pull, manifest. See CLAUDE.md
§1–§16 for the full operational standards.

**What we own**:
- Anything pod / GPU / cost / telemetry / manifest.
- The YAML schema + the validator + the renderer.
- The forensic CLIs that read manifests + events.
- Recipes that document composition patterns.

**What we don't own**:
- Consumer-domain logic (audit, plotting, aggregation, metrics).
- Multi-process workflow orchestration (sweep drivers belong in
  bash/Make/Python in the consumer repo; see
  `docs/recipes/multi-config-sweep.md`).
- Any feature that would run consumer Python or bash locally.

When you have a feature in mind, ask: *is this metadata about the
deploy, or is it consumer-domain logic?* Former → ship as a schema
feature or CLI subcommand. Latter → ship as a recipe under
`docs/recipes/`.

### Contributing a recipe

A recipe is a markdown file under `docs/recipes/` documenting a
composition pattern. Pattern:

1. **Filename** — kebab-case, descriptive verb-phrase
   (`local-preflight-then-run.md`, `cost-reconciliation.md`).
2. **Structure** — top-level `# Recipe: <name>` heading; a
   `**Pattern:**` one-liner explaining the use case; one or more
   code blocks showing the implementation; a `## Notes` or
   `## Pitfalls` section if non-obvious; a `## See also` linking
   related recipes.
3. **Index** — add a one-line entry to `docs/recipes/README.md`
   under the appropriate section.
4. **Code blocks must be valid** — for runpod-deploy YAML
   blocks, `tests/test_recipe_examples.py` (added in v0.7) loads
   them via `load_job_spec`. Keep them schema-correct.

### Contributing a schema feature

A schema feature is a new YAML field or top-level section.

1. **Field on a dataclass** — add to the appropriate `*Spec` in
   `src/runpod_deploy/config.py`. Provide a sane falsy default
   (per the additive-change policy in `MIGRATION.md`).
2. **Validation in `__post_init__`** — raise stdlib exceptions
   with diagnostic messages (CLAUDE.md §6).
3. **Parser recognizes the new key** — update the matching
   `_parse_*` in `src/runpod_deploy/_config_parsers.py` (add to
   `_check_keys` allowed set + extract value).
4. **Use site renders or consumes** — pure functions if possible;
   IO-touching code lives in orchestrator/provider/transport.
5. **Tests** — `tests/test_config.py` for parse + validation;
   `tests/test_orchestrator*.py` for use-site behavior (use the
   `--offline-dry-run` pattern).
6. **Doc** — update `docs/config-reference.md` with the new field
   + an example. Update `MIGRATION.md` "Additive changes since
   schema_version: 2" with a one-bullet summary.
7. **CHANGELOG** — entry under `[Unreleased]` per Keep-a-Changelog.

### Contributing a CLI subcommand

1. **Subparser** — add to `_build_parser` in
   `src/runpod_deploy/cli.py` (after the existing subparsers; sort
   by ship order, not alphabetic).
2. **Handler** — `_cmd_<name>` function returning an exit code
   (0 on success, non-zero on failure-modes the caller may want
   to distinguish).
3. **Dispatch** — add to the `handlers` dict in `main`.
4. **Tests** — `tests/test_cli_<name>.py`. Use `capsys` for stdout
   assertions, `caplog` for logger assertions.
5. **Doc** — note in `docs/quickstart.md` or
   `docs/troubleshooting.md` if it's a forensic tool worth
   highlighting; in the `--help` message regardless.
6. **CHANGELOG + MIGRATION** — additive CLI changes go under
   `MIGRATION.md` "CLI additions" section + CHANGELOG `[Unreleased]`.

### Coding standards

See CLAUDE.md (the canonical doc at repo root). Summary:

- Black, line length 100. ruff for linting. mypy strict.
- Frozen slotted dataclasses for all value types.
- Stdlib exceptions; no `Result[T, Error]` patterns.
- `from __future__ import annotations` at the top of every module
  except `__init__.py`.
- Module-level docstring on every module; one-line docstring on
  every `__all__` function.
- 80%+ unit coverage; coverage gate at `floor(actual) − 5`,
  bumped per-PR.
- Real tests; no stubs / TODOs / placeholders.

### Updating golden CLI files

The v0.7 release introduces golden-file snapshot tests for CLI
output stability. When you intentionally change a CLI's output
format:

```sh
pytest tests/test_cli_golden.py --update-goldens
git diff tests/fixtures/golden/   # eyeball the diff
git add tests/fixtures/golden/*.txt
```

Review the diff carefully — these files lock the UX contract.
