# ADR 0001: Config-First Jobs

## Decision

`runpod-deploy` v1 is config-first and supports one job per YAML config.

## Rationale

The repo needs to serve many projects without becoming a collection of
project-specific conditionals. YAML owns project commands and paths; the core
owns RunPod mechanics.
