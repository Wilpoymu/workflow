# Feature: Flow Bridge — batchexecute migration

**Status**: in progress
**Branch**: `feat/flow-bridge-batchexecute` (from `develop`)
**Created**: 2026-10-06
**Authorized by**: user ("Vamos con ello", 2026-10-06) following the proposed migration plan: port the documented community reverse engineering (flowkit, MIT) of the September 2026 Flow migration.
**Route**: ODD (delegated direct)

## Objective

Restore the Workflow ↔ Google Flow bridge after the September 2026 Flow migration so image generation (scene fragments, thumbnails, character references) works again with the user's connected Flow accounts.

## Problem

Google moved Flow from `labs.google/fx/tools/flow` to **`flow.google.com`** and rewrote the frontend (Angular). The old transport is dead:

- Extension content scripts match only `labs.google/*` → never inject on the new host → no WebSocket → no accounts registered in Workflow ("no salen las cuentas").
- `/fx/api/auth/session` no longer mints `Bearer ya29...`.
- `aisandbox-pa.googleapis.com/.../flowMedia:batchGenerateImages` has no caller.

New transport: `POST https://flow.google.com/_/AiSandboxAngularFrontend/data/batchexecute`, signed **inside the page** (session cookie + per-page `at` token + single-use reCAPTCHA per generate). Envelope shape: `f.req = [[[rpcid, "<inner payload as JSON string>", null, "generic"]]]`. Nothing works headless; one signed-in `flow.google.com` tab must stay open. reCAPTCHA site key and image model wire ids are unchanged across the migration.

## Why

The bridge is the core product value (use the user's own Flow accounts — no official API). Broken since the migration; image generation impossible.

## Scope

### In
- **Extension**: host matches for `flow.google.com`; in-page batchexecute executor (MAIN world) with serialized reCAPTCHA mints; remove bearer/session logic; account identity via Chrome profile (email no longer available).
- **Backend**: envelope builder/parser module (ported from flowkit, MIT + attribution); rewire `forge_bridge.py` dispatch/result handling; reference-image upload through the page (`maseQ`); `FLOW_PROJECT_ID` config (global default; per-account if cheap).
- **Tests**: envelope slot-position unit tests (batch-harness style) + backend suite green.
- **Live E2E**: create Flow project in UI, pin UUID, generate image end-to-end with user account.

### Out (follow-ups)
- UI for managing Flow project id per account (v1: backend config).
- Image export/upscale (`SPrCad`), video RPCs — not needed for image generation now.
- Account email display (lost with bearer; profile label fallback).

## Constraints
- No headless: signed-in `flow.google.com` tab required (one per account/profile).
- Flow project must be created manually in the Flow UI (no programmatic creation on the new API).
- Keep bridge architecture: WS `127.0.0.1:8766`, account chunking, `save_image` semantics.
- MIT attribution for ported code. Technical artifacts in English. No AI co-author trailers on commits.

## Tasks (stable IDs)

- [ ] **T1. Recon** — extract integration spec from flowkit clone (envelope builder, response parser, page executor, captcha serialization, WS protocol, test harness) mapped to our files. *(route: delegated `explore`; trigger: 4+ reference files)*
- [ ] **T2. Backend module** — `flow_batch` module: build `ogiZ0b` (generate) / `maseQ` (upload) envelopes; parse responses → media/signed URL; + slot-position unit tests. *(route: delegated writer; trigger: multi-file, reference-driven)*
- [ ] **T3. Backend wiring** — rewire `forge_bridge.py` dispatch/result + reference upload via page + `FLOW_PROJECT_ID` config; clean up `main.py` auth path. *(route: delegated writer; same thread as T2)*
- [ ] **T4. Extension** — host permissions/matches; rewrite executor (batchexecute + serialized captcha); WS protocol update; profile-based account identity; remove bearer code; rebuild unpacked + zip. *(route: delegated writer; trigger: multi-file)*
- [ ] **T5. Checks** — backend `pytest`; extension `wxt build`; new envelope tests pass. *(route: inline bounded actions + fresh worker if heavy)*
- [ ] **T6. Live E2E** — with user: create Flow project, pin UUID, generate ≥1 scene image end-to-end; character-reference variant. *(route: user + orchestrator; evidence recorded)*
- [ ] **T7. Close** — remove dead code, final cleanup commits, update doc + Engram mirror, honest close report.

## Acceptance criteria
- `/api/accounts` lists account(s) while a signed-in `flow.google.com` tab is open with the extension loaded.
- One fragment generation from Workflow completes: image file saved; no bearer path used.
- Character-reference generation works via page-side upload, OR explicitly documented as deferred.
- Envelope tests prove positional slots (aspect-ratio slot, reference slot) — the traps.
- No code path calls `/fx/api/auth/session` or `aisandbox-pa...` with a bearer.

## Checks
- Backend: `pytest` in `backend/` (incl. new tests).
- Extension: `bunx wxt build` in `extension/` (+ unpacked output refreshed for load-unpacked).
- Manual E2E steps recorded under T6 evidence.

## TDD
Off (project precedent — Standard mode; no user TDD setting). Ordinary functional checks + new unit tests for the envelope builder.

## Progress / evidence
- 2026-10-06: diagnosis complete (Flow host move + transport change). flowkit cloned to `C:\Users\T-Gency\AppData\Local\Temp\opencode\flowkit-ref` as reference. Task doc created; branch `feat/flow-bridge-batchexecute` created from `develop`.

## Next step
T1 recon delegation.
