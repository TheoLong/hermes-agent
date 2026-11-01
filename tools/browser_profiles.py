"""LOCAL CARRY: named browser profiles (``browser.profiles`` in config.yaml).

Each entry maps a name to its own CDP endpoint, so one Hermes can drive several browser identities
(e.g. the agent's Chrome and the user's logged-in Chrome) without crossing an account boundary.
``browser_exec(profile=<name>)`` binds that call to the named endpoint.
"""
from __future__ import annotations

import logging

logger = logging.getLogger(__name__)

DEFAULT_PROFILE = "default"


def get_browser_profiles() -> dict[str, str]:
    """The configured ``browser.profiles`` map (name -> CDP endpoint), read fresh each call so a
    config edit applies on the next browser call. Empty when unset or malformed."""
    try:
        from tools.browser_session_cloud import browser_cfg

        profiles = browser_cfg("profiles", {}, lambda v: v if isinstance(v, dict) else {})
    except Exception as exc:  # health: allow BLE001 -- unreadable config means no profiles
        logger.debug("Could not read browser.profiles from config: %s", exc)
        return {}
    return {str(k): v.strip() for k, v in (profiles or {}).items() if k and isinstance(v, str) and v.strip()}


def resolve_profile_cdp(profile: str) -> str:
    """Resolve a named profile to a concrete CDP URL.

    ``browser.profiles[profile]`` wins; the implicit ``default`` profile falls back to the legacy single
    endpoint (live override / ``BROWSER_CDP_URL`` / ``browser.cdp_url``). An unknown non-default name raises
    ``ValueError`` and never falls back to the default endpoint: silently crossing an account boundary is
    exactly what profiles exist to prevent."""
    from tools.browser_session_cdp import get_cdp_override, resolve_cdp_override

    profiles = get_browser_profiles()
    raw = profiles.get(profile, "")
    if raw:
        return resolve_cdp_override(raw)
    if profile == DEFAULT_PROFILE:
        return get_cdp_override() or ""
    known = ", ".join(sorted(profiles)) or "(none configured)"
    raise ValueError(f"Unknown browser profile {profile!r}. Configured profiles: {known}. "
                     "Add it under browser.profiles in config.yaml.")
