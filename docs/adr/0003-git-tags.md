# ADR 0003: Git Tags For Stable Consumption

## Decision

After local editable use, consumer repos should depend on Git tags.

## Rationale

This matches the current local project workflow and avoids PyPI release overhead
while still making dependencies reproducible.
