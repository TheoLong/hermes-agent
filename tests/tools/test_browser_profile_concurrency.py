"""Concurrency contracts for named browser profiles.

The isolation tests in ``test_browser_profiles.py`` cover *routing* (which endpoint a
profile session talks to). These cover what happens when sessions run at the SAME TIME,
which is the case the feature exists for: the agent operating its own browser identity
while the user's authenticated profile is also in use.

Two distinct guarantees, and they pull in opposite directions:

1. SAME profile  -> commands SERIALIZE. One Chrome, and agent-browser always drives that
   Chrome's *active tab*, so an interleaved activate-then-act from another session would
   land a click on the wrong page. The per-endpoint lock makes each activate+act atomic.
2. DIFFERENT profiles -> commands RUN IN PARALLEL. Separate Chromes share no active-tab
   state, so serializing them would be pure latency for no safety gain — and would make
   "use my profile for this while you keep working in yours" serial.

These assert observable ordering/overlap under real threads, not that a lock object
exists — a lock that is acquired but never actually held would pass the latter.
"""
import threading
import time

import pytest

import tools.browser_tool as browser_tool
import tools.browser_tool_session as _session_mod
import tools.browser_tool_cdp as _cdp_mod
import tools.browser_tool_cloud as _cloud_mod
import tools.browser_tool_install as _install_mod
import tools.browser_tool_lightpanda_fallback as _lp_mod


@pytest.fixture(autouse=True)
def _reset_state(monkeypatch):
    monkeypatch.setattr(browser_tool, "_active_sessions", {})
    monkeypatch.setattr(browser_tool, "_last_active_session_key", {})
    monkeypatch.setattr(browser_tool, "_endpoint_locks", {})
    monkeypatch.setattr(browser_tool, "_session_owned_tab", {})
    monkeypatch.setattr(browser_tool, "_session_endpoint", {})


class TestEndpointLockIsActuallyHeld:
    """The lock must be HELD across the command, not merely acquired and dropped."""

    def test_same_endpoint_serializes_activate_and_act(self, monkeypatch):
        """Two threads on the SAME profile never interleave activate/act pairs.

        The failure this prevents: thread B activates its tab between thread A's activate
        and A's command, so A's click lands on B's page.

        Calls ``_endpoint_lock_for`` INSIDE each thread (as the real command path does), so
        a regression that hands out a fresh lock per call is caught — grabbing one lock up
        front and sharing it would pass even then.
        """
        events = []
        events_guard = threading.Lock()

        def record(tag):
            with events_guard:
                events.append(tag)

        def critical_section(name):
            # Resolve the lock the way _run_browser_command does: by endpoint, per call.
            with browser_tool._endpoint_lock_for("http://same:9224"):
                record(f"{name}:activate")
                time.sleep(0.02)  # window an unsynchronized impl would interleave in
                record(f"{name}:act")

        threads = [threading.Thread(target=critical_section, args=(n,)) for n in ("A", "B")]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        # Each pair must be adjacent: never A:activate, B:activate, A:act.
        assert len(events) == 4
        first_owner = events[0].split(":")[0]
        assert events[1] == f"{first_owner}:act", f"interleaved: {events}"
        second_owner = events[2].split(":")[0]
        assert second_owner != first_owner
        assert events[3] == f"{second_owner}:act", f"interleaved: {events}"

    def test_same_endpoint_returns_the_identical_lock_object(self):
        """Per-call resolution must return the SAME lock for one endpoint.

        Guards the mechanism the serialization test depends on: a fresh lock per call
        serializes nothing, but every individual command still succeeds.
        """
        first = browser_tool._endpoint_lock_for("http://same:9224")
        second = browser_tool._endpoint_lock_for("http://same:9224")
        assert first is second

        # And it must be genuinely exclusive, not a re-entrant/no-op stand-in.
        acquired_while_held = None

        def try_acquire():
            nonlocal acquired_while_held
            acquired_while_held = browser_tool._endpoint_lock_for(
                "http://same:9224"
            ).acquire(timeout=0.2)

        with first:
            t = threading.Thread(target=try_acquire)
            t.start()
            t.join()
        assert acquired_while_held is False, "second acquire succeeded while lock was held"

    def test_distinct_endpoints_overlap_in_time(self):
        """Two profiles must make progress CONCURRENTLY, not one-after-the-other.

        Asserts real overlap: both threads are inside their critical section at once.
        A shared (over-broad) lock would make this deadlock-free but strictly serial,
        which is the regression this catches.
        """
        inside = threading.Barrier(2, timeout=5)
        lock_a = browser_tool._endpoint_lock_for("http://alice:9225")
        lock_b = browser_tool._endpoint_lock_for("http://bob:9226")
        assert lock_a is not lock_b

        overlapped = []

        def worker(lock):
            with lock:
                try:
                    inside.wait()  # only returns if BOTH threads are inside at once
                    overlapped.append(True)
                except threading.BrokenBarrierError:  # pragma: no cover - failure path
                    overlapped.append(False)

        threads = [threading.Thread(target=worker, args=(lk,)) for lk in (lock_a, lock_b)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert overlapped == [True, True], "distinct profiles did not run concurrently"


class TestOwnedTabIsolationUnderConcurrency:
    """Each concurrent session keeps its OWN tab on a shared endpoint."""

    def test_two_sessions_same_endpoint_get_distinct_tabs(self, monkeypatch):
        """Same profile, two tasks: distinct owned tabs, so neither steals the other's page."""
        handed_out = iter([{"success": True, "data": {"tabId": f"t{i}"}} for i in range(1, 10)])
        calls_guard = threading.Lock()

        def fake_raw(session_name, cdp_url, argv, timeout=15):
            with calls_guard:
                return next(handed_out)

        monkeypatch.setattr(_session_mod, "_run_raw_agent_browser", fake_raw)

        refs = {}

        def acquire(session_key):
            refs[session_key] = browser_tool._ensure_owned_tab(
                session_key, f"sess-{session_key}", "http://same:9224"
            )

        threads = [
            threading.Thread(target=acquire, args=(k,))
            for k in ("task1::profile:work", "task2::profile:work")
        ]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert len(refs) == 2
        assert None not in refs.values()
        # Distinct tabs: the whole point — two tasks on one Chrome must not share a tab.
        assert len(set(refs.values())) == 2

    def test_cached_tab_is_stable_across_concurrent_calls(self, monkeypatch):
        """Repeat calls for ONE session reuse its tab instead of opening a new one each time."""
        opened = []
        guard = threading.Lock()

        def fake_raw(session_name, cdp_url, argv, timeout=15):
            with guard:
                opened.append(argv)
                return {"success": True, "data": {"tabId": f"t{len(opened)}"}}

        monkeypatch.setattr(_session_mod, "_run_raw_agent_browser", fake_raw)

        results = []

        def acquire():
            results.append(
                browser_tool._ensure_owned_tab("task::profile:work", "sess", "http://x:9224")
            )

        threads = [threading.Thread(target=acquire) for _ in range(4)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        tab_new_calls = [c for c in opened if c[:2] == ["tab", "new"]]
        # Without the cache this would be 4 tabs for one session, leaking a tab per command.
        assert len(tab_new_calls) <= 2, f"opened too many tabs: {tab_new_calls}"
        assert len(set(results)) == 1, f"session saw inconsistent tab refs: {results}"


class TestProfileIsolationInvariants:
    """Cookie-jar isolation must not be reachable by accident."""

    def test_distinct_profiles_never_share_a_session_key(self):
        keys = {
            browser_tool._compose_profile_session_key("task", name)
            for name in ("tem", "theo", "default")
        }
        assert len(keys) == 3

    def test_profile_key_survives_bare_task_extraction(self):
        """The bare task id is recoverable, but the profile never leaks between tasks."""
        key = browser_tool._compose_profile_session_key("task-7", "theo")
        assert browser_tool._bare_task_id_for_session_key(key) == "task-7"
        assert browser_tool._profile_from_session_key(key) == "theo"

    def test_unknown_profile_never_resolves_to_another_profiles_endpoint(self, monkeypatch):
        """A typo'd profile must ERROR, never silently land on the default browser.

        This is the security-relevant contract: silently falling back would run the agent
        against the user's authenticated identity when it asked for its own.
        """
        monkeypatch.setattr(
            browser_tool, "_get_browser_profiles",
            lambda: {"tem": "http://localhost:9224", "theo": "http://localhost:9225"},
        )
        monkeypatch.setattr(_cdp_mod, "_get_cdp_override", lambda: "ws://localhost:9224/x")

        with pytest.raises(ValueError) as ei:
            browser_tool._resolve_profile_cdp("theoo")  # typo of "theo"
        assert "theoo" in str(ei.value)
        # And it must not have quietly handed back an endpoint.
        assert "9224" not in str(ei.value).replace("theoo", "")
