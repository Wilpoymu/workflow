"""API endpoints for the Gemini Web cookie bridge.

Receives cookies from the Chrome extension and exposes status
about connected profiles for the UI.
"""

from datetime import datetime, timezone

from fastapi import APIRouter
from pydantic import BaseModel

from app.services.gemini_cookie_store import cookie_store

router = APIRouter(prefix="/api/bridge/gemini", tags=["gemini-bridge"])


class PushCookiesRequest(BaseModel):
    profile_id: str = ""
    profile_label: str = ""
    cookie_header: str = ""
    has_active_tab: bool = False
    fingerprint: str = ""


class PushCookiesResponse(BaseModel):
    ok: bool
    profile_id: str = ""
    profile_label: str = ""
    has_psid: bool = False
    sessions_count: int = 0
    cookie_changed: bool = False
    message: str = ""


@router.post("/cookies")
async def push_cookies(body: PushCookiesRequest) -> PushCookiesResponse:
    """Receive Gemini Web cookies from the Chrome extension.

    The extension extracts __Secure-1PSID and __Secure-1PSIDTS cookies
    from gemini.google.com and pushes them here.
    """
    if not body.cookie_header:
        return PushCookiesResponse(
            ok=False,
            message="Empty cookie header",
        )

    session = cookie_store.upsert(body.dict())

    # Determine if PSID changed vs previous
    cookie_changed = session.get("fingerprint", "") != body.fingerprint if body.fingerprint else True

    return PushCookiesResponse(
        ok=True,
        profile_id=session.get("profile_id", ""),
        profile_label=session.get("profile_label", ""),
        has_psid=session.get("has_psid", False),
        sessions_count=len(cookie_store.get_all()),
        cookie_changed=cookie_changed,
        message="Cookies stored",
    )


@router.get("/status")
async def bridge_status() -> dict:
    """Return status of all stored Gemini Web profiles."""
    profiles = cookie_store.get_all()
    authenticated = cookie_store.get_authenticated()
    selected = cookie_store.get_selected()

    profiles_list = []
    for pid, s in profiles.items():
        profiles_list.append({
            "profile_id": pid,
            "profile_label": s.get("profile_label", pid),
            "has_psid": s.get("has_psid", False),
            "has_active_tab": s.get("has_active_tab", False),
            "updated_at": s.get("updated_at", ""),
            "auth_status": s.get("auth_status", "unknown"),
        })

    return {
        "ok": True,
        "total_profiles": len(profiles),
        "authenticated": len(authenticated),
        "profiles": profiles_list,
        "selected": {
            "profile_id": selected.get("profile_id") if selected else None,
            "profile_label": selected.get("profile_label") if selected else None,
        } if selected else None,
    }


@router.post("/cleanup")
async def cleanup_stale_sessions(max_age_hours: int = 24) -> dict:
    """Remove stale sessions older than max_age_hours."""
    removed = cookie_store.remove_stale(max_age_hours=max_age_hours)
    return {
        "ok": True,
        "removed": removed,
        "remaining": len(cookie_store.get_all()),
    }
