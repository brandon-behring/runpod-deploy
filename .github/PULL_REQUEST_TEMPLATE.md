<!-- One-line summary that fits in the PR title. Optional details below. -->

## Summary

<!-- 1–3 bullets: what changed and why. -->

-
-

## Testing

<!-- Mark anything that applies. -->

- [ ] `make ci` green locally (lint + test + coverage)
- [ ] New tests added (unit / smoke / integration / golden)
- [ ] Existing tests still pass; no regressions
- [ ] Golden files reviewed (`tests/fixtures/golden/*.txt`) — only intentional changes
- [ ] `--update-goldens` ran cleanly if any CLI output format changed

## Risk

<!-- Pick one. Anything more than "minimal" needs a line of explanation. -->

- [ ] **Minimal** — pure docs, dead-code removal, additive feature with default-off
- [ ] **Moderate** — public-API surface change with back-compat, new schema field, new CLI flag
- [ ] **High** — breaking change, schema bump, dependency upgrade, retired feature

## Documentation

- [ ] `CHANGELOG.md` `[Unreleased]` entry added
- [ ] `MIGRATION.md` updated if this is a schema change (per the additive-change policy)
- [ ] `docs/config-reference.md` updated if a new YAML field landed
- [ ] `docs/recipes/` updated if a composition pattern changed
- [ ] `docs/troubleshooting.md` updated if a new failure mode is being introduced or addressed

## Linked issues

<!-- Closes #X, fixes #Y, refs #Z. -->

Closes #
