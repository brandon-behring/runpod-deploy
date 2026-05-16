# `runpod_deploy.config`

Strict YAML config loader plus 15 frozen `*Spec` dataclasses that mirror
the v2 schema. The loader rejects unknown fields; each `*Spec`'s
`__post_init__` validates ranges, identifiers, and required combinations
and raises `ValueError` / `TypeError` with a diagnostic message.

```{eval-rst}
.. currentmodule:: runpod_deploy.config

.. rubric:: Constants

.. autosummary::
   :toctree: generated/config/
   :nosignatures:

   DEFAULT_STAGING_EXCLUDES
   SCHEMA_VERSION
   STORAGE_EPHEMERAL
   STORAGE_NETWORK_VOLUME

.. rubric:: Loader + context

.. autosummary::
   :toctree: generated/config/
   :nosignatures:

   load_job_spec
   build_job_context
   validate_local_paths
   JobContext
   RunpodJobSpec

.. rubric:: Pod, storage, and run-script specs

.. autosummary::
   :toctree: generated/config/
   :nosignatures:

   PodSpec
   StorageSpec
   RunSpec
   CommandSpec
   SshSpec
   StopPolicySpec

.. rubric:: Staging, secrets, and artifacts

.. autosummary::
   :toctree: generated/config/
   :nosignatures:

   RsyncPushSpec
   SecretSpec
   ArtifactPullSpec
   LocalSpec

.. rubric:: Environment, budget, and telemetry

.. autosummary::
   :toctree: generated/config/
   :nosignatures:

   RemoteEnvSpec
   BudgetSpec
   TelemetrySpec
```
