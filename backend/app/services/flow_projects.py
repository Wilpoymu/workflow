"""Per-account Flow project ids for the batchexecute transport.

The new Flow (flow.google.com, September 2026) scopes generated media to a
project, and the project has to be created through a signed RPC from inside the
browser. That means every extension account owns its own Flow project id, so
this module keeps a tiny JSON store keyed by account hash.

The functions here are deliberately pure and path-driven: no bridge imports, no
network, no global state, so they are directly unit-testable.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

#: backend/flow_projects.json — resolved from this file, not the working dir,
#: so the server and tests agree on the location.
DEFAULT_STORE_PATH = Path(__file__).resolve().parents[2] / "flow_projects.json"


def load_store(path: str | Path) -> dict[str, str]:
    """Read the account_hash -> flow_project_id store; missing/corrupt reads empty."""
    try:
        with open(path, encoding="utf-8") as f:
            data: Any = json.load(f)
    except FileNotFoundError:
        return {}
    except (OSError, json.JSONDecodeError) as e:
        logger.warning("[FLOW-PROJECTS] Could not read store %s: %s", path, e)
        return {}
    if not isinstance(data, dict):
        logger.warning("[FLOW-PROJECTS] Store %s is not a JSON object, ignoring", path)
        return {}
    return {str(k): str(v) for k, v in data.items() if isinstance(v, str) and v}


def save_store(path: str | Path, data: dict[str, str]) -> None:
    """Persist the store atomically (write temp + replace)."""
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    tmp = target.with_name(target.name + ".tmp")
    tmp.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    tmp.replace(target)


def resolve_project_id(
    account_hash: str,
    *,
    settings_project_id: str,
    store: dict[str, str],
) -> str | None:
    """Resolve one account's Flow project id.

    Precedence: explicit settings override (wins for every account) -> stored
    id for this account -> None (caller must provision).
    """
    if settings_project_id and settings_project_id.strip():
        return settings_project_id.strip()
    stored = store.get(account_hash)
    return stored or None


def remember_project_id(account_hash: str, project_id: str, path: str | Path) -> None:
    """Persist a freshly created project id for an account."""
    store = load_store(path)
    store[account_hash] = project_id
    save_store(path, store)
    logger.info("[FLOW-PROJECTS] Stored project %s for account %s", project_id, account_hash[:12])
