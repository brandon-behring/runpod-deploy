# smoke

Minimal end-to-end deploy check. Provisions an RTX A4000/A4500/A100 (whichever is
in stock) in `EU-RO-1`, mounts the existing `pid-workspace-100gb` network volume,
rsyncs a one-line payload, runs `nvidia-smi`, pulls the output, and stops the
pod. Expected cost: a few cents.

```bash
runpod-deploy validate --config examples/smoke/a4000_smoke.yaml --check-local
runpod-deploy run --config examples/smoke/a4000_smoke.yaml --offline-dry-run
runpod-deploy run --config examples/smoke/a4000_smoke.yaml --dry-run
runpod-deploy run --config examples/smoke/a4000_smoke.yaml
```

All work goes into `/workspace/{run_id}/` on the volume so existing contents are
untouched. Pulled artifacts land under `examples/smoke/artifacts/runpod/<ts>/`
(gitignored).

## Prerequisites (any host)

- `runpodctl` configured (`runpodctl doctor` → all green).
- Your local SSH key registered with RunPod. `runpodctl doctor` reports
  `synced_to_cloud: true` if *any* ed25519 key is synced — that is **not** a
  fingerprint match. Verify with:
  ```bash
  diff <(awk '{print $2}' ~/.ssh/id_ed25519.pub) \
       <(runpodctl ssh list-keys | python3 -c "import json,sys; [print(k['key'].split()[1]) for k in json.load(sys.stdin)['keys']]")
  ```
  If your local pubkey is missing, register it:
  ```bash
  runpodctl ssh add-key --key-file ~/.ssh/id_ed25519.pub
  ```
- `rsync` 3.x on the local host. The orchestrator emits `--info=progress2` which
  rsync 2.x rejects.
  - **Linux**: distro `rsync` is usually 3.x; check with `rsync --version`.
  - **macOS**: `/usr/bin/rsync` is openrsync (2.6.9-compat) and will fail. Install
    GNU rsync: `brew install rsync` (lands at `/usr/local/bin/rsync`, which is
    earlier on PATH).
- `ssh` (any modern version).

The pod side does **not** need rsync preinstalled — this config's `setup` step
runs `apt-get install -y rsync` on the pod before staging.
