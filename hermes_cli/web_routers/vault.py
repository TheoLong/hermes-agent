"""Credential-vault dashboard routes: list, add and remove saved logins, cards and addresses.

The dashboard counterpart of the Desktop's Settings → Passwords & Logins panel
(``tui_gateway/methods_vault.py``), over the same model-blind store
(``agent/vault_store.py``) and the same backend registry (``agent/vault_backends``).

Contracts:

- Responses carry metadata only (``VaultItemMeta.to_dict``). No route ever returns a
  password, card number, CVC, address line or authenticator seed.
- ``POST /api/vault/items`` accepts the secret payload once and writes it straight into the
  encrypted store; error text is scrubbed of submitted values before it leaves the handler,
  and the request body is never logged.
- External password managers (1Password, Bitwarden) are status-only here. Their unlock token
  lives in the process that unlocked it, and the dashboard is not the gateway process, so an
  unlock from this page would not reach the agent's sessions.
- Every route is profile-scoped; removal is a destructive route and requires an explicit
  profile on a multi-profile host (``destructive_profile``).
"""

from __future__ import annotations

from typing import Any, Dict, Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from hermes_cli.web_routers._common import config_scoped_to_thread, destructive_profile

router = APIRouter()


class VaultItemCreate(BaseModel):
    kind: str
    label: str
    origin: Optional[str] = None
    secret: Dict[str, Any] = Field(default_factory=dict)

    def __repr__(self) -> str:  # never let a stray log line render the payload
        return f"VaultItemCreate(kind={self.kind!r}, label={self.label!r}, origin={self.origin!r})"

    __str__ = __repr__


def _list_items() -> dict:
    from agent.vault_backends import enabled_backends

    items = []
    for backend in enabled_backends():
        if backend.needs_unlock and not backend.is_unlocked():
            continue
        items.extend({**meta.to_dict(), "backend": backend.name} for meta in backend.list_items())
    return {"items": items}


def _sources() -> dict:
    from agent.vault_backends import enabled_backends
    from agent.vault_backends.base import external_backend_classes, is_installed

    enabled = {b.name: b for b in enabled_backends()}
    rows = [{"name": "local", "display_name": "Hermes vault", "enabled": True,
             "needs_unlock": False, "unlocked": True, "installed": True}]
    for cls in external_backend_classes():
        live = enabled.get(cls.name)
        rows.append({"name": cls.name, "display_name": cls.display_name, "enabled": live is not None,
                     "needs_unlock": True, "unlocked": bool(live and live.is_unlocked()),
                     "installed": is_installed(cls.name)})
    return {"sources": rows}


@router.get("/api/vault/items")
async def list_vault_items(profile: Optional[str] = None):
    """Metadata of every item the enabled, unlocked backends hold."""
    return await config_scoped_to_thread(profile, _list_items)


@router.get("/api/vault/sources")
async def list_vault_sources(profile: Optional[str] = None):
    """Local vault plus detected password managers: enabled / installed / unlocked."""
    return await config_scoped_to_thread(profile, _sources)


@router.post("/api/vault/items")
async def add_vault_item(body: VaultItemCreate, profile: Optional[str] = None):
    """Save a login, card or address into the local vault. Returns metadata only."""
    secret = dict(body.secret or {})
    if not secret:
        raise HTTPException(status_code=400, detail="secret payload is required")

    def _run() -> dict:
        from agent.vault_store import VaultError, get_vault_store, scrub_secret_from_text

        try:
            meta = get_vault_store().add_item(
                kind=(body.kind or "").strip(), label=body.label or "",
                origin=(body.origin or "").strip() or None, secret=secret,
            )
        except VaultError as exc:
            raise HTTPException(status_code=400, detail=scrub_secret_from_text(str(exc), secret)) from None
        except Exception as exc:
            # ``from None``: the traceback chain must not carry the payload into a log handler.
            raise HTTPException(
                status_code=500, detail=scrub_secret_from_text(f"could not save: {exc}", secret)) from None
        return {"item": {**meta.to_dict(), "backend": "local"}}

    try:
        return await config_scoped_to_thread(profile, _run)
    finally:
        secret.clear()


@router.delete("/api/vault/items/{item_id}")
async def remove_vault_item(item_id: str, profile: Optional[str] = None):
    """Delete a local vault item. Password-manager items are managed in their own app."""
    profile = destructive_profile(profile, "DELETE /api/vault/items/{id}")
    if not item_id.startswith("vault_"):
        raise HTTPException(status_code=400,
                            detail="Only Hermes vault items can be removed here; edit password-manager items in that app.")

    def _run() -> dict:
        from agent.vault_store import get_vault_store

        if not get_vault_store().remove_item(item_id):
            raise HTTPException(status_code=404, detail=f"No vault item {item_id}")
        return {"ok": True}

    return await config_scoped_to_thread(profile, _run)
