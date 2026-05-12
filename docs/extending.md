# Extending runpod-deploy

Version 1 is config-first. A new project should add a YAML file in its own repo
and validate it before editing `runpod-deploy` core code.

Use core config fields for:

- staging local code/data with rsync
- remote setup commands
- remote preflight checks
- a detached run script
- artifact pulls

Do not add provider or project conditionals for a one-off need. If two projects
need the same dynamic behavior, add a narrow, versioned hook slot in a future
schema version.

Reserved future hook categories:

- local preflight
- dynamic remote run script generation
- dynamic artifact pull path generation
- manifest enrichment
