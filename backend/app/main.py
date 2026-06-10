import asyncio
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.config import settings
from app.core.job_store import init_db
from app.routers import projects, fragments, channels, images, transcribe, render, workflow
from app.routers.prompts import router as prompts_router
from app.routers.shorts import router as shorts_router
from app.routers.gemini_bridge import router as gemini_bridge_router
from app.routers.gems import router as gems_router
from app.routers.images import save_image
from app.services import project_service
from app.services.forge_bridge import bridge
from app.services.gems_manager import init_gems
from pydantic import BaseModel
from app.services.forge_bridge import bridge


@asynccontextmanager
async def lifespan(app: FastAPI):
    await init_db()
    init_gems()
    bridge.set_save_image(save_image)
    task = asyncio.create_task(bridge.serve(settings.bridge_host, settings.bridge_ws_port))
    yield
    await bridge.shutdown()
    task.cancel()


app = FastAPI(
    title=settings.app_name,
    version=settings.app_version,
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(channels.router)
app.include_router(projects.router)
app.include_router(fragments.router)
app.include_router(images.router)
app.include_router(transcribe.router)
app.include_router(render.router)
app.include_router(workflow.router)
app.include_router(prompts_router)
app.include_router(shorts_router)
app.include_router(gemini_bridge_router)
app.include_router(gems_router)


@app.get("/api/setup/status")
async def setup_status():
    return await project_service.setup_status()


@app.get("/api/accounts")
async def list_accounts():
    """List connected Forge accounts (global, not project-specific)"""
    return {"accounts": bridge.get_accounts()}


class AuthAutoRequest(BaseModel):
    account: str
    token: str
    email: str | None = None
    name: str | None = None


@app.post("/api/auth/auto")
async def auth_auto(req: AuthAutoRequest):
    """Register account from Chrome extension auto-auth (includes bearer token)"""
    if req.email:
        bridge.register_account_email(req.account, req.email)
    if req.token:
        bridge.register_account_token(req.account, req.token)
    return {"status": "ok", "account": req.account}


@app.get("/api/health")
async def health():
    return {
        "status": "ok",
        "service": settings.app_name,
        "version": settings.app_version,
    }
