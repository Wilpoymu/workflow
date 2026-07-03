"""Thumbnail generation service: Gemini analysis → Flow background → Pillow composition."""

import json
import logging
import random
import uuid
from pathlib import Path

import httpx

from app.core.sse import sse_manager
from app.models.thumbnail import GeminiAnalysis, ThumbnailMode, ThumbnailRequest, ThumbnailStatus, VariantInfo
from app.services import project_service
from app.services.forge_bridge import bridge
from app.services.prompt_generation import repair_json

logger = logging.getLogger(__name__)

# ─── Constants ────────────────────────────────────────────────

THUMBNAIL_WIDTH = 1280
THUMBNAIL_HEIGHT = 720
THUMBNAIL_DIR_NAME = "thumbnail"
THUMBNAIL_FRAGMENT_ID = 9999  # Synthetic fragment ID for thumbnail dispatch


# ─── Prompt Builder ────────────────────────────────────────────


def _build_thumbnail_analysis_prompt(script: str, mode: ThumbnailMode, variant_count: int) -> str:
    """Build a structured prompt for Gemini to analyze a script for thumbnail design.

    Instructs Gemini to return valid JSON with specific fields for YouTube-optimized
    thumbnail analysis including Spanish text optimization.
    """
    variant_instruction = ""
    if mode == ThumbnailMode.AB_TESTING:
        variant_instruction = (
            f'\nAlso provide exactly {variant_count} "variant_suggestions" in the JSON, '
            "each with a different hook_text (3-4 words in Spanish), color_accent, and text_position. "
            "Make each variant meaningfully different in emotional angle and visual approach."
        )

    return (
        "You are a YouTube thumbnail design expert. Analyze the following Spanish script and "
        "return a JSON object with EXACTLY these fields:\n"
        "{\n"
        '  "primary_subject": "main visual subject for the thumbnail",\n'
        '  "mood_emotion": "the dominant emotion or mood",\n'
        '  "recommended_colors": { "background": "#hex", "text": "#hex", "accent": "#hex" },\n'
        '  "recommended_text": "3-4 word hook in Spanish that summarizes the video",\n'
        '  "composition": "lower_third | centered | rule_of_thirds | top_aligned",\n'
        '  "background_image_hint": "detailed visual prompt for generating a background image"\n'
        f"{variant_instruction}\n"
        "}\n\n"
        "RULES:\n"
        "- The recommended_text MUST be 3-4 words in Spanish, high-impact, emotional hook.\n"
        "- recommended_colors must have high contrast for YouTube thumbnails (bright accents, dark backgrounds).\n"
        "- background_image_hint should be a detailed visual scene description for AI image generation "
        "(include lighting, colors, composition, mood).\n"
        "- composition should suggest where text goes: lower_third is most common for YouTube.\n"
        "- Use colors that pop on YouTube: high saturation, high contrast between text and background.\n"
        "- Remember this will be viewed as a small thumbnail on mobile — bold, simple, readable.\n"
        "- Ensure Spanish accents (á, é, í, ó, ú, ü, ñ, ¿, ¡) are properly included.\n"
        "- Return ONLY valid JSON, no markdown, no code fences, no extra text.\n\n"
        f"SCRIPT:\n{script}"
    )


# ─── Gemini Analysis ──────────────────────────────────────────


def _extract_json_block(text: str) -> str:
    """Extract the first JSON object ``{…}`` block from arbitrary text.

    Strips markdown fences, preamble text, trailing commentary, and
    normalises common Gemini quirks (unquoted keys, unquoted short
    string values) so ``json.loads`` or ``repair_json`` can work.
    """
    import re
    candidate = text.strip()
    # Remove markdown fences first
    candidate = re.sub(r"^```(?:json)?\s*\n?", "", candidate, flags=re.IGNORECASE)
    candidate = re.sub(r"\s*```\s*$", "", candidate)
    candidate = candidate.strip()

    # Find the outermost { … } pair
    start = candidate.find("{")
    if start == -1:
        return candidate
    depth = 0
    end = -1
    for i in range(start, len(candidate)):
        ch = candidate[i]
        if ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                end = i + 1
                break
    block = candidate[start:end] if end > start else candidate

    # --- Pre-normalisation for common Gemini output quirks ---
    # Quote unquoted object keys (``key:`` → ``"key":``).
    # Matches positions after `{` or `,` (possibly with whitespace).
    block = re.sub(
        r'(?<=[{,])\s*([A-Za-z_]\w*)\s*:',
        r'"\1":',
        block,
    )
    # Quote unquoted single-word string values (``"key": value`` → ``"key": "value"``).
    # Leaves literal tokens (true/false/null/numbers) untouched.
    def _quote_val(m: re.Match) -> str:
        k = m.group(1)
        v = m.group(2)
        delim = m.group(3) or ''
        if re.match(r'^(true|false|null|\d+\.?\d*)$', v, re.IGNORECASE):
            return f'"{k}": {v}{delim}'
        if v.startswith('"'):
            return f'"{k}": {v}{delim}'  # already quoted
        return f'"{k}": "{v}"{delim}'
    block = re.sub(
        r'"([A-Za-z_]\w*)":\s*([A-Za-záéíóúüñ¿¡][A-Za-záéíóúüñ¿¡\w]*?)([,\s\}\]]|$)',
        _quote_val,
        block,
    )
    return block


def _parse_analysis_json(raw_text: str) -> GeminiAnalysis | None:
    """Parse Gemini's response into GeminiAnalysis with json_repair fallback."""
    trimmed = _extract_json_block(raw_text)

    try:
        data = json.loads(trimmed)
    except (json.JSONDecodeError, ValueError):
        logger.info("Gemini JSON parse failed, attempting repair...")
        repaired = repair_json(trimmed)
        try:
            data = json.loads(repaired)
        except (json.JSONDecodeError, ValueError) as e:
            logger.error("Gemini JSON repair also failed: %s | raw=%.200s", e, trimmed[:200])
            return None

    # Normalize field names (handle case differences, underscores vs spaces)
    normalized = {}
    for k, v in data.items():
        nk = k.strip().lower().replace(" ", "_").replace("-", "_")
        normalized[nk] = v

    return GeminiAnalysis(
        primary_subject=str(normalized.get("primary_subject", "")),
        mood_emotion=str(normalized.get("mood_emotion", "")),
        recommended_colors=normalized.get("recommended_colors", {}),
        recommended_text=str(normalized.get("recommended_text", "")),
        composition=str(normalized.get("composition", "lower_third")),
        background_image_hint=str(normalized.get("background_image_hint", "")),
        variant_suggestions=normalized.get("variant_suggestions", None),
    )


async def analyze_script(project_id: str, script: str, mode: ThumbnailMode, variant_count: int) -> GeminiAnalysis:
    """Send script to Gemini Web and return structured thumbnail analysis."""
    from app.services.gemini_cookie_store import cookie_store
    from app.services.gemini_web import GeminiWebClient

    profiles = cookie_store.get_authenticated()
    if not profiles:
        raise RuntimeError(
            "Gemini Web: no authenticated profiles. "
            "Install the Chrome extension and log into gemini.google.com first."
        )

    profile = profiles[0]
    psid = profile.get("psid", "")
    psidts = profile.get("psidts", "")

    client = GeminiWebClient(psid, psidts)
    prompt = _build_thumbnail_analysis_prompt(script, mode, variant_count)

    logger.info(
        "[THUMBNAIL] Analyzing script for project=%s mode=%s variants=%d",
        project_id, mode.value, variant_count,
    )

    try:
        raw = client.chat(prompt)
    except Exception as e:
        raise RuntimeError(f"Gemini Web analysis failed: {e}") from e

    analysis = _parse_analysis_json(raw)
    if not analysis:
        raise RuntimeError("Failed to parse Gemini analysis response")

    logger.info(
        "[THUMBNAIL] Analysis complete: subject=%s mood=%s text=%s",
        analysis.primary_subject, analysis.mood_emotion, analysis.recommended_text,
    )
    return analysis


# ─── Background Download ──────────────────────────────────────


async def _download_background(fife_url: str, output_path: Path) -> bool:
    """Download background image from Flow fifeUrl to local path."""
    try:
        async with httpx.AsyncClient(timeout=60) as client:
            resp = await client.get(fife_url)
            resp.raise_for_status()
            output_path.write_bytes(resp.content)
            logger.info("[THUMBNAIL] Background downloaded: %s (%d bytes)", output_path.name, len(resp.content))
            return True
    except Exception as e:
        logger.error("[THUMBNAIL] Background download failed: %s", e)
        return False


# ─── Pillow Composition ──────────────────────────────────────


def _find_font(size: int = 48) -> tuple:
    """Find best available bold sans-serif font (Inter, Roboto, or fallback)."""
    from PIL import ImageFont

    font_candidates = [
        "Inter-Bold.ttf",
        "Inter-SemiBold.ttf",
        "Inter-Regular.ttf",
        "Roboto-Bold.ttf",
        "Roboto-Regular.ttf",
        "NotoSans-Bold.ttf",
        "NotoSans-Regular.ttf",
        "Arial.ttf",
        "arial.ttf",
        "DejaVuSans-Bold.ttf",
        "DejaVuSans.ttf",
    ]

    # Search common font directories on Windows
    font_dirs = [
        Path("C:/Windows/Fonts"),
        Path.home() / ".fonts",
        Path("/usr/share/fonts/truetype"),
        Path("/System/Library/Fonts"),
        Path("/Library/Fonts"),
    ]

    for font_dir in font_dirs:
        if not font_dir.exists():
            continue
        for candidate in font_candidates:
            font_path = font_dir / candidate
            if font_path.exists():
                logger.debug("[THUMBNAIL] Using font: %s", font_path)
                try:
                    return ImageFont.truetype(str(font_path), size)
                except Exception:
                    continue

    # Fallback to default
    logger.debug("[THUMBNAIL] No custom font found, using PIL default")
    return ImageFont.load_default()


def compose_thumbnail(
    project_dir: str,
    analysis: GeminiAnalysis,
    background_path: str | None,
    output_path: str,
) -> bool:
    """Compose final thumbnail with Pillow: background + gradient + text overlay.

    Args:
        project_dir: Project base directory.
        analysis: GeminiAnalysis with color and text recommendations.
        background_path: Path to background image (or None for gradient fallback).
        output_path: Where to save the composed PNG.

    Returns:
        True on success, False on failure.
    """
    from PIL import Image, ImageDraw, ImageFilter

    try:
        # ── Step 1: Load or create background ──
        if background_path and Path(background_path).exists():
            with Image.open(background_path) as _bg:
                bg = _bg.convert("RGB")
            bg = bg.resize((THUMBNAIL_WIDTH, THUMBNAIL_HEIGHT), Image.LANCZOS)
        else:
            # Create gradient fallback background
            colors = analysis.recommended_colors
            bg_color = colors.get("background", "#1a1a2e")
            accent = colors.get("accent", "#e94560")
            bg = _create_gradient_background(bg_color, accent)

        # ── Step 2: Apply semi-transparent gradient overlay (bottom half)
        overlay = Image.new("RGBA", bg.size, (0, 0, 0, 0))
        draw = ImageDraw.Draw(overlay)
        for y in range(THUMBNAIL_HEIGHT // 2, THUMBNAIL_HEIGHT):
            alpha = int(180 * (y - THUMBNAIL_HEIGHT // 2) / (THUMBNAIL_HEIGHT // 2))
            draw.line([(0, y), (THUMBNAIL_WIDTH, y)], fill=(0, 0, 0, min(alpha, 180)))
        bg = Image.alpha_composite(bg.convert("RGBA"), overlay).convert("RGB")

        # ── Step 3: Determine text placement ──
        text = analysis.recommended_text or "¡Mira esto!"
        colors = analysis.recommended_colors
        text_color = colors.get("text", "#FFFFFF")
        accent_color = colors.get("accent", "#FF4444")

        composition = analysis.composition or "lower_third"
        draw = ImageDraw.Draw(bg)

        # ── Step 4: Load font with sizing ──
        font_size = 64
        fonts = [
            _find_font(font_size + 8),
            _find_font(font_size),
            _find_font(font_size - 8),
        ]
        font = fonts[1]

        # ── Step 5: Calculate text position ──
        bbox = draw.textbbox((0, 0), text, font=font)
        text_w = bbox[2] - bbox[0]
        text_h = bbox[3] - bbox[1]

        if composition == "centered":
            tx = (THUMBNAIL_WIDTH - text_w) // 2
            ty = (THUMBNAIL_HEIGHT - text_h) // 2
        elif composition == "top_aligned":
            tx = (THUMBNAIL_WIDTH - text_w) // 2
            ty = 60
        elif composition == "rule_of_thirds":
            tx = (THUMBNAIL_WIDTH - text_w) // 2
            ty = THUMBNAIL_HEIGHT // 3 - text_h // 2
        else:  # lower_third (default)
            tx = (THUMBNAIL_WIDTH - text_w) // 2
            ty = THUMBNAIL_HEIGHT - text_h - 80

        # Ensure text stays within bounds
        tx = max(20, min(tx, THUMBNAIL_WIDTH - text_w - 20))
        ty = max(20, min(ty, THUMBNAIL_HEIGHT - text_h - 20))

        # ── Step 6: Draw text shadow (for readability) ──
        shadow_offset = 3
        shadow_color = (0, 0, 0, 180)
        for dx in range(-shadow_offset, shadow_offset + 1):
            for dy in range(-shadow_offset, shadow_offset + 1):
                if dx == 0 and dy == 0:
                    continue
                draw.text((tx + dx, ty + dy), text, font=font, fill=shadow_color)

        # ── Step 7: Draw text outline/stroke ──
        stroke_width = 2
        for angle in range(0, 360, 30):
            import math
            sx = int(stroke_width * math.cos(math.radians(angle)))
            sy = int(stroke_width * math.sin(math.radians(angle)))
            draw.text((tx + sx, ty + sy), text, font=font, fill=(0, 0, 0, 200))

        # ── Step 8: Draw main text ──
        draw.text((tx, ty), text, font=font, fill=text_color)

        # ── Step 9: Save ──
        bg.save(output_path, "PNG")
        logger.info("[THUMBNAIL] Composed and saved: %s", output_path)
        return True

    except Exception as e:
        logger.error("[THUMBNAIL] Composition failed: %s", e)
        return False


def _create_gradient_background(bg_color: str, accent_color: str) -> "Image":
    """Create a gradient background as fallback when no Flow image is available."""
    from PIL import Image, ImageDraw

    img = Image.new("RGB", (THUMBNAIL_WIDTH, THUMBNAIL_HEIGHT))
    draw = ImageDraw.Draw(img)

    # Parse hex colors
    def hex_to_rgb(h: str) -> tuple:
        h = h.lstrip("#")
        if len(h) == 3:
            h = "".join(c * 2 for c in h)
        if len(h) != 6:
            return (30, 30, 50)
        return tuple(int(h[i:i+2], 16) for i in (0, 2, 4))

    bg_rgb = hex_to_rgb(bg_color)
    ac_rgb = hex_to_rgb(accent_color)

    # Draw a smooth vertical gradient
    for y in range(THUMBNAIL_HEIGHT):
        ratio = y / THUMBNAIL_HEIGHT
        r = int(bg_rgb[0] * (1 - ratio) + ac_rgb[0] * ratio)
        g = int(bg_rgb[1] * (1 - ratio) + ac_rgb[1] * ratio)
        b = int(bg_rgb[2] * (1 - ratio) + ac_rgb[2] * ratio)
        draw.line([(0, y), (THUMBNAIL_WIDTH, y)], fill=(r, g, b))

    return img


# ─── Variant Generation ──────────────────────────────────────


def _generate_variants(
    project_dir: str,
    analysis: GeminiAnalysis,
    base_background: str,
    count: int,
) -> list[str]:
    """Create variant thumbnails for A/B testing with different text and color treatments.

    Each variant changes:
    - Text position (top / center / lower-third)
    - Color accent
    - Text phrasing (from variant_suggestions or auto-generated)

    Returns:
        List of paths to generated variant PNGs.
    """
    from PIL import Image, ImageDraw

    output_paths: list[str] = []
    thumb_dir = Path(project_dir) / THUMBNAIL_DIR_NAME
    thumb_dir.mkdir(parents=True, exist_ok=True)

    variants = analysis.variant_suggestions or []
    if not variants:
        # Auto-generate variants if Gemini didn't provide suggestions
        for i in range(count):
            variants.append({
                "hook_text": analysis.recommended_text,
                "color_accent": analysis.recommended_colors.get("accent", "#FF4444"),
                "text_position": ["lower_third", "centered", "top_aligned"][i % 3],
            })

    for i, variant in enumerate(variants[:count]):
        hook = variant.get("hook_text", analysis.recommended_text)
        accent = variant.get("color_accent", analysis.recommended_colors.get("accent", "#FF4444"))
        position = variant.get("text_position", analysis.composition or "lower_third")

        # Create a copy of the analysis with variant-specific overrides
        variant_analysis = GeminiAnalysis(
            primary_subject=analysis.primary_subject,
            mood_emotion=analysis.mood_emotion,
            recommended_colors={
                "background": analysis.recommended_colors.get("background", "#1a1a2e"),
                "text": analysis.recommended_colors.get("text", "#FFFFFF"),
                "accent": accent,
            },
            recommended_text=hook,
            composition=position,
            background_image_hint=analysis.background_image_hint,
        )

        variant_path = str(thumb_dir / f"thumbnail_v{i + 1}.png")
        ok = compose_thumbnail(project_dir, variant_analysis, base_background, variant_path)
        if ok:
            output_paths.append(variant_path)
            logger.info("[THUMBNAIL] Variant %d saved: %s", i + 1, variant_path)

    return output_paths


# ─── Main Orchestrator ───────────────────────────────────────


async def generate_thumbnail(
    project_id: str,
    request: ThumbnailRequest,
) -> list[str]:
    """Orchestrate the full thumbnail generation pipeline.

    Steps:
    1. Analyze script via Gemini → structured analysis
    2. Dispatch background generation via Flow → download fifeUrl
    3. Compose final thumbnail with Pillow (text overlay)
    4. Generate A/B variants if requested

    Returns:
        List of output thumbnail paths.
    """
    project = await project_service.get_project(project_id)
    if not project:
        raise ValueError(f"Project '{project_id}' not found")

    project_dir = project.base_dir
    thumb_dir = Path(project_dir) / THUMBNAIL_DIR_NAME
    thumb_dir.mkdir(parents=True, exist_ok=True)

    # ── Step 1: Analyze script ──
    await sse_manager.emit(project_id, "thumbnail_progress", {
        "status": "analyzing", "progress": 0.1,
        "message": "Analyzing script with Gemini...",
    })

    analysis = await analyze_script(
        project_id, request.script, request.mode, request.variant_count,
    )

    # ── Step 2: Get background image ──
    await sse_manager.emit(project_id, "thumbnail_progress", {
        "status": "generating", "progress": 0.3,
        "message": "Generating background image...",
    })

    background_path: str | None = None

    # Option A: Use existing scene image as background
    if request.use_existing_scene:
        scene_images = sorted(Path(project_dir).glob("imagenes/escena_*.png"))
        if scene_images:
            # Use the last (most relevant) scene image
            background_path = str(scene_images[-1])
            logger.info("[THUMBNAIL] Using existing scene as background: %s", background_path)

    # Option B: Generate background via Flow dispatch
    if not background_path:
        prompt = analysis.background_image_hint
        if not prompt:
            prompt = f"{analysis.primary_subject}, {analysis.mood_emotion}, cinematic thumbnail background"
        fife_url = await bridge.dispatch_thumbnail(project_id, prompt)
        if fife_url:
            bg_output = thumb_dir / "background.png"
            downloaded = await _download_background(fife_url, bg_output)
            if downloaded:
                background_path = str(bg_output)

    # ── Step 3: Compose main thumbnail ──
    await sse_manager.emit(project_id, "thumbnail_progress", {
        "status": "composing", "progress": 0.6,
        "message": "Composing thumbnail with text overlay...",
    })

    main_output = str(thumb_dir / "thumbnail.png")
    ok = compose_thumbnail(project_dir, analysis, background_path, main_output)
    output_paths: list[str] = []
    if ok:
        output_paths.append(main_output)

    # ── Step 4: Generate variants (A/B mode) ──
    if request.mode == ThumbnailMode.AB_TESTING and ok:
        variants = _generate_variants(
            project_dir, analysis, background_path or "", request.variant_count,
        )
        output_paths.extend(variants)

    # ── Update project metadata ──
    thumbnail_paths = [str(Path(p).relative_to(project_dir)) for p in output_paths]
    try:
        await project_service.update_project_meta(project_id, {
            "files": {"thumbnail": thumbnail_paths[0] if thumbnail_paths else ""},
        })
    except Exception as e:
        logger.warning("[THUMBNAIL] Failed to update project meta: %s", e)

    # ── Emit completion ──
    variants_info = [
        VariantInfo(variant=i, url=f"/api/projects/{project_id}/thumbnails/file/{Path(p).name}", seed=random.randint(1, 999999))
        for i, p in enumerate(output_paths)
    ]
    await sse_manager.emit(project_id, "thumbnail_complete", {
        "variants": [v.model_dump() for v in variants_info],
    })

    logger.info(
        "[THUMBNAIL] Generation complete: %d thumbnail(s) for project=%s",
        len(output_paths), project_id,
    )
    return output_paths
