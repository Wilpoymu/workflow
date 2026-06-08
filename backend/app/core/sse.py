import asyncio
from collections import defaultdict


class SSEEventManager:
    def __init__(self):
        self._subscribers: dict[str, list[asyncio.Queue]] = defaultdict(list)

    def subscribe(self, project_id: str) -> asyncio.Queue:
        queue: asyncio.Queue = asyncio.Queue()
        self._subscribers[project_id].append(queue)
        return queue

    def unsubscribe(self, project_id: str, queue: asyncio.Queue):
        listeners = self._subscribers.get(project_id, [])
        if queue in listeners:
            listeners.remove(queue)

    async def emit(self, project_id: str, event: str, data: dict):
        listeners = self._subscribers.get(project_id, [])
        for queue in list(listeners):
            await queue.put((event, data))

    async def emit_progress(self, project_id: str, batch_id: str, fragment_id: int, progress: float):
        await self.emit(project_id, "progress", {
            "batchId": batch_id, "fragmentId": fragment_id, "progress": progress,
        })

    async def emit_result(self, project_id: str, batch_id: str, fragment_id: int, status: str, url: str = ""):
        await self.emit(project_id, "item_result", {
            "batchId": batch_id, "fragmentId": fragment_id, "status": status, "url": url,
        })

    async def emit_complete(self, project_id: str, batch_id: str, stats: dict):
        await self.emit(project_id, "complete", {"batchId": batch_id, "stats": stats})

    # ═══════════════════════════════════════════════════════════════
    # Workflow events
    # ═══════════════════════════════════════════════════════════════

    async def emit_workflow_start(self, project_id: str):
        await self.emit(project_id, "workflow_start", {})

    async def emit_workflow_stage_start(self, project_id: str, stage: str):
        await self.emit(project_id, "workflow_stage_start", {"stage": stage})

    async def emit_workflow_stage_complete(self, project_id: str, stage: str):
        await self.emit(project_id, "workflow_stage_complete", {"stage": stage})

    async def emit_workflow_stage_failed(self, project_id: str, stage: str, error: str):
        await self.emit(project_id, "workflow_stage_failed", {"stage": stage, "error": error})

    async def emit_workflow_progress(self, project_id: str, stage: str, progress: float, message: str = ""):
        await self.emit(project_id, "workflow_progress", {
            "stage": stage, "progress": progress, "message": message
        })

    async def emit_workflow_complete(self, project_id: str, results: dict):
        await self.emit(project_id, "workflow_complete", {"results": results})

    async def emit_workflow_failed(self, project_id: str, error: str):
        await self.emit(project_id, "workflow_failed", {"error": error})

    # ═══════════════════════════════════════════════════════════════
    # Prompt generation events
    # ═══════════════════════════════════════════════════════════════

    async def emit_prompt_batch_complete(self, project_id: str, batch_index: int, total_batches: int, fragment_ids: list[int]):
        await self.emit(project_id, "prompt_batch_complete", {
            "batchIndex": batch_index,
            "totalBatches": total_batches,
            "fragmentIds": fragment_ids,
        })

    async def emit_prompt_all_complete(self, project_id: str, total: int):
        await self.emit(project_id, "prompt_all_complete", {"total": total})

    async def emit_prompt_failed(self, project_id: str, error: str):
        await self.emit(project_id, "prompt_failed", {"error": error})


sse_manager = SSEEventManager()
