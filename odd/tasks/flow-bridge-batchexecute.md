# Feature: Flow Bridge — batchexecute migration

**Status**: in progress — T2 done (native review skipped by explicit user decision, lineage abandoned auditably); T3 launching
**Branch**: `feat/flow-bridge-batchexecute` (from `develop` @867ae4e)
**Created**: 2026-10-06
**Authorized by**: user ("Vamos con ello", 2026-10-06). Project provisioning refined to **auto-create per account** (user question, 2026-10-06). T2 review skip authorized by user ("Pasemos esto sin revisión", 2026-10-06).
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
- [x] **T2. Backend module** — vendored `flow_batch.py` (byte-identical; git blob `0e148562b3ea179ec7107236aa2cb749546bd2b0` matches upstream) + MIT LICENSE/NOTICE + ported slot-grammar tests. Commit `20032b9`. Evidence: `python -m pytest tests/test_flow_batch.py tests/test_flow_batch_golden.py` → **75 passed**; regression baseline `test_thumbnail_pillow.py` + `test_thumbnail_gemini.py` → **43 passed**; parent spot-check re-ran the 75 (passed). *(delegated writer)*
  - **Native review of T2: skipped by explicit user decision** (see incident below; lineage abandoned auditably).
- [ ] **T3. Backend wiring** — rewire `forge_bridge.py` dispatch/result + reference upload via page + project provisioning (`jHPbke` + `flow_projects.json` + override); clean up `main.py` auth path. *(delegated writer, same thread)*
- [ ] **T4. Extension** — host permissions/matches; hijack-bypass (document_start, MAIN); executor rewrite (batchexecute + serialized captcha); WS protocol update; profile-based account identity; remove bearer code; rebuild unpacked + zip. *(delegated writer)*
- [ ] **T5. Checks** — backend `pytest` (new + baseline); extension `wxt build`. *(inline bounded + fresh worker if heavy)*
- [ ] **T6. Live E2E** — with user: open `flow.google.com` signed in, verify account registration + auto project creation, generate ≥1 scene image end-to-end; character-reference variant. *(user + orchestrator; evidence recorded)*
- [ ] **T7. Close** — remove dead code, final cleanup commits, update doc + Engram mirror, honest close report.

## Incident: native review of T2 (2026-10-06) — resolved by skip

RDD assessed T2 commit `20032b9` as medium / `review_due: true` (`slice_budget_reached`). Review START approved by user; transaction frozen (`review-bb36a75575e2f86e`, state `reviewing`, lens `review-reliability`). The single reviewer slot could not be filled:

- **7 bounded launch attempts across 2 models**, all returned typed `opencode_task_output_empty`.
- **Root cause** (verified from OpenCode's own records and reasoning text): the gateway's reviewer models (`deepseek-v4.1-flash`, then `mimo-v2.6-flash` after the config switch + restart) both burn the **~32 K reasoning-token budget** parsing the 1 339-line candidate and finish with `finish: length`, `output: 0`, zero text parts. The reasoning sample shows meticulous line-by-line bookkeeping over a 771-line file — the candidate is simply larger than one review pass can absorb under this gateway's reasoning budget. Not a defect in T2's code; not a Gentle AI provider defect (model/provider-side behavior; gentle-ai typed it correctly).
- **Decision (user, 2026-10-06):** after the diagnosis, pass T2 **without native review** ("Pasemos esto sin revisión, estamos en un loop infinito").
- **Abandoned auditably:** `gentle-ai review abandon --reason operator_disposition --actor user` → reclaim record committed; lineage quarantined at `.git/gentle-ai/review-transactions/quarantine/review-bb36a75575e2f86e-3725445824` (discarded work: no captured lens results, no findings). T2 stands on test evidence under ordinary policy.
- **Reviewer model config left in place:** the six `review-*` agents keep `opencode-go/mimo-v2.6-flash` (backup: `opencode.json.bak-2026-10-06`) for future reviews. Caveat: a future `gentle-ai sync` may rewrite managed agent blocks and drop the `model` field.

## Acceptance criteria
- `/api/accounts` lists account(s) while a signed-in `flow.google.com` tab is open with the extension loaded.
- One fragment generation from Workflow completes: image file saved; no bearer path used.
- Project auto-provisioned per account (created once, persisted, reused); manual override respected.
- Character-reference generation works via page-side upload, OR explicitly documented as deferred.
- Envelope tests prove positional slots (aspect-ratio slot, reference slot) — the traps. ✅ (75 tests green)
- No code path calls `/fx/api/auth/session` or `aisandbox-pa...` with a bearer.
- T2's native review terminal outcome: ✅ explicitly abandoned with recorded audit decision (`operator_disposition`).

## Checks
- Backend: `python -m pytest tests/` in `backend/` — baseline: `test_thumbnail_pillow.py` 22 passed, `test_thumbnail_gemini.py` 21 passed; `test_thumbnail_api.py` hangs pre-existing at `TestEventsEndpoint::test_sse_stream_starts` (SSE stream never ends) — excluded from gating until fixed separately.
- Extension: `bunx wxt build` in `extension/` (+ unpacked output refreshed for load-unpacked).
- Manual E2E steps recorded under T6 evidence.

## TDD
Off (project precedent — Standard mode; no user TDD setting). Ordinary functional checks + new unit tests for the envelope builder.

## Progress / evidence
- 2026-10-06: diagnosis complete (Flow host move + transport change). flowkit cloned to `C:\Users\T-Gency\AppData\Local\Temp\opencode\flowkit-ref` @ `af5e058`. Task doc created; branch `feat/flow-bridge-batchexecute` from `develop` @867ae4e; doc committed (`05985e9`, RDD passive).
- 2026-10-06: T1 recon complete — integration spec extracted.
- 2026-10-06: project provisioning design updated to auto-create (user question).
- 2026-10-06: T2 complete — commit `20032b9` (vendored module byte-identical + tests). RDD assess: medium, `review_due: true` → native review started; reviewer slot blocked by model reasoning-budget exhaustion (7 attempts, 2 models; see incident).
- 2026-10-06: doc updates committed (`3b7d2e0`, `5bb2548` — RDD passive).
- 2026-10-06: user decided to skip T2's native review; lineage abandoned with audit record (`operator_disposition`); T3 launched.

## Next step
T3: backend wiring (delegated writer) — then T4 extension.
