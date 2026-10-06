# Feature: Flow Bridge — batchexecute migration

**Status**: in progress
**Branch**: `feat/flow-bridge-batchexecute` (from `develop` @867ae4e)
**Created**: 2026-10-06
**Authorized by**: user ("Vamos con ello", 2026-10-06). Project provisioning refined to **auto-create per account** (user question, 2026-10-06).
**Route**: ODD (delegated direct)

## Objective

Restore the Workflow ↔ Google Flow bridge after the September 2026 Flow migration so image generation (scene fragments, thumbnails, character references) works again with the user's connected Flow accounts.

## Problem

Google moved Flow from `labs.google/fx/tools/flow` to **`flow.google.com`** and rewrote the frontend (Angular). The old transport is dead:

- Extension content scripts match only `labs.google/*` → never inject on the new host → no WebSocket → no accounts registered in Workflow ("no salen las cuentas").
- `/fx/api/auth/session` no longer mints `Bearer ya29...`.
- `aisandbox-pa.googleapis.com/.../flowMedia:batchGenerateImages` has no caller.

New transport: `POST https://flow.google.com/_/AiSandboxAngularFrontend/data/batchexecute`, signed **inside the page** (session cookie + per-page `at` token + single-use reCAPTCHA per generate). Envelope shape: `f.req = [[[rpcid, "<inner payload as JSON string>", null, "generic"]]]`. Nothing works headless; one signed-in `flow.google.com` tab must stay open. reCAPTCHA site key and image model wire ids are unchanged across the migration.

## Project provisioning (design)

Projects are account-scoped (profile A's project is invisible to profile B) and the old code invented a random UUID per batch, which is invalid now. Instead of a mandatory manual pin per account:

1. `get_or_create_flow_project(account_hash)`: manual override (backend `FLOW_PROJECT_ID` setting and/or per-account map) → persisted store `flow_projects.json` (`{account_hash: project_id}`) → otherwise create via RPC **`jHPbke`** over that account's WS connection (`create_project_request` / `read_created_project` in the vendored module; title `Workflow <profile label>`), validate UUID, persist.
2. Stable reuse per account (no idle rotation, unlike flowkit's session lease).
3. Manual override always wins (fallback if auto-create ever fails on a future Flow change).

## Why

The bridge is the core product value (use the user's own Flow accounts — no official API). Broken since the migration; image generation impossible.

## Scope

### In
- **Extension**: host matches for `flow.google.com`; in-page batchexecute executor (MAIN world) with pristine-captcha hijack bypass + serialized single-use mints; remove bearer/session logic; account identity via Chrome profile (email no longer available).
- **Backend**: envelope builder/parser module (vendored from flowkit, MIT + attribution, byte-identical); rewire `forge_bridge.py` dispatch/result handling; reference-image upload through the page (`maseQ`); project provisioning per design above.
- **Tests**: envelope slot-position unit tests (ported harness) + backend suite green.
- **Live E2E**: auto-provisioned project per account, generate image end-to-end with user account.

### Out (follow-ups)
- UI for managing/overriding the Flow project per account (v1: config + auto-create).
- Image export/upscale (`SPrCad`), video RPCs — not needed for image generation now.
- Account email display (lost with bearer; profile label fallback).

## Constraints
- No headless: signed-in `flow.google.com` tab required (one per account/profile).
- Keep bridge architecture: WS `127.0.0.1:8766`, account chunking, `save_image` semantics.
- MIT attribution for vendored code; keep `flow_batch.py` byte-identical for upstream diffs. Technical artifacts in English. No AI co-author trailers on commits.

## Tasks (stable IDs)

- [x] **T1. Recon** — integration spec extracted from flowkit clone (envelope, `ogiZ0b`/`maseQ` payload slots, captcha hijack + serialization, `jHPbke` project creation, response parsing, tests map). Reference clone pinned at commit `af5e0583eff5633f5775cafe2ab948e9edfa79d9`. *(delegated `explore`; 4+ reference files)*
- [ ] **T2. Backend module** — vendor `flow_batch.py` (byte-identical) + MIT LICENSE/NOTICE + ported slot-grammar tests. *(delegated writer)*
- [ ] **T3. Backend wiring** — rewire `forge_bridge.py` dispatch/result + reference upload via page + project provisioning (`jHPbke` + `flow_projects.json` + override); clean up `main.py` auth path. *(delegated writer, same thread)*
- [ ] **T4. Extension** — host permissions/matches; hijack-bypass (document_start, MAIN); executor rewrite (batchexecute + serialized captcha); WS protocol update; profile-based account identity; remove bearer code; rebuild unpacked + zip. *(delegated writer)*
- [ ] **T5. Checks** — backend `pytest` (new + baseline); extension `wxt build`. *(inline bounded + fresh worker if heavy)*
- [ ] **T6. Live E2E** — with user: open `flow.google.com` signed in, verify account registration + auto project creation, generate ≥1 scene image end-to-end; character-reference variant. *(user + orchestrator; evidence recorded)*
- [ ] **T7. Close** — remove dead code, final cleanup commits, update doc + Engram mirror, honest close report.

## Acceptance criteria
- `/api/accounts` lists account(s) while a signed-in `flow.google.com` tab is open with the extension loaded.
- One fragment generation from Workflow completes: image file saved; no bearer path used.
- Project auto-provisioned per account (created once, persisted, reused); manual override respected.
- Character-reference generation works via page-side upload, OR explicitly documented as deferred.
- Envelope tests prove positional slots (aspect-ratio slot, reference slot) — the traps.
- No code path calls `/fx/api/auth/session` or `aisandbox-pa...` with a bearer.

## Checks
- Backend: `python -m pytest tests/` in `backend/` — baseline: `test_thumbnail_pillow.py` 22 passed, `test_thumbnail_gemini.py` 21 passed; `test_thumbnail_api.py` hangs pre-existing on this machine (>150s, characterized 2026-10-06) — excluded from gating until fixed separately.
- Extension: `bunx wxt build` in `extension/` (+ unpacked output refreshed for load-unpacked).
- Manual E2E steps recorded under T6 evidence.

## TDD
Off (project precedent — Standard mode; no user TDD setting). Ordinary functional checks + new unit tests for the envelope builder.

## Progress / evidence
- 2026-10-06: diagnosis complete (Flow host move + transport change). flowkit cloned to `C:\Users\T-Gency\AppData\Local\Temp\opencode\flowkit-ref` @ `af5e058`. Task doc created; branch `feat/flow-bridge-batchexecute` from `develop` @867ae4e; doc committed (`05985e9`, RDD assess: passive).
- 2026-10-06: T1 recon complete — integration spec extracted (see Engram discovery memory for transport details): page fetch (form-urlencoded `f.req` + `at`), `at`/`f.sid`/`bl` from `WIZ_global_data`, pristine-captcha hijack at document_start + serialized single-use mints, `ogiZ0b` slot layout, `maseQ` upload, `flow-content.google/image/` URL parsing, `jHPbke` project creation, flowkit test map. Baselines: pillow/gemini tests pass; api test hang (pre-existing).
- 2026-10-06: project provisioning design updated to auto-create (user question).

## Next step
T2 delegation (vendor module + tests).
