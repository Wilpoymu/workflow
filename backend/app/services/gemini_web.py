"""Gemini Web client — cookie-based, no API key needed.

Adapted from Gemini Batch Studio's web_client.py.
Uses curl_cffi with Chrome impersonation to hit Gemini Web's internal API,
bypassing the need for a paid API key.
"""

import json
import logging
import random
import re
import time
import uuid
from typing import Any

logger = logging.getLogger(__name__)

INIT_URL = "https://gemini.google.com/app"
BASE_GENERATE_URL = "https://gemini.google.com/_/BardChatUi/data/assistant.lamda.BardFrontendService/StreamGenerate"

HEADERS = {
    "Content-Type": "application/x-www-form-urlencoded;charset=utf-8",
    "Host": "gemini.google.com",
    "Origin": "https://gemini.google.com",
    "Referer": "https://gemini.google.com/",
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/136.0.0.0 Safari/537.36"
    ),
    "X-Same-Domain": "1",
}

_METADATA_RE = re.compile(r"^(rc_|c_|r_)[a-f0-9]+$")


def _is_metadata(text: str) -> bool:
    if _METADATA_RE.match(text):
        return True
    if text.startswith("{") or text.startswith("["):
        return True
    if "google.com" in text or "gstatic.com" in text:
        return True
    return False


def _parse_frames(content: str) -> list[list]:
    """Parse Gemini Web's internal frame protocol response."""
    if not content:
        return []
    if content.startswith(")]}'"):
        nl = content.find("\n")
        if nl != -1:
            content = content[nl + 1 :]
    frames: list[list] = []
    for line in content.splitlines():
        line = line.strip()
        if not line:
            continue
        if not (line.startswith("[[") and line.endswith("]]")):
            continue
        try:
            frames.append(json.loads(line))
        except (json.JSONDecodeError, ValueError):
            pass
    return frames


def _get_nested(data: Any, path: list, default: Any = None) -> Any:
    current = data
    for key in path:
        try:
            if isinstance(key, int):
                current = current[key]
            elif isinstance(key, str) and isinstance(current, dict):
                current = current[key]
            else:
                return default
        except (IndexError, KeyError, TypeError):
            return default
    return current if current is not None else default


def _extract_texts_recursive(obj: Any, depth: int = 0) -> list[str]:
    results: list[str] = []
    if depth > 15:
        return results
    if isinstance(obj, str) and len(obj) > 10:
        results.append(obj)
    elif isinstance(obj, list):
        for item in obj:
            results.extend(_extract_texts_recursive(item, depth + 1))
    elif isinstance(obj, dict):
        for v in obj.values():
            results.extend(_extract_texts_recursive(v, depth + 1))
    return results


class GeminiWebClient:
    """Client for Gemini Web's internal API using cookie authentication."""

    def __init__(self, secure_1psid: str, secure_1psidts: str = ""):
        self.secure_1psid = secure_1psid.strip()
        self.secure_1psidts = secure_1psidts.strip()
        self.access_token: str | None = None
        self.build_label: str | None = None
        self.session_id: str | None = None
        self._reqid = random.randint(10000, 99999)
        self._session = None
        self._account_prefix = ""
        self._device_uuid = str(uuid.uuid4()).upper()
        self._device_fingerprint = uuid.uuid4().hex[:16]
        self._turn_idx = 0
        self._last_session_uuid: str | None = None
        self._chat_metadata: list | None = None

    def _per_request_uuid(self) -> str:
        u = str(uuid.uuid4()).upper()
        self._last_session_uuid = u
        return u

    def _extra_headers(self) -> dict[str, str]:
        sid = self._last_session_uuid or self._per_request_uuid()
        return {
            "x-goog-ext-525001261-jspb": json.dumps(
                [1, None, None, None, self._device_fingerprint, None, None, 0, [4, 5], None, None, 4, None, None, 1, 1, self._device_uuid],
                separators=(",", ":"),
            ),
            "x-goog-ext-525005358-jspb": json.dumps([sid, 1], separators=(",", ":")),
            "x-goog-ext-73010989-jspb": "[0]",
            "x-goog-ext-73010990-jspb": "[0,0,0]",
        }

    def _build_cookies(self) -> dict[str, str]:
        cookies: dict[str, str] = {}
        cookies["__Secure-1PSID"] = self.secure_1psid
        if self.secure_1psidts:
            cookies["__Secure-1PSIDTS"] = self.secure_1psidts
        return cookies

    def _build_inner_req(self, message_content: list, gem_id: str | None = None) -> list:
        sid = self._per_request_uuid()
        inner_req: list = [None] * 81
        inner_req[0] = message_content
        inner_req[1] = ["es"]
        inner_req[2] = self._chat_metadata or ["", "", "", None, None, None, None, None, None, ""]
        inner_req[6] = [1]
        inner_req[7] = 1
        inner_req[10] = 1
        inner_req[11] = 0
        inner_req[17] = [[self._turn_idx]]
        inner_req[18] = 0
        if gem_id:
            inner_req[19] = gem_id
        inner_req[27] = 1
        inner_req[30] = [4]
        inner_req[41] = [1]
        inner_req[53] = 0
        inner_req[59] = sid
        inner_req[61] = []
        inner_req[67] = 0
        inner_req[68] = 2
        inner_req[79] = 1
        inner_req[80] = 1
        return inner_req

    def _detect_account_prefix(self, resp_url: str):
        m = re.search(r"gemini\.google\.com/(u/\d+)/", resp_url)
        if m:
            self._account_prefix = m.group(1)
            logger.debug("Multi-account detected: /%s/", self._account_prefix)
        else:
            self._account_prefix = ""

    def _get_generate_url(self) -> str:
        if self._account_prefix:
            return (
                f"https://gemini.google.com/{self._account_prefix}"
                "/_/BardChatUi/data/assistant.lamda.BardFrontendService/StreamGenerate"
            )
        return BASE_GENERATE_URL

    def init(self) -> bool:
        """Initialize session: fetch access token and build label from Gemini Web."""
        from curl_cffi import requests as cf_requests

        logger.info("Initializing Gemini Web client...")
        session = cf_requests.Session(impersonate="chrome136")
        cookies = self._build_cookies()

        html = ""
        last_status: int | None = None
        for attempt in range(3):
            if attempt > 0:
                logger.info("Retrying init (attempt %d/3) after HTTP %s...", attempt + 1, last_status)
                time.sleep(2 * attempt)
            resp = session.get(INIT_URL, headers=HEADERS, cookies=cookies, timeout=30, impersonate="chrome136")
            last_status = resp.status_code
            if resp.status_code == 200:
                html = resp.text
                self._detect_account_prefix(str(resp.url))
                break
            if resp.status_code not in (502, 503, 504):
                raise RuntimeError(f"Gemini Web: HTTP {resp.status_code} on init")
        else:
            raise RuntimeError("Gemini Web: failed to load after retries")

        if not html:
            raise RuntimeError("Gemini Web: empty HTML response")

        snlm0e = re.search(r'"SNlM0e":\s*"(.*?)"', html)
        if not snlm0e:
            if "accounts.google.com" in html or "ServiceLogin" in html:
                raise RuntimeError("Gemini cookies expired or invalid. Please refresh them.")
            raise RuntimeError("Gemini Web: could not find access token. Cookies may be invalid.")

        self.access_token = snlm0e.group(1)
        cfb2h = re.search(r'"cfb2h":\s*"(.*?)"', html)
        self.build_label = cfb2h.group(1) if cfb2h else None
        fdrfje = re.search(r'"FdrFJe":\s*"(.*?)"', html)
        self.session_id = fdrfje.group(1) if fdrfje else None

        logger.info(
            "Gemini Web initialized. build_label=%s has_session=%s%s",
            self.build_label,
            self.session_id is not None,
            f" prefix={self._account_prefix}" if self._account_prefix else "",
        )
        return True

    def chat(self, prompt: str, system_prompt: str | None = None, gem_id: str | None = None) -> str:
        """Send a chat prompt to Gemini Web and return the response text."""
        if not self.access_token:
            self.init()

        # Build the full prompt with system instructions
        if system_prompt and not gem_id and self._chat_metadata is None:
            full_prompt = (
                "IMPORTANT INSTRUCTIONS - You must follow these instructions "
                "for ALL your responses in this conversation:\n\n"
                + system_prompt
                + f"\n\n---\nUser message:\n{prompt}"
            )
        else:
            full_prompt = prompt

        return self._send_message(full_prompt, gem_id=gem_id)

    def _do_post(self, params: dict, data: dict) -> str:
        from curl_cffi import requests as cf_requests

        gen_url = self._get_generate_url()
        extra_headers = self._extra_headers()
        post_headers = dict(HEADERS)
        post_headers.update(extra_headers)
        cookies = self._build_cookies()
        session = cf_requests.Session(impersonate="chrome136")

        resp = session.post(
            gen_url,
            headers=post_headers,
            cookies=cookies,
            params=params,
            data=data,
            timeout=120,
            impersonate="chrome136",
        )

        if resp.status_code in (401, 403):
            self.access_token = None
            raise RuntimeError("Gemini Web: authentication failed. Cookies may be expired.")
        if resp.status_code == 429:
            logger.warning("Gemini Web HTTP 429 rate limit, retrying after 10s...")
            time.sleep(10)
            resp = session.post(
                gen_url,
                headers=post_headers,
                cookies=cookies,
                params=params,
                data=data,
                timeout=120,
                impersonate="chrome136",
            )
        if resp.status_code != 200:
            raise RuntimeError(f"Gemini Web API error: HTTP {resp.status_code}")

        return resp.text

    def _send_message(self, full_prompt: str, gem_id: str | None = None) -> str:
        message_content = [full_prompt, 0, None, None, None, None, 0]
        inner_req = self._build_inner_req(message_content, gem_id=gem_id)
        if gem_id:
            logger.info("Using gem preset: %s", gem_id)

        reqid = self._reqid
        self._reqid += 100000
        params: dict[str, Any] = {"_reqid": reqid, "rt": "c", "hl": "es"}
        if self.build_label:
            params["bl"] = self.build_label
        if self.session_id:
            params["f.sid"] = self.session_id
        data = {"at": self.access_token, "f.req": json.dumps([None, json.dumps(inner_req)])}

        try:
            raw_text = self._do_post(params, data)
        except Exception as e:
            raise RuntimeError(f"Gemini Web request failed: {e}") from e

        # First parse attempt
        try:
            text = self._parse_response(raw_text)
            self._turn_idx += 1
            return text
        except RuntimeError:
            if len(raw_text) < 300:
                logger.warning("Short response from Gemini Web, retrying after 3s...")
                time.sleep(3)
            else:
                logger.info("Parse failed, reinitializing session...")

            # Retry with fresh session
            old_prefix = self._account_prefix
            self.access_token = None
            self.init()
            if not self._account_prefix and old_prefix:
                self._account_prefix = old_prefix

            self._reqid = random.randint(10000, 99999)
            inner_req2 = self._build_inner_req(message_content, gem_id=gem_id)
            reqid2 = self._reqid
            self._reqid += 100000
            params2: dict[str, Any] = {"_reqid": reqid2, "rt": "c", "hl": "es"}
            if self.build_label:
                params2["bl"] = self.build_label
            if self.session_id:
                params2["f.sid"] = self.session_id
            data2 = {"at": self.access_token, "f.req": json.dumps([None, json.dumps(inner_req2)])}

            raw_text2 = self._do_post(params2, data2)
            text = self._parse_response(raw_text2)
            self._turn_idx += 1
            return text

    def _parse_response(self, raw_text: str) -> str:
        """Parse Gemini Web's response to extract the generated text."""
        frames = _parse_frames(raw_text)
        best_text = ""

        for frame in frames:
            if not isinstance(frame, list):
                continue
            for item in frame:
                if not isinstance(item, list) or len(item) < 3:
                    continue
                inner_str = _get_nested(item, [2])
                if not isinstance(inner_str, str):
                    continue
                try:
                    inner_json = json.loads(inner_str)
                except (json.JSONDecodeError, ValueError):
                    continue
                if not isinstance(inner_json, list):
                    continue

                metadata = _get_nested(inner_json, [1])
                if metadata and isinstance(metadata, list):
                    self._chat_metadata = metadata

                candidates = _get_nested(inner_json, [4], [])
                if not candidates:
                    candidates = _get_nested(inner_json, [0, 4], [])

                if candidates:
                    for cand in candidates:
                        for path in ([1, 0], [1], [0, 1, 0]):
                            text = _get_nested(cand, path, "")
                            if (
                                isinstance(text, str)
                                and len(text) > len(best_text)
                                and not _is_metadata(text)
                            ):
                                text = re.sub(
                                    r"http://googleusercontent\.com/\w+/\d+\n*", "", text
                                )
                                best_text = text

                if not best_text:
                    all_texts = _extract_texts_recursive(inner_json)
                    for t in all_texts:
                        clean = re.sub(r"http://googleusercontent\.com/\w+/\d+\n*", "", t)
                        if len(clean) > len(best_text) and not _is_metadata(clean):
                            best_text = clean

        if not best_text:
            raise RuntimeError(
                f"Gemini Web returned no valid response [frames={len(frames)}]"
            )
        return best_text

    def test_auth(self) -> dict:
        """Test if the current cookies are valid."""
        try:
            self.init()
            return {"ok": True}
        except Exception as e:
            return {"ok": False, "error": str(e)}
