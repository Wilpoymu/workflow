"""Gems (style presets) manager for image prompt generation.

Adapted from Gemini Batch Studio's gems_manager.py.
Stores reusable visual style presets that can be applied to projects.
Each gem can be either:
  - type="prompt": A full system prompt with instructions
  - type="style": A style keyword/description used with build_system_prompt()
"""

import json
import logging
import os
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

GEMS_FILE = Path(os.path.dirname(os.path.dirname(os.path.dirname(__file__)))) / "gems.json"

DEFAULT_GEMS: dict[str, dict[str, str]] = {
    # ── Prompt Maestro ──────────────────────────────────────
    # Este es un system prompt COMPLETO que la IA usara como
    # instruccion principal. Reemplaza TODO lo demas.
    "Prompt Maestro": {
        "type": "prompt",
        "value": (
            "You are a visual prompt generator for 2D minimalist illustration scenes.\n\n"
            "Your task:\n"
            "- Receive script fragments in Spanish.\n"
            "- Convert EACH fragment into 1 or more clear, cinematic visual prompts in English.\n"
            "- Maintain visual consistency across scenes.\n"
            "- Use [subject] as a placeholder for the main character when applicable.\n"
            "- Deliver ONLY useful prompts, no extra explanation.\n"
            "- If a fragment suggests two strong visual ideas, return 2 prompts in the same block.\n"
            "- Maintain aesthetics: minimalist flat vector art, smooth silhouettes,\n"
            "  muted pastel palette, pale background, clean lines, no textures, NO 3D, NO CGI."
        ),
    },
    # ── Estilos visuales ────────────────────────────────────
    # Estos son descriptores de estilo que se combinan con el
    # system prompt generico de build_system_prompt().
    "Cinematico": {
        "type": "style",
        "value": "Cinematic, dramatic lighting, shallow depth of field, epic composition",
    },
    "Fotorrealista": {
        "type": "style",
        "value": "Photorealistic, detailed textures, natural lighting, hyperrealistic",
    },
    "Arte Conceptual": {
        "type": "style",
        "value": "Concept art, expressive brushstrokes, moody atmosphere, dramatic, sketch-like",
    },
    "Anime/Manga": {
        "type": "style",
        "value": "Anime style, cel-shaded, vibrant colors, expressive characters, Studio Ghibli inspired",
    },
    "Animacion 3D": {
        "type": "style",
        "value": "3D animation style, Pixar-like, smooth surfaces, volumetric lighting, playful",
    },
    "Comic": {
        "type": "style",
        "value": "Comic book style, bold outlines, halftone dots, vibrant primary colors, pop art",
    },
    "Acuarela": {
        "type": "style",
        "value": "Watercolor painting, soft washes, paper texture, organic shapes, pastel tones",
    },
    "Noir": {
        "type": "style",
        "value": "Film noir, high contrast, dramatic shadows, monochrome with selective color",
    },
}


def _ensure_gems_file() -> None:
    """Create default gems.json if it doesn't exist."""
    if not GEMS_FILE.exists():
        try:
            GEMS_FILE.write_text(
                json.dumps(DEFAULT_GEMS, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
            logger.info("Created default gems.json at %s", GEMS_FILE)
        except Exception as e:
            logger.warning("Could not create gems.json: %s", e)


def load_gems() -> dict[str, dict[str, str]]:
    """Load all gems from the JSON file."""
    if not GEMS_FILE.exists():
        return dict(DEFAULT_GEMS)
    try:
        data = json.loads(GEMS_FILE.read_text(encoding="utf-8"))
        if not isinstance(data, dict):
            return dict(DEFAULT_GEMS)
        return data
    except (json.JSONDecodeError, OSError) as e:
        logger.warning("Failed to load gems.json: %s", e)
        return dict(DEFAULT_GEMS)


def save_gems(gems: dict[str, dict[str, str]]) -> bool:
    """Save gems dict to JSON file."""
    try:
        GEMS_FILE.write_text(
            json.dumps(gems, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        return True
    except Exception as e:
        logger.error("Failed to save gems.json: %s", e)
        return False


def get_gem(name: str) -> dict[str, str] | None:
    """Get a single gem by name."""
    gems = load_gems()
    return gems.get(name)


def build_system_prompt_from_gem(name: str, style_fallback: str = "Cinematico") -> str:
    """Build a system prompt from a gem name.

    If the gem is type "prompt", returns the value directly.
    If the gem is type "style", uses build_system_prompt() with the style value.
    If the gem is not found, falls back to the style_fallback.
    """
    from app.services.prompt_generation import build_system_prompt

    gem = get_gem(name)
    if gem is None:
        logger.info("Gem '%s' not found, falling back to style: %s", name, style_fallback)
        return build_system_prompt(style_fallback)

    if gem["type"] == "prompt":
        return gem["value"]
    elif gem["type"] == "style":
        return build_system_prompt(gem["value"])
    else:
        return build_system_prompt(style_fallback)


def extract_gem_id(url_or_id: str) -> str | None:
    """Extract Gemini Gem ID from URL or return as-is.

    Example: https://gemini.google.com/app/gems/g_123abc -> g_123abc
    """
    import re

    if not url_or_id:
        return None
    match = re.search(r"gems/([a-z0-9_]+)", url_or_id)
    if match:
        return match.group(1)
    if url_or_id.startswith("g_"):
        return url_or_id
    return None


def init_gems() -> None:
    """Initialize the gems file on startup."""
    _ensure_gems_file()
