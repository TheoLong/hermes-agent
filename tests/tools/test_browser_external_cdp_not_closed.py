"""A CDP-attached browser is someone else's process — cleanup must not close it.

Regression for the externally-owned-Chrome kill: ``cleanup_browser`` sent the
agent-browser ``close`` command to sessions created by attaching to a user-supplied
CDP endpoint (``browser.cdp_url`` or a named ``browser.profiles`` entry). That command
tears down the remote browser, killing a long-lived Chrome that Hermes never launched
and that other sessions (and the user) are still using.

Hermes only owns a browser it spawned itself. Attached endpoints get their local
resources released, never a ``close``.
"""

import pytest

import tools.browser_tool as bt
import tools.browser_tool_lifecycle as lifecycle
import tools.browser_tool_session as session_mod


@pytest.fixture(autouse=True)
def _clean_session_registry():
    """Each test owns the session registry — leaked keys corrupt the next test."""
    saved = dict(bt._active_sessions)
    bt._active_sessions.clear()
    yield
    bt._active_sessions.clear()
    bt._active_sessions.update(saved)


def _track(task_id, session_info):
    bt._active_sessions[task_id] = session_info


def _install_spies(monkeypatch):
    """Record ``close`` commands and resource releases instead of performing them."""
    closed, released = [], []

    def _fake_run(task_id, command, args, timeout=None):
        if command == "close":
            closed.append(task_id)
        return ""

    monkeypatch.setattr(session_mod, "_run_browser_command", _fake_run)
    monkeypatch.setattr(lifecycle, "_release_session_resources",
                        lambda task_id, info: released.append(task_id))
    monkeypatch.setattr(lifecycle._cdp, "_stop_cdp_supervisor", lambda task_id: None)
    monkeypatch.setattr(bt, "_is_camofox_mode", lambda: False)
    monkeypatch.setattr(bt, "_maybe_stop_recording", lambda task_id: None)
    monkeypatch.setattr(bt, "_release_owned_tab", lambda key: None)
    return closed, released


def test_cdp_attached_session_is_not_closed(monkeypatch):
    """A global ``browser.cdp_url`` attach is an external browser — never close it."""
    closed, released = _install_spies(monkeypatch)
    _track("t1", {"session_name": "cdp_abc", "bb_session_id": None,
                  "cdp_url": "http://localhost:9224", "features": {"cdp_override": True}})

    lifecycle.cleanup_browser("t1")

    assert closed == [], "cleanup closed a browser Hermes did not launch"
    assert released == ["t1"], "cleanup must still release its own local resources"


def test_named_profile_session_is_not_closed(monkeypatch):
    """A ``::profile:<name>`` session attaches to that profile's long-lived Chrome."""
    closed, released = _install_spies(monkeypatch)
    key = f"t2{bt._PROFILE_PREFIX}theo"
    _track(key, {"session_name": "cdp_def", "bb_session_id": None,
                 "cdp_url": "http://localhost:9225", "features": {"cdp_override": True}})

    lifecycle.cleanup_browser(key)

    assert closed == [], "cleanup closed a named-profile browser Hermes did not launch"
    assert released == [key]


def test_hermes_launched_session_is_still_closed(monkeypatch):
    """Control: a browser Hermes spawned MUST still be closed, or we leak Chromium."""
    closed, released = _install_spies(monkeypatch)
    _track("t3", {"session_name": "local_xyz", "bb_session_id": None,
                  "cdp_url": None, "features": {"local": True}})

    lifecycle.cleanup_browser("t3")

    assert closed == ["t3"], "a Hermes-launched browser must still be closed"
    assert released == ["t3"]


def test_cleanup_all_spares_attached_but_closes_owned(monkeypatch):
    """Shutdown fans out over every session: attached spared, owned closed."""
    closed, released = _install_spies(monkeypatch)
    _track("attached", {"session_name": "cdp_1", "bb_session_id": None,
                        "cdp_url": "http://localhost:9224", "features": {"cdp_override": True}})
    _track("owned", {"session_name": "local_1", "bb_session_id": None,
                     "cdp_url": None, "features": {"local": True}})

    lifecycle.cleanup_all_browsers()

    assert closed == ["owned"]
    assert sorted(released) == ["attached", "owned"]
