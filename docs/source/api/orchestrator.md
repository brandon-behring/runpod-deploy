# `runpod_deploy.orchestrator`

The single end-to-end entry point. `run_job` provisions a pod, stages
local sources, runs the detached remote script, polls for the success
marker, pulls artifacts, and stops the pod — driven entirely by the
`JobContext` built from the YAML config.

```{eval-rst}
.. currentmodule:: runpod_deploy.orchestrator

.. autosummary::
   :toctree: generated/orchestrator/
   :nosignatures:

   run_job
```
