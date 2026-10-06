# Feature: Flow Bridge — batchexecute migration

**Status**: DONE — T1–T7 complete; E2E green (character-refs live check deferred; Engram mirror pending)
**Branch**: `feat/flow-bridge-batchexecute` (from `develop` @867ae4e)
**Created**: 2026-10-06
**Authorized by**: user ("Vamos con ello", 2026-10-06). Review skips authorized per candidate by user.
**Route**: ODD (delegated direct)

## Objective

Restore the Workflow ↔ Google Flow bridge after the September 2026 Flow migration so image generation (scene fragments, thumbnails, character references) works again with the user's connected Flow accounts. ✅ Achieved (see E2E evidence).

## Result summary

Google moved Flow to `flow.google.com` and replaced the bearer REST API with in-page signed `batchexecute` RPCs. The bridge was rebuilt end-to-end: extension (hijack-bypass + MAIN executor + WS relay + profile identity), backend (vendored envelope codec, per-account dispatch, auto project provisioning), and a post-migration model fix (NARWHAL is rejected by the new API).

**Commits:** `20032b9` (T2 vendored module + tests), `4d2dbf7` (T3 backend rewire + provisioning), `0e83fc1` (T4 extension rewrite), `88f3fbf` (model fix), docs `05985e9`/`e2328ea`/`3b7d2e0`/`5bb2548`/`dccc916`/`3c0b9d4`/`d961436`, close-out chores.

## E2E evidence (live, 2026-10-06)

- **Account registration** (no bearer): `/api/accounts` → `hash 049ba34a` — label "Gemini le5w", `connected: true`, registered over WS from the rebuilt extension.
- **Auto project provisioning**: `backend/flow_projects.json` → `{"049ba34a": "16f2eb7b-f9e6-4372-8510-d2923bc3883d"}`; the Flow project exists and loads in the UI (`https://flow.google.com/project/16f2eb7b-…`) — created via RPC `jHPbke` through our bridge.
- **Image generations saved end-to-end** (scene files on disk; each ~750–920 KB):
  - `escena_007.png` — GEM_PIX_2 · `escena_008.png` — HARBOR_SEAL · `escena_010.png` — GEM_PIX_2 · `escena_012.png` — HARBOR_SEAL · `escena_003.png` — default GEM_PIX_2 (post-fix, no model param).
- **Tests**: backend `pytest` 127 passed (incl. 10 wiring tests, 75 slot tests, 43 baseline, alias test); extension `wxt build` OK + manifest verified; frontend `tsc --noEmit` exit 0.
- **Character-reference path (`maseQ` + refs in `ogiZ0b`)**: implemented and slot-tested; **live check deferred** — no project on disk currently has `personaje/*.png` references.

## Root cause of the `[5]` error hunt

`ogiZ0b` returned a bare batchexecute error slot `["wrb.fr","ogiZ0b",null,null,null,[5],"generic"]` while `jHPbke` (no captcha) worked. Live A/B proved: **the legacy model id `NARWHAL` is rejected by the new Flow API with `[5]`; `GEM_PIX_2` and `HARBOR_SEAL` work** (UI capture from flowkit's netlog confirms the UI uses GEM_PIX_2; the earlier transient "Flow busy" window the user hit affected the UI too and briefly masked the result). Fix `88f3fbf`: defaults → `GEM_PIX_2` everywhere (images/workflow/orchestrator/forge_bridge), legacy `NARWHAL`/`PINHOLE` aliased → `GEM_PIX_2` (`_model_for_api`), frontend selector default `GEM_PIX_2` with `["GEM_PIX_2","HARBOR_SEAL"]`. RDD assess on the fix: medium, `under_budget` (no review required).

## Tasks

- [x] **T1. Recon** — flowkit clone @ `af5e058`; integration spec (envelope, slots, hijack, `jHPbke` creation, readers). *(delegated explore)*
- [x] **T2. Backend module** — `flow_batch.py` byte-identical (blob `0e148562…`) + LICENSE/NOTICE + slot tests. Commit `20032b9`. Review **skipped by user** (7 attempts / 2 reviewer models hit the gateway's ~32K reasoning budget; lineage abandoned auditably `operator_disposition`).
- [x] **T3. Backend wiring** — envelopes per-account at send time; refs via `maseQ`; provisioning (`jHPbke` + `flow_projects.json` + override); `main.py` cleanup; `config.flow_project_id`; `_rpc_over_ws`. Commit `4d2dbf7` (+9 tests). Review **declined** (`declined_this_candidate`).
- [x] **T4. Extension** — `wxt.config.ts` host; NEW `hijack-bypass.content.ts` (MAIN, document_start, pristine capture); NEW `flow-executor.content.ts` (batchexecute fetch, `WIZ_global_data`, serialized single-use captcha, error shapes); `token-gen` deleted; `bridge.content.ts` rewritten (WS map + profile identity); background `WF_GET_PROFILE_META`. Commit `0e83fc1`. Review **declined** (high risk `process_boundary`).
- [x] **T5. Checks** — 127 backend tests green; build + manifest + tsc verified.
- [x] **T6. Live E2E** — ✅ see evidence above (fix `88f3fbf` included).
- [x] **T7. Close** — legacy static extension files (`bridge.js`, `token-gen.js`, root `manifest.json`) removed (unreferenced; the wizard/WXT build uses `.output/chrome-mv3`); `.codegraph/` ignored; docs + mirror (Engram mirror **pending** — `mem_save` failing with "could not confirm session registration" post-restart).

## WS protocol (frozen contract — implemented both sides)
- Batch: backend→ext `{"type":"generate","batchId","requests":[{"requestId","rpcid","freq","captchaAction"}]}`; ext→backend `{"type":"result","batchId","results":[{"requestId","success","status","data","error"}]}`.
- Single RPC: backend→ext `{"type":"rpc","id","rpcid","freq","captchaAction"}`; ext→backend `{"type":"rpc_result","id","success","status","data","error"}`.
- Register: `{"type":"register","account","email"}` (email = Chrome profile label).
- Results reshaped to legacy `{"media":[{"image":{"generatedImage":{"mediaId","fifeUrl"}}}]}` so `images.py::save_image` is untouched.

## Review incident log
- T2: abandoned (`operator_disposition`; quarantine `.git/gentle-ai/review-transactions/quarantine/review-bb36a75575e2f86e-3725445824`).
- T3/T4: `declined_this_candidate` by user. Fix commit `88f3fbf`: `review_due: false` (`under_budget`).
- Reviewer config: six `review-*` agents → `opencode-go/mimo-v2.6-flash` (backup `opencode.json.bak-2026-10-06`); caveat: `gentle-ai sync` may drop the `model` field.

## Acceptance criteria
- `/api/accounts` lists account(s) with a signed-in `flow.google.com` tab. ✅
- One fragment generation completes; image saved; no bearer path. ✅ (×5)
- Project auto-provisioned per account (created once, persisted, reused); manual override respected. ✅
- Character-reference generation via page-side upload — **live check deferred** (no refs on disk; implementation + slot tests in place). 
- Envelope tests prove positional slots. ✅ (75 green)
- No bearer code paths remain. ✅ (grep clean)
- Review outcomes recorded per candidate. ✅

## Known issues / follow-ups
- Engram `mem_save` failing after the OpenCode restart ("session registration") — mirrors pending; local git record is authoritative.
- `gentle-ai sync`/managed-asset refresh may overwrite the reviewer `model` field — re-apply if it regresses.
- `test_thumbnail_api.py` hangs pre-existing at the SSE test (excluded from gating).
- Character-refs live verification when a project with `personaje/*.png` is generated next.

## Checks
- Backend: `python -m pytest tests/ --ignore=tests/test_thumbnail_api.py` → **127 passed**.
- Extension: `bunx wxt build` OK; `.output/chrome-mv3/manifest.json` verified.
- Frontend: `bunx tsc --noEmit` exit 0.

## TDD
Off (project precedent). Ordinary functional checks + unit tests.

## Progress / evidence
- 2026-10-06: diagnosis → T1–T4 implemented; T2 review abandoned; T3/T4 reviews declined; E2E partially blocked by `[5]`.
- 2026-10-06: `[5]` root-caused (NARWHAL rejected; UI netlog capture + live A/B) → fix `88f3fbf` → E2E green (5 images saved); close-out done.
