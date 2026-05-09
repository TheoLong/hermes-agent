"""LOCAL CARRY: the reply fetch hint is a model instruction like the triggering note.

The model gets a ready-made ``fetch_messages(around=…)`` call for the REPLIED-TO message,
anchored on the channel that message lives in; the durable transcript row never keeps it.
"""
import pytest

from gateway.config import GatewayConfig, Platform
from gateway.platforms.event import MessageEvent
from gateway.run import GatewayRunner
from gateway.session import SessionSource


def _runner() -> GatewayRunner:
    runner = object.__new__(GatewayRunner)
    runner.config = GatewayConfig(group_sessions_per_user=False)
    runner.adapters = {}
    runner._model = "test-model"
    runner._base_url = ""
    return runner


@pytest.mark.asyncio
async def test_hint_reaches_model_anchored_on_parent_channel_and_is_not_persisted(monkeypatch):
    monkeypatch.setattr("gateway.session._discord_tools_loaded", lambda: True)
    runner = _runner()
    source = SessionSource(platform=Platform.DISCORD, chat_id="thread9", chat_type="thread", user_id="u1", user_name="Theo")
    event = MessageEvent(
        text="do that", source=source, message_id="200",
        reply_to_message_id="100", reply_to_text="the plan", reply_to_channel_id="parent7",
    )

    model_text = await runner._prepare_inbound_message_text(event=event, source=source, history=[])
    message_text, persisted, _ts = runner._hmwa_apply_message_timestamp(event, model_text)

    assert "discord(action='fetch_messages', channel_id='parent7', around='100', limit=20)" in message_text
    assert persisted.startswith('[Replying to: "the plan"]') and persisted.endswith('do that')
    assert 'fetch_messages' not in persisted


@pytest.mark.asyncio
async def test_no_hint_without_a_reply(monkeypatch):
    monkeypatch.setattr("gateway.session._discord_tools_loaded", lambda: True)
    runner = _runner()
    source = SessionSource(platform=Platform.DISCORD, chat_id="c1", chat_type="group", user_id="u1", user_name="Theo")
    event = MessageEvent(text="hello", source=source, message_id="300")

    model_text = await runner._prepare_inbound_message_text(event=event, source=source, history=[])

    assert "fetch_messages" not in model_text
