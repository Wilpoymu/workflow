# Feature: Flow Bridge — batchexecute migration

**Status**: in progress — T2 done; native review of T2 awaiting OpenCode restart (reviewer model switched to `opencode-go/mimo-v2.6-flash`)
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
- [x] **T2. Backend module** — vendored `flow_batch.py` (byte-identical; git blob `0e148562b3ea179ec7107236aa2cb749546bd2b0` matches upstream) + MIT LICENSE/NOTICE + ported slot-grammar tests. Commit `20032b9`. Evidence: `python -m pytest tests/test_flow_batch.py tests/test_flow_batch_golden.py` → **75 passed**; regression baseline `test_thumbnail_pillow.py` + `test_thumbnail_gemini.py` → **43 passed**; parent spot-check re-ran the 75 (passed). *(delegated writer)*
  - **Native review of T2**: started (lineage `review-bb36a75575e2f86e`, medium, 1 lens `review-reliability`); **blocked by reviewer-model reasoning-budget exhaustion** — see incident below.
- [ ] **T3. Backend wiring** — rewire `forge_bridge.py` dispatch/result + reference upload via page + project provisioning (`jHPbke` + `flow_projects.json` + override); clean up `main.py` auth path. *(delegated writer, same thread)*
- [ ] **T4. Extension** — host permissions/matches; hijack-bypass (document_start, MAIN); executor rewrite (batchexecute + serialized captcha); WS protocol update; profile-based account identity; remove bearer code; rebuild unpacked + zip. *(delegated writer)*
- [ ] **T5. Checks** — backend `pytest` (new + baseline); extension `wxt build`. *(inline bounded + fresh worker if heavy)*
- [ ] **T6. Live E2E** — with user: open `flow.google.com` signed in, verify account registration + auto project creation, generate ≥1 scene image end-to-end; character-reference variant. *(user + orchestrator; evidence recorded)*
- [ ] **T7. Close** — remove dead code, final cleanup commits, update doc + Engram mirror, honest close report.

## Incident: native review of T2 blocked (2026-10-06)

RDD assessed T2 commit `20032b9` as medium / `review_due: true` (`slice_budget_reached`). Review START approved by user; transaction frozen (`review-bb36a75575e2f86e`, state `reviewing`, lens `review-reliability`, correction budget 200). The single reviewer slot could not be filled:

- **5 bounded launch attempts**, all returned typed `opencode_task_output_empty` ("the reviewer Task completed without producing a result").
- **Root cause (verified from OpenCode's own SQLite records):** the reviewer child model `deepseek-v4.1-flash` (`variant: max`) **exhausts its 32 000-token reasoning budget** on the ~70 KB review materialization and finishes with `finish: length`, `output: 0`, no text parts; the OpenCode host renders that as an empty `<task_result>`, and the relay correctly refuses it (`opencode_task_output_empty`). Reasoning parts were ~108–111 K chars per attempt with zero output tokens.
- **Historical context:** same failure class exists across earlier reviewer sessions on this model (flaky; some sessions succeed after 1–2 retries with `finish: stop`). The empty-result host behavior is a known upstream OpenCode class (fix in `anomalyco/opencode#39473`; tracked in gentle-ai `#2609`). Not a defect in the T2 code, and **not a Gentle AI provider defect** (model/provider-side behavior; gentle-ai typed it correctly).
- **State preserved:** the slot is NOT consumed (failed captures never consume the lens slot); lineage remains `reviewing`; candidate tree untouched. Recovery = relaunch the slot once the reviewer environment can produce output.
- **Decision (user, 2026-10-06):** switch the reviewer model. Applied: `"model": "opencode-go/mimo-v2.6-flash"` added to the six `review-*` agents in `~/.config/opencode/opencode.json` (backup: `opencode.json.bak-2026-10-06`; JSON re-validated). Config is not hot-reloaded → **OpenCode restart required**.

### Resume instructions (after OpenCode restart)
1. Query the frozen-binding STATUS (the relaunch slot is reoffered by the same collect):
```
gentle-ai review status --contract=gentle-ai.review-integration/v2 --next-transition=true --lineage=review-bb36a75575e2f86e --repository-context=rctx2_4089c5f9d34d442b9c0f417c3d29c1dddb733e6ffc1e706a6efb86ca5976654a --agent=opencode --base-ref=c7f61c0c801d837ce33148e8cae5097ca8aa5c54 --committed-only=true
```
2. If it reoffers `collect / reviewer_results_required`, launch the provider task (`review-reliability` agent, exact prompt from the input) — now on `mimo-v2.6-flash`.
3. Follow STATUS transitions through capture/closure, then the reviewed boundary advances and work continues with T3.
Caveat: a future `gentle-ai sync` / managed-asset refresh may rewrite the agent blocks and drop the `model` field — re-check and re-apply if the reviewer model regresses.

## Acceptance criteria
- `/api/accounts` lists account(s) while a signed-in `flow.google.com` tab is open with the extension loaded.
- One fragment generation from Workflow completes: image file saved; no bearer path used.
- Project auto-provisioned per account (created once, persisted, reused); manual override respected.
- Character-reference generation works via page-side upload, OR explicitly documented as deferred.
- Envelope tests prove positional slots (aspect-ratio slot, reference slot) — the traps. ✅ (75 tests green)
- No code path calls `/fx/api/auth/session` or `aisandbox-pa...` with a bearer.
- T2's native review reaches a terminal outcome (approved or explicitly declined/abandoned with recorded decision).

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
- 2026-10-06: T2 complete — commit `20032b9` (vendored module byte-identical + tests). RDD assess: medium, `review_due: true` → native review started; reviewer slot blocked by model reasoning-budget exhaustion after 5 attempts (see incident).
- 2026-10-06: doc updated with incident record (commit `3b7d2e0`).
- 2026-10-06: user decided to switch the reviewer model; applied `opencode-go/mimo-v2.6-flash` to the six `review-*` agents (config backup `opencode.json.bak-2026-10-06`); awaiting OpenCode restart to relaunch the reviewer slot.

## Next step
Restart OpenCode (config is not hot-reloaded), then relaunch the T2 reviewer slot (see Resume instructions), drive STATUS to closure, then proceed with T3.
