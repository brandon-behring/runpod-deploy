# ADR 0002: Defer Hook Execution

## Decision

Version 1 documents future hook slots but does not execute hooks.

## Rationale

Hooks are useful but become public API immediately. Deferring them keeps the
first schema small while V3 proves the config-only path.
