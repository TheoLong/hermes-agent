"""browser_exec honors the ``profile`` argument (``browser.profiles`` named identities).

Regression cover for the gap where ``browser_navigate(profile=...)`` could target a named
browser but ``browser_exec`` could not, so agent code had no supported way to drive the
user's own logged-in browser.
"""
import pytest

from tools.browser_use_cli import _route_backend


@pytest.fixture
def two_profiles(monkeypatch):
    """Config with two distinct named CDP endpoints."""
    endpoints = {"default": "http://localhost:9111", "mine": "http://localhost:9222"}
    monkeypatch.setattr("tools.browser_tool._get_browser_profiles", lambda: dict(endpoints))
    return endpoints


def _cdp(env):
    return env.get("BU_CDP_URL") or env.get("BU_CDP_WS")


def test_named_profile_routes_to_its_own_endpoint(two_profiles):
    """A named profile binds the harness to THAT profile's endpoint, not the default."""
    env = {}
    assert _route_backend(env, "", "task-1", False, "mine") is None
    assert _cdp(env) == two_profiles["mine"]


def test_profiles_do_not_share_an_endpoint(two_profiles):
    """Two different profile names must resolve to two different browsers.

    The account-boundary contract: driving profile A must never reach profile B's browser.
    """
    env_a, env_b = {}, {}
    _route_backend(env_a, "", "task-1", False, "default")
    _route_backend(env_b, "", "task-1", False, "mine")
    assert _cdp(env_a) != _cdp(env_b)


def test_unknown_profile_errors_instead_of_falling_back(two_profiles):
    """An unknown name is an error; silently using the default would cross accounts."""
    env = {}
    err = _route_backend(env, "", "task-1", False, "ghost")
    assert err and "ghost" in err
    assert _cdp(env) is None


def test_profile_namespaces_the_daemon_name(two_profiles, monkeypatch):
    """Two profiles must not share a harness daemon.

    A daemon caches the endpoint it started with, so reusing one name across profiles would
    drive the previously-started profile's browser regardless of the requested endpoint.
    """
    captured = {}

    def fake_run(cmd, code, env, timeout):
        captured[env.get("BU_CDP_URL") or env.get("BU_CDP_WS")] = env.get("BU_NAME")
        import subprocess
        return subprocess.CompletedProcess(cmd, 0, "", "")

    monkeypatch.setattr("tools.browser_use_cli._find_cli", lambda: ["browser-use"])
    monkeypatch.setattr("tools.browser_use_cli._base_subprocess_env", dict)
    monkeypatch.setattr("tools.browser_use_cli._attach_vault_supervisor", lambda *a, **k: None)
    monkeypatch.setattr("tools.browser_use_cli._run_cli_killing_process_group", fake_run)

    from tools.browser_use_cli import browser_exec
    browser_exec(code="print(1)", session="work", profile="default")
    browser_exec(code="print(1)", session="work", profile="mine")

    names = list(captured.values())
    assert len(set(names)) == len(names) == 2, f"daemon name reused across profiles: {captured}"
