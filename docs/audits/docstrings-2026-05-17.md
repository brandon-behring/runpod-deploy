# Documentation Audit — 2026-05-17

## Executive summary

This audit covers all documentation surfaces in `runpod-deploy` v0.8.0:
13 Python modules in `src/runpod_deploy/`, 10 recipes in
`docs/source/recipes/`, 10 top-level Sphinx docs in `docs/source/`, and
6 repo-root docs (README, CONTRIBUTING, AGENTS, DEVELOPING, STYLE,
CHANGELOG). Consumer usage was profiled across the two known clients
(`post_transformers`, `prompt-injection-detection-submission`) to weight
priorities.

**Headline findings:**

| Tier | MUST-FIX | SHOULD-FIX | NICE-TO-HAVE | OK |
|---|---|---|---|---|
| Python docstrings | 0 | 0 | 1 | 12 |
| Markdown recipes | 1 | 6 | 0 | 3 |
| docs/source/ top-level | 0 | 3 | 1 | 6 |
| Repo-root docs | 0 | 0 | 1 | 5 |
| **TOTAL** | **1** | **9** | **3** | **26** |

**The Python codebase is in exceptional shape.** All 13 modules have
module docstrings; every public function has a docstring; imperative
mood is used consistently; comments are minimal and justified. The one
nice-to-have is a redundant inline comment in `cli.py`.

**The markdown recipes have accumulated structural drift.** 7 of 9
recipes deviate from the canonical template defined by
`local-preflight-then-run.md`. Specifically, the "Why this is a recipe,
not a schema feature" section, the "What lives where" table, and the
"Anti-pattern to avoid" section are inconsistently present or labeled.

**Top-level docs are mostly clean** with three exceptions:
`migration-v3.md` is a stub; `troubleshooting.md` references a stale
`runpodctl` version (v0.3.2) that should become version-agnostic; and
**`extending.md` introduces the Python API surface but never tells the
reader when to choose it over the CLI** — the "when" decision is
exactly what consumers need to make and the doc leaves them to guess.

**Repo-root docs are clean** with one typo in `DEVELOPING.md:16`
(`coverage-deploy` should be `runpod-deploy`).

**Consumer-fit consequence:** both consumers exclusively use the CLI;
neither imports the Python API. The CLI `--help` text, YAML schema docs,
and manifest field schema are therefore the rev-rev surfaces. They are
all in good shape today.

**Breaking-change candidates: NONE met the strict bar.** This section
was explicitly empty after applying the criterion "meaningful
improvement AND mechanical migration." The minor naming inconsistencies
(`--dry-run` vs `--offline-dry-run`; `staging[].excludes_default`
ambiguity) don't clear the cost-of-migration threshold against
already-shipping consumer configs. See §6 for the considered-and-rejected
list.

**Recommended plan adjustment:** because no breaking changes are
justified, **Phase 3 (PR-B v0.9.0) and Phase 4 (consumer migration
issues) should be skipped**. All work collapses into the doc-only PR-A,
which can ship as a patch bump (v0.8.1) for the `forensics` re-exports
or stay at v0.8.0 for pure documentation.

## Methodology

- **Python**: AST-parse every module for module/class/function
  docstrings, then sample 5 docstrings per module for style + content
  quality. Compare against CLAUDE.md §11–§12 (the canonical style
  reference).
- **Markdown**: Read every file in scope; compare recipes against
  `local-preflight-then-run.md` as the structural exemplar; compare
  top-level docs against their audience-specific role.
- **Consumer usage**: parallel reads across both consumer repos for CLI
  invocations, YAML fields, manifest field parsing, Python imports.
- **Out of scope**: `docs/source/api/generated/**` (Sphinx autosummary
  output, regenerated from docstrings); `tests/*.py` docstrings (per
  CLAUDE.md, asserts + names tell the story); CHANGELOG.md history
  (only the most recent few entries audited; history is preserved).

## Style guide (canonical, to be referenced by future PRs)

This is the prescriptive section. Future PRs should match these
conventions; reviewers should reject deviations citing this guide.

### Python docstrings

Anchors: CLAUDE.md §11–§12.

**Module docstring** — required for every module except `__init__.py`.
One line, "owns X" framing. Example: `"""SSH and rsync transport
primitives."""`.

**Class docstring** — required for every class in `__all__`. One line
summary. Attributes self-document via type hints + frozen dataclass
field list; only add an `Attributes:` block if a field has non-obvious
semantics (rare).

**Public function docstring** — required for every function in
`__all__`. Imperative mood (`"Build X"`, not `"Builds X"`). One-line
summary. Add a blank line + paragraph when the *why* or invariants
aren't obvious from the signature.

NumPy-style `Parameters` / `Returns` / `Raises` sections appear ONLY
when adding real information not expressible in types. Skip for trivial
accessors. The reference exemplar is `provider.py:38
select_gpu_across_datacenters` — multi-paragraph form because the
failover semantics + price-filter edge case ("GPUs missing from prices
are treated as 'unknown, allow'") can't be expressed in types.

**Private function docstring** — optional. Add only when intent isn't
obvious from name + signature.

**Comments** — default NONE per CLAUDE.md §12. Justified comments
explain non-obvious algorithms, invariants, or workarounds. Examples
of justified comments in the repo today:
- `orchestrator.py:464–465`: two-pass variable-rendering algorithm
- `provider.py:194–195`: help-text parsing regex
- `provider.py:209`: function-level cache mechanism
- `preflight.py:40`: universal-noise-excludes invariant (scanner ↔
  rsync must agree)
- `telemetry.py:130`: sample-first algorithm consequence

**Anti-patterns to flag in review:**
- Docstrings that restate the type signature
- Descriptive mood (`"Returns the X"`) when imperative would be tighter
  (`"Return the X"`)
- Multi-paragraph descriptions of trivial accessors
- Inline comments that restate what the next line of code says

### Markdown recipes

Anchor: `docs/source/recipes/local-preflight-then-run.md` is the
canonical exemplar. Every recipe should match this structure:

```markdown
# Recipe: <pattern name>

**Pattern:** one-sentence summary directly under the title.

## Why this is a recipe, not a schema feature

SRP framing — what this recipe owns vs. what `runpod-deploy` owns.
Anchor in the deployment-primitives vs. consumer-domain boundary.

## Pattern (bash | Makefile | Python)

[concrete code block, properly fenced with language tag]

## What lives where

| Concern | Owner |
|---|---|
| ... | ... |

## Anti-pattern to avoid

Explicit do-not-do warning, with reason.

## See also

- [sibling-recipe.md](sibling-recipe.md) — why it's relevant
```

**Required sections** (in this order): title, one-line pattern summary,
SRP-framing section, concrete code block, owner-per-concern table,
anti-pattern warning, see-also cross-links.

**Optional sections** that some recipes legitimately add (extending
the template):
- Detailed pitfalls section (`multi-config-sweep.md` does this well for
  bash semaphore semantics)
- Multiple pattern variants (sequential + parallel, Makefile + Python)
- Enforcement section (e.g., `predictions-only-eval.md`'s Python unit
  test that asserts the contract)

These are encouraged when they add real value; they should appear
*after* the required sections, not replace them.

### docs/source/ top-level prose

Each top-level doc serves a distinct audience. The audience drives the
structure:

| Doc | Audience | Required shape |
|---|---|---|
| `quickstart.md` | New user, ≤5 min to first success | Prerequisites → install → minimal YAML → validate → dry-run → real run → next steps |
| `lifecycle.md` | Intermediate, wanting to understand the pod lifecycle | Per-phase explanation (validate → provision → SSH → setup → staging+preflight+launch+monitor → pull → stop → manifest) with YAML-section + code-symbol mappings |
| `config-reference.md` | Authoring YAML configs | Invocation modes → minimal annotated YAML → required fields → per-section reference |
| `examples.md` | Looking for example configs | Auto-generated bullet list; each example has a one-liner |
| `extending.md` | Building on top of runpod-deploy | Three tiers: no-fork consumers → Python library users → contributors. SRP boundary at the bottom |
| `migration-v3.md` | Migrating an existing consumer from a prior tool | Why migrate → one-time setup → per-job walkthrough → regression testing → backwards-compat timeline |
| `release.md` | Maintainers cutting releases | PyPI setup → GitHub environment → step-by-step release → failure modes |
| `runpod-gotchas.md` | Arriving via an old bookmark | Redirect/stub pointing at the canonical sections of `troubleshooting.md` |
| `troubleshooting.md` | Debugging a failure | Organized by lifecycle phase; each entry: **Symptom** → **Diagnosis** → **Fix** |
| `index.md` | Sphinx TOC entry | toctree only, no prose |

Cross-cutting rules:
- Code-block fences MUST have a language tag (`sh`, `python`, `yaml`,
  `makefile`, etc.). Plain ` ``` ` blocks lose syntax highlighting and
  break the doctest gate's parser.
- Internal links use relative paths (`../quickstart.md`), not absolute
  URLs.
- Tool-version references should be either (a) clearly minimum-version
  language (`runpodctl ≥ 0.3.2`) or (b) version-agnostic guidance
  (`Check your version with runpodctl version`). Avoid bare version
  numbers in prose that will rot.

### Repo-root docs

| Doc | Audience | Role |
|---|---|---|
| `README.md` | First-time visitor | Elevator pitch + quickstart + links to docs |
| `CONTRIBUTING.md` | New contributor | 30-second contribution flow + what we won't merge |
| `AGENTS.md` | Non-Claude AI agents | Discoverability shim pointing at CLAUDE.md + public API summary |
| `DEVELOPING.md` | Contributors doing local dev | Makefile reference + test markers + golden-file workflow + debugging |
| `STYLE.md` | Public-facing summary of CLAUDE.md | Foundational principles + tooling table + brief; CLAUDE.md is the long-form |
| `CHANGELOG.md` | Users tracking versions | Keep-a-Changelog format; `[Unreleased]` at top + per-version sections |

Cross-cutting rules:
- The four discoverability docs (README, CONTRIBUTING, AGENTS,
  DEVELOPING) should each redirect to CLAUDE.md as the canonical
  long-form. Don't duplicate the §1–§16 standards in multiple places.
- CHANGELOG entries follow `## [version] - YYYY-MM-DD — Theme` →
  `### Added/Changed/Migration note` sub-sections. Don't omit the
  theme on the version header.

## Findings by file

### Python (13 modules)

**`__init__.py`** — OK. Module docstring present (`"Config-driven
RunPod orchestration."`). 28 re-exports; all imports, no functions
defined here. `__all__` is alphabetized.

**`_config_parsers.py`** — OK. Module docstring present. 3 public
functions in `__all__`; all have one-line imperative docstrings. ~20
private `_parse_*` and `_as_*` helpers have no docstrings, which is
correct per the style guide — names + type signatures self-document.

**`cli.py`** — NICE-TO-HAVE × 1. Module docstring present. `main()`
has minimal docstring (`"CLI entry point."`) which is appropriate for
an argparse dispatcher. 18+ private helper functions; most have
one-line docstrings; a few self-documenting helpers (`_parse_var_arg`,
`_load_vars_file`) have multi-line docstrings explaining grammar
constraints — justified.
- **NICE-TO-HAVE finding (cli.py:208)**: Inline comment `# Sort by
  price ascending (None last), then gpu_id.` is redundant with the
  visible `rows.sort(key=...)` and key tuple `(row[1] is None, row[1]
  or 0.0, row[0])`. Per CLAUDE.md §12 ("default none"), remove.

**`config.py`** — OK. Module docstring present. 15 frozen dataclasses
in `__all__`; each has a one-line summary. Two dataclasses with
non-obvious semantics (`RsyncPushSpec`, `SecretSpec`) have multi-line
docstrings explaining exclude-list semantics and env-vs-file mutual
exclusion. `build_job_context` has a multi-line docstring explaining
CLI variable override semantics. All justified.

**`forensics.py`** — OK. Multi-line module docstring explains the
artifact-inspection role + error-handling philosophy ("pure helpers;
no subprocess; all errors → WARNING"). All 3 public functions have
appropriate docstrings.

**`manifest.py`** — OK. Module docstring present.
`build_pull_manifest` has a multi-line docstring explaining v2 field
defaults + backward compat. Private helpers `_render_artifact` and
`_estimated_cost_usd` have no docstrings — names self-document.

**`metadata.py`** — OK. Module docstring present. Both public functions
have multi-line docstrings explaining return-dict keys + the
never-raises guarantee.

**`orchestrator.py`** — OK. This module contains some of the best
docstrings in the codebase. `run_job` has a multi-line docstring
explaining the intentional ~70-line linear body (past the 50-line soft
ceiling per CLAUDE.md §8) and documents the `print_run_dir` rare
feature. `_build_python_pin_preflight` explains *why* it runs as
`preflight[0]` not `setup[0]` — a non-obvious ordering choice. Inline
comments at lines 464–465 explain the two-pass template-rendering
algorithm. Reference exemplar for "explain the non-obvious in prose
when types can't."

**`preflight.py`** — OK. Module docstring present. All 4 public
functions have multi-line docstrings explaining iteration order +
filtering semantics. Private `_path_matches_rsync_exclude` has a
detailed docstring with an examples-block — justified because rsync's
exclude grammar is non-obvious.

**`pricing.py`** — OK. Multi-line module docstring explains GraphQL
endpoint + 1h cache TTL + warning-only error handling + stdlib-only
constraint. `fetch_gpu_prices` has multi-line docstring explaining env
var lookup + cache + errors.

**`provider.py`** — OK. Module docstring present.
`select_gpu_across_datacenters` (line 38) is the canonical style
exemplar — multi-paragraph docstring explaining failover semantics +
the "GPUs missing from prices are treated as 'unknown, allow'" edge
case. `_supported_pod_create_flags` has a multi-line docstring with a
NumPy-style `Returns` block — justified because the function caches +
falls back on probe failure, both of which need explanation.

**`telemetry.py`** — OK. Multi-line module docstring explains
never-aborts-a-run invariant + exposed fields. `TelemetrySession`
class docstring clarifies that it's intentionally mutable (background
thread state, not config). `emit_event` docstring includes the
important `"Never raises."` guarantee. Inline comment at line 130
explains the sample-first algorithm consequence (so `stop_sampling()`
can abandon the thread).

**`transport.py`** — OK. Module docstring present
(`"SSH and rsync transport primitives."`). All 3 public classes + 9
methods have appropriate docstrings. `rsync_push` and `rsync_argv`
have multi-line docstrings explaining the `chmod` parameter grammar
(3- or 4-digit octal, mode enforcement via `--chmod=Fnnn`).

### Markdown recipes (10 files)

**`README.md`** (recipe index) — OK. Intro + index + use-case table.
The use-case table at lines 54–62 is exemplary; maps user intent to
recipes.

**`local-preflight-then-run.md`** — OK. **This is the canonical
exemplar.** All required sections present in correct order.

**`cost-reconciliation.md`** — SHOULD-FIX. Has `"Why this matters"`
(line 9) where the canonical section is `"Why this is a recipe, not a
schema feature"`. Sections present but order slightly off. Missing
"What lives where" table. Content quality is strong (concrete
manifest field references).
- **Recommended fix**: rename section, add "What lives where" table.

**`embed-deploy-metadata.md`** — SHOULD-FIX. Has `"When you need this"`
(line 8) instead of the canonical section name. Missing "Anti-pattern"
section. Otherwise strong.
- **Recommended fix**: rename section, add "Anti-pattern to avoid"
  (e.g., "Don't manually parse `git rev-parse HEAD` when `capture-env`
  emits it for you").

**`flash-attention-fallback.md`** — **MUST-FIX**. Multiple missing
sections:
- Missing "Why this is a recipe, not a schema feature" entirely;
  jumps straight from one-liner to code snippet.
- "Why this matters with runpod-deploy" (line 31) conflates "why it
  matters" with "why it's not a schema feature."
- Missing "What lives where" table.
- Missing explicit "Anti-pattern to avoid" section.

This recipe deviates the most from the canonical template. **Highest
priority for normalization.**

**`local-postprocess-after-run.md`** — SHOULD-FIX. All required
sections present but "Inspecting what came back" (lines 33–42) blurs
into tutorial; should be a "What lives where" table for consistency.
- **Recommended fix**: add formal "What lives where" table.

**`multi-config-sweep.md`** — SHOULD-FIX. SRP framing is alluded to in
line 7 but not as a formal section. Pitfalls section (lines 143–191)
is exceptional — the `wait -n` + `set -e` interaction docs at lines
156–176 are gold-standard troubleshooting. Missing formal "What lives
where" table.
- **Recommended fix**: promote line 7 to a formal section; add "What
  lives where" table.

**`predictions-only-eval.md`** — SHOULD-FIX. Missing "What lives
where" table. Missing "Anti-pattern to avoid". "Enforcing the contract"
(lines 50–66) is an excellent extension that should stay.
- **Recommended fix**: add the two missing sections.

**`reproducibility.md`** — SHOULD-FIX. Structure deviates: opens with
"Problem" instead of canonical one-liner. Missing "Why this is a
recipe" section. Missing "What lives where" table. Other sections
("When to use minor vs patch pinning", "Failure mode") are valuable
extensions.
- **Recommended fix**: restructure to match template; preserve the
  extension sections.

**`stock-out-diagnostic.md`** (from PR #84, not yet merged to main) —
OK. Written to match the canonical template exactly (the PR was
intentionally exemplary).

### docs/source/ top-level (10 files)

**`index.md`** — OK. Sphinx toctree, clean hierarchy.

**`quickstart.md`** — OK. 7 sections, clean progression. Minor: line
48 has a GitHub URL reference; ideally would use internal link if docs
are self-hosted.

**`lifecycle.md`** — OK. 8 phases with ASCII flowchart. Minor: line 31
links to `orchestrator.py` on the main branch; should point at tagged
release for versioned docs.

**`config-reference.md`** — OK. Strong reference structure.

**`examples.md`** — NICE-TO-HAVE. Auto-generated; some examples have
"(no README.md; see the contained `*.yaml`)" which is less
discoverable. Optionally write per-example READMEs.

**`extending.md`** — **SHOULD-FIX (consequential).** The doc has good
three-tier structure (consumers / library users / contributors) with
explicit SRP boundary at the bottom. The Python-API section (lines
70–113) introduces the public surface in a table, shows an example
driver, and warns about pitfalls. **What it does NOT do** is answer
the question the reader actually has when they land on this page:
"should I use Python or the CLI?"

The closest the doc comes:
- Line 81: `"Lower-level orchestration primitives (rarely needed; the
  orchestrator wraps them)."` — narrow guidance about a specific
  subset.
- Lines 100–101: `"This is the in-process equivalent of the bash
  sweep recipe."` — equivalence statement without a decision criterion.

A reader finishing this section knows *how* to use the Python API but
not *when*. They're left to guess: "Am I supposed to write a Python
driver instead of a Makefile target? When?" Both current consumers
(`post_transformers`, PID) appear to have answered this guess with
"always CLI" — possibly correctly, possibly by default.

- **Recommended fix**: add a "When to use the Python API vs. the CLI"
  subsection at the top of §2 with the 4 strong + 2 weak use cases
  from this audit's Consumer-fit scorecard. Cross-link to the new
  `python-api-vs-cli.md` top-level doc and the new
  `python-api-for-forensics.md` recipe.

**`troubleshooting.md`** — SHOULD-FIX. References `runpodctl v0.3.2`
feature-detection (line 25) which may become stale as `runpodctl`
evolves.
- **Recommended fix**: replace with version-agnostic guidance ("If
  your `runpodctl` doesn't support `--min-vcpu-count`...") or
  minimum-version language ("requires `runpodctl ≥ 0.3.2`").

**`runpod-gotchas.md`** — OK. Redirect/stub pointing at
`troubleshooting.md`. Explains the refactor.

**`release.md`** — OK. PyPI Trusted Publishing flow accurately
documented.

**`migration-v3.md`** — SHOULD-FIX. **Underdeveloped at 23 lines.**
Reads as a stub. No explanation of: why migrate, one-time setup,
per-job walkthrough, regression testing, backwards-compat timeline.
- **Recommended fix**: expand to ~150 lines covering the standard
  migration-doc shape (see Style Guide § Top-Level).

### Repo-root docs (6 files)

**`README.md`** — OK. Strong elevator pitch + copy-pasteable
quickstart + examples table.

**`CONTRIBUTING.md`** — OK. Brief but complete.

**`AGENTS.md`** — OK. Strong discoverability shim.

**`DEVELOPING.md`** — NICE-TO-HAVE × 1. Comprehensive content. **Typo
at line 16**: `git clone https://github.com/brandon-behring/coverage-deploy.git`
should be `runpod-deploy.git`.

**`STYLE.md`** — OK. Foundational principles + tooling table + public
API surface + security policy.

**`CHANGELOG.md`** — OK. Latest few entries (v0.8.0, v0.7.9, v0.7.8)
are detailed and well-structured. Historical entries (not audited)
preserved per policy.

## Consumer-fit scorecard

Surfaces are scored by both consumers' actual usage (data from
parallel-Explore-agent profiling). "Used heavily" = present in the
consumer's hot path (Makefile target invoked repeatedly). "Used
occasionally" = present in docs or non-default targets. "Not used" =
the consumer does not touch this surface.

### CLI subcommands

| Subcommand | post_transformers | PID | Doc priority |
|---|---|---|---|
| `validate` | Used heavily (`make validate`, `make validate-strict`) | Used heavily (preflight before every billed run) | TIER 1 |
| `run` | Used heavily (`make smoke-cloud`, `make bench-cloud`) | Used heavily (`make headline-*`) | TIER 1 |
| `logs` | Used occasionally (docs only) | Used occasionally (docs only) | TIER 2 |
| `stop` | Used occasionally (emergency teardown) | Used occasionally (cost-cap breach) | TIER 2 |
| `estimate` | Used occasionally (cost preview docs) | Used heavily (`run --dry-run` is the canonical preview) | TIER 1 |
| `gpu-list` | Not used | Not used | TIER 3 |
| `gpu-prices` | Not used | Not used | TIER 3 |
| `gpu-inventory` (from PR #85) | Not used (yet) | Not used (yet) | TIER 3 |
| `manifest-summary` | Not used | Used (via `cost_rollup.py`'s wrapper) | TIER 2 |
| `ls-runs` | Not used | Not used | TIER 3 |
| `compare-runs` | Not used | Not used | TIER 3 |
| `events`, `events-query` | Not used | Not used | TIER 3 |
| `capture-env` | Not used | Not used | TIER 3 |

### YAML schema fields

| Field | post_transformers | PID | Doc priority |
|---|---|---|---|
| `schema_version` | Set to 2 | Set to 2 | TIER 1 |
| `name`, `run_id_prefix`, `state_file` | All set | All set | TIER 1 |
| `pod.image`, `pod.datacenters`, `pod.gpu_order`, `pod.cloud_type` | All set | All set (8-tier `gpu_order` per ADR-020) | TIER 1 |
| `pod.python_version` | Set | Not set | TIER 2 |
| `pod.gpu_count`, `pod.spot`, `pod.min_vcpu_count`, `pod.min_memory_gb` | Not set | Not set | TIER 3 |
| `storage.mode` (ephemeral) | Set | Set | TIER 1 |
| `storage.volume_gb` | Set | Set | TIER 1 |
| `storage.mode` (network_volume) | Not used | Not used | TIER 2 (still documented; for future) |
| `ssh.key_path` | Set | Set | TIER 1 |
| `budget.cost_cap_usd`, `budget.assumed_hourly_rate_usd`, `budget.poll_interval_sec` | All set | All set | TIER 1 |
| `budget.max_runtime_minutes` | Not set | Not set | TIER 2 |
| `setup[*]` | Set (rsync install, uv install) | Set (rsync, uv, HF_TOKEN write) | TIER 1 |
| `staging[*]` (`source`, `destination`, `excludes_default`, `excludes_extra`) | Set | Set | TIER 1 |
| `secrets` | Not set | Set (HF_TOKEN) | TIER 2 |
| `remote_env.exports`, `remote_env.source_files` | Not set | Set | TIER 2 |
| `preflight[*]` | Not set | Set (1 command: `uv sync --extra dev`) | TIER 2 |
| `run.script_path`, `run.log_path`, `run.success_marker`, `run.body` | All set | All set | TIER 1 |
| `artifacts[*]` | Set (log only) | Set (predictions + checkpoints + logs) | TIER 1 |
| `stop.on_success`, `stop.on_failure` | Both set | Both set (PID preserves on failure for forensics) | TIER 1 |

### Manifest JSON fields (the de-facto API surface for `cost_rollup.py`)

| Field | post_transformers | PID | Doc priority |
|---|---|---|---|
| `run_id` | Not parsed | Parsed (`cost_rollup.py:56`) | TIER 1 |
| `job_name` | Not parsed | Parsed | TIER 1 |
| `wall_time_sec` | Not parsed | Parsed | TIER 1 |
| `estimated_cost_usd` | Not parsed | Parsed | TIER 1 |
| `gpu_id` | Not parsed | Parsed | TIER 1 |
| `datacenter_id` | Not parsed | Parsed | TIER 1 |
| `pod_final_state` | Not parsed | Parsed (asserted `== "EXITED"`) | TIER 1 |
| `gpu_price_per_hour_usd`, `gpu_price_source` | Not parsed | Not parsed | TIER 2 |
| `failed` | Not parsed | Not parsed (PID uses `pod_final_state`) | TIER 2 |
| `local_git_sha`, `payload_lockfile_sha256` | Not parsed | Not parsed | TIER 2 |

### Python API (`runpod_deploy/__init__.py`)

| Re-export | post_transformers | PID | Use case it serves | Recommendation |
|---|---|---|---|---|
| Config types (15 × `*Spec` + `JobContext`) | Not imported | Not imported | Type-safe config construction / inspection | KEEP |
| High-level ops (`load_job_spec`, `build_job_context`, `run_job`, `validate_local_paths`) | Not imported | Not imported | Embedded orchestration | KEEP |
| Pricing (`GpuPrice`, `fetch_gpu_prices`, `select_price_for_pod`) | Not imported | Not imported | Cost-prediction tooling | KEEP |
| Metadata (`capture_local_git`, `capture_payload_lockfile`) | Not imported | Not imported | Custom deploy metadata | KEEP |
| Errors (`RemoteRunError`) | Not imported | Not imported | Catch-block ergonomics | KEEP |
| Constants (`STORAGE_*`, `DEFAULT_STAGING_EXCLUDES`, `SCHEMA_VERSION`) | Not imported | Not imported | Comparing against loaded specs | KEEP |
| Forensics (`walk_run_dirs`, `load_manifest`, `load_events`) | Not imported | **Would be used** (`cost_rollup.py` hand-rolls JSON parsing because these aren't re-exported) | Multi-manifest forensics | **ADD** to `__init__.py` |
| Low-level plumbing (`PodConnection`, `RemoteRunner`, `select_gpu_across_datacenters`, `resolve_volume`, `rsync_argv`) | Not imported | Not imported | Weak — direct construction is rare | KEEP for v0.9; consider trim in v1.0 |

**The single actionable Python-API finding:** PID hand-rolls
`json.loads()` + `Path.glob()` in `scripts/cost_rollup.py` because
`runpod_deploy.forensics` isn't in `__init__.py`'s re-exports. Adding
`walk_run_dirs`, `load_manifest`, `load_events` to the top-level API
would let PID drop its manual parsing in favor of type-checked access.
This is non-breaking (additive) and ships in PR-A.

## Breaking-change candidates

**None met the strict bar.**

The strict bar from the plan: candidates only ship if (a) the
improvement is meaningful (not bikeshedding) AND (b) the migration is
mechanical (a 1-line YAML or Makefile edit per consumer per change).

The audit considered these candidates and rejected each:

1. **Rename `--dry-run` / `--offline-dry-run` to clarify relationship.**
   Considered: rename to `--dry-run` + `--dry-run-no-network`.
   Rejected: the existing names are descriptive enough; both consumers
   use them without confusion; migration would touch every config and
   Makefile target for a minor clarity gain.

2. **Rename `staging[].excludes_default` boolean.** Considered: the
   name is ambiguous — does it mean "default value for excludes" or
   "toggle whether the default exclude set applies"? Rejected: both
   consumers use the current name without issue; renaming would force
   every config to migrate; the field is correctly documented in
   `config-reference.md`.

3. **Consolidate `validate` flags (`--all`, `--check-local`,
   `--scan-consumer`, `--check-availability`).** Considered: a
   single `--checks=foo,bar` interface would be tidier. Rejected:
   the current flag-per-check pattern matches argparse conventions
   used elsewhere in the CLI; both consumers use `--all` exclusively
   so they wouldn't benefit from the change.

4. **Rename manifest fields for consistency.** Considered: e.g.,
   `wall_time_sec` → `walltime_seconds` for explicitness. Rejected:
   PID's `cost_rollup.py` parses 5+ fields by name; ADR-020 locks the
   names; cost of migration vastly exceeds any naming improvement.

5. **Rename `gpu-list` to `gpu-stock` to match terminology used
   elsewhere.** Considered: the recipes consistently say "stock-out"
   not "list-out"; `gpu-list` doesn't list all GPUs universally, just
   the configured DC's. Rejected: neither consumer uses `gpu-list`;
   the rename has near-zero impact (no migration needed) but also
   near-zero benefit (no one reads its `--help` text in their hot path).

6. **Trim Python API plumbing from `__init__.py`** (`PodConnection`,
   `RemoteRunner`, `select_gpu_across_datacenters`, `resolve_volume`,
   `rsync_argv`). Considered: these are low-level surfaces no one
   imports today. Rejected per user's "future consumers might"
   guidance; deferred to v1.0 once recommended-API docs have settled
   and no one has complained.

**Honest conclusion:** the codebase is in remarkably good shape. No
CLI/YAML/manifest renames are justified at this time. The audit's
"breaking-change shortlist" is empty.

## Normalization plan

Because no breaking changes are justified, the plan collapses from
4 phases to 1 phase: **the doc-only PR (PR-A)**. Phase 3 (PR-B v0.9.0)
and Phase 4 (consumer migration issues) are skipped.

### PR-A: doc-only normalization + Python-API discoverability

Branch: `docs/normalize-2026-05`

**Files edited / created:**

| Tier | File | Action | Severity |
|---|---|---|---|
| Audit | `docs/audits/docstrings-2026-05-17.md` | NEW (this report) | — |
| Python | `src/runpod_deploy/cli.py` (line 208) | EDIT (remove redundant comment) | NICE |
| Python | `src/runpod_deploy/__init__.py` | EDIT (ADD `walk_run_dirs`, `load_manifest`, `load_events` from forensics; expand module docstring with "when to use Python API vs CLI") | Non-breaking addition |
| Python | NEW `tests/test_init_reexports.py` | NEW (one-line import test for the 3 new forensics re-exports) | — |
| Recipes | `docs/source/recipes/flash-attention-fallback.md` | EDIT (add SRP section, "What lives where" table, "Anti-pattern" section) | **MUST** |
| Recipes | `docs/source/recipes/cost-reconciliation.md` | EDIT (rename "Why this matters" → canonical section name; add "What lives where" table) | SHOULD |
| Recipes | `docs/source/recipes/embed-deploy-metadata.md` | EDIT (rename "When you need this" → canonical section name; add "Anti-pattern" section) | SHOULD |
| Recipes | `docs/source/recipes/local-postprocess-after-run.md` | EDIT (add formal "What lives where" table) | SHOULD |
| Recipes | `docs/source/recipes/multi-config-sweep.md` | EDIT (promote SRP allusion to formal section; add "What lives where" table) | SHOULD |
| Recipes | `docs/source/recipes/predictions-only-eval.md` | EDIT (add "What lives where" + "Anti-pattern" sections) | SHOULD |
| Recipes | `docs/source/recipes/reproducibility.md` | EDIT (restructure: add Pattern one-liner, SRP section, "What lives where" table; preserve extension sections) | SHOULD |
| Top-level | `docs/source/extending.md` (§2 Library users) | EDIT (add "When to use the Python API vs. the CLI" subsection with the 4 strong + 2 weak use cases; cross-link to the new dedicated doc + recipe) | **SHOULD** |
| Top-level | `docs/source/troubleshooting.md` (line 25) | EDIT (replace `v0.3.2` reference with version-agnostic language) | SHOULD |
| Top-level | `docs/source/migration-v3.md` | EDIT (expand from 23 lines to ~150 lines with full migration-doc shape) | SHOULD |
| Top-level | NEW `docs/source/recipes/python-api-for-forensics.md` | NEW (the Python-API-use-case recipe, references the new forensics re-exports) | — |
| Top-level | NEW `docs/source/python-api-vs-cli.md` | NEW (the 4 strong + 2 weak use cases from the scorecard) | — |
| Sphinx | `docs/source/index.md` | EDIT (add 2 new docs to toctree) | — |
| Repo-root | `DEVELOPING.md` (line 16) | EDIT (fix typo: `coverage-deploy` → `runpod-deploy`) | NICE |
| CHANGELOG | `CHANGELOG.md` `[Unreleased]` | EDIT (add Documentation + Added sub-sections) | — |
| Version | `runpod_deploy/__init__.py` + `pyproject.toml` | NO CHANGE | — |

**Total: ~17 files edited or created.** Diff is roughly:
- ~20 lines deleted (the one redundant `cli.py` comment + a few stale
  references)
- ~600–800 lines added (the audit report itself + 2 new docs +
  expanded `migration-v3.md` + recipe section additions)
- ~100 lines edited in place (recipe section renames + structural
  insertions)

**Version recommendation:** because the only code change is the
additive `forensics` re-exports, a **v0.8.1 patch bump** is appropriate
(non-breaking; new public-surface members are an "Added" entry, not
"Changed"). Alternatively stay at v0.8.0 for a pure-docs framing and
let the next functional change pick up the bump.

**Gate plan:**

```bash
make lint    # ruff + black + mypy strict
make test    # 312+ tests pass (new tests/test_init_reexports.py adds 3)
make doctest # pytest-markdown-docs validates new + edited recipes
cd docs && make html  # Sphinx build succeeds; expect 34 pre-existing
                      # autosummary warnings (no new ones)
```

## Out of scope

- `docs/source/api/generated/**` — Sphinx autosummary output. Rebuilt
  from docstrings; not human-edited. Will reflect any docstring edits
  automatically.
- `tests/*.py` docstrings — per CLAUDE.md, asserts + descriptive names
  tell the story. Test files already follow the convention.
- `CHANGELOG.md` history — only the most recent few entries (v0.7.8
  onward) were audited; pre-existing entries are preserved per
  Keep-a-Changelog convention.
- Python API rearrangement — per user's "future consumers might"
  guidance, the trim of low-level plumbing from `__init__.py` is
  deferred to a future v1.0.
- Breaking changes — none met the strict bar; see §6.
- Consumer-repo edits — both consumers continue to work unchanged
  against v0.8.x; no consumer-side action is required.

## Appendix: artifacts and references

- This audit: `docs/audits/docstrings-2026-05-17.md`
- Canonical Python style reference:
  `src/runpod_deploy/provider.py:38 select_gpu_across_datacenters`
- Canonical recipe template: `docs/source/recipes/local-preflight-then-run.md`
- Operational long-form standards: `CLAUDE.md` (internal-only)
- Public-facing style summary: `STYLE.md`
- Plan that produced this audit:
  `~/.claude/plans/let-s-resolve-everything-delightful-moonbeam.md`
