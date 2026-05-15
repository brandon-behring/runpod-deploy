# Security policy

## Supported versions

| Version | Supported |
|---|---|
| 0.7.x | ✅ active |
| 0.6.x | ✅ critical fixes only |
| ≤ 0.5.x | ❌ no longer supported |

Versions prior to v0.7.0 predate the comprehensive test + golden-file
coverage; upgrade to v0.7.x for any security-relevant change.

## Reporting a vulnerability

Please **do not** open a public GitHub issue for vulnerabilities.

Email `brandon.m.behring@gmail.com` with:

- A description of the vulnerability and its impact.
- Steps to reproduce (config + command + observed behavior).
- The version (`runpod-deploy --version` or `pip show runpod-deploy`).
- Whether the issue affects deployed pods (remote-execution risk) or
  only local-side concerns (config parsing, manifest writing).

Expected response time: **within 5 business days**. If the
vulnerability is confirmed, a fix will be cut on a `security/<id>`
branch, reviewed privately, and released as a patch version (e.g.,
`0.7.x+1`). A coordinated disclosure happens within 30 days of fix
release.

## What's in scope

- **Authentication**: anything affecting `runpodctl` API token handling, SSH key resolution, secret rsyncing.
- **Arbitrary remote code execution**: any path where a malformed YAML config could cause unexpected pod-side commands.
- **Secrets leakage**: any path where `secrets[*].source_env` values could be logged, written to disk un-redacted, or transmitted unencrypted.
- **Local-side path traversal**: any path where a malicious YAML could read/write files outside `local.project_root`.

## What's NOT in scope

- **Bugs that don't have a security impact** — file a normal GitHub issue.
- **Vulnerabilities in `runpodctl` itself** — report to https://github.com/runpod/runpodctl.
- **Vulnerabilities in dependencies** — `pip-audit` runs in CI; if you find one the audit missed, please report it.
- **Vulnerabilities in the consumer's own code** that `runpod-deploy` ships to a pod — that's the consumer's responsibility.

## Security-relevant features

- **Trusted Publishing** for PyPI releases: no API tokens stored as repo secrets; OIDC-based per `docs/release.md`.
- **Secrets handling**: see `docs/config-reference.md` "Secrets" + `docs/troubleshooting.md` "Secrets unavailable on ephemeral pods". `secrets[*].source_env` reads from local env vars only; values never logged.
- **`gitleaks`** pre-commit hook prevents accidental secret commits.
- **`pip-audit`** CI job (since v0.7.2) flags CVEs in declared dependencies.
- **No `assert` in `src/runpod_deploy/`**: stripped under `python -O`; all validation uses stdlib exceptions (see CLAUDE.md §6).
