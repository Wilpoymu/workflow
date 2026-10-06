# Feature: Flow Bridge — batchexecute migration

**Status**: in progress — T2 done (review skipped by user), T3 done (review declined this candidate by user), T4 launching
**Branch**: `feat/flow-bridge-batchexecute` (from `develop` @867ae4e)
**Created**: 2026-10-06
**Authorized by**: user ("Vamos con ello", 2026-10-06). Project provisioning refined to **auto-create per account** (user question, 2026-10-06). Review skips authorized per candidate by user (2026-10-06).
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

Projects are account-scoped (profile A's project is invisible to profile B) and the old code invented a random UUID per batch, which is invalid now. Implemented in T3:

1. `get_or_create_flow_project(account_hash)`: manual override (backend `FLOW_PROJECT_ID` setting) → persisted store `flow_projects.json` (`{account_hash: project_id}`) → otherwise create via RPC **`jHPbke`** over that account's WS connection (title `Workflow <profile label>`), validate, persist.
2. Stable reuse per account (no idle rotation).
3. Manual override always wins.

## Why

The bridge is the core product value (use the user's own Flow accounts — no official API). Broken since the migration; image generation impossible.

## Scope

### In
- **Extension** (T4): host matches for `flow.google.com`; in-page batchexecute executor (MAIN world) with pristine-captcha hijack bypass + serialized single-use mints; remove bearer/session logic; account identity via Chrome profile (email no longer available).
- **Backend**: envelope builder/parser module (vendored from flowkit, MIT + attribution, byte-identical); rewire `forge_bridge.py` dispatch/result handling; reference-image upload through the page (`maseQ`); project provisioning per design above. ✅ T3
- **Tests**: envelope slot-position unit tests (ported harness) + backend suite green. ✅ T2/T3
- **Live E2E** (T6): auto-provisioned project per account, generate image end-to-end with user account.

### Out (follow-ups)
- UI for managing/overriding the Flow project per account (v1: config + auto-create).
- Image export/upscale (`SPrCad`), video RPCs — not needed for image generation now.
- Account email display (lost with bearer; profile label fallback).

## Constraints
- No headless: signed-in `flow.google.com` tab required (one per account/profile).
- Keep bridge architecture: WS `127.0.0.1:8766`, account chunking, `save_image` semantics.
- MIT attribution for vendored code; keep `flow_batch.py` byte-identical for upstream diffs. Technical artifacts in English. No AI co-author trailers on commits.

## Tasks (stable IDs)

- [x] **T1. Recon** — integration spec extracted from flowkit clone. Reference clone pinned at commit `af5e0583eff5633f5775cafe2ab948e9edfa79d9`. *(delegated `explore`)*
- [x] **T2. Backend module** — vendored `flow_batch.py` (byte-identical; git blob `0e148562...` matches upstream) + MIT LICENSE/NOTICE + ported slot-grammar tests. Commit `20032b9`; 75 slot tests + 43 baseline green; parent spot-check passed. *(delegated writer)* — **native review skipped by user decision** (7 reviewer attempts across 2 models hit the gateway ~32K reasoning budget; lineage abandoned auditably, `operator_disposition`).
- [x] **T3. Backend wiring** — `forge_bridge.py` rewired to batchexecute envelopes (per-account, built at send time); reference upload via page (`maseQ`); project provisioning (`jHPbke` + `flow_projects.json` + override); `main.py` auth cleanup; `config.flow_project_id`; tests. Commit `4d2dbf7` (6 files, +563/−353). Evidence: `test_flow_bridge_wiring.py` 9 passed; slots 75 passed; baseline 43 passed; `import app.main` ok; parent spot-check re-ran 84 passed. *(delegated writer, same thread)* — **native review declined this candidate by user** (`declined_this_candidate`, no record; ordinary policy).
- [ ] **T4. Extension** — host permissions/matches; hijack-bypass (document_start, MAIN); executor rewrite (batchexecute + serialized captcha); WS protocol update; profile-based account identity; remove bearer code; rebuild unpacked. *(delegated writer)*
- [ ] **T5. Checks** — backend `pytest` (new + baseline); extension `wxt build`. *(inline bounded + fresh worker if heavy)*
- [ ] **T6. Live E2E** — with user: open `flow.google.com` signed in, verify account registration + auto project creation, generate ≥1 scene image end-to-end; character-reference variant. *(user + orchestrator; evidence recorded)*
- [ ] **T7. Close** — remove dead code, final cleanup commits, update doc + Engram mirror, honest close report.

## WS protocol (backend T3 ↔ extension T4) — frozen contract
- Batch: backend→ext `{"type":"generate","batchId","requests":[{"requestId","rpcid","freq","captchaAction"}]}`; ext→backend `{"type":"result","batchId","results":[{"requestId","success","status","data","error"}]}`.
- Single RPC: backend→ext `{"type":"rpc","id","rpcid","freq","captchaAction"}`; ext→backend `{"type":"rpc_result","id","success","status","data","error"}`.
- Register: `{"type":"register","account","email"}` (email now carries the Chrome profile label).
- Envelopes built by `app.services.flow_batch`; results reshaped to legacy `{"media":[{"image":{"generatedImage":{"mediaId","fifeUrl"}}}]}` so `images.py::save_image` is untouched.

## Incident log (reviews)
- **T2 (2026-10-06):** review_due (medium, slice_budget_reached) → START approved → 7 reviewer launches across `deepseek-v4.1-flash` (variant max) and `mimo-v2.6-flash` all failed with `opencode_task_output_empty`: both models burn the gateway's ~32K reasoning-token budget parsing the 1 339-line candidate (finish=length, output=0, no text parts; reasoning ~110K chars). User decided to skip; lineage abandoned auditably (`gentle-ai review abandon --reason operator_disposition --actor user`; quarantine at `.git/gentle-ai/review-transactions/quarantine/review-bb36a75575e2f86e-3725445824`).
- **T3 (2026-10-06):** review_due (medium, slice_budget_reached, 916 lines) → consent relayed → user chose **"Omitir esta vez"** → `declined_this_candidate` (no record; future reviews stay enabled).
- Reviewer config: six `review-*` agents set to `opencode-go/mimo-v2.6-flash` (backup `opencode.json.bak-2026-10-06`); caveat: `gentle-ai sync` may rewrite managed agent blocks and drop the `model` field.

## Acceptance criteria
- `/api/accounts` lists account(s) while a signed-in `flow.google.com` tab is open with the extension loaded.
- One fragment generation from Workflow completes: image file saved; no bearer path used.
- Project auto-provisioned per account (created once, persisted, reused); manual override respected.
- Character-reference generation works via page-side upload, OR explicitly documented as deferred.
- Envelope tests prove positional slots (aspect-ratio slot, reference slot) — the traps. ✅ (75 tests green)
- No code path calls `/fx/api/auth/session` or `aisandbox-pa...` with a bearer.
- Native review outcomes recorded per candidate (T2 abandoned; T3 declined). ✅

## Checks
- Backend: `python -m pytest tests/` in `backend/` — baseline: `test_thumbnail_pillow.py` 22 passed, `test_thumbnail_gemini.py` 21 passed; `test_thumbnail_api.py` hangs pre-existing at `TestEventsEndpoint::test_sse_stream_starts` (SSE stream never ends) — excluded from gating until fixed separately.
- Extension: `bunx wxt build` in `extension/` (+ verify `.output/chrome-mv3/manifest.json`).
- Manual E2E steps recorded under T6 evidence.

## TDD
Off (project precedent — Standard mode; no user TDD setting). Ordinary functional checks + new unit tests.

## Progress / evidence
- 2026-10-06: diagnosis; T1 recon; provisioning auto; T2 `20032b9` (+review incident, abandoned with audit); docs `05985e9`, `e2328ea`, `3b7d2e0`, `5bb2548`, `dccc916` (all RDD passive).
- 2026-10-06: T3 `4d2dbf7` — backend rewired; 9 + 75 + 43 tests green; import ok; parent re-ran 84 green; review declined by user (`declined_this_candidate`).
- 2026-10-06: Engram `mem_save` failing post-restart ("could not confirm session registration") — mirrors for the latest doc updates are **pending**; retry later. Local doc record is committed and authoritative.

## Next step
T4: extension rewrite (delegated writer) → build verify → then T5/T6.
