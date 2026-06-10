"""API endpoints for managing visual style gems.

Inspired by Gemini Batch Studio's GemsPage.
Gems are reusable style presets that can be either:
  - type="prompt": Full system prompt with instructions
  - type="style": Style keyword/description
"""

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from app.services.gems_manager import (
    load_gems,
    save_gems,
    get_gem,
    extract_gem_id,
    build_system_prompt_from_gem,
)

router = APIRouter(prefix="/api/gems", tags=["gems"])


class GemCreate(BaseModel):
    name: str
    type: str = "style"  # "prompt" or "style"
    value: str


class GemUpdate(BaseModel):
    name: str | None = None
    type: str | None = None
    value: str | None = None


class GemResponse(BaseModel):
    name: str
    type: str
    value: str


@router.get("")
async def list_gems() -> dict:
    """List all available style gems."""
    gems = load_gems()
    result = []
    for name, config in gems.items():
        # Truncate value for listing
        preview = config.get("value", "")[:120]
        if len(config.get("value", "")) > 120:
            preview += "..."
        result.append({
            "name": name,
            "type": config.get("type", "style"),
            "preview": preview,
        })
    return {"gems": result, "total": len(result)}


@router.get("/{name}", response_model=GemResponse)
async def get_gem_by_name(name: str):
    """Get a specific gem by name."""
    gem = get_gem(name)
    if not gem:
        raise HTTPException(404, f"Gem '{name}' not found")
    return GemResponse(name=name, type=gem["type"], value=gem["value"])


@router.post("", status_code=201)
async def create_gem(body: GemCreate) -> dict:
    """Create a new style gem."""
    gems = load_gems()
    if body.name in gems:
        raise HTTPException(409, f"Gem '{body.name}' already exists")

    if body.type not in ("prompt", "style"):
        raise HTTPException(400, "Type must be 'prompt' or 'style'")

    gems[body.name] = {"type": body.type, "value": body.value}
    if not save_gems(gems):
        raise HTTPException(500, "Failed to save gems")
    return {"ok": True, "name": body.name}


@router.put("/{name}")
async def update_gem(name: str, body: GemUpdate) -> dict:
    """Update an existing gem."""
    gems = load_gems()
    if name not in gems:
        raise HTTPException(404, f"Gem '{name}' not found")

    if body.name:
        # Rename: move value to new key
        if body.name != name and body.name in gems:
            raise HTTPException(409, f"Gem '{body.name}' already exists")
        gems[body.name] = gems.pop(name)
        name = body.name

    if body.type is not None:
        if body.type not in ("prompt", "style"):
            raise HTTPException(400, "Type must be 'prompt' or 'style'")
        gems[name]["type"] = body.type
    if body.value is not None:
        gems[name]["value"] = body.value

    if not save_gems(gems):
        raise HTTPException(500, "Failed to save gems")
    return {"ok": True, "name": name}


@router.delete("/{name}")
async def delete_gem(name: str) -> dict:
    """Delete a gem."""
    gems = load_gems()
    if name not in gems:
        raise HTTPException(404, f"Gem '{name}' not found")

    # Prevent deleting the default gem
    if name == "Ilustracion 2D (Default)":
        raise HTTPException(400, "Cannot delete the default gem")

    del gems[name]
    if not save_gems(gems):
        raise HTTPException(500, "Failed to save gems")
    return {"ok": True, "deleted": name}


@router.get("/{name}/resolve")
async def resolve_gem_prompt(name: str, style_fallback: str = "Cinematico") -> dict:
    """Resolve a gem into a full system prompt.

    Returns the compiled system prompt as it would be sent to the AI provider.
    Useful for UI preview before generation.
    """
    gem = get_gem(name)
    if not gem:
        raise HTTPException(404, f"Gem '{name}' not found")

    system_prompt = build_system_prompt_from_gem(name, style_fallback)

    gem_id = None
    if gem["type"] == "prompt":
        gem_id = extract_gem_id(gem["value"])

    return {
        "name": name,
        "type": gem["type"],
        "system_prompt": system_prompt,
        "gem_id": gem_id,
    }
