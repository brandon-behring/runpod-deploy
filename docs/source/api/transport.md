# `runpod_deploy.transport`

SSH and rsync primitives. `RemoteRunner` wraps `subprocess` for SSH
command execution with explicit `RemoteRunError` semantics (distinguishes
"SSH command failed" from "orchestrator state error"). `rsync_argv`
constructs the rsync command line, including the resolved exclude list
from `RsyncPushSpec.effective_excludes`.

```{eval-rst}
.. currentmodule:: runpod_deploy.transport

.. autosummary::
   :toctree: generated/transport/
   :nosignatures:

   RemoteRunner
   RemoteRunError
   rsync_argv
```
