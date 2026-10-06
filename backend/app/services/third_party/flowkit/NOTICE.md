# Third-party notice: flowkit

This directory contains vendored code from the **flowkit** project.

- **Upstream repository**: https://github.com/crisng95/flowkit
- **Pinned commit**: `af5e0583eff5633f5775cafe2ab948e9edfa79d9`
- **License**: MIT (see `LICENSE` in this directory)

## Copied files

| Upstream path | Local path |
| --- | --- |
| `agent/services/flow_batch.py` | `app/services/flow_batch.py` |

## Modification status

The copied file is **unmodified and byte-identical** to the upstream file at the
pinned commit. No edits, reformatting, or header changes were applied.

Verification (SHA-256):

- Upstream `agent/services/flow_batch.py`:
  `2c8e5ee6cbe8716d3ff5f214642a49fac200f6f21691ab207cda65e1a6a34b7a`
- Local `app/services/flow_batch.py`:
  `2c8e5ee6cbe8716d3ff5f214642a49fac200f6f21691ab207cda65e1a6a34b7a`

## Purpose

The module vendors Google Flow's signed `batchexecute` RPC envelope
builder/parser (RPCs such as `ogiZ0b`, `maseQ`, `jHPbke`) so the backend can
build request envelopes and read responses locally. It is stdlib-only and never
performs network I/O.
