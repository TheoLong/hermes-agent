"""LOCAL CARRY: browser_exec honors ``profile`` (``browser.profiles`` named browser identities).

Contract: a named profile binds the call to THAT profile's CDP endpoint, two profiles never share a
browser or a harness daemon, and an unknown name errors instead of falling back to the default.
"""
import subprocess

import pytest

import tools.browser_profiles as bp
import tools.browser_session_cdp as cdp_mod
import tools.browser_session_cloud as cloud_mod
from tools.browser_use_cli import _route_backend


@pytest.fixture
def two_profiles(monkeypatch):
    endpoints = {"default": "http://localhost:9111", "mine": "http://localhost:9222"}
    monkeypatch.setattr(bp, "get_browser_profiles", lambda: dict(endpoints))
    monkeypatch.setattr(cdp_mod, "resolve_cdp_override", lambda u: u)
    return endpoints


def _cdp(env):
    return env.get("BU_CDP_URL") or env.get("BU_CDP_WS")


class TestProfilesMap:
    def test_reads_and_filters_config(self, monkeypatch):
        section = {"profiles": {"good": " http://localhost:9225 ", "blank": "  ", "nullish": None,
                                "": "http://localhost:9999"}}
        monkeypatch.setattr(cloud_mod, "browser_section", lambda: section)
        assert bp.get_browser_profiles() == {"good": "http://localhost:9225"}

    def test_missing_or_malformed_is_empty(self, monkeypatch):
        monkeypatch.setattr(cloud_mod, "browser_section", lambda: {})
        assert bp.get_browser_profiles() == {}
        monkeypatch.setattr(cloud_mod, "browser_section", lambda: {"profiles": ["x"]})
        assert bp.get_browser_profiles() == {}


class TestResolution:
    def test_named_profile_resolves(self, two_profiles):
        assert bp.resolve_profile_cdp("mine") == "http://localhost:9222"

    def test_default_falls_back_to_legacy_endpoint(self, monkeypatch):
        monkeypatch.setattr(bp, "get_browser_profiles", lambda: {})
        monkeypatch.setattr(cdp_mod, "get_cdp_override", lambda: "ws://localhost:9224/x")
        assert bp.resolve_profile_cdp("default") == "ws://localhost:9224/x"

    def test_unknown_profile_raises(self, two_profiles, monkeypatch):
        monkeypatch.setattr(cdp_mod, "get_cdp_override", lambda: "ws://localhost:9224/x")
        with pytest.raises(ValueError) as ei:
            bp.resolve_profile_cdp("ghost")
        assert "ghost" in str(ei.value) and "mine" in str(ei.value)


def test_named_profile_routes_to_its_own_endpoint(two_profiles):
    env = {}
    assert _route_backend(env, "", "task-1", False, profile="mine") is None
    assert _cdp(env) == two_profiles["mine"]


def test_profiles_do_not_share_an_endpoint(two_profiles):
    env_a, env_b = {}, {}
    _route_backend(env_a, "", "task-1", False, profile="default")
    _route_backend(env_b, "", "task-1", False, profile="mine")
    assert _cdp(env_a) != _cdp(env_b)


def test_unknown_profile_errors_instead_of_falling_back(two_profiles):
    env = {}
    err = _route_backend(env, "", "task-1", False, profile="ghost")
    assert err and "ghost" in err
    assert _cdp(env) is None


def test_profile_namespaces_the_daemon_and_skips_sidecar(two_profiles, monkeypatch):
    """A daemon caches its start endpoint: reusing one name across profiles would drive the wrong browser.
    A private URL must not divert a profile call to the hybrid local sidecar either."""
    captured = {}

    def fake_run(cmd, code, env, timeout):
        captured[_cdp(env)] = env.get("BU_NAME")
        return subprocess.CompletedProcess(cmd, 0, "", "")

    monkeypatch.setattr("tools.browser_use_cli._find_cli", lambda: ["browser-use"])
    monkeypatch.setattr("tools.browser_use_cli._base_subprocess_env", dict)
    monkeypatch.setattr("tools.browser_use_cli._attach_vault_supervisor", lambda *a, **k: None)
    monkeypatch.setattr("tools.browser_use_cli._run_cli_killing_process_group", fake_run)

    from tools.browser_use_cli import browser_exec
    browser_exec(code="new_tab('http://localhost:8080')", session="work", profile="default")
    browser_exec(code="print(1)", session="work", profile="mine")

    assert set(captured) == {"http://localhost:9111", "http://localhost:9222"}
    names = list(captured.values())
    assert len(set(names)) == 2 and all("profile-" in n for n in names), captured


def test_invalid_profile_name_rejected():
    from tools.browser_use_cli import browser_exec
    out = browser_exec(code="print(1)", profile="../etc")
    assert "Invalid profile name" in out


def test_schema_exposes_profile():
    from tools.browser_use_cli import BROWSER_EXEC_SCHEMA
    assert "profile" in BROWSER_EXEC_SCHEMA["parameters"]["properties"]
