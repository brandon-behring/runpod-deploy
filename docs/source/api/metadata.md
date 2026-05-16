# `runpod_deploy.metadata`

Reproducibility-manifest capture helpers. `capture_local_git` snapshots
the operator's git state (branch, HEAD SHA, dirty flag) at deploy time;
`capture_payload_lockfile` records `pyproject.toml` + `uv.lock` content
hashes so the same payload can be rebuilt identically later.

```{eval-rst}
.. currentmodule:: runpod_deploy.metadata

.. autosummary::
   :toctree: generated/metadata/
   :nosignatures:

   capture_local_git
   capture_payload_lockfile
```
