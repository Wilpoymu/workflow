import asyncio
import json
import logging
import time
import uuid
from typing import Awaitable, Callable

import websockets
from websockets.asyncio.server import ServerConnection

from app.config import settings
from app.core.sse import sse_manager
from app.services import flow_batch as fb
from app.services import flow_projects

logger = logging.getLogger(__name__)

SaveImageFn = Callable[[str, int, dict], Awaitable[bool]]

#: Accounts that answered PUBLIC_ERROR_UNUSUAL_ACTIVITY are parked this long
#: before the bridge hands them new work. That error is a session-score signal,
#: not a per-request one: retrying immediately makes the next call worse.
ACCOUNT_COOLDOWN_S = 120


def _legacy_image_payload(img: fb.GeneratedImage) -> dict:
    """Wrap a generated image in the payload shape save_image() consumes."""
    return {
        "media": [
            {
                "image": {
                    "generatedImage": {
                        "mediaId": img.media_id,
                        "fifeUrl": img.url,
                    }
                }
            }
        ]
    }


def _parse_generated_image(raw_data: str) -> fb.GeneratedImage:
    """Read the first generated image out of a raw batchexecute response."""
    payload = fb.first_payload(raw_data or "", fb.RPC_GEN_IMAGE)
    images = fb.read_images(payload)
    if not images:
        raise fb.FlowBatchError("batchexecute response carried no generated image")
    return images[0]


def _failure_text(raw_data, error: str = "") -> str:
    """Human-readable failure text: extension error first, raw data second."""
    text = str(error or "").strip()
    if not text:
        text = str(raw_data or "").strip()
    if not text:
        return "Flow request failed without an error message"
    return text[:300]


class ForgeBridge:
    def __init__(self):
        self.accounts: dict[str, ServerConnection] = {}
        self._account_emails: dict[str, str] = {}
        self._pending: list[dict] = []
        self._server = None
        self._save_image: SaveImageFn | None = None
        self._batch_results: dict[str, dict] = {}
        self._pending_chunks: dict[str, list[list]] = {}
        self._batch_events: dict[str, asyncio.Event] = {}
        self._reference_media_ids: dict[str, list[str]] = {}  # project_id -> [media_id, ...]
        self._rpc_pending: dict[str, asyncio.Future] = {}     # rpc id -> result future
        self._rpc_accounts: dict[str, str] = {}               # rpc id -> account hash
        self._account_cooldown: dict[str, float] = {}         # account_hash -> unix ts
        self._flow_projects_path = flow_projects.DEFAULT_STORE_PATH

    def set_save_image(self, fn: SaveImageFn):
        self._save_image = fn

    def get_accounts(self) -> list[dict]:
        accounts = [
            {
                "hash": h,
                "email": self._account_emails.get(h, f"Account {h[:8]}"),
                "connected": True,
            }
            for h in self.accounts.keys()
        ]
        logger.info("[ACCOUNTS] get_accounts: %d accounts | hashes: %s", len(accounts), [a["hash"][:12] for a in accounts])
        for a in accounts:
            logger.info("[ACCOUNTS]   %s: %s (connected=%s)", a["hash"][:12], a["email"], a["connected"])
        return accounts

    def get_reference_media_ids(self, project_id: str) -> list[str]:
        return self._reference_media_ids.get(project_id, [])

    def clear_reference_media_ids(self, project_id: str):
        """Clear stored reference media IDs for a project."""
        self._reference_media_ids.pop(project_id, None)
        logger.info("[BRIDGE] Cleared reference media IDs for %s", project_id)

    async def serve(self, host: str = "127.0.0.1", port: int = 8766):
        self._server = await websockets.serve(self._handler, host, port)
        logger.info("Forge bridge WS server started on %s:%s", host, port)

    async def shutdown(self):
        if self._server:
            self._server.close()
            await self._server.wait_closed()
            logger.info("Forge bridge WS server stopped")

    # ── batchexecute RPC transport ──────────────────────────────────────────

    def _available_accounts(self, selected_accounts: list[str] | None = None) -> list[tuple[str, ServerConnection]]:
        """Connected accounts, skipping any parked by an UNUSUAL_ACTIVITY cooldown."""
        now = time.time()
        cooling = [h for h in self.accounts if self._account_cooldown.get(h, 0) > now]
        if cooling:
            logger.info("[BRIDGE] Skipping %d cooling account(s): %s", len(cooling), [h[:12] for h in cooling])
        available = [(h, ws) for h, ws in self.accounts.items() if self._account_cooldown.get(h, 0) <= now]
        if selected_accounts:
            available = [(h, ws) for h, ws in available if h in selected_accounts]
        return available

    def _cool_down(self, account_hash: str | None):
        if not account_hash:
            return
        self._account_cooldown[account_hash] = time.time() + ACCOUNT_COOLDOWN_S
        logger.warning(
            "[BRIDGE] Account %s hit PUBLIC_ERROR_UNUSUAL_ACTIVITY — cooling down for %ds",
            account_hash[:12], ACCOUNT_COOLDOWN_S,
        )

    def _fail_pending_rpcs(self, account_hash: str):
        """Fail in-flight RPC futures promptly when their WS connection drops."""
        for rpc_id, acc in list(self._rpc_accounts.items()):
            if acc != account_hash:
                continue
            self._rpc_accounts.pop(rpc_id, None)
            fut = self._rpc_pending.pop(rpc_id, None)
            if fut and not fut.done():
                fut.set_exception(
                    RuntimeError(f"WS closed while awaiting rpc on account {account_hash[:12]}")
                )

    async def _rpc_over_ws(
        self,
        account_hash: str,
        rpcid: str,
        freq: str,
        captcha_action: str | None = None,
        timeout: float = 60,
    ) -> dict:
        """Send one RPC to an extension and await its ``rpc_result`` reply.

        The extension signs and issues the call inside the Flow tab (fresh
        reCAPTCHA per call); the backend only moves envelopes.
        """
        ws = self.accounts.get(account_hash)
        if ws is None:
            raise RuntimeError(f"account {account_hash[:12]} is not connected")
        rpc_id = str(uuid.uuid4())
        fut = asyncio.get_running_loop().create_future()
        self._rpc_pending[rpc_id] = fut
        self._rpc_accounts[rpc_id] = account_hash
        msg = {"type": "rpc", "id": rpc_id, "rpcid": rpcid, "freq": freq}
        if captcha_action:
            msg["captchaAction"] = captcha_action
        try:
            await ws.send(json.dumps(msg))
            return await asyncio.wait_for(fut, timeout=timeout)
        except websockets.exceptions.ConnectionClosed as e:
            raise RuntimeError(
                f"WS closed while sending {rpcid} to account {account_hash[:12]}"
            ) from e
        except asyncio.TimeoutError:
            raise TimeoutError(
                f"{rpcid} timed out after {timeout:g}s on account {account_hash[:12]}"
            ) from None
        finally:
            self._rpc_pending.pop(rpc_id, None)
            self._rpc_accounts.pop(rpc_id, None)

    # ── Flow project provisioning ───────────────────────────────────────────

    async def project_id_for(self, account_hash: str) -> str:
        """Resolve (or create + persist) this account's Flow project id."""
        store = flow_projects.load_store(self._flow_projects_path)
        project_id = flow_projects.resolve_project_id(
            account_hash,
            settings_project_id=settings.flow_project_id,
            store=store,
        )
        if project_id:
            return project_id

        if account_hash not in self.accounts:
            raise RuntimeError(f"cannot provision Flow project: account {account_hash[:12]} is not connected")

        email = self._account_emails.get(account_hash) or "account"
        raw = await self._rpc_over_ws(
            account_hash,
            fb.RPC_CREATE_PROJECT,
            fb.create_project_request("Workflow " + email[:60]),
            None,
            30,
        )
        if not raw.get("success"):
            raise RuntimeError(
                f"create project failed on account {account_hash[:12]}: "
                f"{raw.get('error') or raw.get('status')}"
            )
        project_id, _title = fb.read_created_project(
            fb.first_payload(raw.get("data", ""), fb.RPC_CREATE_PROJECT)
        )
        project_id = str(project_id or "").strip()
        if not project_id:
            raise fb.FlowBatchError("create project response carried no project id")
        flow_projects.remember_project_id(account_hash, project_id, self._flow_projects_path)
        logger.info("[BRIDGE] Provisioned Flow project %s for account %s", project_id, account_hash[:12])
        return project_id

    # ── dispatch ────────────────────────────────────────────────────────────

    async def dispatch(
        self,
        project_id: str,
        project_dir: str,
        fragments: list,
        batch_id: str,
        model: str = "NARWHAL",
        concurrency: int = 2,
        selected_accounts: list[str] | None = None,
        reference_image_ids: list[str] | None = None,
        reference_image_bytes: list[str] | None = None,
    ) -> int:
        fragments = [f for f in fragments if f.image_prompt.strip()]
        if not fragments:
            return 0

        state = {
            "batch_id": batch_id,
            "project_id": project_id,
            "project_dir": project_dir,
            "fragments": fragments,
            "total": len(fragments),
            "done": 0,
            "failed": 0,
            "model": model,
            "results": {},
            "accounts_used": [],
            # Reference material for the batchexecute builds. Bytes are uploaded
            # once per account (see _reference_ids_for) and cached here, so a
            # later chunk never re-uploads the same image.
            "reference_image_ids": list(reference_image_ids or []),
            "reference_image_bytes": list(reference_image_bytes or []),
            "ref_ids_by_account": {},
        }
        self._batch_results[batch_id] = state

        logger.info(
            "[BRIDGE] dispatch: batch=%s project=%s requests=%d model=%s",
            batch_id, project_id, len(fragments), model,
        )
        logger.info("[DISPATCH] accounts pool: %d | selected_accounts: %s",
                     len(self.accounts), selected_accounts)
        for h in self.accounts:
            logger.info("[DISPATCH]   account: %s (email: %s)", h[:12], self._account_emails.get(h, "?"))

        if not self.accounts:
            self._pending.append(state)
            logger.info("[DISPATCH] No accounts connected, batch %s queued", batch_id)
            return len(fragments)

        available = self._available_accounts(selected_accounts)
        if not available:
            self._pending.append(state)
            logger.info("[DISPATCH] No selected accounts available, batch %s queued", batch_id)
            return len(fragments)

        # One queue of fragment chunks. Envelopes are built per account when a
        # chunk is handed over, because freq embeds that account's project id.
        pending = [fragments[i:i + concurrency] for i in range(0, len(fragments), concurrency)]
        accounts_used: list[str] = []

        for acc_hash, ws in available:
            if not pending:
                break
            chunk = pending[0]
            try:
                requests = await self._build_batch_requests(chunk, acc_hash, state)
            except Exception as e:
                logger.error(
                    "[DISPATCH] Flow project/reference setup failed for account %s: %s",
                    acc_hash[:12], e,
                )
                continue  # leave the chunk queued and try the next account
            if not requests:
                pending.pop(0)
                continue
            try:
                await ws.send(json.dumps({
                    "type": "generate", "batchId": batch_id, "requests": requests,
                }))
            except websockets.exceptions.ConnectionClosed:
                self.accounts.pop(acc_hash, None)
                logger.warning("[DISPATCH] Account %s closed during send, chunk requeued", acc_hash[:12])
                continue  # leave the chunk queued
            pending.pop(0)
            accounts_used.append(acc_hash)
            logger.info("Sent %d prompts to account %s (concurrency=%d)", len(chunk), acc_hash[:12], concurrency)

        state["accounts_used"] = accounts_used

        if not accounts_used:
            logger.error("[DISPATCH] Batch %s could not be dispatched to any account", batch_id)
            self._batch_results.pop(batch_id, None)
            self._pending_chunks.pop(batch_id, None)
            return 0

        if pending:
            self._pending_chunks[batch_id] = pending
            logger.info("Queued %d remaining chunks for batch %s", len(pending), batch_id)

        return len(fragments)

    async def _build_batch_requests(self, fragments: list, account_hash: str, state: dict) -> list[dict]:
        """Build batchexecute generate items for one account at send time."""
        project_id = await self.project_id_for(account_hash)
        refs = await self._reference_ids_for(state, account_hash, project_id)
        model = fb.resolve_image_model(state.get("model"))
        requests_list = []
        for f in fragments:
            freq = fb.image_request(
                prompt=f.image_prompt,
                project_id=project_id,
                aspect="IMAGE_ASPECT_RATIO_LANDSCAPE",
                model=model,
                ref_media_ids=refs,
            )
            requests_list.append({
                "requestId": str(f.fragment_id),
                "rpcid": fb.RPC_GEN_IMAGE,
                "freq": freq,
                "captchaAction": fb.CAPTCHA_IMAGE,
            })
        return requests_list

    async def _reference_ids_for(self, state: dict, account_hash: str, project_id: str) -> list[str]:
        """Reference media ids for one account, uploading bytes on first use.

        Media ids are account-scoped on the new Flow, so the cache lives per
        account inside this dispatch (state["ref_ids_by_account"]).
        """
        cache = state.setdefault("ref_ids_by_account", {})
        if account_hash in cache:
            return cache[account_hash]
        refs = list(state.get("reference_image_ids") or [])
        for b64_img in state.get("reference_image_bytes") or []:
            try:
                raw = await self._rpc_over_ws(
                    account_hash,
                    fb.RPC_UPLOAD_IMAGE,
                    fb.upload_request(b64_img, project_id, mime_type="image/png", file_name="reference.png"),
                    fb.CAPTCHA_IMAGE,
                    60,
                )
                if not raw.get("success"):
                    logger.warning("[REF] Upload failed on %s: %s",
                                   account_hash[:12], raw.get("error") or raw.get("status"))
                    continue
                media_id = fb.read_uploaded_media_id(
                    fb.first_payload(raw.get("data", ""), fb.RPC_UPLOAD_IMAGE)
                )
                refs.append(media_id)
                logger.info("[REF] Uploaded reference %s via %s", media_id[:12], account_hash[:12])
            except Exception as e:
                logger.warning("[REF] Upload error on %s: %s", account_hash[:12], e)
        refs = list(dict.fromkeys(refs))
        cache[account_hash] = refs
        return refs

    async def dispatch_thumbnail(
        self,
        project_id: str,
        thumbnail_prompt: str,
        model: str = "NARWHAL",
    ) -> str | None:
        """Dispatch a SINGLE Flow image request for thumbnail background generation.

        Returns the flow-content.google image URL, or None on failure.
        """
        available = self._available_accounts(None)
        if not available:
            logger.warning("[THUMBNAIL] No accounts connected for dispatch")
            return None

        acc_hash, _ws = available[0]
        logger.info("[THUMBNAIL] dispatch: project=%s prompt=%.60s", project_id, thumbnail_prompt[:60])
        try:
            flow_project_id = await self.project_id_for(acc_hash)
            freq = fb.image_request(
                prompt=thumbnail_prompt,
                project_id=flow_project_id,
                count=1,
                aspect="IMAGE_ASPECT_RATIO_LANDSCAPE",
                model=fb.resolve_image_model(model),
            )
            raw = await self._rpc_over_ws(acc_hash, fb.RPC_GEN_IMAGE, freq, fb.CAPTCHA_IMAGE, 120)
        except Exception as e:
            logger.warning("[THUMBNAIL] Flow request failed: %s", e)
            return None

        if not raw.get("success"):
            err = _failure_text(raw.get("data", ""), str(raw.get("error") or ""))
            if "PUBLIC_ERROR_UNUSUAL_ACTIVITY" in f"{raw.get('error') or ''} {raw.get('data') or ''}":
                self._cool_down(acc_hash)
            logger.warning("[THUMBNAIL] Flow request failed: %s", err)
            return None

        try:
            img = _parse_generated_image(raw.get("data", ""))
        except (fb.RpcError, fb.FlowBatchError, ValueError) as e:
            logger.warning("[THUMBNAIL] Failed to parse Flow response: %s", e)
            return None

        logger.info("[THUMBNAIL] Got image url: %.100s", img.url)
        return img.url

    async def wait_for_batch(self, batch_id: str, timeout: int = 600) -> dict:
        """Wait for a batch to complete and return results"""
        evt = asyncio.Event()
        self._batch_events[batch_id] = evt
        try:
            await asyncio.wait_for(evt.wait(), timeout=timeout)
        except asyncio.TimeoutError:
            self._batch_events.pop(batch_id, None)
            raise TimeoutError(f"Batch {batch_id} timed out after {timeout}s")
        state = self._batch_results.pop(batch_id, {})
        if not state:
            state = {"done": 0, "failed": 0, "total": 0, "results": {}}
        return state

    def get_batch_progress(self, batch_id: str) -> dict | None:
        """Get current progress of a batch without waiting"""
        state = self._batch_results.get(batch_id)
        if not state:
            return None
        total = state.get("total", 1)
        done = state.get("done", 0)
        failed = state.get("failed", 0)
        return {"total": total, "done": done, "failed": failed, "progress": (done + failed) / max(total, 1)}

    def cancel_batch(self, batch_id: str) -> bool:
        """Cancel a pending/running batch"""
        state = self._batch_results.pop(batch_id, None)
        if not state:
            return False
        self._pending_chunks.pop(batch_id, None)
        evt = self._batch_events.pop(batch_id, None)
        if evt:
            evt.set()
        logger.info("Batch %s cancelled", batch_id)
        return True

    async def _handler(self, ws: ServerConnection):
        account_hash = None
        logger.info("New WS connection from client")
        try:
            async for raw in ws:
                msg = json.loads(raw)
                t = msg.get("type")
                if t == "register":
                    account_hash = msg["account"]
                    old_count = len(self.accounts)
                    self.accounts[account_hash] = ws
                    if "email" in msg:
                        self._account_emails[account_hash] = msg["email"]
                    logger.info("[ACCOUNTS] Registered: %s (email: %s) | total accounts: %d (was %d) | hashes: %s",
                                account_hash[:12], msg.get("email", "N/A"),
                                len(self.accounts), old_count,
                                list(self.accounts.keys()))
                    await self._flush_pending(ws, account_hash)
                elif t == "result":
                    logger.info("[BRIDGE] Result received: batch=%s results=%d from=%s", msg.get("batchId"), len(msg.get("results", [])), (account_hash or "?")[:12])
                    await self._handle_result(msg.get("batchId"), msg.get("results", []), account_hash)
                elif t == "rpc_result":
                    rpc_id = msg.get("id")
                    fut = self._rpc_pending.get(rpc_id)
                    if fut is None or fut.done():
                        logger.info("[BRIDGE] rpc_result for unknown/completed id: %s", rpc_id)
                    else:
                        fut.set_result(msg)
                else:
                    logger.info("[WS] Unknown message type: %s from %s", t, (account_hash or "?")[:12])
        except websockets.exceptions.ConnectionClosed:
            logger.info("[WS] Connection closed: %s", (account_hash or "?")[:12] if account_hash else "anonymous")
        except Exception as e:
            logger.error("[WS] Handler error: %s", e)
        finally:
            if account_hash and account_hash in self.accounts:
                del self.accounts[account_hash]
                logger.info("[ACCOUNTS] Disconnected: %s | remaining: %d | hashes: %s",
                            account_hash[:12], len(self.accounts), list(self.accounts.keys()))
            if account_hash:
                self._fail_pending_rpcs(account_hash)

    async def _flush_pending(self, ws: ServerConnection, account_hash: str):
        if not self._pending:
            return
        state = self._pending.pop(0)
        try:
            requests = await self._build_batch_requests(state["fragments"], account_hash, state)
            await ws.send(json.dumps({
                "type": "generate", "batchId": state["batch_id"], "requests": requests,
            }))
        except Exception as e:
            logger.error("[BRIDGE] Failed to flush queued batch %s to %s: %s",
                         state["batch_id"], account_hash[:12], e)
            self._pending.insert(0, state)
            return
        state.setdefault("accounts_used", []).append(account_hash)

    async def _handle_result(self, batch_id: str, results: list[dict], account_hash: str | None = None):
        state = self._batch_results.get(batch_id)
        if not state:
            logger.warning("Unknown batch result: %s", batch_id)
            return

        for r in results:
            rid = str(r.get("requestId", ""))
            raw_data = r.get("data") or ""
            if not isinstance(raw_data, str):
                raw_data = json.dumps(raw_data)
            ext_error = str(r.get("error") or "")
            try:
                fid = int(rid)
            except (TypeError, ValueError):
                logger.warning("[BRIDGE] Non-numeric requestId %r in batch %s — ignored", rid, batch_id)
                continue

            ok = bool(r.get("success", False))
            parse_error = ""
            img: fb.GeneratedImage | None = None
            if ok:
                try:
                    img = _parse_generated_image(raw_data)
                except (fb.RpcError, fb.FlowBatchError, ValueError) as e:
                    ok = False
                    parse_error = str(e)
                    logger.warning("[BRIDGE] Fragment %s: batchexecute parse failed: %s", rid, e)

            status = r.get("status", 0)
            logger.info("[BRIDGE] Result item: request=%s success=%s status=%s data_len=%d",
                        rid, ok, status, len(raw_data))
            state["results"][rid] = r

            if ok and self._save_image:
                saved = await self._save_image(state["project_id"], fid, _legacy_image_payload(img))
                if saved:
                    state["done"] += 1
                    await sse_manager.emit_result(state["project_id"], batch_id, fid, "done")
                else:
                    state["failed"] += 1
                    await sse_manager.emit_result(state["project_id"], batch_id, fid, "failed",
                                                   error="Flow returned 200 but no image data")
                    logger.warning("[BRIDGE] Fragment %s: envelope ok but save_image failed", rid)
            elif ok:
                state["done"] += 1
                await sse_manager.emit_result(state["project_id"], batch_id, fid, "done")
            else:
                state["failed"] += 1
                err_msg = _failure_text(raw_data, ext_error or parse_error)
                if "PUBLIC_ERROR_UNUSUAL_ACTIVITY" in f"{ext_error} {raw_data}":
                    self._cool_down(account_hash)
                await sse_manager.emit_result(state["project_id"], batch_id, fid, "failed", error=err_msg)
                logger.error("[BRIDGE] Fragment %s FAILED: status=%s error=%.300s", rid, status, err_msg)

            progress = (state["done"] + state["failed"]) / state["total"] * 100
            await sse_manager.emit_progress(state["project_id"], batch_id, fid, progress)

        # Flush next chunk to the reporting account (or a replacement if it is cooling)
        if account_hash and account_hash in self.accounts:
            await self._flush_next_chunk(batch_id, account_hash, self.accounts[account_hash])

        if state["done"] + state["failed"] >= state["total"]:
            await sse_manager.emit_complete(state["project_id"], batch_id, {
                "total": state["total"], "done": state["done"], "failed": state["failed"], "model": state["model"],
            })
            evt = self._batch_events.pop(batch_id, None)
            if evt:
                evt.set()
            self._batch_results.pop(batch_id, None)
            self._pending_chunks.pop(batch_id, None)

    async def _flush_next_chunk(self, batch_id: str, account_hash: str, ws: ServerConnection):
        chunks = self._pending_chunks.get(batch_id)
        if not chunks:
            return
        state = self._batch_results.get(batch_id)
        if not state:
            self._pending_chunks.pop(batch_id, None)
            return

        target_hash, target_ws = account_hash, ws
        if self._account_cooldown.get(account_hash, 0) > time.time():
            alternatives = self._available_accounts(None)
            if not alternatives:
                logger.warning(
                    "[BRIDGE] Account %s cooling and no replacement available — %d chunk(s) for batch %s stay queued",
                    account_hash[:12], len(chunks), batch_id,
                )
                return
            target_hash, target_ws = alternatives[0]
            logger.info("[BRIDGE] Account %s cooling — handing next chunk to %s",
                        account_hash[:12], target_hash[:12])

        chunk = chunks[0]
        try:
            requests = await self._build_batch_requests(chunk, target_hash, state)
        except Exception as e:
            logger.error("[BRIDGE] Failed to build next chunk for batch %s on %s: %s",
                         batch_id, target_hash[:12], e)
            return  # keep the chunk queued
        try:
            await target_ws.send(json.dumps({
                "type": "generate", "batchId": batch_id, "requests": requests,
            }))
        except websockets.exceptions.ConnectionClosed:
            self.accounts.pop(target_hash, None)
            logger.warning("[BRIDGE] Account %s closed while flushing batch %s", target_hash[:12], batch_id)
            return  # keep the chunk queued
        chunks.pop(0)
        state.setdefault("accounts_used", []).append(target_hash)
        logger.info("Flushed next chunk (%d prompts) to account %s", len(chunk), target_hash[:12])
        if not chunks:
            self._pending_chunks.pop(batch_id, None)

    def _chunk(self, items: list, n: int) -> list[list]:
        if n < 1:
            return [items]
        k, m = divmod(len(items), n)
        return [items[i * k + min(i, m):(i + 1) * k + min(i + 1, m)] for i in range(n)]


bridge = ForgeBridge()
