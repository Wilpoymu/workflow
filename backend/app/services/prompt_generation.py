"""AI-powered image prompt generation from script fragments.

Adapted from scripting-tool's /api/prompts/generate route.
Supports Google Gemini, Ollama, Groq, OpenRouter, and Gemini Web (cookie-based).
"""

import json
import logging
import re
import time
from collections import Counter
from collections.abc import Callable
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from app.config import settings
from app.services.gemini_web_provider import request_gemini_web_batch

logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)

# Ensure the handler propagates to visible output
if not logger.handlers:
    _handler = logging.StreamHandler()
    _handler.setFormatter(logging.Formatter("[prompt-gen] %(levelname)s %(message)s"))
    logger.addHandler(_handler)
    logger.propagate = False

# ─── Types ────────────────────────────────────────────────

PromptFragment = dict[str, Any]
PromptResult = dict[str, Any]


# ─── System Prompt ────────────────────────────────────────


def sanitize_style(style: str) -> str:
    """Sanitize style string to prevent prompt injection."""
    return re.sub(r"[\x00-\x1f\x7f]", "", style).replace("<", "").replace(">", "").strip()[:500]


def build_system_prompt(style: str) -> str:
    """Build system prompt for image prompt generation."""
    sanitized = sanitize_style(style)
    return (
        "You are an expert prompt engineer for AI image generation models. "
        f"The selected image style is defined between <style> tags: "
        f"<style>{sanitized}</style> "
        "For each input fragment, generate one image prompt in English only. "
        "Prompts must be highly descriptive, cinematic, visual, specific in scene composition, "
        "lighting, mood, camera, and materials. "
        "Keep the meaning of the original text, but optimize for visual generation. "
        "Return ONLY valid raw JSON array and nothing else. "
        "Do not include markdown code fences. "
        'Every object must use exactly these keys: "fragment_id", "original_text", "image_prompt". '
        "Never use 'image_prompt:' or aliases. "
        "Even when there is only one input fragment, return an array with one object. "
        'Expected format: [{"fragment_id":1,"original_text":"...","image_prompt":"..."}] '
        'IMPORTANT: The "fragment_id" in your output JSON MUST exactly match the "id" provided '
        "in each input fragment. Do not change, reorder, or invent IDs."
    )


# ─── JSON Extraction & Repair ─────────────────────────────


def extract_first_json_array(text: str) -> str:
    start = text.index("[")
    try:
        end = text.rindex("]")
    except ValueError:
        # Truncated — take everything from [ to end
        return text[start:]
    return text[start : end + 1]


def extract_first_json_object(text: str) -> str:
    start = text.index("{")
    end = text.rindex("}")
    return text[start : end + 1]


def repair_json(text: str) -> str:
    """Attempt to repair common JSON issues from LLM output."""
    fixed = text.strip()

    # Strip markdown code blocks
    fixed = re.sub(r"^```(?:json)?\s*\n?", "", fixed, flags=re.IGNORECASE)
    fixed = re.sub(r"```\s*$", "", fixed)

    # Fix "key:"literal → "key":"literal (only for alpha-starting values, not numbers)
    fixed = re.sub(r'"([A-Za-z_][A-Za-z0-9_]*)":\s*(?=[A-Za-z])', r'"\1":"', fixed)

    # Fix "key:"[ → "key": [ and "key:"{ → "key": {
    fixed = re.sub(r'"([A-Za-z_][A-Za-z0-9_]*)":\s*(?=[\[{"])', r'"\1":', fixed)

    # Remove trailing commas before } or ]
    fixed = re.sub(r",\s*([}\]])", r"\1", fixed)

    # Close truncated strings
    in_string = False
    escaped = False
    for ch in fixed:
        if escaped:
            escaped = False
            continue
        if ch == "\\":
            escaped = True
            continue
        if ch == '"':
            in_string = not in_string
    if in_string:
        fixed += '"'

    # Close unclosed braces and brackets
    open_braces = fixed.count("{")
    close_braces = fixed.count("}")
    open_brackets = fixed.count("[")
    close_brackets = fixed.count("]")
    if open_braces > close_braces:
        fixed += "}" * (open_braces - close_braces)
    if open_brackets > close_brackets:
        fixed += "]" * (open_brackets - close_brackets)

    return fixed.strip()


def _normalize_keys(obj: dict) -> dict:
    return {k.strip().rstrip(":").replace(" ", "_").lower(): v for k, v in obj.items()}


def _first_defined(obj: dict, keys: list[str]) -> Any:
    for k in keys:
        if k in obj and obj[k] is not None:
            return obj[k]
    return None


def _to_positive_int(val: Any) -> int | None:
    if isinstance(val, int) and val > 0:
        return val
    if isinstance(val, str):
        try:
            n = int(val.strip())
            return n if n > 0 else None
        except ValueError:
            return None
    return None


def _to_nonempty_string(val: Any) -> str | None:
    if isinstance(val, str) and val.strip():
        return val.strip()
    return None


def _is_low_quality_prompt(val: str) -> bool:
    clean = re.sub(r"[\s{}\[\]\"',.:;]+", "", val)
    return len(val.strip()) < 24 or len(clean) < 12 or not re.search(r"[a-zA-Z]", val)


def _unwrap_payload(parsed: Any) -> list[Any]:
    if isinstance(parsed, list):
        return parsed
    if isinstance(parsed, dict):
        normalized = _normalize_keys(parsed)
        for key in ("results", "prompts", "items", "data", "response"):
            if key in normalized and isinstance(normalized[key], list):
                return normalized[key]
        return [parsed]
    return [parsed]


def _normalize_prompt_result(
    item: Any, expected: list[PromptFragment]
) -> PromptResult:
    if not isinstance(item, dict):
        raise ValueError("Model item is not a JSON object")

    expected_by_id = {f["id"]: f for f in expected}
    single_expected = expected[0] if len(expected) == 1 else None
    normalized = _normalize_keys(item)

    parsed_id = _to_positive_int(
        _first_defined(normalized, [
            "fragment_id", "fragmentid", "id", "fragment",
            "fragment_index", "fragmentindex", "index",
        ])
    )
    fragment_id = parsed_id if (parsed_id and parsed_id in expected_by_id) else (single_expected["id"] if single_expected else None)
    exp_frag = expected_by_id.get(fragment_id) if fragment_id else single_expected

    original_text = (
        (exp_frag["text"] if exp_frag else None)
        or _to_nonempty_string(
            _first_defined(normalized, [
                "original_text", "originaltext", "text",
                "source_text", "sourcetext", "input_text", "inputtext",
            ])
        )
    )
    image_prompt = _to_nonempty_string(
        _first_defined(normalized, [
            "image_prompt", "imageprompt", "prompt",
            "visual_prompt", "visualprompt", "image", "description",
        ])
    )

    # Fallback: longest descriptive text
    if not image_prompt:
        texts = [v for v in normalized.values() if isinstance(v, str) and len(v) >= 50]
        if texts:
            image_prompt = max(texts, key=len)

    return {
        "fragment_id": fragment_id,
        "original_text": original_text or "",
        "image_prompt": image_prompt or "",
    }


def parse_model_json(
    raw_text: str, expected: list[PromptFragment]
) -> list[PromptResult]:
    """Parse LLM output, trying multiple extraction strategies in priority order."""
    trimmed = raw_text.strip()
    
    # Build candidates in priority order (most complete first)
    candidates: list[str] = []

    # Strategy 1: JSON array (full text, with repair for truncation)
    if trimmed.startswith("["):
        candidates.append(trimmed)

    # Strategy 2: Find array with regex (handles extra text)
    m = re.search(r"\[[\s\S]*\]", trimmed)
    if m:
        candidates.append(m.group(0))

    # Strategy 3: Extract first JSON array (handles truncated)
    try:
        arr = extract_first_json_array(trimmed)
        if arr != trimmed:
            candidates.append(arr)
    except ValueError:
        pass

    # Strategy 4: Extract first JSON object (last resort, partial)
    try:
        obj = extract_first_json_object(trimmed)
        candidates.append(obj)
    except ValueError:
        pass

    errors: list[str] = []
    for candidate in candidates:
        try:
            parsed = json.loads(candidate)
            return [_normalize_prompt_result(item, expected) for item in _unwrap_payload(parsed)]
        except (json.JSONDecodeError, ValueError):
            try:
                repaired = repair_json(candidate)
                parsed = json.loads(repaired)
                return [_normalize_prompt_result(item, expected) for item in _unwrap_payload(parsed)]
            except (json.JSONDecodeError, ValueError) as e:
                errors.append(str(e))

    # Strategy 5: Try numbered format (N. [prompt] or N. prompt)
    # Used when the model follows a non-JSON format (e.g., Prompt Maestro)
    expected_ids = {f["id"] for f in expected}
    numbered_results = _parse_numbered_format(trimmed, expected_ids)
    if numbered_results:
        logger.info("Fallback to numbered format parsing: got %d/%d results",
                     len(numbered_results), len(expected))
        return [
            {
                "fragment_id": fid,
                "original_text": next(
                    (f["text"] for f in expected if f["id"] == fid), ""
                ),
                "image_prompt": prompt,
            }
            for fid, prompt in sorted(numbered_results.items())
        ]

    logger.error("JSON parse failed. Raw (first 1000): %s", trimmed[:1000])
    raise ValueError("Model returned invalid JSON. Try a shorter fragment or retry.")


def _parse_numbered_format(text: str, expected_ids: set[int]) -> dict[int, str]:
    """Parse N. [prompt] or N. prompt or N: prompt format.

    Returns dict of fragment_id -> prompt text.
    """
    pattern = re.compile(r"^\s*(\d+)[.\):]\s*(.+?)$", re.MULTILINE)
    results: dict[int, str] = {}
    for m in pattern.finditer(text.strip()):
        fid = int(m.group(1))
        if fid in expected_ids:
            content = m.group(2).strip()
            # Clean markdown fences
            content = re.sub(r"^\s*```[a-zA-Z0-9_-]*\s*", "", content)
            content = re.sub(r"\s*```\s*$", "", content)
            content = content.replace("```", "").replace("`", "")
            content = re.sub(r"\n{3,}", "\n", content).strip()
            if content:
                results[fid] = content
    return results


# ─── Provider Implementations ─────────────────────────────


def _should_fallback(error: Exception) -> bool:
    msg = str(error).lower()
    status = getattr(error, "status", None) or getattr(error, "status_code", None)
    if status in (401, 403, 429, 503):
        return True
    return any(
        kw in msg
        for kw in ("rate", "quota", "too many", "context", "token", "api key", "unauthorized")
    )


async def request_google_batch(
    system_prompt: str, batch: list[PromptFragment]
) -> list[PromptResult]:
    """Call Google Gemini API."""
    import httpx

    api_keys = [k.strip() for k in settings.google_ai_api_key.split(",") if k.strip()]
    if not api_keys:
        raise ValueError("GOOGLE_AI_API_KEY not configured")

    model = settings.google_model
    url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"

    for api_key in api_keys:
        try:
            async with httpx.AsyncClient(timeout=25) as client:
                resp = await client.post(
                    url,
                    headers={
                        "Content-Type": "application/json",
                        "x-goog-api-key": api_key,
                    },
                    json={
                        "contents": [
                            {
                                "parts": [
                                    {"text": f"{system_prompt}\n\n{json.dumps(batch)}"}
                                ]
                            }
                        ],
                        "generationConfig": {
                            "temperature": 0.5,
                            "maxOutputTokens": 4096,
                        },
                    },
                )
                payload = resp.json()
                if not resp.is_success:
                    err_msg = payload.get("error", {}).get("message", str(resp.text[:200]))
                    raise RuntimeError(f"Google AI: {resp.status_code} {err_msg}")

                text = _extract_google_content(payload)
                if not text:
                    raise RuntimeError("Google AI returned empty content")
                return parse_model_json(text, batch)
        except Exception as e:
            if not _should_fallback(e):
                raise
            logger.warning("Google key failed, trying next: %s", e)

    raise RuntimeError("All Google API keys failed")


def _extract_google_content(payload: dict) -> str:
    try:
        return payload["candidates"][0]["content"]["parts"][0]["text"]
    except (KeyError, IndexError, TypeError):
        return ""


async def request_ollama_batch(
    system_prompt: str, batch: list[PromptFragment]
) -> list[PromptResult]:
    """Call local Ollama API."""
    import httpx

    url = f"{settings.ollama_base_url.rstrip('/')}/api/chat"
    # Ollama is more reliable with one fragment per request
    if len(batch) > 1:
        results = []
        for fragment in batch:
            results.extend(await request_ollama_batch(system_prompt, [fragment]))
        return results

    async with httpx.AsyncClient(timeout=25) as client:
        resp = await client.post(
            url,
            json={
                "model": settings.ollama_model,
                "format": "json",
                "messages": [
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": json.dumps(batch)},
                ],
                "stream": False,
                "options": {"temperature": 0.2, "num_predict": 4096},
            },
        )
        if not resp.is_success:
            raise RuntimeError(f"Ollama: {resp.status_code} {resp.text[:200]}")

        payload = resp.json()
        text = _extract_ollama_content(payload)
        if not text:
            raise RuntimeError("Ollama returned empty content")
        return parse_model_json(text, batch)


def _extract_ollama_content(payload: dict) -> str:
    return payload.get("message", {}).get("content", "")


async def request_groq_batch(
    system_prompt: str, batch: list[PromptFragment]
) -> list[PromptResult]:
    """Call Groq API."""
    import httpx

    if not settings.groq_api_key:
        raise ValueError("GROQ_API_KEY not configured")

    # Groq free tier has 6000 TPM — keep input small
    estimated = (len(system_prompt) + len(json.dumps(batch))) // 4
    truncated = system_prompt
    if estimated > 3500:
        max_sys_len = int(3500 * 4 - len(json.dumps(batch)) / 4)
        truncated = system_prompt[:max_sys_len]

    async with httpx.AsyncClient(timeout=25) as client:
        resp = await client.post(
            "https://api.groq.com/openai/v1/chat/completions",
            headers={
                "Authorization": f"Bearer {settings.groq_api_key}",
                "Content-Type": "application/json",
            },
            json={
                "model": settings.groq_model,
                "temperature": 0.5,
                "max_tokens": 2048,
                "messages": [
                    {"role": "system", "content": truncated},
                    {"role": "user", "content": json.dumps(batch)},
                ],
            },
        )
        if not resp.is_success:
            raise RuntimeError(f"Groq: {resp.status_code} {resp.text[:200]}")

        payload = resp.json()
        text = payload.get("choices", [{}])[0].get("message", {}).get("content", "")
        if not text:
            raise RuntimeError("Groq returned empty content")
        return parse_model_json(text, batch)


async def request_openrouter_batch(
    system_prompt: str, batch: list[PromptFragment]
) -> list[PromptResult]:
    """Call OpenRouter API, trying multiple free models in sequence."""
    import httpx

    if not settings.openrouter_api_key:
        raise ValueError("OPENROUTER_API_KEY not configured")

    # Build model list: primary + fallbacks
    models = [settings.openrouter_model]
    if settings.openrouter_fallback_models:
        models.extend(
            m.strip()
            for m in settings.openrouter_fallback_models.split(",")
            if m.strip()
        )

    last_error: Exception | None = None
    for model in models:
        try:
            async with httpx.AsyncClient(timeout=25) as client:
                resp = await client.post(
                    "https://openrouter.ai/api/v1/chat/completions",
                    headers={
                        "Authorization": f"Bearer {settings.openrouter_api_key}",
                        "Content-Type": "application/json",
                    },
                    json={
                        "model": model,
                        "temperature": 0.5,
                        "max_tokens": 8192,
                        "messages": [
                            {"role": "system", "content": system_prompt},
                            {"role": "user", "content": json.dumps(batch)},
                        ],
                    },
                )
                if not resp.is_success:
                    err_text = resp.text[:200]
                    if resp.status_code in (429, 503):
                        logger.warning("OpenRouter model %s rate-limited: %s", model, err_text)
                        continue  # Try next model
                    raise RuntimeError(f"OpenRouter {model}: {resp.status_code} {err_text}")

                payload = resp.json()
                text = (
                    payload.get("choices", [{}])[0]
                    .get("message", {})
                    .get("content", "")
                )
                if not text:
                    raise RuntimeError(f"OpenRouter {model} returned empty content")

                logger.info("OpenRouter model %s succeeded", model)
                return parse_model_json(text, batch)
        except Exception as e:
            last_error = e
            logger.warning("OpenRouter model %s failed: %s", model, e)
            # Non-retryable errors (401, 403) — don't try other models
            if getattr(e, "status_code", None) in (401, 403) or "401" in str(e) or "403" in str(e):
                raise

    raise last_error or RuntimeError("All OpenRouter models failed")


# ─── Provider Registry ────────────────────────────────────


def _get_retry_delay(error: Exception, retry_count: int) -> int | None:
    msg = str(error).lower()
    if "quota" in msg and "limit: 0" in msg:
        return None
    m = re.search(r"retry in ([\d.]+)s", msg)
    if m:
        return min(int(float(m.group(1)) * 1000), 30000)
    if any(kw in msg for kw in ("rate", "too many", "429")):
        return min(1000 * (2 ** retry_count), 15000)
    return None


ProviderEntry = dict[str, Any]


def _build_providers() -> list[ProviderEntry]:
    """Build provider list ordered by PROMPT_PROVIDER_ORDER."""
    registry: dict[str, ProviderEntry] = {
        "google": {
            "id": "google",
            "name": "Google AI",
            "enabled": bool(settings.google_ai_api_key),
            "request": request_google_batch,
            "max_retries": 2,
        },
        "ollama": {
            "id": "ollama",
            "name": "Ollama",
            "enabled": bool(settings.ollama_base_url),
            "request": request_ollama_batch,
            "max_retries": 0,
        },
        "groq": {
            "id": "groq",
            "name": "Groq",
            "enabled": bool(settings.groq_api_key),
            "request": request_groq_batch,
            "max_retries": 0,
        },
        "openrouter": {
            "id": "openrouter",
            "name": "OpenRouter",
            "enabled": bool(settings.openrouter_api_key),
            "request": request_openrouter_batch,
            "max_retries": 0,
        },
        "gemini-web": {
            "id": "gemini-web",
            "name": "Gemini Web",
            "enabled": settings.gemini_web_enabled,
            "request": request_gemini_web_batch,
            "max_retries": 0,  # Retries handled internally
        },
    }

    order = [s.strip().lower() for s in settings.prompt_provider_order.split(",") if s.strip()]
    order_map = {pid: i for i, pid in enumerate(order)}
    sorted_providers = sorted(registry.values(), key=lambda p: order_map.get(p["id"], 999))
    return [p for p in sorted_providers if p["enabled"]]


# ─── Main Entry Point ─────────────────────────────────────


_cooldown_providers: set[str] = set()  # Skip failed providers for remaining batches


async def _request_batch_with_fallback(
    batch: list[PromptFragment],
    providers: list[ProviderEntry],
    system_prompt: str,
) -> list[PromptResult]:
    """Send a batch of fragments to the provider chain.

    All fragments in the batch are sent in a single request.
    Validates that ALL fragment IDs are returned exactly once.
    Skips providers that are in cooldown (previously failed).
    """
    batch_ids = {f["id"] for f in batch}
    provider_errors: list[str] = []

    for entry in providers:
        if entry["id"] in _cooldown_providers:
            logger.debug("Skipping %s (cooldown)", entry["name"])
            continue
        for retry in range(entry["max_retries"] + 1):
            try:
                results = await entry["request"](system_prompt, batch)

                # Validate all IDs present
                returned_ids = {r.get("fragment_id") for r in results}
                missing = batch_ids - returned_ids
                if missing:
                    raise RuntimeError(
                        f"{entry['name']} missing fragment_ids: {missing}"
                    )
                # Check for duplicates
                counts = Counter(r.get("fragment_id") for r in results)
                dupes = {fid for fid, cnt in counts.items() if cnt > 1 and fid in batch_ids}
                if dupes:
                    raise RuntimeError(
                        f"{entry['name']} returned duplicate fragment_ids: {dupes}"
                    )

                # Tag with provider info
                for r in results:
                    r["provider"] = entry["name"]
                    r["model"] = settings.openrouter_model  # best-effort

                return results
            except Exception as e:
                delay = _get_retry_delay(e, retry)
                if delay is not None and retry < entry["max_retries"]:
                    logger.warning(
                        "%s rate limited, retrying in %dms (attempt %d)",
                        entry["name"], delay, retry + 1,
                    )
                    time.sleep(delay / 1000)
                    continue
                logger.warning("%s failed: %s", entry["name"], e)
                # Add to cooldown so we skip it for remaining batches
                _cooldown_providers.add(entry["id"])
                provider_errors.append(f"{entry['name']}: {e}")
                break

    detail = f" Last: {provider_errors[-1]}" if provider_errors else ""
    # Report which fragments failed
    failed_ids = ",".join(str(f["id"]) for f in batch)
    raise RuntimeError(f"All providers failed for batch [{failed_ids}].{detail}")


async def generate_prompts_for_project(
    project_id: str,
    style: str = "Cinematico",
    fragment_ids: list[int] | None = None,
    progress_callback: Callable[[float, str], None] | None = None,
    use_gemini_web: bool = True,
) -> list[PromptResult]:
    """Generate image prompts for all pending fragments of a project.

    Reads fragments from prompts-*.json, generates prompts via AI providers
    with fallback chain, and saves the results back to the file.
    Fragments are sent in batches of ``prompt_batch_size`` to reduce API calls.
    """
    global _cooldown_providers
    _cooldown_providers.clear()
    from app.services.project_service import _resolve_prompts_path
    from app.core.job_store import get_db
    from app.core.sse import sse_manager
    from app.services.gems_manager import build_system_prompt_from_gem

    db = await get_db()
    try:
        cursor = await db.execute("SELECT path FROM projects WHERE id = ?", (project_id,))
        row = await cursor.fetchone()
        if not row:
            raise ValueError(f"Project '{project_id}' not found")
        project_dir = row["path"]
    finally:
        await db.close()

    prompts_path = _resolve_prompts_path(project_dir)
    if not prompts_path or not prompts_path.exists():
        raise ValueError("No prompts file found. Fragment the script first.")

    fragments: list[dict] = json.loads(prompts_path.read_text(encoding="utf-8"))

    # Filter to target fragments: either specified IDs or all pending
    if fragment_ids:
        target = [f for f in fragments if f.get("fragment_id") in fragment_ids]
    else:
        target = [
            f for f in fragments
            if not f.get("image_prompt") or f["image_prompt"].strip() == ""
        ]

    if not target:
        raise ValueError("No pending fragments to generate prompts for.")

    # If style matches a gem, resolve it properly (type="prompt" uses value directly)
    system_prompt = build_system_prompt_from_gem(style, style_fallback=style)
    providers = _build_providers()
    # Allow user to disable Gemini Web from the UI
    if not use_gemini_web:
        providers = [p for p in providers if p["id"] != "gemini-web"]
    if not providers:
        raise ValueError(
            "No AI providers configured. Set OPENROUTER_API_KEY, GOOGLE_AI_API_KEY, "
            "GROQ_API_KEY, or OLLAMA_BASE_URL in .env"
        )

    batch_size = settings.prompt_batch_size
    # Group into batches
    batches = [target[i:i + batch_size] for i in range(0, len(target), batch_size)]

    logger.info(
        "Generating prompts for %d fragments in %d batches of %d (providers: %s)",
        len(target), len(batches), batch_size,
        " > ".join(p["name"] for p in providers),
    )

    results: list[PromptResult] = []
    last_batch_ratelimited = False
    for batch_idx, batch_target in enumerate(batches):
        # Convert to provider format: [{id, text}, ...]
        provider_batch = [
            {"id": f["fragment_id"], "text": f.get("original_text", "")}
            for f in batch_target
        ]
        batch_ids = [f["fragment_id"] for f in batch_target]
        logger.info(
            "Processing batch %d/%d: fragments %s",
            batch_idx + 1, len(batches), batch_ids,
        )

        batch_results = await _request_batch_with_fallback(provider_batch, providers, system_prompt)
        results.extend(batch_results)

        # Track if this batch hit rate limits
        cooldown_before = len(_cooldown_providers)

        # Update in-memory fragments AND persist to disk after each batch
        for r in batch_results:
            fid = r.get("fragment_id")
            for f in fragments:
                if f["fragment_id"] == fid:
                    f["image_prompt"] = r.get("image_prompt", "")
                    f["updatedAt"] = datetime.now(timezone.utc).isoformat()
                    break

        # Save incrementally — each batch persisted immediately
        prompts_path.write_text(
            json.dumps(fragments, ensure_ascii=False, indent=2), encoding="utf-8"
        )

        # Emit SSE event for real-time UI update
        await sse_manager.emit_prompt_batch_complete(
            project_id, batch_idx, len(batches), batch_ids
        )

        # Call progress callback (used by orchestrator for workflow_progress events)
        if progress_callback:
            progress = (batch_idx + 1) / len(batches)
            await progress_callback(progress, f"Batch {batch_idx + 1}/{len(batches)}")

        # Delay between batches — adaptive
        # Full delay only when no rate limiting was detected;
        # short delay (1s) when any provider was rate-limited
        new_cooldowns = len(_cooldown_providers) - cooldown_before
        delay = settings.prompt_inter_fragment_delay_ms
        if new_cooldowns > 0 or len(_cooldown_providers) > 0:
            delay = min(delay, 1000)  # 1s max when rate limiting detected
        if delay > 0 and batch_idx < len(batches) - 1:
            logger.info("Waiting %dms before next batch...", delay)
            await asyncio_sleep(delay / 1000)

    # Write final state (redundant but ensures consistency)
    prompts_path.write_text(
        json.dumps(fragments, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    # Emit final "all complete" event so the frontend stops the progress bar
    await sse_manager.emit_prompt_all_complete(project_id, len(results))
    logger.info("Generated %d prompts successfully", len(results))
    return results


# Helper for async sleep
import asyncio
asyncio_sleep = asyncio.sleep
