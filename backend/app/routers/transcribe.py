import asyncio
import json
import logging
import uuid
from pathlib import Path

from fastapi import APIRouter, HTTPException, UploadFile, File, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse

from app.core.task_queue import run_in_thread
from app.services import project_service
from app.services.whisper_pipeline import transcribe_audio, save_transcription

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/projects/{project_id}/transcribe", tags=["transcribe"])


class TranscribeJob:
    def __init__(self):
        self.jobs: dict[str, dict] = {}
        self.ws_connections: dict[str, list[WebSocket]] = {}

    def create_job(self, project_id: str, audio_path: str) -> str:
        job_id = uuid.uuid4().hex[:8]
        self.jobs[job_id] = {
            "id": job_id,
            "project_id": project_id,
            "audio_path": audio_path,
            "status": "queued",
            "progress": 0,
            "message": "",
            "result": None,
        }
        return job_id

    def update_job(self, job_id: str, **kwargs):
        if job_id in self.jobs:
            self.jobs[job_id].update(kwargs)

    def get_job(self, job_id: str) -> dict | None:
        return self.jobs.get(job_id)

    async def broadcast(self, project_id: str, data: dict):
        connections = self.ws_connections.get(project_id, [])
        logger.info("[TRANSCRIBE] broadcast project=%s connections=%d data_type=%s", project_id, len(connections), data.get("type"))
        dead = []
        for ws in connections:
            try:
                await ws.send_json(data)
            except Exception as e:
                logger.warning("[TRANSCRIBE] broadcast error: %s", e)
                dead.append(ws)
        for ws in dead:
            connections.remove(ws)

    def add_ws(self, project_id: str, ws: WebSocket):
        if project_id not in self.ws_connections:
            self.ws_connections[project_id] = []
        self.ws_connections[project_id].append(ws)

    def remove_ws(self, project_id: str, ws: WebSocket):
        if project_id in self.ws_connections:
            if ws in self.ws_connections[project_id]:
                self.ws_connections[project_id].remove(ws)


transcribe_job = TranscribeJob()


@router.post("/upload")
async def upload_audio(
    project_id: str,
    audio: UploadFile = File(...),
    text: UploadFile = File(None),
):
    project = await project_service.get_project(project_id)
    if not project:
        raise HTTPException(404, "Project not found")

    audio_dir = Path(project.base_dir) / "audio"
    audio_dir.mkdir(parents=True, exist_ok=True)

    audio_path = audio_dir / audio.filename
    content = await audio.read()
    audio_path.write_bytes(content)

    if text:
        text_path = audio_dir / "reference.txt"
        text_content = await text.read()
        text_path.write_bytes(text_content)

    return {
        "status": "uploaded",
        "audio_file": audio.filename,
        "audio_path": str(audio_path),
        "has_reference_text": text is not None,
    }


@router.post("/start")
async def start_transcription(project_id: str):
    project = await project_service.get_project(project_id)
    if not project:
        raise HTTPException(404, "Project not found")

    project_path = Path(project.base_dir)
    audio_dir = project_path / "audio"
    audio_dir.mkdir(exist_ok=True)

    audio_files = list(audio_dir.glob("*.mp3")) + list(audio_dir.glob("*.wav")) + list(audio_dir.glob("*.m4a"))

    if not audio_files:
        audio_extensions = [".mp3", ".wav", ".m4a", ".ogg", ".flac"]
        for ext in audio_extensions:
            for f in project_path.glob(f"*{ext}"):
                dest = audio_dir / f.name
                f.rename(dest)
                audio_files.append(dest)

    if not audio_files:
        raise HTTPException(400, "No audio file found. Upload an audio file first.")

    audio_path = audio_files[0]
    job_id = transcribe_job.create_job(project_id, str(audio_path))

    asyncio.create_task(run_transcription(job_id, project_id, str(audio_path)))

    return {"job_id": job_id, "status": "started"}


@router.post("")
async def transcribe_endpoint(
    project_id: str,
    audio: UploadFile = File(...),
    text: UploadFile = File(None),
):
    project = await project_service.get_project(project_id)
    if not project:
        raise HTTPException(404, "Project not found")

    audio_dir = Path(project.base_dir) / "audio"
    audio_dir.mkdir(parents=True, exist_ok=True)

    audio_path = audio_dir / audio.filename
    content = await audio.read()
    audio_path.write_bytes(content)

    if text:
        text_path = audio_dir / "reference.txt"
        text_content = await text.read()
        text_path.write_bytes(text_content)

    job_id = transcribe_job.create_job(project_id, str(audio_path))

    asyncio.create_task(run_transcription(job_id, project_id, str(audio_path)))

    return {"job_id": job_id, "status": "started"}


async def run_transcription(job_id: str, project_id: str, audio_path: str):
    loop = asyncio.get_event_loop()

    def progress_cb(progress: float, message: str):
        transcribe_job.update_job(job_id, progress=progress, message=message, status="running")
        asyncio.run_coroutine_threadsafe(
            transcribe_job.broadcast(project_id, {
                "type": "progress",
                "job_id": job_id,
                "progress": progress,
                "message": message,
            }),
            loop
        )

    try:
        transcribe_job.update_job(job_id, status="running", progress=0.05, message="Starting...")
        await transcribe_job.broadcast(project_id, {
            "type": "progress", "job_id": job_id, "progress": 0.05, "message": "Starting...",
        })

        segment = await run_in_thread(transcribe_audio, audio_path, progress_cb)

        project = await project_service.get_project(project_id)
        if not project:
            raise RuntimeError("Project not found")

        text_path = Path(project.base_dir) / "text.txt"
        text_path_arg = str(text_path) if text_path.exists() else None

        result = save_transcription(project.base_dir, segment, text_path_arg)

        transcribe_job.update_job(job_id, status="done", progress=1.0, message="Complete", result=result)
        await transcribe_job.broadcast(project_id, {
            "type": "complete",
            "job_id": job_id,
            "result": result,
        })

    except Exception as e:
        logger.error(f"Transcription failed: {e}")
        transcribe_job.update_job(job_id, status="failed", message=str(e))
        await transcribe_job.broadcast(project_id, {
            "type": "error",
            "job_id": job_id,
            "message": str(e),
        })


@router.get("/media")
async def get_media_info(project_id: str):
    """Detectar archivos de audio y texto en el proyecto"""
    project = await project_service.get_project(project_id)
    if not project:
        raise HTTPException(404, "Project not found")

    project_path = Path(project.base_dir)
    
    # Buscar archivos de audio en raíz y subcarpeta audio/
    audio_extensions = [".mp3", ".wav", ".m4a", ".ogg", ".flac"]
    audio_files = []
    
    # Buscar en raíz del proyecto
    for ext in audio_extensions:
        for file in project_path.glob(f"*{ext}"):
            stat = file.stat()
            audio_files.append({
                "filename": file.name,
                "path": str(file),
                "size_mb": round(stat.st_size / 1024 / 1024, 2),
                "modified": stat.st_mtime,
                "location": "root",
            })
    
    # Buscar en subcarpeta audio/
    audio_dir = project_path / "audio"
    if audio_dir.exists():
        for ext in audio_extensions:
            for file in audio_dir.glob(f"*{ext}"):
                stat = file.stat()
                audio_files.append({
                    "filename": file.name,
                    "path": str(file),
                    "size_mb": round(stat.st_size / 1024 / 1024, 2),
                    "modified": stat.st_mtime,
                    "location": "audio",
                })

    # Buscar archivos .txt (guión/script)
    text_files = []
    
    # Buscar en raíz
    for file in project_path.glob("*.txt"):
        stat = file.stat()
        text_files.append({
            "filename": file.name,
            "path": str(file),
            "size_kb": round(stat.st_size / 1024, 2),
            "modified": stat.st_mtime,
            "location": "root",
        })
    
    # Buscar en subcarpeta audio/
    if audio_dir.exists():
        for file in audio_dir.glob("*.txt"):
            stat = file.stat()
            text_files.append({
                "filename": file.name,
                "path": str(file),
                "size_kb": round(stat.st_size / 1024, 2),
                "modified": stat.st_mtime,
                "location": "audio",
            })

    # Ordenar por fecha de modificación (más reciente primero)
    audio_files.sort(key=lambda x: x["modified"], reverse=True)
    text_files.sort(key=lambda x: x["modified"], reverse=True)
    
    return {
        "has_audio": len(audio_files) > 0,
        "audio_files": audio_files,
        "primary_audio": audio_files[0] if audio_files else None,
        "has_text": len(text_files) > 0,
        "text_files": text_files,
        "primary_text": text_files[0] if text_files else None,
    }


@router.get("")
async def get_transcription(project_id: str):
    project = await project_service.get_project(project_id)
    if not project:
        raise HTTPException(404, "Project not found")

    audio_dir = Path(project.base_dir) / "audio"
    srt_path = audio_dir / "script.srt"
    json_path = audio_dir / "script.json"

    if not json_path.exists():
        return {"has_transcription": False}

    import json as json_module
    data = json_module.loads(json_path.read_text(encoding="utf-8"))

    # Handle both formats: list (Transcriptor) or dict (legacy)
    if isinstance(data, list):
        first = data[0] if data else {}

        # Read SRT file and parse into SrtBlock format
        srt_blocks: list[dict] = []
        if srt_path.exists():
            content = srt_path.read_text(encoding="utf-8")
            blocks = content.strip().split("\n\n")
            for block in blocks:
                lines = block.strip().split("\n")
                if len(lines) >= 3:
                    idx = lines[0].strip()
                    time_range = lines[1].strip()
                    text = "\n".join(lines[2:]).strip()
                    parts = time_range.split(" --> ")
                    srt_blocks.append({
                        "index": int(idx) if idx.isdigit() else 0,
                        "start": parts[0] if len(parts) > 0 else "",
                        "end": parts[1] if len(parts) > 1 else "",
                        "text": text,
                    })

        return {
            "has_transcription": True,
            "language": first.get("language_code", "es"),
            "word_count": len([w for w in first.get("words", []) if w.get("type") == "word"]),
            "segment_count": len(srt_blocks),
            "srt": srt_blocks,
        }

    return {
        "has_transcription": True,
        "language": data.get("language"),
        "word_count": data.get("word_count"),
        "segment_count": data.get("segment_count", len(data.get("segments", []))),
        "srt": data.get("srt", []),
    }


@router.get("/download/{filename}")
async def download_file(project_id: str, filename: str):
    project = await project_service.get_project(project_id)
    if not project:
        raise HTTPException(404, "Project not found")

    audio_dir = Path(project.base_dir) / "audio"
    file_path = audio_dir / filename

    if not file_path.exists():
        raise HTTPException(404, "File not found")

    return FileResponse(str(file_path), filename=filename)


@router.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket, project_id: str):
    await websocket.accept()
    transcribe_job.add_ws(project_id, websocket)
    logger.info("[TRANSCRIBE] WS connected project=%s", project_id)

    try:
        while True:
            data = await websocket.receive_text()
            msg = json.loads(data)
            if msg.get("type") == "ping":
                await websocket.send_json({"type": "pong"})
    except WebSocketDisconnect:
        pass
    finally:
        transcribe_job.remove_ws(project_id, websocket)
        logger.info("[TRANSCRIBE] WS disconnected project=%s", project_id)
