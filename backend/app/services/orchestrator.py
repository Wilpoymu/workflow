"""
Orchestrator service - Pipeline completo de un solo clic
Ejecuta: generate prompts → generate images → transcribe audio → render video
"""
import asyncio
import logging
import uuid
from pathlib import Path
from typing import Optional
from datetime import datetime

from app.services.forge_bridge import bridge
from app.services.whisper_pipeline import transcribe_audio, save_transcription
from app.services.kenburns import render_kenburns_video, KenBurnsConfig
from app.services.prompt_generation import generate_prompts_for_project
from app.services import project_service
from app.core.sse import sse_manager

logger = logging.getLogger(__name__)


class PipelineStage:
    PROMPTS = "prompts"
    GENERATE = "generate"
    TRANSCRIBE = "transcribe"
    RENDER = "render"

    ALL = (PROMPTS, GENERATE, TRANSCRIBE, RENDER)


class PipelineStatus:
    IDLE = "idle"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"


class WorkflowState:
    def __init__(self, project_id: str):
        self.project_id = project_id
        self.status = PipelineStatus.IDLE
        self.current_stage: Optional[str] = None
        self.stage_progress: dict[str, float] = {
            stage: 0.0 for stage in PipelineStage.ALL
        }
        self.stage_status: dict[str, str] = {
            stage: PipelineStatus.IDLE for stage in PipelineStage.ALL
        }
        self.error: Optional[str] = None
        self.started_at: Optional[datetime] = None
        self.completed_at: Optional[datetime] = None
        self.results: dict = {}
        self.stage_timings: dict[str, dict] = {
            stage: {} for stage in PipelineStage.ALL
        }


# Estado global de workflows activos
_active_workflows: dict[str, WorkflowState] = {}


def get_workflow_state(project_id: str) -> Optional[WorkflowState]:
    """Obtener el estado de un workflow"""
    return _active_workflows.get(project_id)


async def start_workflow(
    project_id: str,
    render_config: Optional[dict] = None,
    concurrency: int = 2,
    accounts: list[str] | None = None,
) -> str:
    """
    Iniciar el pipeline completo para un proyecto.
    Retorna el project_id.
    """
    if project_id in _active_workflows:
        workflow = _active_workflows[project_id]
        if workflow.status == PipelineStatus.RUNNING:
            raise RuntimeError(f"Workflow already running for project {project_id}")
    
    # Crear estado del workflow
    workflow = WorkflowState(project_id)
    workflow.status = PipelineStatus.RUNNING
    workflow.started_at = datetime.utcnow()
    _active_workflows[project_id] = workflow
    
    # Emitir evento de inicio
    await sse_manager.emit_workflow_start(project_id)
    
    # Ejecutar pipeline en background
    asyncio.create_task(_run_pipeline(project_id, render_config or {}, concurrency, accounts or []))
    
    return project_id


async def _run_pipeline(project_id: str, render_config: dict, concurrency: int = 2, accounts: list[str] | None = None):
    """Ejecutar el pipeline completo"""
    workflow = _active_workflows.get(project_id)
    if not workflow:
        return
    
    try:
        # Obtener proyecto
        project = await project_service.get_project(project_id)
        if not project:
            raise RuntimeError(f"Project {project_id} not found")
        
        project_path = Path(project.base_dir)

        # ═══════════════════════════════════════════════════════════════
        # STAGE 0: GENERATE PROMPTS (AI image prompts for fragments)
        # ═══════════════════════════════════════════════════════════════
        workflow.current_stage = PipelineStage.PROMPTS
        workflow.stage_status[PipelineStage.PROMPTS] = PipelineStatus.RUNNING
        workflow.stage_timings[PipelineStage.PROMPTS]["started_at"] = datetime.utcnow().isoformat()
        await sse_manager.emit_workflow_stage_start(project_id, PipelineStage.PROMPTS)

        try:
            fragments = await project_service.list_fragments(project_id)
            pending_prompts = [f for f in fragments if not f.image_prompt or not f.image_prompt.strip()]

            if pending_prompts:
                logger.info("[WORKFLOW] Generating prompts for %d fragments", len(pending_prompts))
                # Read saved style from project metadata
                style = (project.prompt_style
                         if hasattr(project, "prompt_style") and project.prompt_style
                         else "Cinematico")
                async def _on_prompt_progress(p: float, msg: str):
                    workflow.stage_progress[PipelineStage.PROMPTS] = p
                    await sse_manager.emit_workflow_progress(
                        project_id, PipelineStage.PROMPTS, p, msg,
                    )

                results = await generate_prompts_for_project(
                    project_id, style=style,
                    progress_callback=_on_prompt_progress,
                )
                workflow.results["prompts"] = {"total": len(results), "generated": len(results)}
            else:
                logger.info("[WORKFLOW] All fragments already have prompts, skipping")
                workflow.results["prompts"] = {"total": 0, "generated": 0, "skipped": True}

            workflow.stage_progress[PipelineStage.PROMPTS] = 1.0
            workflow.stage_status[PipelineStage.PROMPTS] = PipelineStatus.COMPLETED
            st = workflow.stage_timings[PipelineStage.PROMPTS]
            st["completed_at"] = datetime.utcnow().isoformat()
            st["duration_s"] = round((datetime.utcnow() - datetime.fromisoformat(st["started_at"])).total_seconds(), 1)
            await sse_manager.emit_workflow_stage_complete(project_id, PipelineStage.PROMPTS)

        except Exception as e:
            workflow.stage_status[PipelineStage.PROMPTS] = PipelineStatus.FAILED
            workflow.error = f"Prompts stage failed: {str(e)}"
            st = workflow.stage_timings[PipelineStage.PROMPTS]
            st["failed_at"] = datetime.utcnow().isoformat()
            if "started_at" in st:
                st["duration_s"] = round((datetime.utcnow() - datetime.fromisoformat(st["started_at"])).total_seconds(), 1)
            await sse_manager.emit_workflow_stage_failed(project_id, PipelineStage.PROMPTS, str(e))
            raise

        # ═══════════════════════════════════════════════════════════════
        # STAGE 1: GENERATE IMAGES
        # ═══════════════════════════════════════════════════════════════
        workflow.current_stage = PipelineStage.GENERATE
        workflow.stage_status[PipelineStage.GENERATE] = PipelineStatus.RUNNING
        workflow.stage_timings[PipelineStage.GENERATE]["started_at"] = datetime.utcnow().isoformat()
        await sse_manager.emit_workflow_stage_start(project_id, PipelineStage.GENERATE)

        try:
            fragments = await project_service.list_fragments(project_id)
            pending = [f for f in fragments if f.image_prompt.strip()]
            if not pending:
                raise RuntimeError("No fragments with prompts found. Generate prompts in Editor first.")

            # Skip fragments that already have a generated image
            img_dir = project_path / "imagenes"
            existing_ids: set[int] = set()
            if img_dir.exists():
                for p in img_dir.glob("escena_*.png"):
                    try:
                        fid = int(p.stem.split("_")[1])
                        existing_ids.add(fid)
                    except (IndexError, ValueError):
                        pass
            if existing_ids:
                logger.info("[WORKFLOW] %d images already exist, skipping them", len(existing_ids))
                pending = [f for f in pending if f.fragment_id not in existing_ids]
            if not pending:
                logger.info("[WORKFLOW] All fragments already have images, skipping generate stage")
                workflow.stage_progress[PipelineStage.GENERATE] = 1.0
                workflow.stage_status[PipelineStage.GENERATE] = PipelineStatus.COMPLETED
                workflow.results["generate"] = {"completed": 0, "failed": 0, "total": 0, "skipped": True}
                st = workflow.stage_timings[PipelineStage.GENERATE]
                st["completed_at"] = datetime.utcnow().isoformat()
                st["duration_s"] = round((datetime.utcnow() - datetime.fromisoformat(st["started_at"])).total_seconds(), 1)
                await sse_manager.emit_workflow_stage_complete(project_id, PipelineStage.GENERATE)
            else:
                total = len(pending)
                batch_id = uuid.uuid4().hex[:8]

                sent = await bridge.dispatch(
                    project_id,
                    str(project_path),
                    pending,
                    batch_id,
                    concurrency=concurrency,
                    selected_accounts=accounts,
                )

                if sent == 0:
                    raise RuntimeError("No prompts were dispatched. Check connected accounts.")

                # Poll for progress with cancellation support
                result = None
                while result is None:
                    # Check if workflow was cancelled
                    wf = _active_workflows.get(project_id)
                    if wf and wf.status == PipelineStatus.FAILED:
                        bridge.cancel_batch(batch_id)
                        raise RuntimeError("Workflow cancelled by user")

                    progress_data = bridge.get_batch_progress(batch_id)
                    if progress_data:
                        pct = progress_data["progress"]
                        workflow.stage_progress[PipelineStage.GENERATE] = pct
                        await sse_manager.emit_workflow_progress(
                            project_id, PipelineStage.GENERATE, pct,
                            f"Generated {progress_data['done']}/{progress_data['total']} images",
                        )

                    try:
                        result = await asyncio.wait_for(
                            bridge.wait_for_batch(batch_id, timeout=5),
                            timeout=5,
                        )
                    except asyncio.TimeoutError:
                        pass  # Poll again

                completed = result.get("done", 0)
                failed = result.get("failed", 0)

                workflow.stage_progress[PipelineStage.GENERATE] = 1.0
                workflow.stage_status[PipelineStage.GENERATE] = PipelineStatus.COMPLETED
                workflow.results["generate"] = {"completed": completed, "failed": failed, "total": total}
                st = workflow.stage_timings[PipelineStage.GENERATE]
                st["completed_at"] = datetime.utcnow().isoformat()
                st["duration_s"] = round((datetime.utcnow() - datetime.fromisoformat(st["started_at"])).total_seconds(), 1)
                await sse_manager.emit_workflow_stage_complete(project_id, PipelineStage.GENERATE)

        except Exception as e:
            workflow.stage_status[PipelineStage.GENERATE] = PipelineStatus.FAILED
            workflow.error = f"Generate stage failed: {str(e)}"
            st = workflow.stage_timings[PipelineStage.GENERATE]
            st["failed_at"] = datetime.utcnow().isoformat()
            if "started_at" in st:
                st["duration_s"] = round((datetime.utcnow() - datetime.fromisoformat(st["started_at"])).total_seconds(), 1)
            await sse_manager.emit_workflow_stage_failed(project_id, PipelineStage.GENERATE, str(e))
            raise
        # ═══════════════════════════════════════════════════════════════
        # STAGE 2: TRANSCRIBE AUDIO
        # ═══════════════════════════════════════════════════════════════
        workflow.current_stage = PipelineStage.TRANSCRIBE
        workflow.stage_status[PipelineStage.TRANSCRIBE] = PipelineStatus.RUNNING
        workflow.stage_timings[PipelineStage.TRANSCRIBE]["started_at"] = datetime.utcnow().isoformat()
        await sse_manager.emit_workflow_stage_start(project_id, PipelineStage.TRANSCRIBE)
        
        try:
            # Buscar archivo de audio
            audio_dir = project_path / "audio"
            audio_dir.mkdir(exist_ok=True)
            audio_files = list(audio_dir.glob("*.mp3")) + list(audio_dir.glob("*.wav"))

            if not audio_files:
                audio_extensions = [".mp3", ".wav", ".m4a", ".ogg", ".flac"]
                for ext in audio_extensions:
                    for f in project_path.glob(f"*{ext}"):
                        dest = audio_dir / f.name
                        f.rename(dest)
                        audio_files.append(dest)

            if not audio_files:
                raise RuntimeError("No audio file found. Upload an audio file first.")
            
            audio_file = audio_files[0]
            
            # Función de callback para progreso (se llama desde thread pool)
            def progress_callback(progress: float, message: str):
                workflow.stage_progress[PipelineStage.TRANSCRIBE] = progress
                asyncio.run_coroutine_threadsafe(
                    sse_manager.emit_workflow_progress(
                        project_id,
                        PipelineStage.TRANSCRIBE,
                        progress,
                        message
                    ),
                    loop
                )
            
            # Transcribir (ejecutar en thread pool)
            loop = asyncio.get_event_loop()
            segment = await loop.run_in_executor(
                None,
                lambda: transcribe_audio(str(audio_file), progress_callback)
            )
            
            # Guardar transcripción
            text_path = project_path / "text.txt"
            text_path_arg = str(text_path) if text_path.exists() else None
            save_transcription(str(project_path), segment, text_path_arg)
            
            workflow.stage_progress[PipelineStage.TRANSCRIBE] = 1.0
            workflow.stage_status[PipelineStage.TRANSCRIBE] = PipelineStatus.COMPLETED
            workflow.results["transcribe"] = {"words": len([w for w in segment.words if w.type == "word"])}
            st = workflow.stage_timings[PipelineStage.TRANSCRIBE]
            st["completed_at"] = datetime.utcnow().isoformat()
            st["duration_s"] = round((datetime.utcnow() - datetime.fromisoformat(st["started_at"])).total_seconds(), 1)
            await sse_manager.emit_workflow_stage_complete(project_id, PipelineStage.TRANSCRIBE)
            
        except Exception as e:
            workflow.stage_status[PipelineStage.TRANSCRIBE] = PipelineStatus.FAILED
            workflow.error = f"Transcribe stage failed: {str(e)}"
            st = workflow.stage_timings[PipelineStage.TRANSCRIBE]
            st["failed_at"] = datetime.utcnow().isoformat()
            if "started_at" in st:
                st["duration_s"] = round((datetime.utcnow() - datetime.fromisoformat(st["started_at"])).total_seconds(), 1)
            await sse_manager.emit_workflow_stage_failed(project_id, PipelineStage.TRANSCRIBE, str(e))
            raise
        
        # ═══════════════════════════════════════════════════════════════
        # STAGE 3: RENDER VIDEO
        # ═══════════════════════════════════════════════════════════════
        workflow.current_stage = PipelineStage.RENDER
        workflow.stage_status[PipelineStage.RENDER] = PipelineStatus.RUNNING
        workflow.stage_timings[PipelineStage.RENDER]["started_at"] = datetime.utcnow().isoformat()
        await sse_manager.emit_workflow_stage_start(project_id, PipelineStage.RENDER)
        
        try:
            # Configurar Ken Burns
            config = KenBurnsConfig(
                filter_mode=render_config.get("filter_mode", "all"),
                width=render_config.get("width", 1920),
                height=render_config.get("height", 1080),
                fps=render_config.get("fps", 30),
                intensity=render_config.get("intensity", 0.04),
                seed=render_config.get("seed", 42),
                subtitles=render_config.get("subtitles", True),
            )
            
            # Función de callback para progreso
            def render_progress_callback(progress: float, message: str):
                workflow.stage_progress[PipelineStage.RENDER] = progress
                asyncio.create_task(sse_manager.emit_workflow_progress(
                    project_id,
                    PipelineStage.RENDER,
                    progress,
                    message
                ))
            
            # Renderizar video
            output_path = await render_kenburns_video(
                str(project_path),
                config,
                render_progress_callback
            )
            
            if not output_path:
                raise RuntimeError("Render failed - no output file")
            
            workflow.stage_progress[PipelineStage.RENDER] = 1.0
            workflow.stage_status[PipelineStage.RENDER] = PipelineStatus.COMPLETED
            workflow.results["render"] = {"output": str(output_path)}
            st = workflow.stage_timings[PipelineStage.RENDER]
            st["completed_at"] = datetime.utcnow().isoformat()
            st["duration_s"] = round((datetime.utcnow() - datetime.fromisoformat(st["started_at"])).total_seconds(), 1)
            await sse_manager.emit_workflow_stage_complete(project_id, PipelineStage.RENDER)
            
        except Exception as e:
            workflow.stage_status[PipelineStage.RENDER] = PipelineStatus.FAILED
            workflow.error = f"Render stage failed: {str(e)}"
            st = workflow.stage_timings[PipelineStage.RENDER]
            st["failed_at"] = datetime.utcnow().isoformat()
            if "started_at" in st:
                st["duration_s"] = round((datetime.utcnow() - datetime.fromisoformat(st["started_at"])).total_seconds(), 1)
            await sse_manager.emit_workflow_stage_failed(project_id, PipelineStage.RENDER, str(e))
            raise
        
        # ═══════════════════════════════════════════════════════════════
        # PIPELINE COMPLETED
        # ═══════════════════════════════════════════════════════════════
        workflow.current_stage = None
        workflow.status = PipelineStatus.COMPLETED
        workflow.completed_at = datetime.utcnow()
        await sse_manager.emit_workflow_complete(project_id, workflow.results)
        
        logger.info(f"Workflow completed for project {project_id}")
        
    except Exception as e:
        workflow.status = PipelineStatus.FAILED
        workflow.error = str(e)
        workflow.completed_at = datetime.utcnow()
        await sse_manager.emit_workflow_failed(project_id, str(e))
        logger.error(f"Workflow failed for project {project_id}: {e}")


def cancel_workflow(project_id: str) -> bool:
    """Cancelar un workflow en ejecución"""
    workflow = _active_workflows.get(project_id)
    if not workflow:
        return False
    
    if workflow.status != PipelineStatus.RUNNING:
        return False
    
    workflow.status = PipelineStatus.FAILED
    workflow.error = "Cancelled by user"
    workflow.completed_at = datetime.utcnow()
    
    # Nota: No podemos cancelar fácilmente las tareas de asyncio en ejecución
    # pero marcamos el estado como failed para que no continúe
    
    return True
