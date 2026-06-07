import asyncio
import json
import logging
import random
import time
import uuid
from typing import Awaitable, Callable

import websockets
from websockets.asyncio.server import ServerConnection

from app.core.sse import sse_manager

logger = logging.getLogger(__name__)

SaveImageFn = Callable[[str, int, dict], Awaitable[None]]


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

    def set_save_image(self, fn: SaveImageFn):
        self._save_image = fn

    def get_accounts(self) -> list[dict]:
        return [
            {
                "hash": h,
                "email": self._account_emails.get(h, f"Account {h[:8]}"),
                "connected": True,
            }
            for h in self.accounts.keys()
        ]

    def register_account_email(self, account_hash: str, email: str):
        self._account_emails[account_hash] = email

    async def serve(self, host: str = "127.0.0.1", port: int = 8766):
        self._server = await websockets.serve(self._handler, host, port)
        logger.info("Forge bridge WS server started on %s:%s", host, port)

    async def shutdown(self):
        if self._server:
            self._server.close()
            await self._server.wait_closed()
            logger.info("Forge bridge WS server stopped")

    async def dispatch(
        self,
        project_id: str,
        project_dir: str,
        fragments: list,
        batch_id: str,
        model: str = "NARWHAL",
        concurrency: int = 2,
        selected_accounts: list[str] | None = None,
    ) -> int:
        flow_project_id = uuid.uuid4().hex
        base_url = f"https://aisandbox-pa.googleapis.com/v1/projects/{flow_project_id}/flowMedia:batchGenerateImages"
        session_id = f";{int(time.time() * 1000)}"

        requests = []
        for f in fragments:
            if not f.image_prompt.strip():
                continue
            body = {
                "clientContext": {
                    "projectId": flow_project_id,
                    "tool": "PINHOLE",
                    "sessionId": session_id,
                },
                "mediaGenerationContext": {
                    "batchId": batch_id,
                },
                "useNewMedia": True,
                "requests": [
                    {
                        "clientContext": {
                            "projectId": flow_project_id,
                            "tool": "PINHOLE",
                            "sessionId": session_id,
                        },
                        "imageModelName": model,
                        "imageAspectRatio": "IMAGE_ASPECT_RATIO_LANDSCAPE",
                        "structuredPrompt": {
                            "parts": [{"text": f.image_prompt}],
                        },
                        "seed": random.randint(1, 999999),
                    }
                ],
            }
            requests.append({
                "requestId": str(f.fragment_id),
                "url": base_url,
                "body": body,
                "prompt": f.image_prompt,
            })
        if not requests:
            return 0

        logger.info(
            "[BRIDGE] dispatch: batch=%s project=%s requests=%d url=%s first_prompt=%.60s",
            batch_id, project_id, len(requests), base_url, requests[0].get("prompt", "")[:60],
        )

        state = {
            "batch_id": batch_id,
            "project_id": project_id,
            "project_dir": project_dir,
            "requests": requests,
            "total": len(requests),
            "done": 0,
            "failed": 0,
            "model": model,
            "results": {},
            "accounts_used": [],
        }
        self._batch_results[batch_id] = state

        if not self.accounts:
            self._pending.append(state)
            logger.info("No accounts connected, batch %s queued", batch_id)
            return len(requests)

        available = list(self.accounts.items())
        if selected_accounts:
            available = [(h, ws) for h, ws in available if h in selected_accounts]

        if not available:
            self._pending.append(state)
            logger.info("No selected accounts available, batch %s queued", batch_id)
            return len(requests)

        # Create concurrency-sized chunks (prompts per account per round)
        chunks = [requests[i:i+concurrency] for i in range(0, len(requests), concurrency)]

        # Send one chunk per account
        accounts_used = []
        for i, (acc_hash, ws) in enumerate(available):
            if i >= len(chunks):
                break
            chunk = chunks[i]
            if not chunk:
                continue
            accounts_used.append(acc_hash)
            try:
                await ws.send(json.dumps({
                    "type": "generate", "batchId": batch_id, "requests": chunk,
                }))
                logger.info("Sent %d prompts to account %s (concurrency=%d)", len(chunk), acc_hash[:12], concurrency)
            except websockets.exceptions.ConnectionClosed:
                self.accounts.pop(acc_hash, None)

        state["accounts_used"] = accounts_used

        # Queue remaining chunks for accounts that finish their batch
        remaining = chunks[len(accounts_used):]
        if remaining:
            self._pending_chunks[batch_id] = remaining
            logger.info("Queued %d remaining chunks for batch %s", len(remaining), batch_id)

        return len(requests)

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
                    self.accounts[account_hash] = ws
                    if "email" in msg:
                        self._account_emails[account_hash] = msg["email"]
                    logger.info("Account registered: %s (email: %s)", account_hash[:12], msg.get("email", "N/A"))
                    await self._flush_pending(ws, account_hash)
                elif t == "result":
                    logger.info("[BRIDGE] Result received: batch=%s results=%d from=%s", msg.get("batchId"), len(msg.get("results", [])), (account_hash or "?")[:12])
                    await self._handle_result(msg.get("batchId"), msg.get("results", []), account_hash)
        except websockets.exceptions.ConnectionClosed:
            pass
        finally:
            if account_hash and account_hash in self.accounts:
                del self.accounts[account_hash]
                logger.info("Account disconnected: %s", account_hash[:12])

    async def _flush_pending(self, ws: ServerConnection, account_hash: str):
        if not self._pending:
            return
        state = self._pending.pop(0)
        try:
            await ws.send(json.dumps({
                "type": "generate", "batchId": state["batch_id"], "requests": state["requests"],
            }))
        except Exception:
            self._pending.insert(0, state)

    async def _handle_result(self, batch_id: str, results: list[dict], account_hash: str | None = None):
        state = self._batch_results.get(batch_id)
        if not state:
            logger.warning("Unknown batch result: %s", batch_id)
            return

        for r in results:
            rid = r.get("requestId", "")
            ok = r.get("success", False)
            status = r.get("status", 0)
            raw_data = r.get("data", "")
            # The response body is a JSON string — parse it
            parsed = raw_data
            if isinstance(raw_data, str):
                try:
                    parsed = json.loads(raw_data)
                except (json.JSONDecodeError, TypeError):
                    parsed = {"raw": raw_data}
            elif not isinstance(raw_data, dict):
                parsed = {"raw": str(raw_data)}
            
            data_preview = (raw_data or "")[:200]
            logger.info("[BRIDGE] Result item: request=%s success=%s status=%s data_len=%d preview=%.120s", rid, ok, status, len(data_preview), data_preview)
            state["results"][rid] = r
            fid = int(rid)

            if ok:
                state["done"] += 1
                if self._save_image:
                    await self._save_image(state["project_id"], fid, parsed)
                await sse_manager.emit_result(state["project_id"], batch_id, fid, "done")
            else:
                state["failed"] += 1
                await sse_manager.emit_result(state["project_id"], batch_id, fid, "failed")

            progress = (state["done"] + state["failed"]) / state["total"] * 100
            await sse_manager.emit_progress(state["project_id"], batch_id, fid, progress)

        # Flush next chunk to the reporting account
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
        chunk = chunks.pop(0)
        try:
            await ws.send(json.dumps({
                "type": "generate", "batchId": batch_id, "requests": chunk,
            }))
            logger.info("Flushed next chunk (%d prompts) to account %s", len(chunk), account_hash[:12])
        except websockets.exceptions.ConnectionClosed:
            self.accounts.pop(account_hash, None)
            chunks.insert(0, chunk)
        if not chunks:
            self._pending_chunks.pop(batch_id, None)

    def _chunk(self, items: list, n: int) -> list[list]:
        if n < 1:
            return [items]
        k, m = divmod(len(items), n)
        return [items[i * k + min(i, m):(i + 1) * k + min(i + 1, m)] for i in range(n)]


bridge = ForgeBridge()
