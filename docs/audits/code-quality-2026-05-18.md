# Code-Quality & Organization Audit — 2026-05-18

## Executive summary

This audit covers four surfaces of `runpod-deploy` v0.8.3: code quality
in `src/runpod_deploy/` (13 modules, 6,014 LOC), organization
(dependency graph, public API, layering), documentation (re-baselined
post-v0.8.3), and tests + CI hygiene. It complements the prior
documentation-only audit at
[`docstrings-2026-05-17.md`](docstrings-2026-05-17.md) (1 day old);
prior findings have been largely resolved during the v0.8.2 + v0.8.3
work and are tracked under §C below.

**Headline findings:**

| Surface | MUST-FIX | SHOULD-FIX | NICE-TO-HAVE | OK |
|---|---|---|---|---|
| A. Code quality | 0 | 2 | 1 | 9 |
| B. Organization | 0 | 1 | 1 | 4 |
| C. Documentation | 0 | 2 | 0 | 10 |
| D. Tests + CI | 0 | 3 | 2 | 8 |
| **TOTAL** | **0** | **8** | **4** | **31** |

**The codebase is in strong shape.** Zero MUST-FIX items. All
CLAUDE.md §3–§7, §9, §10, §13 (in the marker dimension), §14, §15, §16
checks pass. The eight SHOULD-FIX items are either narrowly-scoped
refactor opportunities (Surface A & B), focused content fixes in
documentation (Surface C), or coverage-gap-or-organization issues in
tests (Surface D). None block a release.

**Top three highest-leverage items:**

1. **`cli.py:928 main()` — 396 lines, extractable** (A1). The
   parser-building portion (~280 lines of argparse `sub.add_parser`
   calls) can move to a `_build_parser() -> argparse.ArgumentParser`
   helper. Reduces `main()` to ~60 lines (linear: build → parse →
   configure → dispatch), and makes the parser independently
   unit-testable.
2. **`provider.py:611 cleanup_pod()` — 90 lines, dispatch-by-conditional**
   (A2). Four action branches (`preserve` / `stop` / `delete` /
   `recycle`) follow the dict-handler pattern already used at
   `cli.py:1306-1323`. Extract `_cleanup_preserve/stop/delete/recycle()`
   and dispatch via dict.
3. **`docs/source/lifecycle.md` — 4 stale references to removed v0.8.3
   syntax** (C1). Lines 104, 113, 403, 406 still reference
   `runpod-deploy stop` and `stop.on_failure`. Mechanical fix; risk is
   that consumers reading lifecycle.md get a wrong mental model of the
   v0.8.3 public surface.

**Notable strengths verified:**

- Zero `assert` in `src/runpod_deploy/` (CLAUDE.md §6 ✓).
- Zero `TODO/FIXME/XXX/HACK` markers in src/ or tests/.
- Zero `print(...)` calls in src/; all output via `logger.*` (Phase H
  complete per CLAUDE.md §9).
- 20/20 dataclasses have `slots=True`; all value/config types are
  `frozen=True`; 12/12 with `__post_init__` use stdlib exceptions with
  diagnostic messages (CLAUDE.md §5–§6 ✓).
- No `Pydantic`, no `Result[T,E]`, no `_inplace`, no custom exception
  hierarchy beyond `RemoteRunError` (CLAUDE.md §15 ✓).
- All 13 modules have module-level docstrings (CLAUDE.md §11 ✓).
- Zero modern-syntax violations (`Optional[`, `List[`, `Dict[`); every
  non-`__init__.py` module has `from __future__ import annotations`
  (CLAUDE.md §4 ✓).
- Module dependency graph is clean: `cli.py` is a leaf (nothing imports
  from it); `_config_parsers.py` is only imported by `config.py`
  (private as intended). No circular imports.
- 391 tests, 390 marked; only 1 missing-marker case (D1).
- CI matrix is comprehensive: Python 3.13 + 3.14 across test/build/
  doctest/security/publish jobs. Trusted Publishing enabled for
  release.yml (no API tokens in repo secrets).
- Coverage floor drift policy correctly applied: `fail_under = 82` =
  `floor(87.36) − 5` (CLAUDE.md §13 operational addendum ✓).
- Prior-audit migration-v3.md "stub" finding is fully resolved
  (23 lines → 266 lines after v0.8.2 + v0.8.3 expansions).
- Prior-audit `extending.md` "missing Python-vs-CLI section" is fully
  resolved (new dedicated doc `python-api-vs-cli.md` + cross-link
  in `extending.md:72–102`).

**Recommended sequencing**: file the eight SHOULD-FIX items as
GitHub issues (P2, `tracked` label) so they're picked up
independently. Bundle the four NICE-TO-HAVE items into the audit doc
only — no separate issues. Top-priority for the next contributor pass
is the cli.py + provider.py refactor pair (A1 + A2), which together
remove ~400 lines of mechanical-but-tangled flow without altering
behavior.

## Methodology

- **Surface A (Code quality)**: applied CLAUDE.md §3–§16 as the
  rubric. AST-parsed every module for docstrings, dataclass discipline,
  imports. Grepped for §15 anti-patterns (Pydantic, Result, _inplace,
  custom-exception hierarchies). Counted inline comments and
  cross-checked each survivor against §12 legitimacy criteria. Read
  each function over 80 lines in full to assess soft-ceiling
  justification.
- **Surface B (Organization)**: built the intra-package dependency
  graph by grepping `from runpod_deploy.<module>`. Counted `__all__`
  symbols. Cross-referenced the documented "low-level plumbing" set in
  `python-api-vs-cli.md:141-150` with `__init__.py:__all__`. Ran a
  static dead-code scan (defined-but-not-referenced) and verified each
  candidate by-hand for actual usage in src/ + tests/ + docs/.
- **Surface C (Documentation)**: AST-checked every module for
  docstrings. Grepped recipes for the three required canonical sections
  per the 2026-05-17 audit's structural exemplar
  (`local-preflight-then-run.md`). Read every top-level Sphinx doc for
  freshness against v0.8.3 (looking for stale references to the removed
  `runpod-deploy stop` subcommand and `stop:` YAML block). Spot-read
  repo-root docs. Re-baselined against the prior audit's findings.
- **Surface D (Tests + CI)**: AST-parsed every `tests/test_*.py` for
  the marker discipline check. Read `make coverage` output and traced
  per-module gaps to specific functions. Read every workflow under
  `.github/workflows/` for matrix coverage. Read `.pre-commit-config.yaml`
  and verified it aligns with `make lint` enforcement.
- **Out of scope**: consumer-repo audit (post_transformers,
  prompt-injection-v3/v4/v5; covered separately in the v0.8.3
  migration session); performance benchmarking; security audit;
  external link liveness checks beyond a five-link sample.

## Style guide reference

The rubric is **CLAUDE.md §3–§16** at the repo root. STYLE.md is the
public-facing condensed version of the same standards. The 2026-05-17
doc-audit established the recipe template (anchored at
`local-preflight-then-run.md`) and the docs/source/ audience-driven
shape; both are reused here without restatement.

---

## Findings — Surface A: Code quality

### [SHOULD-FIX] A1. `cli.py:928 main()` at 396 lines — extract `_build_parser()`

**Why this is a finding.** CLAUDE.md §8 sets a soft ceiling of 20–50
lines per function (longer permitted when "cohesive linear flow"). The
soft ceiling is documented at `orchestrator.run_job` ~45 lines.
`main()` is 8× the soft ceiling. The size is driven by ~280 lines of
argparse subparser registration (15 `sub.add_parser(...)` blocks); the
actual dispatch logic is 4 lines via a `dict[str, Callable]` at
`cli.py:1327-1344`. The parser-building is mechanically extractable
without coupling to dispatch.

**Evidence.**
- `cli.py:928–1305` — argparse parser construction.
- `cli.py:1306–1326` — `_configure_logging` + arg parse.
- `cli.py:1327–1346` — handler dict + dispatch.

**Recommendation.** Extract `_build_parser() -> argparse.ArgumentParser`
to return the fully-configured root parser. `main()` then becomes:
```
def main(argv: Sequence[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)
    _configure_logging(_level_from_args(args))
    return _HANDLERS[args.command](args)
```
~10 lines. The handler dict can become a module-level constant
`_HANDLERS` so it's not rebuilt per call.

**Cost-of-fix.** Small (mechanical refactor, no behavior change). Add
a unit test that the extracted `_build_parser()` registers all
expected subcommands (regression against accidental removal).

**GitHub issue.** [runpod-deploy#102](https://github.com/brandon-behring/runpod-deploy/issues/102).

### [SHOULD-FIX] A2. `provider.py:611 cleanup_pod()` at 90 lines — extract action dispatch

**Why this is a finding.** Same §8 soft-ceiling logic as A1. The
function is a dispatch-by-conditional across four `LifecycleAction`
values (`preserve` / `stop` / `delete` / `recycle`). Each branch is
6–16 lines of subprocess + logging logic. The pattern is identical to
the already-clean dict dispatch used at `cli.py:1306-1323`.

**Evidence.**
- `provider.py:611` — function declaration with docstring.
- `provider.py:625-700` (approx) — four action branches.

**Recommendation.** Extract `_cleanup_preserve(...)`,
`_cleanup_stop(...)`, `_cleanup_delete(...)`, `_cleanup_recycle(...)`
(each ~6–16 lines), then dispatch via:
```
_HANDLERS = {"preserve": _cleanup_preserve, "stop": _cleanup_stop, ...}
```
`cleanup_pod()` shrinks to ~30 lines (resolve state → look up handler →
invoke → wrap errors). Each helper is independently unit-testable;
adding a future action (e.g., `archive`) becomes one-line + one helper.

**Cost-of-fix.** Small. Existing tests in
`tests/test_provider_subprocess.py` already exercise each branch; the
extraction should keep them green without modification.

**GitHub issue.** [runpod-deploy#103](https://github.com/brandon-behring/runpod-deploy/issues/103).

### [NICE-TO-HAVE] A3. ~18 inline comments in `config.py` + `orchestrator.py` restate code

**Why this is a finding.** CLAUDE.md §12 sets a zero-comment default;
legitimate exceptions are bug workarounds, subtle invariants, and
non-obvious algorithm choices. Surface A audit found ~61 inline
comments total in `src/`, of which ~43 are §12-legitimate (algorithm
notes, citations, invariants) and ~18 restate code or describe call
sites. Highest concentration in `config.py` (9) and `orchestrator.py`
(3).

**Evidence.** Specific candidate lines noted in the audit data; full
review on cleanup PR rather than this doc to avoid bit-rotting line
numbers. Notable §12-justified comments to KEEP:
- `orchestrator.py:464-465` — two-pass variable-rendering algorithm
- `provider.py:204-210` — help-text parsing regex + function-level
  cache rationale
- `preflight.py:44-48` — universal-noise excludes invariant (scanner
  ↔ rsync must agree)
- `telemetry.py:130-131` — sample-first algorithm consequence

**Recommendation.** Bundle into the next adjacent maintenance PR; do
not file as a standalone issue per CLAUDE.md §12 ("default: none").
NICE-TO-HAVE because the surviving 30% of comments don't degrade
correctness — they only mildly degrade signal-to-noise.

### [OK] A4. `orchestrator.py:53 run_job()` at 162 lines — justified linear orchestration

CLAUDE.md §8 explicitly documents `run_job` as the soft-ceiling
exemplar (~45 lines documented; now ~162 with the lifecycle-redesign
additions). Read in full: the body remains a single straight path —
validate → acquire → stage → setup → preflight → launch → monitor →
pull → cleanup. No branching state machine, no hidden coupling. Each
section is 10–40 lines and cohesive. Soft ceiling applies to *helpers*;
orchestrators are documented exceptions. **No action.**

### [OK] A5. `provider.py:445 try_resume_pod()` at 129 lines — cohesive linear guard logic

Read in full: state-file validation → pod-get check → drift detection
(image / GPU / datacenter mismatch) → resume-or-fall-through. Each
guard is a 3–6-line `if-raise` block; collectively they form one
inseparable decision flow. Could split drift detection into a separate
helper, but the cost of indirection exceeds the readability gain.
**No action.**

### [OK] A6. `src/runpod_deploy/` zero asserts, zero TODO/FIXME/XXX/HACK

CLAUDE.md §6 ✓. Verified by grep.

### [OK] A7. `src/runpod_deploy/` zero `print(...)` calls — all output via `logger.*`

CLAUDE.md §9 ✓. Phase H (logging migration) complete in commit 698c04a.

### [OK] A8. `__future__ import annotations` at top of every non-`__init__.py` module

CLAUDE.md §4 ✓. 12/12 modules.

### [OK] A9. Modern type syntax — zero `Optional[`, `List[`, `Dict[`

CLAUDE.md §4 ✓. Verified by grep across `src/`.

### [OK] A10. Dataclass discipline — `slots=True` on all 20 dataclasses

CLAUDE.md §5 ✓. All value/config/result types are also `frozen=True`.
The single non-frozen dataclass (`TelemetrySession`, `telemetry.py:35`)
is documented as runtime-state with bound-once attributes; correct per
intent.

### [OK] A11. Error discipline — stdlib only, diagnostic messages

CLAUDE.md §6 ✓. Only `ValueError` / `TypeError` / `RuntimeError` /
`FileNotFoundError` / `KeyError` in `raise` sites. The single custom
exception `RemoteRunError` (`transport.py:15-16`) is the documented
carve-out for distinguishing "SSH command failed" from "orchestrator
state error" in `orchestrator.py`. 12/12 `__post_init__` validations
use diagnostic messages (e.g., `pod.container_disk_gb must be > 0, got
{!r}`) per the §6 "caller can fix without reading internals" rule.

### [OK] A12. CLAUDE.md §15 no-go list — clean

No `Pydantic` / `LangChain` / `Result[T,E]` / `_inplace` / custom
exception hierarchies. Verified by grep.

---

## Findings — Surface B: Organization

### [SHOULD-FIX] B1. Low-level plumbing in `__init__.py:__all__` with zero known consumer usage

**Why this is a finding.** `python-api-vs-cli.md:141-150` explicitly
flags `PodConnection`, `RemoteRunner`, and `select_gpu_across_datacenters`
as "low-level orchestration plumbing surfaces" that "consumers almost
never need to call directly." Grep across the four known consumer repos
(post_transformers, prompt-injection-v3/v4/v5) returns zero imports of
any of the three. The doc says "if you have a genuine use case for the
low-level surfaces, file an issue" — implying the bar is "no current
use case, but kept for future." The bar isn't wrong, but the public
contract isn't explicit either: a user reading `__all__` doesn't see
the "you probably don't want this" framing.

**Evidence.**
- `src/runpod_deploy/__init__.py:75-121` — `__all__` lists all three.
- `docs/source/python-api-vs-cli.md:141-150` — "Do NOT use the Python
  API for ... Direct construction of `PodConnection`, `RemoteRunner`,
  or `select_gpu_across_datacenters`."
- Consumer grep: zero imports.

**Recommendation.** Pick one of:
1. **Keep `__all__` and add a docstring tag.** Annotate the three
   names with a `"""Low-level — see python-api-vs-cli.md."""` line in
   their respective definitions. Most lightweight.
2. **Demote to module-public, not package-public.** Remove from
   `__init__.py:__all__`; consumers wanting them can still
   `from runpod_deploy.provider import PodConnection` (intentional
   friction). Mildly breaking *iff* anyone is importing today (no one
   is — consumer grep is empty).
3. **Keep as-is and explicit in the audit only.** Mark this finding
   as a documented architectural choice; revisit at v1.0.

Recommend option 1 for minimal churn. The decision belongs to the
owner (see Open Questions below).

**Cost-of-fix.** Small (option 1) or small + minor public-API change
(option 2).

**GitHub issue.** [runpod-deploy#104](https://github.com/brandon-behring/runpod-deploy/issues/104).

### [NICE-TO-HAVE] B2. `report_gpu_inventory` returns `InventoryReport` but neither is in top-level `__all__`

**Why this is a finding.** `preflight.py:__all__` includes
`report_gpu_inventory`, `InventoryReport`, and `DatacenterInventory`
(module-public). But `__init__.py:__all__` re-exports none of them.
This creates asymmetry: `runpod-deploy gpu-inventory` is a documented
CLI subcommand (closed issue #66), but the equivalent Python entry
point requires `from runpod_deploy.preflight import report_gpu_inventory`
— inconsistent with the rest of the public surface (e.g.,
`from runpod_deploy import fetch_gpu_prices`).

**Evidence.**
- `src/runpod_deploy/preflight.py:21-22` — both types in
  `preflight.__all__`.
- `src/runpod_deploy/__init__.py:75-121` — neither name appears.
- `docs/source/python-api-vs-cli.md` — does not list this use case
  among the four documented Python-API entry points.

**Recommendation.** Either (a) add the three names to
`__init__.py:__all__` (additive, non-breaking), making the Python
parity with the CLI subcommand explicit, OR (b) document that
`report_gpu_inventory` is intentionally not in the top-level public
API. Defer to the owner.

**Cost-of-fix.** Tiny (3-symbol `__all__` addition + 3-line import).

### [OK] B3. Module dependency graph clean

`cli.py` is a leaf (no module imports from it). `_config_parsers.py`
is imported only by `config.py` (private-as-intended). `transport.py`,
`metadata.py`, `forensics.py`, `pricing.py` have zero intra-package
imports (correct layering — they're leaf utilities). No circular
imports. Full graph:

```
cli       -> [config, orchestrator, provider, transport]
_config_parsers -> [config]
config    -> [_config_parsers]
manifest  -> [config, provider]
orchestrator    -> [config, manifest, provider, telemetry, transport]
preflight -> [config, provider]
provider  -> [config, pricing, transport]
telemetry -> [config, transport]
(forensics, metadata, pricing, transport: zero intra-package imports)
```

### [OK] B4. Pure-vs-IO separation maintained

`manifest.py` (manifest builders), `_config_parsers.py` (YAML parsers),
`provider.build_pod_create_argv` (subprocess argv builder) are
verifiably pure (no subprocess/SSH/filesystem writes). `transport.py`,
`provider.run_json`, `telemetry.py`'s background sampler stay in thin
wrappers around subprocess/SSH/rsync. CLAUDE.md §1.4 ✓.

### [OK] B5. No dead code

Static dead-code scan flagged 6 candidates; manual verification
confirmed each is used (either inside its own module via methods or
inline calls, exported via the owning module's `__all__`, or imported
by tests). Specifically:
- `parse_ts` (cli.py): used at cli.py:552, 558.
- `callback` (orchestrator.py): closure returned by
  `_build_failover_callback`; false positive.
- `ssh_argv` (transport.py): method on `RemoteRunner`, used by other
  methods + tests.
- `build_pull_manifest` (manifest.py): in `manifest.__all__`, used by
  manifest.py + 5 test cases.
- `DatacenterInventory`, `InventoryReport` (preflight.py): in
  `preflight.__all__`, used by `preflight.report_gpu_inventory` +
  tests. (See B2 for the related package-public question.)

### [OK] B6. Public API helper discipline (CLAUDE.md §16)

Every module declares `__all__`. The package re-export
(`__init__.py:75-121`) is alphabetized. Private helpers are prefixed
with `_` and never re-exported. No leakage of internal names being
imported elsewhere as if public.

---

## Findings — Surface C: Documentation

### [SHOULD-FIX] C1. `docs/source/lifecycle.md` has 4 stale references to removed v0.8.3 syntax

**Why this is a finding.** v0.8.3 removed the `runpod-deploy stop` CLI
subcommand and the bool-valued `stop:` YAML block. The migration is
fully documented in `migration-v3.md`, the CHANGELOG, and most other
docs. But `lifecycle.md` — the canonical lifecycle-explanation doc per
the 2026-05-17 audit — still references the removed syntax in four
places. A user reading lifecycle.md will form an incorrect mental
model of the v0.8.3 public surface.

**Evidence.**
- `lifecycle.md:104` — "in `spec.resolved_state_file` for later
  `runpod-deploy stop` recovery."
- `lifecycle.md:113` — "stopped (or preserved if `stop.on_failure:
  false`)."
- `lifecycle.md:403` — "  `stop.on_failure`. Log a WARNING."
- `lifecycle.md:406` — "  `tel.capture_end()`. Stop pod per
  `stop.on_failure`."

The lifecycle.md §7 lifecycle-action table (lines 222-242) is correct;
only the prose references rotted.

**Recommendation.** Mechanical s/`runpod-deploy stop`/`runpod-deploy
cleanup --state-file ... --mode stop`/g and s/`stop.on_failure`/
`lifecycle.on_failure`/g. Verify no other prose drifted (final pass
grep for `stop.on_success`, `stop.on_failure`, `runpod-deploy stop`
across `docs/source/`).

**Cost-of-fix.** Trivial (4 edits, 1 commit).

**GitHub issue.** [runpod-deploy#105](https://github.com/brandon-behring/runpod-deploy/issues/105).

### [SHOULD-FIX] C2. 6 recipes still missing canonical sections (carry-over from 2026-05-17 audit)

**Why this is a finding.** The 2026-05-17 audit flagged 7 of 9 recipes
as missing one or more of the three canonical sections defined by the
exemplar `local-preflight-then-run.md`:
1. "Why this is a recipe, not a schema feature" (SRP framing)
2. "What lives where" table
3. "Anti-pattern to avoid" section

Since 2026-05-17, 5 new recipes were added (`forensics-then-cleanup`,
`payload-reuse-via-network-volume`, `python-api-for-forensics`,
`recycle-pod-for-fast-iteration`, `stale-pod-audit`) — only some adhere
to the template. The total surface is now 14 recipes; 6 are
non-compliant. The original audit's tier (SHOULD-FIX) is unchanged.

**Evidence.**

| Recipe | Missing |
|---|---|
| `cost-reconciliation.md` | "Anti-pattern to avoid" |
| `forensics-then-cleanup.md` | "What lives where" |
| `local-postprocess-after-run.md` | "Anti-pattern to avoid" |
| `payload-reuse-via-network-volume.md` | "What lives where" + "Anti-pattern" |
| `recycle-pod-for-fast-iteration.md` | "What lives where" + "Anti-pattern" |
| `stale-pod-audit.md` | "What lives where" + "Anti-pattern" |

**Recommendation.** One PR adding the missing sections across the
six files. Each section is 5–10 lines per recipe. Total add is
~80–100 lines.

**Cost-of-fix.** Medium (content-writing for 6 distinct domain
contexts; not mechanical).

**GitHub issue.** [runpod-deploy#106](https://github.com/brandon-behring/runpod-deploy/issues/106).

### [OK] C3. All 13 modules have module-level docstrings (CLAUDE.md §11)

AST-verified.

### [OK] C4. All 45 symbols in `__init__.py:__all__` have underlying docstrings

AST-verified. The 2026-05-17 audit had counted 28; the count is now
45 after the v0.8.3 expansions (forensics re-exports + new lifecycle
helpers). No regression — every new symbol came with its docstring.

### [OK] C5. `migration-v3.md` reflects v0.8.3 removal accurately

Verified by hand: the doc was expanded during this session to call out
"**v0.8.3 removed the bool shim**" (lines 56-59 region). Title is
"Migration notes (v0.8.2 and prompt-injection-v3)" matching the
loose-semver posture.

### [OK] C6. `troubleshooting.md` no stale `runpodctl` version pins

Prior audit flagged a `v0.3.2` reference; verified gone.

### [OK] C7. `extending.md` includes "When to use the Python API vs. CLI" section

Prior audit flagged this as missing; verified present at lines 72-102,
with cross-link to the new `python-api-vs-cli.md`.

### [OK] C8. `python-api-vs-cli.md` is complete

New file added since 2026-05-17. 162 lines, four documented use cases
(forensics, dynamic configs, cost prediction, embedded orchestration)
+ two explicit anti-patterns (parallel sweeps, low-level plumbing).
Matches the audience-driven shape the prior audit established.

### [OK] C9. Repo-root docs (README, CONTRIBUTING, AGENTS, DEVELOPING, STYLE, SECURITY) clean

All six read in full. No stale `runpod-deploy stop` references. No
broken cross-links. `DEVELOPING.md:16` typo flagged by prior audit
(`coverage-deploy`) is fixed.

### [OK] C10. CHANGELOG.md properly structured

`[Unreleased]` empty (we just cut v0.8.3). v0.8.2 and v0.8.3 sections
both dated `2026-05-18` with theme lines. Keep-a-Changelog format
followed.

### [OK] C11. Audit doc placement

`docs/audits/` directory established by the prior audit; this audit
follows the same dated-filename convention.

### [OK] C12. CLAUDE.md ↔ STYLE.md alignment

STYLE.md is the public-facing condensed version of CLAUDE.md §1–§16.
Both reflect the v0.8.3 deprecation-removal posture consistently. The
prior audit established the alignment expectation; verified still
holding.

---

## Findings — Surface D: Tests + CI hygiene

### [SHOULD-FIX] D1. `test_integration.py:381` `test_integration_module_loads` is missing a marker

**Why this is a finding.** CLAUDE.md §13 mandates that every test has
exactly one of the registered markers (`unit`, `smoke`, `network`).
`pyproject.toml:135-140` confirms the marker registry. An unmarked test
silently fails marker-selective runs (`pytest -m smoke` skips it
without warning). 390 of 391 tests are correctly marked; this is the
sole gap.

**Evidence.** `tests/test_integration.py:381 def test_integration_module_loads`.

**Recommendation.** Add `@pytest.mark.unit` (it's a synchronous import
check, no subprocess/SSH/network).

**Cost-of-fix.** Trivial (1 line).

**GitHub issue.** [runpod-deploy#107](https://github.com/brandon-behring/runpod-deploy/issues/107).

### [SHOULD-FIX] D2. `config.py` `__post_init__` validation branches at 82% coverage — real bug class

**Why this is a finding.** `config.py` is at 82% line coverage, the
lowest in `src/`. The uncovered branches cluster in the 15 `*Spec`
dataclass `__post_init__` methods (lines 96-108, 128-136, 163-173,
205-207, 230-234, 260-264, 280-284, 311-313, etc.). These are
boundary-validation paths (negative values, empty strings, type
mismatches). Per CLAUDE.md §6, these raise `ValueError` /`TypeError`
with diagnostic messages — silently accepting an invalid spec would be
a real bug class because the failure surfaces deep inside
orchestration rather than at YAML-load time.

**Evidence.** `make coverage` output: `config.py 82% (38 missed)`. Most
of the missed lines are inside `__post_init__` raise sites.

**Recommendation.** Add parametrized validation tests in
`tests/test_config.py` exercising the unhappy path for each `*Spec`'s
required fields (one test per Spec, each parametrized across its
fields). Many can be one-liners using `pytest.raises(ValueError,
match="...")` against `_write_minimal_config(...)` with an invalid
override.

**Cost-of-fix.** Medium (write ~15 parametrized tests; should lift
coverage from 82% → 90%+ on `config.py`).

**GitHub issue.** [runpod-deploy#108](https://github.com/brandon-behring/runpod-deploy/issues/108).

### [SHOULD-FIX] D3. `orchestrator.py` budget-early-return paths at 86% coverage — worth covering

**Why this is a finding.** `orchestrator.py:94-95, 186-188` are
budget-constraint early-return paths in `run_job`. Per CLAUDE.md §13,
"every operational lesson learned from a real deploy becomes a
regression test." These budget paths exist precisely because a prior
operational lesson (closed via #67 / #66 lineage) revealed cost-burn
risk; the test surface should pin the behavior.

**Evidence.** `make coverage` output: `orchestrator.py 86% (32 missed)`.
Lines 94-95 and 186-188 are budget early-returns; lines 320-322, 326,
331 are failover-callback paths.

**Recommendation.** Two new tests in `tests/test_orchestrator_run_job.py`:
(a) all candidate GPU prices exceed `budget.max_gpu_price_per_hour` →
early `RuntimeError` before pod creation; (b) all datacenters exhausted
inventory at the price cap → same.

**Cost-of-fix.** Small (2 tests using the existing `FakeSubprocess`
seam).

**GitHub issue.** [runpod-deploy#109](https://github.com/brandon-behring/runpod-deploy/issues/109).

### [NICE-TO-HAVE] D4. `tests/test_orchestrator_run_job.py` is 919 lines — split candidate

**Why this is a finding.** Soft test-file size guideline isn't in
CLAUDE.md, but the file is the only one over 900 lines and the largest
test file by ~50%. It mixes lifecycle/recycle scenarios with SSH
timeout scenarios with budget scenarios with failover-callback
scenarios.

**Evidence.** `tests/test_orchestrator_run_job.py` — 919 LOC, 19 tests.

**Recommendation.** Defer until the file grows further or a logical
split becomes obvious (e.g., when adding a new test that doesn't fit
the existing topic). Splitting prematurely fragments cohesive context.
NICE-TO-HAVE, not SHOULD-FIX.

### [NICE-TO-HAVE] D5. `_config_parsers.py` optional-field branches at 83% coverage

**Why this is a finding.** `_config_parsers.py:194, 196, 214, 216` are
branches handling YAML optional-field defaults. Coverage gap is small
(7 missed lines out of 166); marginal value.

**Recommendation.** Defer or fold into D2 if convenient.

### [OK] D6. CI matrix is comprehensive — Python 3.13 + 3.14, multi-job

`.github/workflows/test.yml` runs lint + test + coverage on Python
3.13 + 3.14 matrix, plus separate jobs for base-install verification,
published-wheel verification, doctest gate, and security scanning. No
skipped jobs. No commented-out matrix entries.

### [OK] D7. `release.yml` uses Trusted Publishing — no API tokens in repo secrets

Triggers only on `v*` tag push. Uses
`pypa/gh-action-pypi-publish@release/v1` with OIDC. Verified in this
session (v0.8.2 + v0.8.3 published in 19s + 45s respectively).

### [OK] D8. `.pre-commit-config.yaml` aligned with `make lint`

ruff + black + mypy match the Makefile target. Standard hygiene hooks
(trailing-whitespace, end-of-file-fixer, check-yaml/toml, large-file
guard, gitleaks). mypy runs at `pre-push` rather than `pre-commit` to
keep commit cycles fast.

### [OK] D9. Coverage floor drift policy correctly applied

`pyproject.toml:147` → `fail_under = 82`. Actual = 87.36%.
`floor(87.36) − 5 = 82`. Per CLAUDE.md §13 operational addendum ✓.

### [OK] D10. Marker registry per CLAUDE.md §13

`pyproject.toml:135-140` registers `unit`, `smoke`, `network`. (Also
an advisory `golden` marker for golden-file tests; not part of the §13
canonical trio but doesn't conflict.) 390/391 tests are correctly
marked; see D1 for the lone gap.

### [OK] D11. `FakeSubprocess` / `FakePopen` is the canonical seam

`tests/conftest.py:143` (approx) defines both. Used by 30+ test files
including `tests/test_orchestrator_run_job.py`, `tests/test_provider_subprocess.py`,
`tests/test_transport_subprocess.py`. Operational addendum ✓.

### [OK] D12. Operational-lesson regression tests for closed issues

Verified via grep: #88 (SSH timeout) — covered in
`test_provider_subprocess.py` + `test_orchestrator_run_job.py`. #90
(recycle lifecycle) — covered. #94 (FUSE scan) — covered in
`test_preflight.py`. #97 (image-registry HEAD) — covered in
`test_preflight_image_registry.py:189
test_check_image_registry_warns_on_404` with the canonical
`runpod/pytorch:phantom` example from the incident. Coverage of
operational lessons is healthy.

### [OK] D13. Pre-commit config freshness

Pin dates (ruff v0.15.13 May 2025, black 26.3.1 Jan 2026) are current;
no stale-pin signal.

---

## Considered and rejected

Findings that look like issues but were considered and not filed:

- **`orchestrator.py:53 run_job()` at 162 lines.** CLAUDE.md §8
  explicitly documents this as the soft-ceiling exemplar; the body is
  cohesive linear orchestration with no helper-extraction win.
- **`provider.py:445 try_resume_pod()` at 129 lines.** Same logic as
  above; cohesive linear guard flow.
- **Inline comments restating code in `config.py` + `orchestrator.py`
  (~18 cases).** Rolled into NICE-TO-HAVE A3 (not a standalone issue);
  bundle into next adjacent maintenance PR.
- **`__all__` size of 45 symbols as "too broad."** CLAUDE.md §16
  permits the broad re-export; the documented use cases in
  `python-api-vs-cli.md` actually consume most of these. No action.
- **Whether to publish the audit doc to the Sphinx site index.** Not in
  scope — audits go under `docs/audits/` and aren't indexed in
  `docs/source/index.md` per the prior precedent.
- **A `pre-commit` hook to fail on inline comments restating code.**
  No reliable mechanical check; the §12 legitimate-exception criteria
  are judgment calls. Reject; depend on review.

## Recommended sequencing

Bundle the SHOULD-FIX items into three small PRs:

**PR-A (mechanical refactor)** — A1 + A2.
- Extract `_build_parser()` in `cli.py`.
- Extract action dispatch helpers in `provider.py:cleanup_pod`.
- Add the regression test for `_build_parser` subcommand registration.
- Cost: small. Coverage should rise on both files (the per-action
  helpers become independently testable).

**PR-B (docs + recipes)** — C1 + C2 + B2 docstring tags (optional).
- Fix the 4 stale references in `lifecycle.md`.
- Add the missing canonical sections to the 6 recipes.
- Optionally: add the "low-level — see python-api-vs-cli.md" docstring
  tag for `PodConnection` / `RemoteRunner` /
  `select_gpu_across_datacenters`.

**PR-C (test coverage)** — D1 + D2 + D3.
- Add the marker to `test_integration_module_loads`.
- Add parametrized `__post_init__` validation tests for each `*Spec`.
- Add the two `run_job` budget-early-return tests.
- Should lift overall coverage from 87.36% → ~91%. Per CLAUDE.md §13
  operational addendum, bump `fail_under` to `floor(actual) − 5`
  after.

NICE-TO-HAVE items (A3, B2, D4, D5) appear in this audit doc only;
no separate issues. Fold them into adjacent PRs opportunistically.

## Open questions for the owner

1. **B1 — `PodConnection` / `RemoteRunner` / `select_gpu_across_datacenters`
   in `__all__`.** Three options: (a) keep + add docstring tag, (b)
   demote to module-public, (c) keep + revisit at v1.0. Recommend (a).
   Decision affects whether the GitHub issue's recommendation is
   "tag" vs "remove."

2. **B2 — Top-level export of `report_gpu_inventory` /
   `InventoryReport` / `DatacenterInventory`.** Add to
   `__init__.py:__all__` for parity with the CLI subcommand, or leave
   intentional friction at the `runpod_deploy.preflight` module level?
   Recommend adding (low-cost, additive); but it's a public-API
   commitment.

3. **D4 — Split `test_orchestrator_run_job.py` (919 lines)?** Defer
   recommended; revisit when the file grows or an obvious topic split
   appears. Owner may have stronger opinion on test organization.
