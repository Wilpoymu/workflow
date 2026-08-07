import asyncio
import json
import logging
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from app.services.gemini_web import GeminiWebClient
from app.services.gemini_cookie_store import cookie_store

logger = logging.getLogger(__name__)

MAX_RETRIES = 3
RETRY_DELAY_SECONDS = 5

SYSTEM_PROMPT = """Eres un experto en SEO de YouTube con 10+ años de experiencia. Tu especialidad es maximizar el alcance orgánico de videos optimizando cada campo de metadata.

A partir del texto completo del video, genera metadata en el siguiente formato JSON exacto. Sigue CADA regla al pie de la letra.

Reglas generales:
{language_rule}
- No uses clickbait engañoso. Debe ser honesto pero irresistible.
- Los títulos y descripciones deben incluir naturalmente las keywords sin keyword stuffing.

FORMATO JSON REQUERIDO:
{
  "title_variants": [
    {"variant": 1, "title": "string (máx 70 chars)", "strategy": "hook | pregunta | curiosidad | beneficio | lista | tutorial", "target_keyword": "string"},
    {"variant": 2, ...},
    {"variant": 3, ...},
    {"variant": 4, ...},
    {"variant": 5, ...}
  ],
  "description": {
    "primary": "string (primer párrafo con hook + keyword principal, 2-3 líneas)",
    "body": "string (2-3 párrafos con resumen del video, incluir naturalmente 3-5 keywords secundarias)",
    "cta": "string (call-to-action final: like, suscripción, comentario, ver siguiente)",
    "chapters": [
      {"timestamp": "00:00", "title": "string (título del capítulo, máx 40 chars)"},
      {"timestamp": "01:30", "title": "string"},
      ...
    ],
    "links_suggestion": "string (sugerencia de enlaces relevantes: playlist, video relacionado, redes sociales)"
  },
  "tags": ["tag1", "tag2", ..., "tag15-20"],
  "hashtags": ["hashtag1", ..., "hashtag8-12"],
  "category": "string (categoría estándar de YouTube nombrada en el idioma del contenido, ej: Educación, Entretenimiento, Ciencia y Tecnología, Música, Deportes, Noticias, Estilo de Vida, Cómo hacer y estilo, etc.)",
  "thumbnail_text_overlays": [
    {"text": "string (máx 40 chars, 3-4 palabras)", "style": "gran impacto | pregunta | curiosidad | beneficio"},
    {"text": "string", "style": "string"},
    {"text": "string", "style": "string"}
  ],
  "seo_keywords": [
    {"keyword": "string", "volume": "alto | medio | bajo", "type": "principal | secundario | long-tail"}
  ],
  "target_audience": {
    "age_range": "string (ej: 25-45)",
    "interests": ["string", "string"],
    "pain_points": ["string", "string"],
    "value_proposition": "string"
  },
  "end_screen_suggestions": ["string", "string"],
  "cards_suggestions": ["string", "string"]
}

REGLAS ESPECÍFICAS:
1. Títulos: 5 variantes con distintas estrategias. Máximo 70 caracteres cada uno. Cada variante DEBE incluir la keyword principal.
2. Descripción: El campo primary DEBE contener la keyword principal en las primeras 150 caracteres. 
3. Capítulos: Debe haber al menos 4 capítulos. Calcula timestamps aproximados basados en la longitud del texto (asume ~2.5 palabras/segundo). NO inventes timestamps que no puedas estimar del texto.
4. Tags: Mínimo 15, máximo 20. Los primeros 5 deben ser de nicho específico, el resto generales.
5. Hashtags: Incluir 2-3 de tendencia general, 2-3 del nicho, 2-3 específicos del contenido.
6. SEO Keywords: Incluir al menos 6 keywords con estimación de volumen. Al menos 1 keyword long-tail.
7. Thumbnail: 3 opciones de texto overlay, máx 40 caracteres cada una. Deben ser legibles en miniatura.
8. Audiencia: Define el rango etario y 2-3 intereses clave. Los pain points deben conectar emocionalmente.
9. End screen y cards: 2 sugerencias cada uno relevantes al contenido.

RESPONDE ÚNICAMENTE CON EL JSON. Sin markdown, sin explicaciones, sin código fences."""


def _build_system_prompt(language: str) -> str:
    if language == "auto":
        rule = (
            "- Detecta el idioma del texto del video y genera TODA la metadata (títulos, descripción, "
            "capítulos, tags, hashtags, categoría, keywords, audiencia y end screen) en ese mismo idioma."
        )
    else:
        rule = (
            f"- Todo el contenido debe estar en el idioma del video: {language}. "
            "Genera TODA la metadata (títulos, descripción, capítulos, tags, hashtags, categoría, "
            "keywords, audiencia y end screen) en este idioma."
        )
    return SYSTEM_PROMPT.replace("{language_rule}", rule)


USER_PROMPT_TEMPLATE = """Genera metadata SEO completa para YouTube a partir del siguiente texto de video. Genera la metadata EN EL IDIOMA {language}.

{text}

Respeta EXACTAMENTE el formato JSON especificado. Calcula los capítulos aproximados dividiendo el texto por temas. Para los timestamps, asume aproximadamente 2.5 palabras por segundo de narración.

RESPONDE EXACTAMENTE CON ESTE FORMATO:

### FRAGMENTO 1
{{...json aquí...}}"""


def _parse_metadata_response(response_text: str) -> dict[str, Any] | None:
    text = response_text.strip()

    # Try ### FRAGMENTO 1 format
    m = re.search(r"###\s*FRAGMENTO\s+1\s*\n(.*)", text, re.IGNORECASE | re.DOTALL)
    if m:
        content = m.group(1).strip()
        content = re.sub(r"^```(?:json)?\s*\n?", "", content)
        content = re.sub(r"\n```\s*$", "", content)
        try:
            return json.loads(content)
        except json.JSONDecodeError:
            logger.warning("Failed to parse JSON from FRAGMENTO: %s", content[:200])
            json_match = re.search(r"\{[\s\S]*\}", content)
            if json_match:
                try:
                    return json.loads(json_match.group(0))
                except json.JSONDecodeError:
                    pass

    # Fallback: find any JSON object
    json_match = re.search(r"\{[\s\S]*\}", text)
    if json_match:
        try:
            return json.loads(json_match.group(0))
        except json.JSONDecodeError:
            pass

    return None


METADATA_PATH = "metadata/video.json"


def _load_metadata(project_dir: Path) -> dict[str, Any] | None:
    path = project_dir / METADATA_PATH
    if path.exists():
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            return None
    return None


def _save_metadata(project_dir: Path, data: dict[str, Any]) -> None:
    path = project_dir / METADATA_PATH
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def _detect_language(text: str, project_dir: Path | None = None) -> str:
    if project_dir:
        for candidate in (project_dir / "audio" / "script.json", project_dir / "script.json"):
            if candidate.exists():
                try:
                    data = json.loads(candidate.read_text(encoding="utf-8"))
                    code = data[0].get("language_code") if isinstance(data, list) else data.get("language_code")
                    if code and isinstance(code, str):
                        code = code.strip().lower()
                        if re.fullmatch(r"[a-z]{2,3}", code):
                            return code
                except Exception:
                    pass
    return "auto"


async def generate_metadata(text: str, project_dir: Path | None = None) -> dict[str, Any]:
    if not text or not text.strip():
        raise ValueError("Text is required to generate metadata")

    language = _detect_language(text, project_dir)
    language_label = language if language != "auto" else "AUTO (detecta el idioma del texto del video)"

    profiles = cookie_store.get_authenticated()
    if not profiles:
        raise RuntimeError(
            "Gemini Web: no authenticated profiles. "
            "Install the Chrome extension and log into gemini.google.com first."
        )

    profile = profiles[0]
    psid = profile.get("psid", "")
    psidts = profile.get("psidts", "")

    user_prompt = USER_PROMPT_TEMPLATE.format(text=text.strip(), language=language_label)

    client = GeminiWebClient(psid, psidts)
    last_error: Exception | None = None

    for attempt in range(1, MAX_RETRIES + 1):
        try:
            logger.info(
                "Generating video metadata via Gemini Web (attempt %d/%d, profile: %s)",
                attempt, MAX_RETRIES,
                profile.get("profile_label", "unknown"),
            )

            raw = client.chat(user_prompt, system_prompt=_build_system_prompt(language))
            parsed = _parse_metadata_response(raw)

            if not parsed:
                raise RuntimeError("Failed to parse Gemini Web response as metadata JSON")

            result = {
                "generated_at": datetime.now(timezone.utc).isoformat(),
                "generated_from_length": len(text.strip()),
                **parsed,
            }
            return result

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


async def get_metadata(project_id: str, project_dir: Path) -> dict[str, Any] | None:
    return _load_metadata(project_dir)


async def save_metadata(project_id: str, project_dir: Path, data: dict[str, Any]) -> dict[str, Any]:
    data["updated_at"] = datetime.now(timezone.utc).isoformat()
    _save_metadata(project_dir, data)
    return data


async def generate_and_save(project_id: str, project_dir: Path, text: str) -> dict[str, Any]:
    result = await generate_metadata(text, project_dir)
    result = _validate_chapters_with_timestamps(result, project_dir)
    _save_metadata(project_dir, result)
    return result


async def validate_chapters(project_id: str, project_dir: Path) -> dict[str, Any] | None:
    data = _load_metadata(project_dir)
    if not data:
        return None
    data = _validate_chapters_with_timestamps(data, project_dir)
    _save_metadata(project_dir, data)
    return data


def _find_word_timestamps(project_dir: Path) -> list[dict]:
    for candidate in (project_dir / "audio" / "script.json", project_dir / "script.json"):
        if candidate.exists():
            try:
                data = json.loads(candidate.read_text(encoding="utf-8"))
                words = data[0].get("words", []) if isinstance(data, list) else data.get("words", [])
                return [w for w in words if w.get("type") == "word" and w.get("text", "").strip()]
            except Exception:
                pass
    return []


def _normalize(text: str) -> str:
    text = text.lower().strip()
    text = re.sub(r"[^\w\sáéíóúüñ]", "", text)
    return re.sub(r"\s+", " ", text).strip()


def _validate_chapters_with_timestamps(metadata: dict, project_dir: Path) -> dict:
    chapters = metadata.get("description", {}).get("chapters")
    if not chapters:
        return metadata

    words = _find_word_timestamps(project_dir)
    if not words:
        return metadata

    total_duration = words[-1]["end"] if words else 0
    word_texts = [_normalize(w["text"]) for w in words]

    full_text = " ".join(word_texts)

    for chapter in chapters:
        title_norm = _normalize(chapter["title"])

        # Search for chapter title words in the full text
        title_words = title_norm.split()
        if not title_words:
            continue

        # Try to find where this chapter's content starts in the transcript
        search_phrase = " ".join(title_words[:min(5, len(title_words))])
        pos = full_text.find(search_phrase)

        if pos >= 0:
            # Count words up to this position
            char_count = 0
            for i, wt in enumerate(word_texts):
                char_count += len(wt) + 1
                if char_count > pos:
                    real_sec = words[i]["start"]
                    chapter["timestamp"] = _format_timestamp(real_sec)
                    break
        else:
            # Fallback: estimate position based on chapter index
            # If chapters are evenly distributed, each covers ~1/N of the video
            chapter_idx = chapters.index(chapter)
            estimated_sec = (chapter_idx / len(chapters)) * total_duration
            chapter["timestamp"] = _format_timestamp(estimated_sec)

    metadata["description"]["chapters"] = chapters
    return metadata


def _format_timestamp(seconds: float) -> str:
    m = int(seconds // 60)
    s = int(seconds % 60)
    return f"{m:02d}:{s:02d}"
