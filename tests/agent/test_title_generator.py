"""Tests for agent.title_generator — auto-generated session titles."""

from unittest.mock import MagicMock, patch


from agent.title_generator import (
    generate_title,
    regenerate_title,
    _condense_history,
    auto_title_session,
    maybe_auto_title,
    maybe_retitle_session,
    _title_language,
)


class TestGenerateTitle:
    """Unit tests for generate_title()."""

    def test_returns_title_on_success(self):
        mock_response = MagicMock()
        mock_response.choices = [MagicMock()]
        mock_response.choices[0].message.content = "Debugging Python Import Errors"

        with patch("agent.title_generator.call_llm", return_value=mock_response):
            title = generate_title("help me fix this import", "Sure, let me check...")
            assert title == "Debugging Python Import Errors"

    def test_default_prompt_matches_user_language(self):
        mock_response = MagicMock()
        mock_response.choices = [MagicMock()]
        mock_response.choices[0].message.content = "Some Title"

        with patch("agent.title_generator.call_llm", return_value=mock_response) as llm:
            generate_title("質問です", "回答です")

        system_prompt = llm.call_args.kwargs["messages"][0]["content"]
        assert "same language the user is writing in" in system_prompt

    def test_configured_language_pins_prompt(self):
        mock_response = MagicMock()
        mock_response.choices = [MagicMock()]
        mock_response.choices[0].message.content = "Some Title"

        with (
            patch("agent.title_generator.call_llm", return_value=mock_response) as llm,
            patch("agent.title_generator._title_language", return_value="Japanese"),
        ):
            generate_title("hello", "hi")

        system_prompt = llm.call_args.kwargs["messages"][0]["content"]
        assert "Write the title in Japanese" in system_prompt
        assert "same language the user" not in system_prompt

    def test_title_language_reads_config(self):
        cfg = {"auxiliary": {"title_generation": {"language": "  French "}}}

        with patch("hermes_cli.config.load_config", return_value=cfg):
            assert _title_language() == "French"
        with patch("hermes_cli.config.load_config", return_value={}):
            assert _title_language() == ""
        with patch("hermes_cli.config.load_config", side_effect=RuntimeError("bad config")):
            assert _title_language() == ""

    def test_strips_quotes(self):
        mock_response = MagicMock()
        mock_response.choices = [MagicMock()]
        mock_response.choices[0].message.content = '"Setting Up Docker Environment"'

        with patch("agent.title_generator.call_llm", return_value=mock_response):
            title = generate_title("how do I set up docker", "First install...")
            assert title == "Setting Up Docker Environment"

    def test_strips_title_prefix(self):
        mock_response = MagicMock()
        mock_response.choices = [MagicMock()]
        mock_response.choices[0].message.content = "Title: Kubernetes Pod Debugging"

        with patch("agent.title_generator.call_llm", return_value=mock_response):
            title = generate_title("my pod keeps crashing", "Let me look...")
            assert title == "Kubernetes Pod Debugging"

    def test_truncates_long_titles(self):
        mock_response = MagicMock()
        mock_response.choices = [MagicMock()]
        mock_response.choices[0].message.content = "A" * 100

        with patch("agent.title_generator.call_llm", return_value=mock_response):
            title = generate_title("question", "answer")
            assert len(title) == 80
            assert title.endswith("...")

    def test_returns_none_on_empty_response(self):
        mock_response = MagicMock()
        mock_response.choices = [MagicMock()]
        mock_response.choices[0].message.content = ""

        with patch("agent.title_generator.call_llm", return_value=mock_response):
            assert generate_title("question", "answer") is None

    def test_returns_none_on_exception(self):
        with patch("agent.title_generator.call_llm", side_effect=RuntimeError("no provider")):
            assert generate_title("question", "answer") is None

    def test_invokes_failure_callback_on_exception(self):
        """failure_callback must fire so the user sees a warning (issue #15775)."""
        captured = []

        def _cb(task, exc):
            captured.append((task, exc))

        exc = RuntimeError("openrouter 402: credits exhausted")
        with patch("agent.title_generator.call_llm", side_effect=exc):
            result = generate_title("question", "answer", failure_callback=_cb)

        assert result is None
        assert len(captured) == 1
        assert captured[0][0] == "title generation"
        assert captured[0][1] is exc

    def test_failure_callback_errors_are_swallowed(self):
        """A broken callback must not crash title generation."""

        def _bad_cb(task, exc):
            raise ValueError("callback bug")

        with patch("agent.title_generator.call_llm", side_effect=RuntimeError("nope")):
            # Should return None without re-raising the callback error
            assert generate_title("q", "a", failure_callback=_bad_cb) is None

    def test_no_callback_matches_legacy_behavior(self):
        """Omitting failure_callback preserves the silent-None return."""
        with patch("agent.title_generator.call_llm", side_effect=RuntimeError("nope")):
            assert generate_title("q", "a") is None

    def test_truncates_long_messages(self):
        """Long user/assistant messages should be truncated in the LLM request."""
        captured_kwargs = {}

        def mock_call_llm(**kwargs):
            captured_kwargs.update(kwargs)
            resp = MagicMock()
            resp.choices = [MagicMock()]
            resp.choices[0].message.content = "Short Title"
            return resp

        with patch("agent.title_generator.call_llm", side_effect=mock_call_llm):
            generate_title("x" * 1000, "y" * 1000)

        # The user content in the messages should be truncated
        user_content = captured_kwargs["messages"][1]["content"]
        assert len(user_content) < 1100  # 500 + 500 + formatting


class TestAutoTitleSession:
    """Tests for auto_title_session() — the sync worker function."""

    def test_skips_if_no_session_db(self):
        auto_title_session(None, "sess-1", "hi", "hello")  # should not crash

    def test_skips_if_title_exists(self):
        db = MagicMock()
        db.get_session_title.return_value = "Existing Title"

        with patch("agent.title_generator.generate_title") as gen:
            auto_title_session(db, "sess-1", "hi", "hello")
            gen.assert_not_called()

    def test_generates_and_sets_title(self):
        db = MagicMock()
        db.get_session_title.return_value = None

        with patch("agent.title_generator.generate_title", return_value="New Title"):
            auto_title_session(db, "sess-1", "hi", "hello")
            db.set_session_title.assert_called_once_with("sess-1", "New Title")

    def test_invokes_title_callback_after_setting_title(self):
        db = MagicMock()
        db.get_session_title.return_value = None
        seen = []
        with patch("agent.title_generator.generate_title", return_value="Readable Session"):
            auto_title_session(
                db,
                "sess-1",
                "hello",
                "hi there",
                title_callback=seen.append,
            )
        db.set_session_title.assert_called_once_with("sess-1", "Readable Session")
        assert seen == ["Readable Session"]

    def test_skips_if_generation_fails(self):
        db = MagicMock()
        db.get_session_title.return_value = None

        with patch("agent.title_generator.generate_title", return_value=None):
            auto_title_session(db, "sess-1", "hi", "hello")
            db.set_session_title.assert_not_called()


class TestMaybeAutoTitle:
    """Tests for maybe_auto_title() — the fire-and-forget entry point."""

    def test_skips_if_not_first_exchange(self):
        """Should not fire for conversations with more than 2 user messages."""
        db = MagicMock()
        history = [
            {"role": "user", "content": "first"},
            {"role": "assistant", "content": "response 1"},
            {"role": "user", "content": "second"},
            {"role": "assistant", "content": "response 2"},
            {"role": "user", "content": "third"},
            {"role": "assistant", "content": "response 3"},
        ]

        with patch("agent.title_generator.auto_title_session") as mock_auto:
            maybe_auto_title(db, "sess-1", "third", "response 3", history)
            # Wait briefly for any thread to start
            import time
            time.sleep(0.1)
            mock_auto.assert_not_called()

    def test_fires_on_first_exchange(self):
        """Should fire a background thread for the first exchange."""
        db = MagicMock()
        db.get_session_title.return_value = None
        history = [
            {"role": "user", "content": "hello"},
            {"role": "assistant", "content": "hi there"},
        ]

        with patch("agent.title_generator.auto_title_session") as mock_auto:
            maybe_auto_title(db, "sess-1", "hello", "hi there", history)
            # Wait for the daemon thread to complete
            import time
            time.sleep(0.3)
            mock_auto.assert_called_once_with(
                db,
                "sess-1",
                "hello",
                "hi there",
                failure_callback=None,
                main_runtime=None,
                title_callback=None,
            )

    def test_forwards_failure_callback_to_worker(self):
        """maybe_auto_title must forward failure_callback into the thread."""
        db = MagicMock()
        db.get_session_title.return_value = None
        history = [
            {"role": "user", "content": "hello"},
            {"role": "assistant", "content": "hi there"},
        ]

        def _cb(task, exc):
            pass

        with patch("agent.title_generator.auto_title_session") as mock_auto:
            maybe_auto_title(db, "sess-1", "hello", "hi there", history, failure_callback=_cb)
            import time
            time.sleep(0.3)
            mock_auto.assert_called_once_with(
                db,
                "sess-1",
                "hello",
                "hi there",
                failure_callback=_cb,
                main_runtime=None,
                title_callback=None,
            )

    def test_skips_if_no_response(self):
        db = MagicMock()
        maybe_auto_title(db, "sess-1", "hello", "", [])  # empty response

    def test_skips_if_no_session_db(self):
        maybe_auto_title(None, "sess-1", "hello", "response", [])  # no db


class TestCondenseHistory:
    """Tests for _condense_history() — the whole-conversation renderer."""

    def test_empty_history_returns_empty(self):
        assert _condense_history([]) == ""
        assert _condense_history(None) == ""

    def test_skips_system_and_tool_roles(self):
        history = [
            {"role": "system", "content": "you are an agent"},
            {"role": "user", "content": "hello"},
            {"role": "tool", "content": "tool output"},
            {"role": "assistant", "content": "hi there"},
        ]
        out = _condense_history(history)
        assert "you are an agent" not in out
        assert "tool output" not in out
        assert "User: hello" in out
        assert "Assistant: hi there" in out

    def test_short_history_not_elided(self):
        history = [
            {"role": "user", "content": "q1"},
            {"role": "assistant", "content": "a1"},
            {"role": "user", "content": "q2"},
            {"role": "assistant", "content": "a2"},
        ]
        out = _condense_history(history)
        assert "omitted" not in out
        assert out.count("User:") == 2

    def test_long_history_keeps_head_and_tail_with_elision(self):
        # 10 exchanges = 20 messages; head_turns=1 (2 msgs) + tail_turns=3 (6 msgs)
        history = []
        for i in range(10):
            history.append({"role": "user", "content": f"question {i}"})
            history.append({"role": "assistant", "content": f"answer {i}"})
        out = _condense_history(history)
        # Opening turn preserved (anchors intent)
        assert "question 0" in out
        assert "answer 0" in out
        # Latest turns preserved (detect drift)
        assert "question 9" in out
        assert "answer 9" in out
        # A middle turn is gone
        assert "question 5" not in out
        # Elision marker present
        assert "omitted" in out

    def test_truncates_long_messages(self):
        history = [
            {"role": "user", "content": "x" * 1000},
            {"role": "assistant", "content": "y" * 1000},
        ]
        out = _condense_history(history)
        # each message truncated to per_message (400) + ellipsis, not full 1000
        assert "x" * 401 not in out
        assert "…" in out


class TestRegenerateTitle:
    """Tests for regenerate_title() — whole-conversation, sticky re-assessment."""

    def _resp(self, text):
        r = MagicMock()
        r.choices = [MagicMock()]
        r.choices[0].message.content = text
        return r

    def test_returns_none_on_empty_history(self):
        # No LLM call should happen when there's no transcript.
        with patch("agent.title_generator.call_llm") as llm:
            assert regenerate_title([], "Some Title") is None
            llm.assert_not_called()

    def test_keeps_current_title_when_unchanged(self):
        history = [
            {"role": "user", "content": "help me draft the USCIS RFE response"},
            {"role": "assistant", "content": "Here's the outline..."},
            {"role": "user", "content": "now write the PDF"},
            {"role": "assistant", "content": "Generating the PDF..."},
        ]
        # Model, seeing the whole conversation, returns the existing title verbatim.
        with patch("agent.title_generator.call_llm", return_value=self._resp("USCIS RFE Response")):
            out = regenerate_title(history, "USCIS RFE Response")
            assert out == "USCIS RFE Response"

    def test_whole_conversation_passed_to_model_not_just_last_exchange(self):
        """The USCIS-RFE bug: a localized 'write the PDF' detour must not be the
        only thing the model sees. The opening intent must reach the prompt."""
        history = [
            {"role": "user", "content": "help me draft the USCIS RFE response gist"},
            {"role": "assistant", "content": "Here's the outline of the RFE response..."},
            {"role": "user", "content": "looks good, keep going"},
            {"role": "assistant", "content": "Continuing the RFE draft..."},
            {"role": "user", "content": "now produce the PDF of it"},
            {"role": "assistant", "content": "Rendering the PDF now..."},
        ]
        captured = {}

        def _cap(**kwargs):
            captured.update(kwargs)
            return self._resp("USCIS RFE Response")

        with patch("agent.title_generator.call_llm", side_effect=_cap):
            regenerate_title(history, "USCIS RFE Response")

        user_block = captured["messages"][1]["content"]
        system_block = captured["messages"][0]["content"]
        # Current title is handed to the model
        assert "USCIS RFE Response" in user_block
        # Opening intent (the real gist) is present, not just the PDF detour
        assert "RFE response gist" in user_block
        # The PDF detour is present too (tail), but as context, not the sole input
        assert "PDF" in user_block
        # Prompt instructs whole-conversation, keep-biased assessment
        assert "WHOLE" in system_block
        assert "UNCHANGED" in system_block

    def test_returns_new_title_on_genuine_drift(self):
        history = [
            {"role": "user", "content": "help me draft the USCIS RFE response"},
            {"role": "assistant", "content": "Here's the outline..."},
            {"role": "user", "content": "actually forget that, let's debug my docker setup"},
            {"role": "assistant", "content": "Let's look at your Dockerfile..."},
            {"role": "user", "content": "the container won't start"},
            {"role": "assistant", "content": "Check the entrypoint..."},
        ]
        with patch("agent.title_generator.call_llm", return_value=self._resp("Debugging Docker Setup")):
            out = regenerate_title(history, "USCIS RFE Response")
            assert out == "Debugging Docker Setup"

    def test_pinned_language_prompt(self):
        history = [
            {"role": "user", "content": "hola"},
            {"role": "assistant", "content": "hola, como estas"},
        ]
        captured = {}

        def _cap(**kwargs):
            captured.update(kwargs)
            return self._resp("Saludo")

        with (
            patch("agent.title_generator.call_llm", side_effect=_cap),
            patch("agent.title_generator._title_language", return_value="Spanish"),
        ):
            regenerate_title(history, "Greeting")

        system_block = captured["messages"][0]["content"]
        assert "Write the title in Spanish" in system_block

    def test_returns_none_on_exception(self):
        history = [{"role": "user", "content": "q"}, {"role": "assistant", "content": "a"}]
        with patch("agent.title_generator.call_llm", side_effect=RuntimeError("no provider")):
            assert regenerate_title(history, "Title") is None

    def test_invokes_failure_callback_on_exception(self):
        history = [{"role": "user", "content": "q"}, {"role": "assistant", "content": "a"}]
        captured = []
        exc = RuntimeError("boom")
        with patch("agent.title_generator.call_llm", side_effect=exc):
            regenerate_title(history, "Title", failure_callback=lambda t, e: captured.append((t, e)))
        assert captured == [("title regeneration", exc)]


class TestMaybeRetitleSession:
    """Tests for maybe_retitle_session() — the periodic re-title gate."""

    def _history(self, n_user):
        h = []
        for i in range(n_user):
            h.append({"role": "user", "content": f"q{i}"})
            h.append({"role": "assistant", "content": f"a{i}"})
        return h

    def test_skips_before_third_user_turn(self):
        db = MagicMock()
        with patch("agent.title_generator.regenerate_title") as regen:
            maybe_retitle_session(db, "s1", "q", "a", self._history(2), every_n_turns=6)
            import time
            time.sleep(0.1)
            regen.assert_not_called()

    def test_skips_off_cadence(self):
        db = MagicMock()
        # 4 user turns, every_n_turns=6 -> 4 % 6 != 0 -> skip
        with patch("agent.title_generator.regenerate_title") as regen:
            maybe_retitle_session(db, "s1", "q", "a", self._history(4), every_n_turns=6)
            import time
            time.sleep(0.1)
            regen.assert_not_called()

    def test_fires_on_cadence_and_uses_regenerate_title(self):
        db = MagicMock()
        db.get_session_title.return_value = "Old Title"
        history = self._history(6)  # 6 % 6 == 0 -> fire
        with patch("agent.title_generator.regenerate_title", return_value="New Title") as regen:
            maybe_retitle_session(db, "s1", "q", "a", history, every_n_turns=6)
            import time
            time.sleep(0.3)
            regen.assert_called_once()
            # regenerate_title must receive the full history + current title,
            # NOT just the last user/assistant message.
            args, kwargs = regen.call_args
            assert args[0] == history
            assert args[1] == "Old Title"
        db.set_session_title.assert_called_once_with("s1", "New Title")

    def test_no_db_write_when_title_unchanged(self):
        db = MagicMock()
        db.get_session_title.return_value = "Same Title"
        history = self._history(6)
        with patch("agent.title_generator.regenerate_title", return_value="Same Title"):
            maybe_retitle_session(db, "s1", "q", "a", history, every_n_turns=6)
            import time
            time.sleep(0.3)
        db.set_session_title.assert_not_called()

    def test_callback_fires_on_change(self):
        db = MagicMock()
        db.get_session_title.return_value = "Old"
        history = self._history(6)
        seen = []
        with patch("agent.title_generator.regenerate_title", return_value="Brand New"):
            maybe_retitle_session(
                db, "s1", "q", "a", history, every_n_turns=6, title_callback=seen.append
            )
            import time
            time.sleep(0.3)
        assert seen == ["Brand New"]
