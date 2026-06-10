"""Thread-safe in-memory cookie store for Gemini Web sessions.

Cookies are pushed by the Chrome extension and consumed by the
Gemini Web provider at prompt generation time.
"""

import threading
from datetime import datetime, timezone
from typing import Any


class GeminiCookieStore:
    """Stores Gemini Web cookies from Chrome extension pushes.

    Thread-safe via RLock. Supports multiple profiles (multi-account).
    """

    def __init__(self):
        self._lock = threading.RLock()
        # profile_id -> session dict
        self._profiles: dict[str, dict[str, Any]] = {}
        self._selected_profile_id: str | None = None

    def upsert(self, payload: dict[str, Any]) -> dict[str, Any]:
        """Insert or update a session from extension push.

        Payload expected keys:
          - profile_id (str): unique profile identifier
          - profile_label (str, optional): human-readable label
          - cookie_header (str): raw Cookie header value
          - has_active_tab (bool, optional)
          - fingerprint (str, optional): dedup key
        """
        with self._lock:
            profile_id = payload.get("profile_id", "")
            if not profile_id:
                profile_id = f"profile_{len(self._profiles)}"

            now = datetime.now(timezone.utc).isoformat(timespec="seconds")
            cookie_header = payload.get("cookie_header", "")

            # Parse PSID from cookie header
            psid, psidts = self._parse_psid(cookie_header)

            current = self._profiles.get(profile_id, {})
            new_fingerprint = payload.get("fingerprint", "")
            old_fingerprint = current.get("fingerprint", "")

            cookie_changed = (
                current.get("psid", "") != psid
                or current.get("psidts", "") != psidts
                or (new_fingerprint and old_fingerprint != new_fingerprint)
            )

            session = {
                "profile_id": profile_id,
                "profile_label": payload.get(
                    "profile_label", current.get("profile_label", profile_id)
                ),
                "cookie_header": cookie_header,
                "psid": psid,
                "psidts": psidts,
                "has_psid": bool(psid),
                "has_psidts": bool(psidts),
                "has_active_tab": bool(payload.get("has_active_tab", False)),
                "fingerprint": new_fingerprint or old_fingerprint,
                "updated_at": now,
                "auth_status": "Pendiente" if cookie_changed else current.get("auth_status", "Pendiente"),
            }

            self._profiles[profile_id] = session

            # Auto-select first profile or one with PSID
            if not self._selected_profile_id or (
                not self._profiles.get(self._selected_profile_id, {}).get("psid")
                and bool(psid)
            ):
                self._selected_profile_id = profile_id

            return session

    def get_authenticated(self) -> list[dict[str, Any]]:
        """Return all profiles with valid PSID cookies."""
        with self._lock:
            return [
                s for s in self._profiles.values()
                if s.get("psid")
            ]

    def get_selected(self) -> dict[str, Any] | None:
        """Return the currently selected profile, or the best available."""
        with self._lock:
            if self._selected_profile_id and self._selected_profile_id in self._profiles:
                return self._profiles[self._selected_profile_id]
            # Fallback: first profile with PSID
            for s in self._profiles.values():
                if s.get("psid"):
                    self._selected_profile_id = s["profile_id"]
                    return s
            return None

    def count(self) -> dict:
        """Return summary stats about stored profiles."""
        with self._lock:
            total = len(self._profiles)
            with_psid = sum(1 for s in self._profiles.values() if s.get("psid"))
            return {"total": total, "authenticated": with_psid}

    def get_all(self) -> dict[str, dict[str, Any]]:
        """Return all profiles (for status endpoint)."""
        with self._lock:
            return dict(self._profiles)

    def remove_stale(self, max_age_hours: int = 24) -> int:
        """Remove profiles older than max_age_hours."""
        with self._lock:
            now = datetime.now(timezone.utc)
            to_remove: list[str] = []
            for pid, s in self._profiles.items():
                updated = s.get("updated_at", "")
                if not updated:
                    to_remove.append(pid)
                    continue
                try:
                    dt = datetime.fromisoformat(updated)
                    if (now - dt).total_seconds() > max_age_hours * 3600:
                        to_remove.append(pid)
                except (ValueError, TypeError):
                    to_remove.append(pid)
            for pid in to_remove:
                del self._profiles[pid]
            # Fix selected if removed
            if self._selected_profile_id and self._selected_profile_id not in self._profiles:
                self._selected_profile_id = next(iter(self._profiles.keys()), None)
            return len(to_remove)

    @staticmethod
    def _parse_psid(cookie_header: str) -> tuple[str, str]:
        """Extract __Secure-1PSID and __Secure-1PSIDTS from cookie header."""
        if not cookie_header:
            return "", ""
        raw = cookie_header.strip()
        if raw.lower().startswith("cookie:"):
            raw = raw.split(":", 1)[1].strip()
        psid = ""
        psidts = ""
        for part in raw.split(";"):
            part = part.strip()
            if "=" not in part:
                continue
            name, val = part.split("=", 1)
            name = name.strip()
            val = val.strip()
            if name == "__Secure-1PSID":
                psid = val
            elif name == "__Secure-1PSIDTS":
                psidts = val
        return psid, psidts


# Global singleton
cookie_store = GeminiCookieStore()
