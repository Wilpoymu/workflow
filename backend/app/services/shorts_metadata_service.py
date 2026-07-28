import asyncio
import json
import logging
import re
from typing import Any

from app.config import settings
from app.services.gemini_web import GeminiWebClient
from app.services.gemini_cookie_store import cookie_store

logger = logging.getLogger(__name__)

MAX_RETRIES = 3
RETRY_DELAY_SECONDS = 5

SYSTEM_PROMPT = """Eres un experto en marketing de contenido para redes sociales. Tu tarea es generar metadata optimizada para TikTok y YouTube Shorts a partir del texto de un video corto (short).

Para CADA plataforma, debes devolver:
- **title**: Un título atractivo, con gancho, que capture atención en los primeros 2 segundos. Máximo 60 caracteres para TikTok, máximo 70 para YouTube Shorts.
- **description**: Descripción de 2-3 líneas que incluya un resumen del video, un call-to-action y palabras clave relevantes. Máximo 2200 caracteres para YouTube, máximo 400 para TikTok.
- **tags**: Lista de 10-15 tags/palabras clave relevantes al contenido, ordenadas por importancia.
- **hashtags**: Lista de 8-12 hashtags optimizados para descubrimiento (incluye 2-3 de tendencia general, 2-3 del nicho, 2-3 específicos del contenido).

Reglas:
1. El título debe empezar con un hook potente: pregunta, curiosidad, beneficio directo o controversia suave.
2. Los hashtags deben combinar volumen alto (ej: #motivacion) con especificidad de nicho (ej: #limpiezaenergetica).
3. La descripción debe incluir naturalmente 3-4 keywords sin sobre-optimizar.
4. Para YouTube Shorts, sugiere una categoría apropiada del listado estándar de YouTube.
5. Para TikTok, sugiere un efecto de sonido o tipo de audio trending si aplica."""

USER_PROMPT_TEMPLATE = """Genera metadata para {platform_desc} a partir de este texto:

{text}

RESPONDE EXACTAMENTE CON ESTE FORMATO:

### FRAGMENTO 1
{{"tiktok": {{"title": "...", "description": "...", "hashtags": [...], "tags": [...], "audio_suggestion": null}},"youtube": {{"title": "...", "description": "...", "tags": [...], "hashtags": [...], "category": "..."}}}}

No expliques nada. Solo devuelve el bloque ### FRAGMENTO 1 con el JSON dentro."""


def _parse_metadata_response(response_text: str) -> dict[str, Any] | None:
    """Extract JSON metadata from a Gemini Web response in ### FRAGMENTO N format."""
    text = response_text.strip()

    # Try to extract content after ### FRAGMENTO 1
    m = re.search(
        r"###\s*FRAGMENTO\s+1\s*\n(.*)",
        text,
        re.IGNORECASE | re.DOTALL,
    )
    if m:
        content = m.group(1).strip()

        # Remove markdown code fences if present
        content = re.sub(r"^```(?:json)?\s*\n?", "", content)
        content = re.sub(r"\n```\s*$", "", content)

        try:
            return json.loads(content)
        except json.JSONDecodeError:
            logger.warning("Failed to parse JSON from FRAGMENTO block: %s", content[:200])
            # Try to extract JSON object from the content
            json_match = re.search(r"\{.*\}", content, re.DOTALL)
            if json_match:
                try:
                    return json.loads(json_match.group(0))
                except json.JSONDecodeError:
                    pass

    # Fallback: try to find any JSON object in the entire response
    json_match = re.search(r"\{.*\}", text, re.DOTALL)
    if json_match:
        try:
            return json.loads(json_match.group(0))
        except json.JSONDecodeError:
            pass

    return None


def _clean_tag(tag: str) -> str:
    tag = tag.strip().strip("#").strip()
    return tag


def _build_result(data: dict, platform: str, text: str) -> dict[str, Any]:
    result: dict[str, Any] = {"generated_from": text[:200]}
    if platform in ("both", "tiktok"):
        tiktok = data.get("tiktok", {})
        result["tiktok"] = {
            "title": tiktok.get("title", ""),
            "description": tiktok.get("description", ""),
            "hashtags": [_clean_tag(h) for h in tiktok.get("hashtags", []) if h],
            "tags": [_clean_tag(t) for t in tiktok.get("tags", []) if t],
            "audio_suggestion": tiktok.get("audio_suggestion"),
        }
    if platform in ("both", "youtube"):
        youtube = data.get("youtube", {})
        result["youtube"] = {
            "title": youtube.get("title", ""),
            "description": youtube.get("description", ""),
            "tags": [_clean_tag(t) for t in youtube.get("tags", []) if t],
            "hashtags": [_clean_tag(h) for h in youtube.get("hashtags", []) if h],
            "category": youtube.get("category", ""),
        }
    return result


async def generate_metadata(text: str, platform: str = "both") -> dict[str, Any]:
    if not text or not text.strip():
        raise ValueError("Text is required to generate metadata")

    profiles = cookie_store.get_authenticated()
    if not profiles:
        raise RuntimeError(
            "Gemini Web: no authenticated profiles. "
            "Install the Chrome extension and log into gemini.google.com first."
        )

    profile = profiles[0]
    psid = profile.get("psid", "")
    psidts = profile.get("psidts", "")

    platform_desc = "ambas plataformas" if platform == "both" else f"la plataforma {platform}"
    user_prompt = USER_PROMPT_TEMPLATE.format(text=text.strip(), platform_desc=platform_desc)

    client = GeminiWebClient(psid, psidts)
    last_error: Exception | None = None

    for attempt in range(1, MAX_RETRIES + 1):
        try:
            logger.info(
                "Generating shorts metadata via Gemini Web (attempt %d/%d, profile: %s)",
                attempt, MAX_RETRIES,
                profile.get("profile_label", "unknown"),
            )

            raw = client.chat(user_prompt, system_prompt=SYSTEM_PROMPT)
            parsed = _parse_metadata_response(raw)

            if not parsed:
                raise RuntimeError("Failed to parse Gemini Web response as metadata JSON")

            return _build_result(parsed, platform, text)

        except Exception as e:
            last_error = e
            logger.warning("Gemini Web attempt %d failed: %s", attempt, e)
            if attempt < MAX_RETRIES:
                client = GeminiWebClient(psid, psidts)
                await asyncio.sleep(RETRY_DELAY_SECONDS * attempt)

    raise RuntimeError(
        f"Gemini Web: all {MAX_RETRIES} attempts failed. "
        f"Last error: {last_error}"
    ) from last_error
