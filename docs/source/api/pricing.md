# `runpod_deploy.pricing`

GPU price catalog fetched live from RunPod, plus a deterministic selector
that picks the cheapest GPU matching a `PodSpec`'s `gpu_order` and
`cloud_type` filter.

```{eval-rst}
.. currentmodule:: runpod_deploy.pricing

.. autosummary::
   :toctree: generated/pricing/
   :nosignatures:

   GpuPrice
   fetch_gpu_prices
   select_price_for_pod
```
