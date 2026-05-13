# Changelog

This project follows Semantic Versioning.

## [Unreleased]

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

### Changed

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
