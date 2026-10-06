# Feature: Flow Bridge — batchexecute migration

**Status**: in progress — T1–T5 done; T6 Live E2E in progress (awaiting user browser steps)
**Branch**: `feat/flow-bridge-batchexecute` (from `develop` @867ae4e)
**Created**: 2026-10-06
**Authorized by**: user ("Vamos con ello", 2026-10-06). Review skips authorized per candidate by user (2026-10-06).
**Route**: ODD (delegated direct)

## Objective

Restore the Workflow ↔ Google Flow bridge after the September 2026 Flow migration so image generation (scene fragments, thumbnails, character references) works again with the user's connected Flow accounts.

## Problem

Google moved Flow from `labs.google/fx/tools/flow` to **`flow.google.com`** and rewrote the frontend (Angular). The old transport is dead:

- Extension content scripts match only `labs.google/*` → never inject on the new host → no WebSocket → no accounts registered in Workflow ("no salen las cuentas").
- `/fx/api/auth/session` no longer mints `Bearer ya29...`.
- `aisandbox-pa.googleapis.com/.../flowMedia:batchGenerateImages` has no caller.

New transport: `POST https://flow.google.com/_/AiSandboxAngularFrontend/data/batchexecute`, signed **inside the page** (session cookie + per-page `at` token + single-use reCAPTCHA per generate). Envelope shape: `f.req = [[[rpcid, "<inner payload as JSON string>", null, "generic"]]]`. Nothing works headless; one signed-in `flow.google.com` tab must stay open.

## Project provisioning (design — implemented in T3)

1. `get_or_create_flow_project(account_hash)`: manual override (backend `FLOW_PROJECT_ID`) → persisted store `flow_projects.json` → otherwise create via RPC **`jHPbke`** over that account's WS connection (title `Workflow <profile label>`), validate, persist.
2. Stable reuse per account. 3. Manual override always wins.

## Scope

### In
- **Extension** (T4 ✅): host matches for `flow.google.com`; in-page batchexecute executor (MAIN) with pristine-captcha hijack bypass + serialized single-use mints; bearer/session logic removed; account identity via Chrome profile.
- **Backend** (T2/T3 ✅): vendored `flow_batch.py` (byte-identical, MIT); `forge_bridge.py` rewired; reference upload via page (`maseQ`); provisioning per design.
- **Tests**: 75 slot tests + 9 wiring tests + 43 baseline (all green). ✅
- **Live E2E** (T6): with user — account registration, auto project creation, ≥1 image end-to-end.

### Out (follow-ups)
- UI for managing/overriding the Flow project per account (v1: config + auto-create).
- Image export/upscale (`SPrCad`), video RPCs.
- Account email display (profile label fallback).

## Constraints
- No headless: signed-in `flow.google.com` tab required (one per account/profile).
- Keep bridge architecture: WS `127.0.0.1:8766`, account chunking, `save_image` semantics.
- MIT attribution for vendored/ported code. English artifacts. No AI co-author trailers.

## Tasks (stable IDs)

- [x] **T1. Recon** — integration spec from flowkit clone @ `af5e058`. *(delegated explore)*
- [x] **T2. Backend module** — `flow_batch.py` byte-identical (blob `0e148562...`) + LICENSE/NOTICE + slot tests. Commit `20032b9`; 75+43 green. **Review skipped by user** (7 attempts / 2 models hit the ~32K gateway reasoning budget; lineage abandoned auditably `operator_disposition`).
- [x] **T3. Backend wiring** — `forge_bridge.py` envelopes per-account; refs via `maseQ`; provisioning (`jHPbke` + `flow_projects.json`); `main.py` cleanup; `config.flow_project_id`. Commit `4d2dbf7`; wiring 9 + slots 75 + baseline 43 green; import ok. **Review declined this candidate** (`declined_this_candidate`).
- [x] **T4. Extension** — `wxt.config.ts` (+flow.google.com host); NEW `hijack-bypass.content.ts` (MAIN, document_start; pristine grecaptcha capture, ported from flowkit); NEW `flow-executor.content.ts` (MAIN; batchexecute fetch with `WIZ_global_data` at/f.sid/bl; serialized single-use captcha via pristine; replaces all `__CAPTCHA__`; error shapes `CAPTCHA_FAILED:`/`NO_AT_TOKEN`/`CAPTCHA_REQUIRED`); `token-gen.content.ts` deleted; `bridge.content.ts` rewritten (WS map generate→result / rpc→rpc_result; profile-based identity via `WF_GET_PROFILE_META` + djb2); background handler added. Commit `0e83fc1`; `bunx wxt build` OK (parent re-ran: 707 ms; manifest verified: ISOLATED bridge + MAIN executor + MAIN hijack `document_start`, all on `flow.google.com`); no bearer remnants. **Review declined this candidate** (high risk `process_boundary`; user "Omitir esta vez").
- [x] **T5. Checks** — full backend suite minus pre-existing hang: **127 passed**; extension build OK; manifest verified.
- [ ] **T6. Live E2E** — IN PROGRESS: backend already running NEW code (`--reload`; `/api/auth/auto` 404; WS 8766 OPEN); frontend started by orchestrator; **awaiting user**: reload unpacked extension → open signed-in `flow.google.com` tab → confirm. Then: verify `/api/accounts` registration → auto project creation → one image generation end-to-end → record evidence.
- [ ] **T7. Close** — dead code removal, final commits, doc + Engram mirror, honest close report.

## WS protocol (frozen contract — implemented both sides)
- Batch: backend→ext `{"type":"generate","batchId","requests":[{"requestId","rpcid","freq","captchaAction"}]}`; ext→backend `{"type":"result","batchId","results":[{"requestId","success","status","data","error"}]}`.
- Single RPC: backend→ext `{"type":"rpc","id","rpcid","freq","captchaAction"}`; ext→backend `{"type":"rpc_result","id","success","status","data","error"}`.
- Register: `{"type":"register","account","email"}` (email = Chrome profile label).
- Results reshaped to legacy `{"media":[{"image":{"generatedImage":{"mediaId","fifeUrl"}}}]}` so `images.py::save_image` is untouched.

## Incident log (reviews)
- T2: abandoned (`operator_disposition`); quarantine `.git/gentle-ai/review-transactions/quarantine/review-bb36a75575e2f86e-3725445824`.
- T3/T4: `declined_this_candidate` (user chose "Omitir esta vez" in the consent relay; no records; future reviews stay enabled).
- Reviewer config: six `review-*` agents set to `opencode-go/mimo-v2.6-flash` (backup `opencode.json.bak-2026-10-06`); caveat: `gentle-ai sync` may drop the `model` field.

## Acceptance criteria
- `/api/accounts` lists account(s) while a signed-in `flow.google.com` tab is open with the extension loaded. *(pending T6)*
- One fragment generation from Workflow completes: image file saved; no bearer path used. *(pending T6)*
- Project auto-provisioned per account (created once, persisted, reused); manual override respected. *(pending T6)*
- Character-reference generation via page-side upload, OR documented deferred. *(pending T6 — optional)*
- Envelope tests prove positional slots. ✅
- No code path calls `/fx/api/auth/session` or `aisandbox-pa...` with a bearer. ✅ (grep clean)
- Review outcomes recorded per candidate. ✅

## Checks
- Backend: `python -m pytest tests/ --ignore=tests/test_thumbnail_api.py` → **127 passed**. `test_thumbnail_api.py` hangs pre-existing at the SSE test (excluded).
- Extension: `bunx wxt build` OK; `.output/chrome-mv3/manifest.json` verified.
- E2E evidence → recorded under T6.

## TDD
Off (project precedent). Ordinary functional checks + unit tests.

## Progress / evidence
- 2026-10-06: diagnosis; T1; provisioning auto; T2 `20032b9`; docs `05985e9`/`e2328ea`/`3b7d2e0`/`5bb2548`/`dccc916`/`3c0b9d4` (RDD passive).
- 2026-10-06: T3 `4d2dbf7` (review declined); T4 `0e83fc1` (review declined); T5 127 passed; backend verified running NEW code; frontend started.
- Engram `mem_save` failing post-restart ("could not confirm session registration") — mirrors pending; local doc is authoritative.

## Next step
T6: awaiting user browser steps (reload extension, open signed-in Flow tab), then run the E2E verification chain.
