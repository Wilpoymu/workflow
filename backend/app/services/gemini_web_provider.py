"""Gemini Web provider for the prompt generation fallback chain.

Uses cookie-based authentication (no API key) by connecting to Gemini Web's
internal API. Adapted from Gemini Batch Studio's batch approach which uses
a `### FRAGMENTO N` format for more reliable LLM parsing.
"""

import asyncio
import logging
import re
from typing import Any

from app.config import settings
from app.services.gemini_web import GeminiWebClient
from app.services.gemini_cookie_store import cookie_store

logger = logging.getLogger(__name__)

MAX_RETRIES = 3
RETRY_DELAY_SECONDS = 5
SUCCESS_DELAY_SECONDS = 2
MAX_BATCH_SIZE = 10


def build_batch_prompt(batch: list[dict]) -> str:
    """Build a batch prompt using the ### FRAGMENTO N format.

    This format is more reliable than JSON for LLM output because the
    parser only needs regex, not JSON parsing.
    """
    lines: list[str] = []
    lines.append("Process ALL of the following fragments and return a response for each one.")
    lines.append("You MUST respond using EXACTLY this format:")
    lines.append("")
    lines.append("### FRAGMENTO 12")
    lines.append("image prompt in English here")
    lines.append("")
    lines.append("### FRAGMENTO 13")
    lines.append("image prompt in English here")
    lines.append("")
    lines.append("Mandatory rules:")
    lines.append("- Return ALL fragments in the batch, without skipping any.")
    lines.append("- Keep the exact same fragment number you received.")
    lines.append("- Do NOT explain anything, do NOT add comments, do NOT use JSON.")
    lines.append("- Each block MUST start with: ### FRAGMENTO N")
    lines.append("- Below each header, write only the final image prompt.")
    lines.append("- If a fragment suggests two strong visual ideas, place both in the same block.")
    lines.append("")
    lines.append("BATCH FRAGMENTS:")
    lines.append("")
    for item in batch:
        fid = item.get("id", 0)
        text = item.get("text", "")
        lines.append(f"### FRAGMENTO {fid}")
        lines.append(text)
        lines.append("")
    return "\n".join(lines).strip()


def parse_batch_response(response_text: str, expected_ids: set[int]) -> dict[int, str]:
    """Parse Gemini Web response, supporting multiple output formats.

    Supports:
    - ### FRAGMENTO N / prompt (Gemini Batch Studio format)
    - N. [prompt] or N. prompt (Prompt Maestro format)
    - N: prompt

    Args:
        response_text: Raw response text from Gemini Web.
        expected_ids: Set of fragment IDs we expect to find.

    Returns:
        Dict mapping fragment_id -> extracted prompt text.
    """
    results: dict[int, str] = {}
    text = response_text.strip()

    # Strategy 1: Try ### FRAGMENTO N format first
    frag_pattern = re.compile(
        r"###\s*FRAGMENTO\s+(\d+)\s*\n(.*?)(?=\n###\s*FRAGMENTO\s+\d+\s*\n|\Z)",
        re.IGNORECASE | re.DOTALL,
    )
    for m in frag_pattern.finditer(text):
        fid = int(m.group(1))
        content = _clean_prompt_text(m.group(2))
        if content:
            results[fid] = content

    # Strategy 2: If no results, try N. [prompt] or N. prompt format
    if not results:
        line_pattern = re.compile(
            r"^\s*(\d+)[.\):]\s*(.+?)$",
            re.MULTILINE,
        )
        for m in line_pattern.finditer(text):
            fid = int(m.group(1))
            if fid in expected_ids:
                content = _clean_prompt_text(m.group(2))
                if content:
                    results[fid] = content

    return results


def _clean_prompt_text(text: str) -> str:
    """Clean up extracted prompt text."""
    if not text:
        return ""
    text = re.sub(r"^\s*```[a-zA-Z0-9_-]*\s*", "", text)
    text = re.sub(r"\s*```\s*$", "", text)
    text = text.replace("```", "").replace("`", "")
    text = re.sub(r"\n{3,}", "\n", text)
    return text.strip()


def _build_system_prompt(style: str) -> str:
    """Build the system prompt for Gemini Web.

    This is adapted from Gemini Batch Studio's DEFAULT_SYSTEM_PROMPT
    but parameterized with the user's chosen style.
    """
    style_part = f" with a {style} aesthetic" if style and style != "Cinematico" else ""
    return (
        f"You are a visual prompt generator for 2D minimalist illustration scenes{style_part}.\n\n"
        "Your task:\n"
        "- Receive script fragments in Spanish.\n"
        "- Convert EACH fragment into 1 or more clear, cinematic visual prompts in English.\n"
        "- Maintain visual consistency across scenes.\n"
        "- Use [subject] as a placeholder for the main character when applicable.\n"
        "- Deliver ONLY useful prompts, no extra explanation.\n"
        "- If a fragment suggests two strong visual ideas, return 2 prompts in the same block.\n"
        "- Maintain aesthetics: minimalist flat vector art, smooth silhouettes,\n"
        "  muted pastel palette, pale background, clean lines, no textures, NO 3D, NO CGI."
    )


def _sanitize_for_fragment_format(system_prompt: str) -> str:
    """Remove JSON output instructions from the system prompt.

    The generic build_system_prompt() instructs models to return JSON,
    but Gemini Web uses the ### FRAGMENTO N format. We strip the JSON
    instructions while keeping the style definition and context.
    """
    sanitized = system_prompt

    # Remove "Return ONLY valid raw JSON array and nothing else" and similar
    sanitized = re.sub(
        r"Return ONLY valid raw JSON array[^.]*\.\s*",
        "",
        sanitized,
        flags=re.IGNORECASE,
    )
    sanitized = re.sub(
        r"Do not include markdown code fences[^.]*\.\s*",
        "",
        sanitized,
        flags=re.IGNORECASE,
    )
    sanitized = re.sub(
        r"Expected format:[^.]*\.\s*",
        "",
        sanitized,
        flags=re.IGNORECASE,
    )
    sanitized = re.sub(
        r"Every object must use[^.]*\.\s*",
        "",
        sanitized,
        flags=re.IGNORECASE,
    )
    sanitized = re.sub(
        r'IMPORTANT: The "fragment_id"[^.]*\.\s*',
        "",
        sanitized,
        flags=re.IGNORECASE,
    )

    # Add format instruction ONLY if the prompt doesn't already have its own format
    has_format = any(marker in sanitized.lower() for marker in [
        "formato de salida", "output format", "### fragmento",
        "respond using exactly", "debemos responder",
    ])
    if not has_format:
        sanitized += (
            "\n\nYou MUST respond using EXACTLY this format for each fragment:\n"
            "### FRAGMENTO N\n"
            "image prompt in English here\n"
            "Do NOT use JSON. Do NOT add extra text. Respond ONLY with the prompt blocks."
        )

    return sanitized.strip()


def _build_gemini_web_batch_prompt(batch: list[dict], style: str, system_prompt: str | None = None) -> tuple[str, str | None]:
    """Build the full user prompt and system prompt for a Gemini Web batch request.

    Returns:
        (user_prompt, system_prompt_or_none)
    """
    batch_prompt = build_batch_prompt(batch)

    if system_prompt:
        # Sanitize the incoming system prompt to remove JSON instructions
        sys_prompt = _sanitize_for_fragment_format(system_prompt)
    else:
        sys_prompt = _build_system_prompt(style)

    return batch_prompt, sys_prompt


async def request_gemini_web_batch(
    system_prompt: str, batch: list[dict]
) -> list[dict[str, Any]]:
    """Send a batch of fragments to Gemini Web via cookie auth.

    This is the provider function registered in the prompt_generation
    fallback chain.

    Args:
        system_prompt: System prompt from prompt_generation (contains style + format instructions).
        batch: List of {"id": int, "text": str} fragments.

    Returns:
        List of {"fragment_id": int, "original_text": str, "image_prompt": str} results.

    Raises:
        RuntimeError: If no cookies available, authentication fails, or all retries exhausted.
    """
    # 1. Get cookies
    profiles = cookie_store.get_authenticated()
    if not profiles:
        raise RuntimeError(
            "Gemini Web: no authenticated profiles. "
            "Install the Chrome extension and log into gemini.google.com first."
        )

    # 2. Use the first available profile
    profile = profiles[0]
    psid = profile.get("psid", "")
    psidts = profile.get("psidts", "")

    logger.info(
        "Gemini Web batch: %d fragments via profile %s",
        len(batch),
        profile.get("profile_label", "unknown"),
    )

    # 3. Build prompts using the ### FRAGMENTO N format
    # Sanitize system_prompt to remove JSON instructions (incompatible with fragment format)
    batch_prompt, clean_system_prompt = _build_gemini_web_batch_prompt(
        batch, "", system_prompt=system_prompt,
    )
    expected_ids = {item["id"] for item in batch}

    # 4. Send with retries
    client = GeminiWebClient(psid, psidts)
    last_error: Exception | None = None

    for attempt in range(1, MAX_RETRIES + 1):
        try:
            logger.info("Gemini Web attempt %d/%d...", attempt, MAX_RETRIES)
            raw = client.chat(batch_prompt, system_prompt=clean_system_prompt)
            results = parse_batch_response(raw, expected_ids)

            missing = expected_ids - set(results.keys())
            if missing:
                logger.warning(
                    "Gemini Web incomplete: got %d/%d, missing: %s",
                    len(results), len(expected_ids), missing,
                )
                if attempt < MAX_RETRIES:
                    # Retry with only missing fragments
                    retry_batch = [
                        {"id": fid, "text": text}
                        for item in batch
                        if (fid := item["id"]) in missing
                        for text in [item["text"]]
                    ]
                    batch_prompt = build_batch_prompt(retry_batch)
                    await asyncio.sleep(RETRY_DELAY_SECONDS)
                    continue
                else:
                    # Mark missing as errors
                    for fid in missing:
                        results[fid] = f"ERROR: No response after {MAX_RETRIES} retries"

            # 5. Format results in the expected format
            formatted = []
            for item in batch:
                fid = item["id"]
                original = item.get("text", "")
                prompt = results.get(fid, "")
                if prompt.startswith("ERROR:"):
                    formatted.append({
                        "fragment_id": fid,
                        "original_text": original,
                        "image_prompt": "",
                    })
                else:
                    formatted.append({
                        "fragment_id": fid,
                        "original_text": original,
                        "image_prompt": prompt,
                    })

            return formatted

        except Exception as e:
            last_error = e
            logger.warning("Gemini Web attempt %d failed: %s", attempt, e)
            if attempt < MAX_RETRIES:
                # Reinitialize client (cookies might have been stale)
                client = GeminiWebClient(psid, psidts)
                await asyncio.sleep(RETRY_DELAY_SECONDS * attempt)

    raise RuntimeError(
        f"Gemini Web: all {MAX_RETRIES} attempts failed. "
        f"Last error: {last_error}"
    ) from last_error
