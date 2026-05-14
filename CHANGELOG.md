# Changelog

This project follows Semantic Versioning.

## [Unreleased]

## [0.3.3] - 2026-05-14 — template rendering for run.* path/marker fields

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
