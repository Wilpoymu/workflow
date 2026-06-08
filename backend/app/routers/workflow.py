"""
Workflow router - Orquestador de pipeline completo
"""
import asyncio
import json

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from typing import Optional

from app.services import orchestrator
from app.services.orchestrator import PipelineStatus
from app.core.sse import sse_manager

router = APIRouter(prefix="/api/projects/{project_id}/workflow", tags=["workflow"])


class WorkflowConfig(BaseModel):
    """Configuración opcional para el workflow"""
    concurrency: int = 2
    accounts: list[str] | None = None
    render: Optional[dict] = None


class WorkflowStageStatus(BaseModel):
    status: str
    progress: float


class WorkflowStateResponse(BaseModel):
    project_id: str
    status: str
    current_stage: Optional[str]
    stages: dict[str, WorkflowStageStatus]
    error: Optional[str]
    started_at: Optional[str]
    completed_at: Optional[str]
    results: dict
    stage_timings: dict[str, dict] = {}


@router.post("")
async def start_workflow(project_id: str, config: WorkflowConfig = WorkflowConfig()):
    """
    Iniciar el pipeline completo: prompts → generate → transcribe → render
    
    Ejecuta las 4 etapas en secuencia:
    1. Prompts: Genera image_prompt para fragments via AI (Google/Groq/Ollama/OpenRouter)
    2. Generate: Genera imágenes desde los prompts vía Forge
    3. Transcribe: Transcribe el audio con Whisper
    4. Render: Genera video con Ken Burns
    
    Retorna inmediatamente. Usa SSE para seguir el progreso.
    """
    try:
        await orchestrator.start_workflow(
            project_id,
            config.render,
            concurrency=config.concurrency,
            accounts=config.accounts,
        )
        return {"project_id": project_id, "status": "started"}
    except RuntimeError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("")
async def get_workflow_status(project_id: str):
    """
    Obtener el estado actual del workflow para un proyecto.
    
    Retorna el estado de cada etapa y el progreso general.
    """
    workflow = orchestrator.get_workflow_state(project_id)
    
    if not workflow:
        return {
            "project_id": project_id,
            "status": PipelineStatus.IDLE,
            "current_stage": None,
            "stages": {
                "prompts": {"status": PipelineStatus.IDLE, "progress": 0.0},
                "generate": {"status": PipelineStatus.IDLE, "progress": 0.0},
                "transcribe": {"status": PipelineStatus.IDLE, "progress": 0.0},
                "render": {"status": PipelineStatus.IDLE, "progress": 0.0},
            },
            "error": None,
            "started_at": None,
            "completed_at": None,
            "results": {},
        }
    
    return WorkflowStateResponse(
        project_id=workflow.project_id,
        status=workflow.status,
        current_stage=workflow.current_stage,
        stages={
            stage: WorkflowStageStatus(
                status=workflow.stage_status[stage],
                progress=workflow.stage_progress[stage]
            )
            for stage in workflow.stage_status
        },
        error=workflow.error,
        started_at=workflow.started_at.isoformat() if workflow.started_at else None,
        completed_at=workflow.completed_at.isoformat() if workflow.completed_at else None,
        results=workflow.results,
        stage_timings=workflow.stage_timings,
    )


@router.post("/cancel")
async def cancel_workflow(project_id: str):
    """
    Cancelar un workflow en ejecución.
    
    Nota: No puede cancelar inmediatamente las tareas en curso,
    pero marca el workflow como failed para detener la progresión.
    """
    success = orchestrator.cancel_workflow(project_id)
    
    if not success:
        raise HTTPException(
            status_code=400,
            detail="No active workflow to cancel or workflow already completed"
        )
    
    return {"project_id": project_id, "status": "cancelled"}


@router.get("/events")
async def workflow_events(request: Request, project_id: str):
    """
    Server-Sent Events para seguir el progreso del workflow en tiempo real.
    
    Eventos emitidos:
    - workflow_start: El workflow comenzó
    - workflow_stage_start: Una etapa comenzó
    - workflow_stage_complete: Una etapa se completó
    - workflow_stage_failed: Una etapa falló
    - workflow_progress: Progreso de una etapa
    - workflow_complete: El workflow completo terminó
    - workflow_failed: El workflow completo falló
    - prompt_batch_complete: Un batch de prompts se generó
    - prompt_all_complete: Todos los prompts se generaron
    - prompt_failed: Falló la generación de prompts
    """
    queue = sse_manager.subscribe(project_id)
    
    async def event_generator():
        try:
            while True:
                if await request.is_disconnected():
                    break
                try:
                    event_type, data = await asyncio.wait_for(queue.get(), timeout=30)
                    if event_type.startswith("workflow_") or event_type.startswith("prompt_"):
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
