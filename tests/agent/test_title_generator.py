"""Tests for agent.title_generator — auto-generated session titles."""

import pytest
from unittest.mock import MagicMock, patch


from agent.title_generator import (
    MAX_TITLE_INPUT_CHARS,
    _EXAMPLE_ECHO_REJECT,
    build_title_input,
    derive_title,
    generate_title,
    regenerate_title,
    _condense_history,
    auto_title_session,
    is_titleable_user_message,
    maybe_auto_title,
    wait_for_title_upgrades,
    maybe_retitle_session,
    _title_language,
)
from hermes_state import SessionDB


class TestGenerateTitle:
    """Unit tests for generate_title()."""

    @pytest.mark.parametrize(
        ("instruction", "paste_preview", "expected_parts"),
        [
            ("@file:/tmp/composer-pastes/pasted_content_1.txt", "Quarterly incident analysis for the database migration",
             ["Quarterly incident analysis"]),
            ("Analyze this", "Quarterly incident analysis for the database migration", ["Analyze this", "Quarterly incident analysis"]),
            ("Prepare the deployment follow-up", "Quarterly incident analysis", ["Prepare the deployment follow-up", "Quarterly incident analysis"]),
        ],
    )
    def test_generated_paste_preview_reaches_the_shared_title_input(self, instruction, paste_preview, expected_parts):
        """A Desktop large paste stays an @file attachment for the turn, but its preview informs BOTH title
        paths (derive_title instant + generate_title model input) through the one shared input."""
        title_input = build_title_input(instruction, paste_preview)

        assert all(part in title_input for part in expected_parts)
        assert "@file:" not in title_input
        # Paste-only opener (just the generated ref): the instant title is the paste's topic, not the path.
        lead = paste_preview if instruction.startswith("@file:") else instruction
        assert derive_title(instruction, paste_preview).startswith(lead[:12])

    def test_expanded_paste_ref_footer_does_not_demote_the_preview(self):
        """The titler receives the opener AFTER @-reference expansion: the generated ref carries a
        `--- Context Warnings ---` (or `--- Attached Context ---`) footer, which must not turn a
        paste-only opener into "instruction + trailing preview" (live wire finding on #114984)."""
        ref = "@file:/home/u/.hermes/attachments/pasted_content_2026-09-18_14-09-43-735_d0ee85.txt"
        preview = "Quarterly incident analysis for the database cluster"
        for footer in (f"\n\n--- Context Warnings ---\n- {ref}: path is outside the allowed workspace",
                       "\n\n--- Attached Context ---\n\n### file: pasted_content.txt\n" + preview):
            title_input = build_title_input(ref + footer, preview)

            assert title_input.startswith(preview)
            assert "---" not in title_input and "@file:" not in title_input
            assert derive_title(ref + footer, preview).startswith("Quarterly incident analysis")

    def test_manual_attachment_only_opener_yields_no_path_title(self):
        """#92068: the manual-attach path (composer attach chip / hand-typed
        ``@file:``) sends NO Desktop paste preview, so the build_title_input
        ref-only shortcut cannot rescue it. The titler must still refuse to
        name the session after the truncated file path."""
        msg = "@file:AppData/Local/hermes/profiles/local/attachments/report.pdf"

        assert is_titleable_user_message(msg) is False
        assert derive_title(msg) is None
        assert derive_title(msg + "\n\n--- Attached Context ---\n(file content)") is None
        # Backtick-quoted (space-bearing) paths and @folder: refs too.
        assert is_titleable_user_message("@file:`my file.txt`") is False
        assert is_titleable_user_message("@folder:/some/dir") is False
        # A quoted path with a line range is one reference token for the
        # canonical parser (context_references.REFERENCE_PATTERN), so the
        # guard must strip the range too, not leave ":3" behind as "prose".
        assert is_titleable_user_message("@file:`my file.txt`:3") is False
        assert is_titleable_user_message('@file:"spaced name.md":12-14') is False
        assert is_titleable_user_message("@file:'single quoted.md':1") is False
        # The background model-title path refuses the same opener.
        assert generate_title(msg) is None

    def test_attachment_plus_instruction_titles_from_the_instruction(self):
        """Prose around a manual attachment keeps driving the title — an
        attachment WITH a typed request is a real question, not a file drop."""
        msg = "Review @file:notes.txt and fix the off-by-one"

        assert is_titleable_user_message(msg) is True
        assert derive_title(msg) == "Review @file:notes.txt and fix the off-by-one"

    def test_title_input_budget_and_manual_attachments_stay_unread(self):
        title_input = build_title_input("Describe the release plan", "p" * MAX_TITLE_INPUT_CHARS)

        assert len(title_input) == MAX_TITLE_INPUT_CHARS
        assert title_input.startswith("Describe the release plan")
        assert title_input.endswith("p" * 20)
        # No preview => an ordinary manual attachment ref is never read for titling.
        assert build_title_input("Summarize @file:notes.txt", None) == "Summarize @file:notes.txt"




    def test_title_language_reads_config(self):
        cfg = {"auxiliary": {"title_generation": {"language": "  French "}}}

        with patch("hermes_cli.config.load_config", return_value=cfg), patch("hermes_cli.config.load_config_readonly", return_value=cfg):
            assert _title_language() == "French"
        with patch("hermes_cli.config.load_config", return_value={}), patch("hermes_cli.config.load_config_readonly", return_value={}):
            assert _title_language() == ""
        with patch("hermes_cli.config.load_config", side_effect=RuntimeError("bad config")), \
         patch("hermes_cli.config.load_config_readonly", side_effect=RuntimeError("bad config")):
            assert _title_language() == ""


    def test_generate_title_disables_reasoning(self):
        """The titling pass must explicitly disable thinking (#91927).

        With the aux default reasoning_effort "" (provider default), Gemini
        bills internal thought tokens against max_tokens=64, the JSON payload
        never lands, and the prose fallback stores the opening fence
        ("```json") as the title. Enforce the module's documented
        thinking-disabled contract at the call site.
        """
        captured_kwargs = {}

        def mock_call_llm(**kwargs):
            captured_kwargs.update(kwargs)
            resp = MagicMock()
            resp.choices = [MagicMock()]
            resp.choices[0].message.content = '{"title": "Reasoning Off"}'
            return resp

        with patch("agent.title_generator.call_llm", side_effect=mock_call_llm):
            assert generate_title("question") == "Reasoning Off"

        assert captured_kwargs.get("reasoning_config") == {"enabled": False}

    @pytest.mark.parametrize(
        ("content", "expected"),
        [
            # #83903: a token cap cutting the JSON mid-value or right after the fence opener must not
            # persist the fragment; the derived title survives instead.
            ('{"title":"Investigate and fix the login butt', None),
            ("```json", None),
            ('{"title"', None),
            # Legit titles the structural check must keep: emphasized/quoted prose, non-Latin, numeric.
            ("*Fix the login flow*", "*Fix the login flow*"),
            ("修复登录按钮", "修复登录按钮"),
            ("42", "42"),
            ('```json\n{"title": "Fix login button"', "Fix login button"),
            # Bracket/brace-prefixed prose and a literal fence inside a sentence are titles, not
            # truncated JSON — a provider that ignores response_format still gets its title kept.
            ("[WIP] Fix login flow", "[WIP] Fix login flow"),
            ("Fix ``` rendering in chat", "Fix ``` rendering in chat"),
        ],
    )
    def test_truncated_structured_output_never_becomes_the_title(self, content, expected):
        mock_response = MagicMock()
        mock_response.choices = [MagicMock()]
        mock_response.choices[0].message.content = content
        with patch("agent.title_generator.call_llm", return_value=mock_response):
            assert generate_title("login is broken") == expected

    def test_json_in_reasoning_content_is_used_but_reasoning_prose_is_not(self):
        """#82291: glm-5/minimax under json_schema return content='' with the JSON in reasoning_content /
        reasoning. That payload titles the session; chain-of-thought prose never does."""
        def response(content, **reasoning):
            resp = MagicMock(spec=["choices"])
            resp.choices = [MagicMock(spec=["message"])]
            resp.choices[0].message = MagicMock(spec=["content", *reasoning])
            resp.choices[0].message.content = content
            for k, v in reasoning.items():
                setattr(resp.choices[0].message, k, v)
            return resp

        cases = [
            (response("", reasoning_content='{"title": "Check FFmpeg on this machine"}'), "Check FFmpeg on this machine"),
            (response(None, reasoning='{"title": "Check FFmpeg on this machine"}'), "Check FFmpeg on this machine"),
            (response("", reasoning_content="The user wants ffmpeg checked. A short title would be"), None),
        ]
        for resp, expected in cases:
            with patch("agent.title_generator.call_llm", return_value=resp):
                assert generate_title("check ffmpeg") == expected

    def test_strips_think_blocks(self):
        """Reasoning-model output wrapped in <think>...</think> must not
        leak into the session title."""
        mock_response = MagicMock()
        mock_response.choices = [MagicMock()]
        mock_response.choices[0].message.content = (
            "<think>The user wants a title. I'll summarize the topic "
            "concisely.</think>Debugging Python Import Errors"
        )

        with patch("agent.title_generator.call_llm", return_value=mock_response):
            title = generate_title("help me fix this import")
            assert title == "Debugging Python Import Errors"
            assert "<think>" not in title
            assert "summarize" not in title

    def test_strips_unterminated_think_block(self):
        """An unterminated <think> block (no close tag) must still be
        stripped so the leaked reasoning doesn't become the title."""
        mock_response = MagicMock()
        mock_response.choices = [MagicMock()]
        mock_response.choices[0].message.content = (
            "<think>Let me reason about a good title for this session"
        )

        with patch("agent.title_generator.call_llm", return_value=mock_response):
            title = generate_title("hello")
            # Everything from the unterminated open tag onward is stripped,
            # leaving nothing → None.
            assert title is None


    def test_truncates_long_titles(self):
        mock_response = MagicMock()
        mock_response.choices = [MagicMock()]
        mock_response.choices[0].message.content = "A" * 100

        with patch("agent.title_generator.call_llm", return_value=mock_response):
            title = generate_title("question")
            assert len(title) == 80
            assert title.endswith("...")

    def test_rejects_answer_shaped_output(self):
        """A model that ignores the titling task and answers the user's
        message returns a full sentence; without a word bound the whole
        reply (truncated mid-sentence) became the session title.
        Regression for the can1357/oh-my-pi#7306 bug class."""
        answer = (
            "I don't have context on a \"registration system\" - that's not "
            "something I recognize from this conversation, and I don't see "
            "any prior discussion or code about it here"
        )
        mock_response = MagicMock()
        mock_response.choices = [MagicMock()]
        mock_response.choices[0].message.content = answer

        with patch("agent.title_generator.call_llm", return_value=mock_response):
            assert generate_title("how does the registration system work?", "...") is None

    def test_rejects_many_short_words(self):
        """13 short words stays under the 80-char cap but is not a title."""
        mock_response = MagicMock()
        mock_response.choices = [MagicMock()]
        mock_response.choices[0].message.content = (
            "one two three four five six seven eight nine ten eleven twelve thirteen"
        )

        with patch("agent.title_generator.call_llm", return_value=mock_response):
            assert generate_title("question", "answer") is None

    def test_accepts_normal_title(self):
        """A normal 3-7 word title is unaffected by the answer-shape guard."""
        mock_response = MagicMock()
        mock_response.choices = [MagicMock()]
        mock_response.choices[0].message.content = "Investigate the title resolver bug"

        with patch("agent.title_generator.call_llm", return_value=mock_response):
            assert generate_title("question", "answer") == "Investigate the title resolver bug"

    @pytest.mark.parametrize("echo", [
        wrap.format(example)
        for example in sorted(_EXAMPLE_ECHO_REJECT)
        for wrap in ("{}", '"{}"', "({})", "[{}]")
    ])
    def test_rejects_prompt_example_echo(self, echo):
        """A model that parrots one of the prompt's own example titles back
        must be rejected — a canned example says nothing about the session.
        Port of QwenLM/qwen-code#9709 (their #9706 bug class)."""
        mock_response = MagicMock()
        mock_response.choices = [MagicMock()]
        mock_response.choices[0].message.content = echo

        with patch("agent.title_generator.call_llm", return_value=mock_response):
            assert generate_title("help me with something unrelated") is None

    def test_friendly_greeting_example_is_allowed(self):
        """'Friendly greeting' is prescribed output for bare greetings, not an
        echo failure — it must pass the guard."""
        mock_response = MagicMock()
        mock_response.choices = [MagicMock()]
        mock_response.choices[0].message.content = "Friendly greeting"

        with patch("agent.title_generator.call_llm", return_value=mock_response):
            assert generate_title("hey there!") == "Friendly greeting"

    def test_topical_title_resembling_example_passes(self):
        """The guard is exact-match only: a genuinely topical title that merely
        resembles an example must not be rejected."""
        mock_response = MagicMock()
        mock_response.choices = [MagicMock()]
        mock_response.choices[0].message.content = "Fix login button on desktop"

        with patch("agent.title_generator.call_llm", return_value=mock_response):
            assert generate_title("the login button is broken on desktop") == (
                "Fix login button on desktop"
            )



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











class TestAutoTitleSession:
    """Tests for auto_title_session() — the sync worker function."""




    def test_does_not_overwrite_title_set_immediately_before_conditional_write(
        self, tmp_path
    ):
        db = SessionDB(tmp_path / "state.db")
        db.create_session(session_id="sess-1", source="cli")
        seen = []

        def generate_after_manual_title(*_args, **_kwargs):
            db.set_session_title("sess-1", "Manual Title")
            return "Auto Title"

        with patch(
            "agent.title_generator.generate_title",
            side_effect=generate_after_manual_title,
        ):
            auto_title_session(
                db,
                "sess-1",
                "hi",
                title_callback=lambda title, source: seen.append(title),
            )

        assert db.get_session_title("sess-1") == "Manual Title"
        assert seen == []

    def test_invokes_title_callback_after_setting_title(self):
        db = MagicMock()
        db.get_session_title_source.return_value = None
        db.set_auto_title.return_value = True
        seen = []
        with patch("agent.title_generator.generate_title", return_value="Readable Session"):
            auto_title_session(
                db,
                "sess-1",
                "hello",
                title_callback=lambda title, source: seen.append((title, source)),
            )
        db.set_auto_title.assert_called_once_with(
            "sess-1", "Readable Session", source="llm"
        )
        # The stage reaches the consumer, so one that spends a rate-limited
        # remote call per title can take this and skip the derived one.
        assert seen == [("Readable Session", "llm")]

    def test_upgrades_a_derived_title_but_not_an_llm_one(self, tmp_path):
        """The instant title is provisional; a model title is final.

        This is the "session renames itself" guard: re-running the titler on a
        session that already has an LLM title must be a no-op.
        """
        db = SessionDB(tmp_path / "state.db")
        db.create_session(session_id="sess-1", source="cli")
        db.set_auto_title("sess-1", "fix the flaky auth test", source="derived")

        with patch("agent.title_generator.generate_title", return_value="Fix flaky auth test"):
            auto_title_session(db, "sess-1", "fix the flaky auth test")
        assert db.get_session_title("sess-1") == "Fix flaky auth test"

        with patch("agent.title_generator.generate_title", return_value="Totally Different"):
            auto_title_session(db, "sess-1", "fix the flaky auth test")
        assert db.get_session_title("sess-1") == "Fix flaky auth test"



    def test_body_exception_routed_to_failure_callback(self):
        db = MagicMock()
        db.get_session_title.return_value = None
        db.get_session_title_source.return_value = None
        seen = []

        boom = ImportError("stale module")
        with patch("agent.title_generator.generate_title", side_effect=boom):
            auto_title_session(
                db,
                "sess-1",
                "hi",
                failure_callback=lambda task, exc: seen.append((task, exc)),
            )
        assert seen == [("title generation", boom)]



class TestMaybeAutoTitle:
    """Tests for maybe_auto_title() — the fire-and-forget entry point."""



    @pytest.mark.parametrize(
        "main_runtime, title_cfg, deferred",
        [
            ({"provider": "custom", "base_url": "http://127.0.0.1:8080/v1"}, {}, True),
            ({"provider": "custom:gptoss-local", "base_url": "http://127.0.0.1:8080/v1"}, {}, True),
            ({"provider": "lmstudio", "base_url": "http://127.0.0.1:1234/v1"}, {}, True),
            ({"provider": "custom", "base_url": "http://127.0.0.1:8080/v1"}, {"base_url": "http://127.0.0.1:8080/v1/"}, True),
            ({"provider": "custom", "base_url": "http://127.0.0.1:8080/v1"}, {"provider": "openrouter"}, False),
            ({"provider": "custom", "base_url": "http://127.0.0.1:8080/v1"}, {"base_url": "http://10.0.0.2:8080/v1"}, False),
            ({"provider": "openrouter", "base_url": "https://openrouter.ai/api/v1"}, {}, False),
        ],
    )
    def test_title_call_waits_for_the_turn_when_it_shares_a_self_hosted_endpoint(self, main_runtime, title_cfg, deferred):
        """#117296: a self-hosted server serving the main turn and the concurrent json_schema title request
        can decode the title into the main reply. The upgrade must not go on the wire until the caller starts
        it after the turn; every other route keeps the turn-start timing."""
        import threading
        from agent import title_generator as tg
        db = MagicMock()
        db.get_session_title.return_value = None
        started = threading.Event()
        with patch.object(tg, "_title_config", return_value=title_cfg), \
                patch.object(tg, "auto_title_session", side_effect=lambda *a, **k: started.set()):
            upgrade = maybe_auto_title(db, "sess-1", "hello", [{"role": "user", "content": "hello"}], main_runtime=main_runtime)
            assert isinstance(upgrade, threading.Thread)
            if deferred:
                assert upgrade.ident is None and not started.wait(0.3), "title request went out during the turn"
                assert upgrade not in tg._UPGRADE_THREADS  # join-before-start would raise in wait_for_title_upgrades
                tg.start_title_upgrade(upgrade)
            assert started.wait(timeout=10), "auto_title thread never ran"
            assert upgrade in tg._UPGRADE_THREADS

    @pytest.mark.parametrize(
        "main_provider, title_cfg, deferred",
        [
            ("Custom:GPTOSS-Local", {}, True),  # /model stores the id as typed; the gate lowercases
            ("custom:gptoss-local", {"provider": "custom:gptoss-local"}, True),
            ("custom:gptoss-local", {"provider": "gptoss-local"}, True),  # bare config name
            ("custom:gptoss-local", {"provider": "GPTOSS Local"}, True),  # display name
            ("custom:gptoss", {"provider": "GPTOSS Local"}, True),  # display name of a keyed `providers:` entry
            ("custom:gptoss-local", {"provider": "custom"}, True),
            ("custom:gptoss-local", {"provider": "custom:gptoss-local", "base_url": "http://127.0.0.1:8080/v1/"}, True),
            ("custom:gptoss-local", {"provider": "custom:other", "base_url": "http://10.0.0.2:8080/v1"}, False),
            ("custom:gptoss-local", {"provider": "gptoss-local", "base_url": "http://10.0.0.2:8080/v1"}, False),
            ("custom:gptoss-local", {"provider": "openrouter"}, False),
            ("custom:gptoss-local", {"provider": "nous"}, False),
            ("custom", {"provider": "ollama"}, True),  # alias of custom
            ("custom", {"provider": "vllm"}, True),  # normalises to `local`: the same local server
            ("lmstudio", {"provider": "lm-studio"}, True),
            ("lmstudio", {"provider": "lmstudio", "base_url": "http://10.0.0.2:1234/v1"}, False),
            ("lmstudio", {"provider": "openrouter"}, False),
        ],
    )
    def test_title_pin_naming_the_same_self_hosted_route_still_waits_for_the_turn(self, main_provider, title_cfg, deferred):
        """#120558: a ``/model`` switch to a named custom provider runs the turn as ``custom:<name>``. A title pin
        spelled as that route (``custom:<name>``, the bare config name or its display name) is the same single-slot
        server, so the gate must still defer; only a differing pinned base_url or a hosted pin fires at turn start."""
        from agent import title_generator as tg

        main_runtime = {"provider": main_provider, "base_url": "http://127.0.0.1:8080/v1"}
        keyed = {"providers": {"gptoss": {"name": "GPTOSS Local", "base_url": "http://127.0.0.1:8080/v1"}}}
        with patch.object(tg, "_title_config", return_value=title_cfg), \
                patch("hermes_cli.config.load_config_readonly", return_value=keyed):
            assert tg.title_upgrade_must_wait_for_turn(main_runtime) is deferred

    def test_kanban_worker_is_named_after_its_card_without_the_llm_thread(self, tmp_path, monkeypatch):
        """A worker's session takes the board card's title synchronously; no auxiliary model call (#111166)."""
        from hermes_cli import kanban_db, kanban_db_connect

        with kanban_db_connect.connect_closing(board="default") as conn:
            task_id = kanban_db.create_task(conn, title="Fix flaky worker startup", board="default")
            conn.commit()
        monkeypatch.setenv("HERMES_KANBAN_TASK", task_id)
        db = SessionDB(tmp_path / "state.db")
        db.create_session(session_id="sess-1", source="kanban")

        with patch("agent.title_generator.auto_title_session") as mock_auto:
            maybe_auto_title(db, "sess-1", f"work kanban task {task_id}", [])

        assert db.get_session_title("sess-1") == "Fix flaky worker startup"
        assert db.get_session_title_source("sess-1") == "llm"
        mock_auto.assert_not_called()

    def test_kanban_worker_with_an_overlong_card_title_is_still_named(self, tmp_path, monkeypatch):
        """Cards have no length cap; the store rejects past MAX_TITLE_LENGTH, so the card title is trimmed, not dropped."""
        from hermes_cli import kanban_db, kanban_db_connect

        card = "Investigate why the swap modal intermittently fails to render its confirmation step on mobile Safari after a retry"
        assert len(card) > SessionDB.MAX_TITLE_LENGTH
        with kanban_db_connect.connect_closing(board="default") as conn:
            task_id = kanban_db.create_task(conn, title=card, board="default")
            conn.commit()
        monkeypatch.setenv("HERMES_KANBAN_TASK", task_id)
        db = SessionDB(tmp_path / "state.db")
        for sid in ("sess-1", "sess-2"):  # a retried card must still get the ``#N`` suffix within the cap
            db.create_session(session_id=sid, source="kanban")
            with patch("agent.title_generator.auto_title_session"):
                maybe_auto_title(db, sid, f"work kanban task {task_id}", [])

        first, second = db.get_session_title("sess-1"), db.get_session_title("sess-2")
        assert first and first.startswith(card[:40]) and first.endswith("…")
        assert second == f"{first} #2"
        assert len(second) <= SessionDB.MAX_TITLE_LENGTH

    def test_kanban_worker_with_unreadable_card_falls_back_to_the_task_id(self, tmp_path, monkeypatch):
        monkeypatch.setenv("HERMES_KANBAN_TASK", "t_missing")
        db = SessionDB(tmp_path / "state.db")
        db.create_session(session_id="sess-1", source="kanban")

        with patch("agent.title_generator.auto_title_session") as mock_auto:
            maybe_auto_title(db, "sess-1", "work kanban task t_missing", [])

        assert db.get_session_title("sess-1") == "Kanban task t_missing"
        mock_auto.assert_not_called()

    def test_delegated_child_of_a_worker_is_not_named_after_the_card(self, tmp_path, monkeypatch):
        """A delegate_task child inherits ``HERMES_KANBAN_TASK`` but is not the card's session;
        it takes the ordinary title path instead of the parent's card title (#112817)."""
        from agent.delegation_context import delegated_child_context

        monkeypatch.setenv("HERMES_KANBAN_TASK", "t_parent")
        db = SessionDB(tmp_path / "state.db")
        db.create_session(session_id="child-1", source="kanban")

        with delegated_child_context(), patch("agent.title_generator.auto_title_session") as mock_auto:
            maybe_auto_title(db, "child-1", "research the auth flow for the parent", [])

        assert db.get_session_title("child-1") != "Kanban task t_parent"
        mock_auto.assert_called_once()

    def test_writes_instant_title_before_the_model_runs(self, tmp_path):
        """The derived title lands synchronously — no LLM, no waiting."""
        db = SessionDB(tmp_path / "state.db")
        db.create_session(session_id="sess-1", source="cli")
        with patch("agent.title_generator.auto_title_session"):
            maybe_auto_title(
                db, "sess-1", "fix the flaky auth test in login", []
            )
        assert db.get_session_title("sess-1") == "fix the flaky auth test in login"
        assert db.get_session_title_source("sess-1") == "derived"

    def test_model_upgrade_disabled_keeps_derived_title_and_spawns_no_thread(self, tmp_path):
        db = SessionDB(tmp_path / "state.db")
        db.create_session(session_id="sess-1", source="cli")
        config = {
            "auxiliary": {"title_generation": {
                "enabled": True, "model_upgrade_enabled": False,
            }}
        }
        with patch("hermes_cli.config.load_config_readonly", return_value=config), \
             patch("agent.memory_provider.spawn_context_thread") as thread, \
             patch("agent.title_generator.call_llm") as call_llm:
            maybe_auto_title(db, "sess-1", "repair startup memory routing", [])
        assert db.get_session_title("sess-1") == "repair startup memory routing"
        assert db.get_session_title_source("sess-1") == "derived"
        thread.assert_not_called()
        call_llm.assert_not_called()
        # The toggle only silences the automatic upgrade: an explicit ``generate_title`` call
        # (``hermes sessions retitle-skills``) still asks the model.
        resp = MagicMock()
        resp.choices = [MagicMock()]
        resp.choices[0].message.content = '{"title": "Repair startup memory routing"}'
        with patch("hermes_cli.config.load_config_readonly", return_value=config), \
             patch("agent.title_generator.call_llm", return_value=resp):
            assert generate_title("repair startup memory routing") == "Repair startup memory routing"

    def test_enabled_false_still_disables_derived_and_model_titles(self, tmp_path):
        db = SessionDB(tmp_path / "state.db")
        db.create_session(session_id="sess-1", source="cli")
        config = {
            "auxiliary": {"title_generation": {
                "enabled": False, "model_upgrade_enabled": True,
            }}
        }
        with patch("hermes_cli.config.load_config_readonly", return_value=config), \
             patch("agent.memory_provider.spawn_context_thread") as thread, \
             patch("agent.title_generator.call_llm") as call_llm:
            maybe_auto_title(db, "sess-1", "repair startup memory routing", [])
        assert db.get_session_title("sess-1") is None
        thread.assert_not_called()
        call_llm.assert_not_called()


    @pytest.mark.parametrize(
        "opener",
        [
            "[CONTEXT COMPACTION — REFERENCE ONLY] Earlier turns were compacted",
            "[CONTEXT SUMMARY]: the user was refactoring the auth module",
            "[System note: the user switched models]",
            "[Runtime note: resumed from checkpoint]",
        ],
    )
    def test_skips_every_shape_of_machine_authored_opener(self, tmp_path, opener):
        """A session named after our own scaffolding is named after us."""
        db = SessionDB(tmp_path / "state.db")
        db.create_session(session_id="sess-1", source="cli")
        with patch("agent.title_generator.auto_title_session") as mock_auto:
            maybe_auto_title(db, "sess-1", opener, [])
        assert db.get_session_title("sess-1") is None
        mock_auto.assert_not_called()

    def test_a_multimodal_turn_counts_as_a_real_question(self, tmp_path):
        """"Here's a screenshot, fix the login" is a question, parts list or not.

        Judging a turn by `content` alone reads a multimodal one as machinery
        and undercounts the conversation, so a session deep into its history
        looks like it is still on its opening turn.
        """
        from agent.title_generator import _is_real_user_turn

        assert _is_real_user_turn(
            {
                "role": "user",
                "content": [
                    {"type": "image_url", "image_url": {"url": "data:image/png;base64,x"}},
                    {"type": "text", "text": "fix the login button"},
                ],
            }
        )
        # An image with no words is not a question we can name anything after.
        assert not _is_real_user_turn(
            {"role": "user", "content": [{"type": "image_url", "image_url": {"url": "x"}}]}
        )

    def test_titles_on_a_later_turn_when_the_opener_was_not_titleable(self, tmp_path):
        """A session whose opener couldn't be titled gets named by a later turn.

        The opener here is a compaction handoff, so turn one leaves the session
        nameless. Nothing used to reconsider it: the guard that stops re-titling
        a named session also stopped the nameless one from ever asking again.
        """
        db = SessionDB(tmp_path / "state.db")
        db.create_session(session_id="sess-1", source="cli")
        history = [
            {"role": "user", "content": "[CONTEXT COMPACTION — REFERENCE ONLY] x"},
            {"role": "assistant", "content": "ok"},
            {"role": "user", "content": "thanks"},
            {"role": "assistant", "content": "sure"},
        ]
        with patch("agent.title_generator.auto_title_session"):
            maybe_auto_title(db, "sess-1", "fix the flaky auth test", history)
        assert db.get_session_title("sess-1") == "fix the flaky auth test"

    def test_leaves_an_already_titled_session_alone_on_later_turns(self, tmp_path):
        """The retry is for nameless sessions only; a named one asks nothing."""
        db = SessionDB(tmp_path / "state.db")
        db.create_session(session_id="sess-1", source="cli")
        db.set_session_title("sess-1", "Existing name")
        history = [
            {"role": "user", "content": "hello"},
            {"role": "assistant", "content": "hi"},
            {"role": "user", "content": "thanks"},
            {"role": "assistant", "content": "sure"},
        ]
        with patch("agent.title_generator.auto_title_session") as mock_auto:
            maybe_auto_title(db, "sess-1", "and now something else", history)
        assert db.get_session_title("sess-1") == "Existing name"
        mock_auto.assert_not_called()

    @pytest.mark.parametrize("title, provisional", [
        ("Friendly greeting", True),
        ("'Friendly greeting in chat'", True),
        ("Friendly greeting card design", False),
        ("Friendly greetings and pleasantries", False),
    ])
    def test_only_the_exact_greeting_placeholder_is_provisional(self, title, provisional):
        """A topical title that merely starts with the phrase keeps its ``llm`` rank."""
        from agent.title_generator import _is_provisional_greeting_title
        assert _is_provisional_greeting_title(title) is provisional

    def test_upgrades_a_provisional_greeting_on_a_substantive_second_turn(self, tmp_path):
        """A bare "hi" opener leaves only placeholders (instant slice / the model's greeting title);
        the next real request must still be allowed to name the session."""
        db = SessionDB(tmp_path / "state.db")
        db.create_session(session_id="sess-1", source="cli")
        answers = iter(["Friendly greeting", "Debug scheduler failures"])

        def stub_call_llm(**kwargs):
            resp = MagicMock()
            resp.choices[0].message.content = next(answers)
            resp.choices[0].message.reasoning = None
            return resp

        history = [{"role": "user", "content": "hi how are you"}]
        with patch("agent.title_generator.call_llm", side_effect=stub_call_llm), \
                patch("agent.title_generator._auto_title_enabled", return_value=True), \
                patch("agent.title_generator._model_title_upgrade_enabled", return_value=True):
            maybe_auto_title(db, "sess-1", "hi how are you", history)
            wait_for_title_upgrades(10)
            assert db.get_session_title_source("sess-1") == "derived"
            history += [{"role": "assistant", "content": "Well, thanks."},
                        {"role": "user", "content": "help me debug the scheduler"}]
            maybe_auto_title(db, "sess-1", "help me debug the scheduler", history)
            wait_for_title_upgrades(10)

        assert db.get_session_title("sess-1") == "Debug scheduler failures"
        assert db.get_session_title_source("sess-1") == "llm"

    def test_a_placeholder_title_stops_retrying_after_the_third_turn(self, tmp_path):
        """A derived name gets turns 2-3 to upgrade, not a model call on every later turn."""
        db = SessionDB(tmp_path / "state.db")
        db.create_session(session_id="sess-1", source="cli")
        db.set_auto_title("sess-1", "hi", source="derived")
        history = [{"role": "user", "content": f"turn {n}"} for n in range(3)]
        with patch("agent.title_generator.auto_title_session") as mock_auto, \
                patch("agent.title_generator._auto_title_enabled", return_value=True), \
                patch("agent.title_generator._model_title_upgrade_enabled", return_value=True):
            maybe_auto_title(db, "sess-1", "and now the real question", history)
            wait_for_title_upgrades(10)
            assert mock_auto.call_count == 1  # turn 3: the placeholder still gets a model shot
            history.append({"role": "user", "content": "turn 3"})
            maybe_auto_title(db, "sess-1", "and now the real question", history)
            wait_for_title_upgrades(10)
        assert mock_auto.call_count == 1  # turn 4: capped, no call

    def test_instant_title_declines_a_name_collision(self, tmp_path):
        """A colliding derived title is skipped, not scanned into 'hi #2'.

        Common openers collide constantly, and the lineage scan that resolves
        the collision runs inline on the turn. The model's title lands moments
        later, so the session is named either way.
        """
        db = SessionDB(tmp_path / "state.db")
        db.create_session(session_id="taken", source="cli")
        db.set_session_title("taken", "hi")
        db.create_session(session_id="sess-1", source="cli")
        with patch("agent.title_generator.auto_title_session"):
            maybe_auto_title(db, "sess-1", "hi", [])
        assert db.get_session_title("sess-1") is None






class TestAutoTitleDuplicateHandling:
    """Duplicate auto-title handling and not-found hardening (#50537)."""

    def test_background_stage_names_a_collision_the_instant_stage_declined(
        self, tmp_path
    ):
        """The lineage scan the turn skipped happens here instead.

        The inline stage declines a collision to stay off the critical path, and
        the model can still come back empty. Between them the session would be
        left nameless, so the background stage spends the scan the turn wouldn't.
        """
        db = SessionDB(tmp_path / "state.db")
        db.create_session(session_id="taken", source="cli")
        db.set_session_title("taken", "hi")
        db.create_session(session_id="sess-1", source="cli")
        with patch("agent.title_generator.generate_title", return_value=None):
            auto_title_session(db, "sess-1", "hi")
        assert db.get_session_title("sess-1") == "hi #2"

    def test_dedupes_duplicate_title_via_lineage(self):
        db = MagicMock()
        db.get_session_title_source.return_value = None
        # Atomic write path: collision raises ValueError, retry persists.
        db.set_auto_title.side_effect = [ValueError("in use"), True]
        db.get_next_title_in_lineage.return_value = "Debugging Import Error #2"
        with patch(
            "agent.title_generator.generate_title",
            return_value="Debugging Import Error",
        ):
            seen = []
            auto_title_session(
                db,
                "sess-1",
                "hi",
                title_callback=lambda title, _source: seen.append(title),
            )
        db.get_next_title_in_lineage.assert_called_once_with("Debugging Import Error")
        assert db.set_auto_title.call_args_list[-1][0] == (
            "sess-1",
            "Debugging Import Error #2",
        )
        # callback fires with the actually-persisted (deduped) title
        assert seen == ["Debugging Import Error #2"]






class TestRuntimeValidator:
    """runtime_validator gating (#19027): a stale background title request
    must not fire when the session's model/provider changed after spawn."""



    def test_broken_validator_fails_open(self):
        mock_response = MagicMock()
        mock_response.choices = [MagicMock()]
        mock_response.choices[0].message.content = "Resilient Title"

        def _bad_validator():
            raise RuntimeError("validator gone")

        with patch("agent.title_generator.call_llm", return_value=mock_response) as mock_llm:
            title = generate_title(
                "question", "answer",
                runtime_validator=_bad_validator,
            )
            assert title == "Resilient Title"
            mock_llm.assert_called_once()



class TestModelSwitchMarkerNotTitleable:
    """Regression: a model-switch marker must never become the session title.

    ``_append_model_switch_marker`` (tui_gateway/server.py) persists its notice
    with ``role="user"`` because strict OpenAI-compatible providers reject a
    system message that is not first (#48338). Titling therefore has to
    recognise it as machine-authored, or switching models before asking the
    first real question titles the session
    "[System: The active model for this chat has…".
    """

    MARKER = (
        "[System: The active model for this chat has changed to "
        "deepseek-v4-flash via provider 94mei. From this point forward, use "
        "this runtime metadata when answering questions about what "
        "model/provider is active.]"
    )

    def test_marker_prefix_matches_gateway_constant(self):
        """The guard must stay in sync with the gateway's marker builder."""
        from tui_gateway.server import _MODEL_SWITCH_MARKER_PREFIX
        from agent.title_generator import _MACHINE_PREFIXES

        assert _MODEL_SWITCH_MARKER_PREFIX in _MACHINE_PREFIXES
        assert self.MARKER.startswith(_MODEL_SWITCH_MARKER_PREFIX)

    def test_marker_is_not_titleable(self):
        from agent.title_generator import is_titleable_user_message

        assert is_titleable_user_message(self.MARKER) is False


    def test_unrelated_system_bracket_text_still_titleable(self):
        """The guard is narrow: real user text starting "[System:" still titles."""
        from agent.title_generator import is_titleable_user_message

        assert is_titleable_user_message("[System: my own note] how do I ...") is True

    def test_real_question_after_marker_still_titles(self):
        """The marker must not consume the session's one titling opportunity.

        The marker is a role="user" row, so counting it made the first real
        question look like turn 2 — and titling bailed out entirely, leaving
        the session permanently untitled.
        """
        db = MagicMock()
        db.get_session_title.return_value = None
        db.get_session_title_source.return_value = None
        history = [
            {"role": "user", "content": self.MARKER},
            {"role": "user", "content": "南京市秦淮区 小时级天气预报"},
        ]

        with patch("agent.title_generator.auto_title_session") as mock_auto:
            import threading

            called = threading.Event()
            mock_auto.side_effect = lambda *a, **k: called.set()
            maybe_auto_title(db, "sess-1", "南京市秦淮区 小时级天气预报", history)
            assert called.wait(timeout=10), "auto_title never ran after marker"

    def test_instant_title_skips_marker_uses_real_message(self):
        from agent.title_generator import apply_instant_title

        db = MagicMock()
        db.get_session_title_source.return_value = None

        assert apply_instant_title(db, "sess-1", self.MARKER) is None
        assert apply_instant_title(db, "sess-1", "南京市秦淮区 小时级天气预报") == (
            "南京市秦淮区 小时级天气预报"
        )


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

    def test_rejects_conversational_prose_instead_of_truncating(self):
        """Regression: the model answered the "should this change?" question in
        PROSE ("The title remains accurate. The conversation is still about …")
        instead of returning a title. The old code sanitized + truncated it at
        80 chars and stored the sentence AS the title, which then became the
        Discord thread name. Prose must be rejected → None → keep current title.
        """
        history = [
            {"role": "user", "content": "run hermes update"},
            {"role": "assistant", "content": "Starting the triage..."},
            {"role": "user", "content": "restart and verify"},
            {"role": "assistant", "content": "Gateway restarted cleanly."},
        ]
        prose = (
            "The title remains accurate. The conversation is still about "
            "triaging and executing the hermes update"
        )
        with patch("agent.title_generator.call_llm", return_value=self._resp(prose)):
            out = regenerate_title(history, "Hermes Update Triage")
        assert out is None

    def test_rejects_overlong_prose_not_truncate(self):
        """A >80-char blob must be rejected (None), never truncated into a title."""
        history = [
            {"role": "user", "content": "q"},
            {"role": "assistant", "content": "a"},
        ]
        with patch("agent.title_generator.call_llm", return_value=self._resp("A" * 100)):
            assert regenerate_title(history, "Existing Title") is None

    def test_accepts_abbreviation_titles_with_internal_dots(self):
        """The prose guard must NOT false-reject legit titles whose dotted
        component is an abbreviation ("U.S. Visa Renewal") — only lowercase-
        word sentence breaks count as prose."""
        history = [
            {"role": "user", "content": "help with my visa"},
            {"role": "assistant", "content": "Sure..."},
            {"role": "user", "content": "timeline?"},
            {"role": "assistant", "content": "Here..."},
        ]
        with patch("agent.title_generator.call_llm", return_value=self._resp("U.S. Visa Renewal Timeline")):
            assert regenerate_title(history, "Visa Help") == "U.S. Visa Renewal Timeline"


class TestLooksLikeTitle:
    """Unit tests for the _looks_like_title prose-rejection shape guard."""

    @pytest.mark.parametrize("text", [
        "USCIS RFE Response",
        "Debugging Python Import Errors",
        "Setting Up Docker Environment",
        "Kubernetes Pod Debugging",
        "U.S. Visa Renewal Timeline",   # uppercase/single-letter abbreviation dots
        "Q3 Financial Review",
    ])
    def test_accepts_real_titles(self, text):
        from agent.title_generator import _looks_like_title
        assert _looks_like_title(text) is True

    @pytest.mark.parametrize("text", [
        "",
        "The title remains accurate. The conversation is still about triaging",  # sentence break
        "A" * 100,                                                                # >80 chars
        "one two three four five six seven eight nine ten eleven",                # >10 words
        "Fixing the bug. Then shipping it",                                       # mid-sentence period
        "Line one\nLine two",                                                     # internal newline
    ])
    def test_rejects_prose_and_garbage(self, text):
        from agent.title_generator import _looks_like_title
        assert _looks_like_title(text) is False


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
