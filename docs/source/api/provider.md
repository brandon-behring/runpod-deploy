# `runpod_deploy.provider`

`runpodctl`-backed pod provisioning + cross-datacenter GPU selection.
Network-volume resolution validates that a named volume exists in the
expected datacenter before provisioning starts.

```{eval-rst}
.. currentmodule:: runpod_deploy.provider

.. autosummary::
   :toctree: generated/provider/
   :nosignatures:

   PodConnection
   resolve_volume
   select_gpu_across_datacenters
```
