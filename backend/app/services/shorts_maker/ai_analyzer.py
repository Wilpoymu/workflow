"""AI-powered, topic-agnostic short segment generation and analysis.

Uses Gemini Web (cookie-based) to both identify natural segment boundaries
and evaluate their short potential — without hardcoded topic assumptions.
"""

import asyncio
import json
import logging
import re
from typing import Any

from app.services.gemini_cookie_store import cookie_store
from app.services.gemini_web import GeminiWebClient

logger = logging.getLogger(__name__)

MAX_RETRIES = 3
RETRY_DELAY_SECONDS = 5

SYSTEM_PROMPT = """Eres un experto editor de contenido para YouTube Shorts. Tu tarea es LEER el texto completo de un video, IDENTIFICAR los mejores segmentos para convertir en Shorts, y DEVOLVERLOS con metadatos.

REGLAS:
- Cada segmento debe ser una **unidad temática completa** con inicio y cierre naturales. Debe entenderse por sí solo, sin depender del contexto anterior.
- **NO cortes a mitad de una idea u oración.** Cada segmento debe empezar al inicio de una oración y terminar al final de una.
- Duración estimada: 25-60 segundos cada uno. Suficiente para desarrollar una idea completa.
- Los segmentos NO deben solaparse entre sí. Cada uno cubre una parte diferente del video.
- Prioriza segmentos con: gancho inicial fuerte, emoción, sorpresa, utilidad práctica, datos interesantes, o reflexiones profundas.
- NO asumas ningún tema específico. Evalúa según el contenido real que veas.

Para CADA segmento, devuelve:
1. **start_words**: Las primeras 4-6 palabras EXACTAS del segmento (tal cual aparecen en el texto). Debe ser el inicio de una oración completa.
2. **end_words**: Las últimas 4-6 palabras EXACTAS del segmento (tal cual aparecen). Debe ser el final de una oración.
3. **category**: Categoría temática en español (1-2 palabras). Ejemplos: "Consejo Práctico", "Historia Personal", "Dato Curioso", "Lección de Vida", "Reflexión", "Tutorial", "Explicación", "Anécdota", "Opinión", "Revelación", "Secreto", "Error Común", "Cambio de Perspectiva", "Descubrimiento".
4. **score**: 0-10 (qué tan bien funciona como Short).
5. **hook**: "alto" | "medio" | "bajo".
6. **viral_potential**: "alto" | "medio" | "bajo".
7. **reason**: Explica por qué funciona como Short (máx 12 palabras).

RESPONDE ÚNICAMENTE CON:

### SEGMENTOS
[
  {"start_words": "...", "end_words": "...", "category": "...", "score": 8.5, "hook": "alto", "viral_potential": "alto", "reason": "..."},
  ...
]

No expliques nada más. No incluyas markdown. Solo el bloque ### SEGMENTOS con el JSON array."""

USER_PROMPT_TEMPLATE = """Analiza este texto completo de video y encuentra los mejores {top_n} segmentos para convertir en Shorts:

--- TEXTO COMPLETO ---
{full_text}
--- FIN DEL TEXTO ---

Identifica {top_n} segmentos temáticamente coherentes con sentido completo. Cada segmento debe ser una unidad temática que se entienda por sí sola. Indica las primeras y últimas palabras EXACTAS para ubicarlos en el texto."""


def _normalize(text: str) -> str:
    t = text.lower().strip()
    t = re.sub(r"[^\w\sáéíóúüñ]", "", t)
    t = re.sub(r"\s+", " ", t)
    return t


def _find_sentence_start_entry(entries: list, start_idx: int) -> int:
    for i in range(start_idx, -1, -1):
        if i == 0:
            return 0
        prev_text = entries[i - 1].text.strip()
        if prev_text and prev_text[-1] in ".!?\"\u2026":
            return i
    return max(0, start_idx)


def _find_sentence_end_entry(entries: list, end_idx: int) -> int:
    for i in range(end_idx, len(entries)):
        text = entries[i].text.strip()
        if text and text[-1] in ".!?\"\u2026":
            return i
    return min(len(entries) - 1, end_idx)


def _find_entry_containing(search_words: str, srt_entries: list) -> int | None:
    """Find the index of the first SRT entry whose text contains the search words."""
    norm_search = _normalize(search_words)
    search_tokens = norm_search.split()
    if not search_tokens:
        return None

    # Try all search tokens
    for wlen in (len(search_tokens), 3, 2):
        tokens = search_tokens[:wlen]
        for i, entry in enumerate(srt_entries):
            entry_norm = _normalize(entry.text)
            if all(t in entry_norm for t in tokens):
                return i

    # Last resort: try first single token
    for i, entry in enumerate(srt_entries):
        entry_norm = _normalize(entry.text)
        if search_tokens[0] in entry_norm:
            return i

    return None


def _find_entry_containing_end(search_words: str, srt_entries: list) -> int | None:
    """Find the index of the last SRT entry whose text contains the search words."""
    norm_search = _normalize(search_words)
    search_tokens = norm_search.split()
    if not search_tokens:
        return None

    best = None
    for wlen in (len(search_tokens), 3, 2):
        tokens = search_tokens[:wlen]
        for i, entry in enumerate(srt_entries):
            entry_norm = _normalize(entry.text)
            if all(t in entry_norm for t in tokens):
                best = i

    if best is not None:
        return best

    for i, entry in enumerate(srt_entries):
        entry_norm = _normalize(entry.text)
        if search_tokens[0] in entry_norm:
            best = i
    return best


def _build_full_text(srt_entries: list) -> str:
    return " ".join(e.text for e in srt_entries)


def _parse_segments_response(response_text: str) -> list[dict[str, Any]] | None:
    text = response_text.strip()

    # Try ### SEGMENTOS format
    m = re.search(r"###\s*SEGMENTOS\s*\n(.*)", text, re.IGNORECASE | re.DOTALL)
    if m:
        content = m.group(1).strip()
        content = re.sub(r"^```(?:json)?\s*\n?", "", content)
        content = re.sub(r"\n```\s*$", "", content)
        try:
            parsed = json.loads(content)
            if isinstance(parsed, list):
                return parsed
            return None
        except json.JSONDecodeError:
            json_match = re.search(r"\[[\s\S]*\]", content)
            if json_match:
                try:
                    parsed = json.loads(json_match.group(0))
                    if isinstance(parsed, list):
                        return parsed
                except json.JSONDecodeError:
                    pass

    # Fallback: find any JSON array
    json_match = re.search(r"\[[\s\S]*\]", text)
    if json_match:
        try:
            parsed = json.loads(json_match.group(0))
            if isinstance(parsed, list):
                return parsed
        except json.JSONDecodeError:
            pass

    return None


async def generate_ai_segments(
    srt_entries: list,
    word_timestamps: list[dict] | None = None,
    top_n: int = 15,
) -> list[dict[str, Any]]:
    """Use AI to identify the best segments for Shorts directly from the full transcript.
    
    Returns segments with: start_sec, end_sec, text, ai_score, ai_category,
    ai_hook, ai_viral_potential, ai_reason
    """
    full_text = _build_full_text(srt_entries)
    if not full_text.strip():
        return []

    profiles = cookie_store.get_authenticated()
    if not profiles:
        raise RuntimeError(
            "Gemini Web: no authenticated profiles. "
            "Install the Chrome extension and log into gemini.google.com first."
        )

    profile = profiles[0]
    psid = profile.get("psid", "")
    psidts = profile.get("psidts", "")

    # Truncate if too long (Gemini Web has limits)
    max_chars = 25000
    display_text = full_text[:max_chars]
    if len(full_text) > max_chars:
        logger.warning("Truncating transcript from %d to %d chars", len(full_text), max_chars)

    user_prompt = USER_PROMPT_TEMPLATE.format(
        full_text=display_text,
        top_n=top_n,
    )

    client = GeminiWebClient(psid, psidts)
    last_error: Exception | None = None

    for attempt in range(1, MAX_RETRIES + 1):
        try:
            logger.info(
                "AI generating segments (attempt %d/%d, text=%d chars)",
                attempt, MAX_RETRIES, len(display_text),
            )

            raw = client.chat(user_prompt, system_prompt=SYSTEM_PROMPT)
            segments_data = _parse_segments_response(raw)

            if not segments_data:
                raise RuntimeError("Failed to parse AI segments response")

            # Map AI segments to real timestamps with sentence snapping
            results = []
            for sd in segments_data:
                start_words = sd.get("start_words", "")
                end_words = sd.get("end_words", "")
                if not start_words or not end_words:
                    continue

                start_idx = _find_entry_containing(start_words, srt_entries)
                end_idx = _find_entry_containing_end(end_words, srt_entries)

                if start_idx is None or end_idx is None:
                    logger.warning("Could not map segment boundaries: %r / %r", start_words, end_words)
                    continue

                # Snap to sentence boundaries
                start_idx = _find_sentence_start_entry(srt_entries, start_idx)
                end_idx = _find_sentence_end_entry(srt_entries, end_idx)

                start_sec = srt_entries[start_idx].start_sec
                end_sec = srt_entries[end_idx].end_sec

                # Enforce minimum duration: extend end forward if needed
                min_duration = 20.0
                duration = end_sec - start_sec
                while duration < min_duration and end_idx < len(srt_entries) - 1:
                    end_idx = _find_sentence_end_entry(srt_entries, end_idx + 1)
                    end_sec = srt_entries[end_idx].end_sec
                    duration = end_sec - start_sec

                if duration < min_duration or duration > 120:
                    continue

                # Extract actual text for this segment
                seg_text = _entries_text_in_range(srt_entries, start_sec, end_sec)

                raw_score = sd.get("score", 5.0)
                try:
                    score = min(10.0, max(0.0, float(raw_score)))
                except (ValueError, TypeError):
                    score = 5.0

                results.append({
                    "start_sec": start_sec,
                    "end_sec": end_sec,
                    "text": seg_text,
                    "ai_score": score,
                    "ai_hook": sd.get("hook", "medio"),
                    "ai_category": sd.get("category", "General"),
                    "ai_viral_potential": sd.get("viral_potential", "medio"),
                    "ai_reason": sd.get("reason", ""),
                })

            if not results:
                raise RuntimeError("AI returned segments but none could be mapped to timestamps")

            logger.info("AI generated %d segments", len(results))
            return results

        except Exception as e:
            last_error = e
            logger.warning("AI segment generation attempt %d failed: %s", attempt, e)
            if attempt < MAX_RETRIES:
                client = GeminiWebClient(psid, psidts)
                await asyncio.sleep(RETRY_DELAY_SECONDS * attempt)

    raise RuntimeError(
        f"AI segment generation: all {MAX_RETRIES} attempts failed. "
        f"Last error: {last_error}"
    ) from last_error


def _entries_text_in_range(entries: list, start_sec: float, end_sec: float) -> str:
    texts = []
    for e in entries:
        if e.start_sec >= start_sec and e.end_sec <= end_sec:
            texts.append(e.text)
        elif e.start_sec < end_sec and e.end_sec > start_sec:
            texts.append(e.text)
    return " ".join(texts)


async def analyze_segment(text: str, duration: float, position_ratio: float) -> dict[str, Any]:
    """Analyze a single segment using AI (Gemini Web).
    
    Used in 'combined' mode to score existing rule-based segments.
    """
    profiles = cookie_store.get_authenticated()
    if not profiles:
        raise RuntimeError(
            "Gemini Web: no authenticated profiles. "
            "Install the Chrome extension and log into gemini.google.com first."
        )

    profile = profiles[0]
    psid = profile.get("psid", "")
    psidts = profile.get("psidts", "")

    position_pct = position_ratio * 100
    user_prompt = ANALYSIS_USER_PROMPT_TEMPLATE.format(text=text.strip(), duration=duration, position=position_pct)

    client = GeminiWebClient(psid, psidts)
    last_error: Exception | None = None

    for attempt in range(1, MAX_RETRIES + 1):
        try:
            logger.info(
                "AI analyzing segment (attempt %d/%d, len=%d chars)",
                attempt, MAX_RETRIES, len(text.strip()),
            )

            raw = client.chat(user_prompt, system_prompt=ANALYSIS_SYSTEM_PROMPT)
            parsed = _parse_analysis_response(raw)

            if not parsed:
                raise RuntimeError("Failed to parse AI response as JSON")

            score = parsed.get("score")
            if score is not None:
                try:
                    parsed["score"] = min(10.0, max(0.0, float(score)))
                except (ValueError, TypeError):
                    parsed["score"] = 5.0

            return parsed

        except Exception as e:
            last_error = e
            logger.warning("AI analysis attempt %d failed: %s", attempt, e)
            if attempt < MAX_RETRIES:
                client = GeminiWebClient(psid, psidts)
                await asyncio.sleep(RETRY_DELAY_SECONDS * attempt)

    raise RuntimeError(
        f"AI analysis: all {MAX_RETRIES} attempts failed. "
        f"Last error: {last_error}"
    ) from last_error


async def analyze_segments_batch(
    segments: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Score existing rule-based segments with AI. Used in 'combined' mode."""
    total_duration = max(s["end_sec"] for s in segments) - min(s["start_sec"] for s in segments)
    if total_duration <= 0:
        total_duration = 1

    results = []
    for seg in segments:
        position_ratio = seg["start_sec"] / total_duration if total_duration > 0 else 0
        duration = seg["end_sec"] - seg["start_sec"]

        try:
            ai_result = await analyze_segment(seg["text"], duration, position_ratio)
        except Exception as e:
            logger.error("AI analysis failed for segment: %s", e)
            ai_result = {
                "score": 5.0,
                "hook": "medio",
                "category": "General",
                "viral_potential": "medio",
                "reason": "Analyze not available",
            }

        results.append({
            **seg,
            "ai_score": float(ai_result.get("score", 5.0)),
            "ai_hook": ai_result.get("hook", "medio"),
            "ai_category": ai_result.get("category", "General"),
            "ai_viral_potential": ai_result.get("viral_potential", "medio"),
            "ai_reason": ai_result.get("reason", ""),
        })

    return results


ANALYSIS_SYSTEM_PROMPT = """Evalúa este segmento de video para Shorts:

1. **Score** (0-10): Engagement potencial en primeros 3 segundos.
2. **Hook** (alto/medio/bajo): ¿Tiene gancho inicial?
3. **Category**: Categoría temática en español (1-2 palabras). Ej: Consejo, Historia, Dato Curioso, Lección, Reflexión, Explicación, Secreto, etc.
4. **Viral Potential** (alto/medio/bajo).
5. **Reason**: Por qué funciona (máx 12 palabras).

### SEGMENTO 0
{"score": 0-10, "hook": "alto|medio|bajo", "category": "...", "viral_potential": "alto|medio|bajo", "reason": "..."}

Solo el JSON. Sin explicación."""

ANALYSIS_USER_PROMPT_TEMPLATE = """Texto: {text}
Duración: {duration:.1f}s  Posición: {position:.0f}%
Responde con ### SEGMENTO 0"""


def _parse_analysis_response(response_text: str) -> dict[str, Any] | None:
    text = response_text.strip()

    m = re.search(r"###\s*SEGMENTO\s+0\s*\n(.*)", text, re.IGNORECASE | re.DOTALL)
    if m:
        content = m.group(1).strip()
        content = re.sub(r"^```(?:json)?\s*\n?", "", content)
        content = re.sub(r"\n```\s*$", "", content)
        try:
            return json.loads(content)
        except json.JSONDecodeError:
            json_match = re.search(r"\{[\s\S]*\}", content)
            if json_match:
                try:
                    return json.loads(json_match.group(0))
                except json.JSONDecodeError:
                    pass

    json_match = re.search(r"\{[\s\S]*\}", text)
    if json_match:
        try:
            return json.loads(json_match.group(0))
        except json.JSONDecodeError:
            pass

    return None
