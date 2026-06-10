import asyncio
import json
from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from app.services import prompt_generation, project_service
from app.core.sse import sse_manager

router = APIRouter(prefix="/api/projects/{project_id}/prompts", tags=["prompts"])


class GeneratePromptsRequest(BaseModel):
    style: str = "Cinematico"
    fragment_ids: list[int] | None = None
    use_gemini_web: bool = True


class SetStyleRequest(BaseModel):
    style: str


@router.post("/generate")
async def generate_prompts(project_id: str, body: GeneratePromptsRequest):
    """Generate AI image prompts for project fragments.

    Reads pending fragments from prompts-*.json, sends them through the
    AI provider fallback chain (Google -> Ollama -> Groq -> OpenRouter),
    and updates each fragment with its generated image_prompt.
    """
    try:
        # Persist the style for the workflow to use later
        await project_service.save_project_style(project_id, body.style)

        results = await prompt_generation.generate_prompts_for_project(
            project_id,
            style=body.style,
            fragment_ids=body.fragment_ids,
            use_gemini_web=body.use_gemini_web,
        )
        return {
            "project_id": project_id,
            "total": len(results),
            "results": results,
        }
    except ValueError as e:
        await sse_manager.emit_prompt_failed(project_id, str(e))
        raise HTTPException(400, str(e))
    except RuntimeError as e:
        await sse_manager.emit_prompt_failed(project_id, str(e))
        raise HTTPException(502, str(e))


@router.put("/style")
async def set_prompt_style(project_id: str, body: SetStyleRequest):
    """Save the image style for this project (used by the workflow)."""
    await project_service.save_project_style(project_id, body.style)
    return {"project_id": project_id, "style": body.style, "saved": True}


@router.get("/events")
async def prompt_events(request: Request, project_id: str):
    """SSE endpoint for real-time prompt generation progress.

    Events:
    - prompt_batch_complete: a batch of fragments was processed
    - prompt_all_complete: all fragments processed
    - prompt_failed: generation failed
    """
    queue = sse_manager.subscribe(project_id)

    async def event_generator():
        try:
            while True:
                if await request.is_disconnected():
                    break
                try:
                    event_type, data = await asyncio.wait_for(queue.get(), timeout=30)
                    if event_type.startswith("prompt_"):
                        yield f"event: {event_type}\ndata: {json.dumps(data)}\n\n"
                except asyncio.TimeoutError:
                    yield ": keepalive\n\n"
        finally:
            sse_manager.unsubscribe(project_id, queue)

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )
