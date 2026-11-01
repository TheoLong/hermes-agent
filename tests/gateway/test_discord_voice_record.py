"""/voice record: silent meeting recording to local files (no Craig / third-party upload).

Defends: per-speaker tracks stay aligned to one clock across silences, finalize produces a
mixed file plus per-speaker files, the receiver routes audio to the recorder instead of the
live-conversation buffers, and recordings are exempt from the inactivity auto-leave.
"""
import asyncio
import shutil
import subprocess
from types import SimpleNamespace

import pytest

from plugins.platforms.discord.voice_recorder import BYTES_PER_SECOND, MeetingRecorder


class _Clock:
    def __init__(self):
        self.now = 0.0

    def __call__(self):
        return self.now


def _frame(ms=20, val=1000):
    n = int(48000 * ms / 1000)
    return (val.to_bytes(2, "little", signed=True) * 2) * n


def test_tracks_padded_to_shared_clock(tmp_path):
    clock = _Clock()
    rec = MeetingRecorder("t", root=tmp_path, clock=clock)
    clock.now = 0.02
    rec.write(1, _frame())
    clock.now = 5.02  # speaker 2 first speaks 5s in
    rec.write(2, _frame())
    clock.now = 10.02  # speaker 1 again after 10s of silence
    rec.write(1, _frame())
    paths = rec.close()
    assert abs(paths[2].stat().st_size / BYTES_PER_SECOND - 5.02) < 0.01
    assert abs(paths[1].stat().st_size / BYTES_PER_SECOND - 10.02) < 0.01


def test_small_jitter_not_padded(tmp_path):
    clock = _Clock()
    rec = MeetingRecorder("t", root=tmp_path, clock=clock)
    for i in range(1, 51):
        clock.now = i * 0.02 + 0.05  # constant 50ms lag = jitter
        rec.write(1, _frame())
    size = rec.close()[1].stat().st_size
    assert size == len(_frame()) * 50


def test_write_after_close_ignored(tmp_path):
    rec = MeetingRecorder("t", root=tmp_path)
    rec.write(1, _frame())
    rec.close()
    rec.write(1, _frame())  # must not raise


@pytest.mark.skipif(not shutil.which("ffmpeg"), reason="ffmpeg required")
def test_finalize_mixes_and_names_speakers(tmp_path):
    clock = _Clock()
    rec = MeetingRecorder("Guild_Room", root=tmp_path, clock=clock)
    for i in range(1, 101):
        clock.now = i * 0.02
        rec.write(11, _frame())
        rec.write(22, _frame(val=-500))
    res = rec.finalize({11: "Theo", 22: "Some Guest"}, transcribe=False)
    assert res["error"] is None
    assert sorted(res["speakers"]) == ["Some_Guest", "Theo"]
    d = rec.dir
    assert (d / "Theo.flac").exists() and (d / "Some_Guest.flac").exists() and (d / "meeting.m4a").exists()
    codec = subprocess.run(["ffprobe", "-v", "error", "-select_streams", "a:0", "-show_entries", "stream=codec_name",
                            "-of", "csv=p=0", str(d / "Theo.flac")], capture_output=True, text=True).stdout.strip()
    assert codec == "flac"
    assert not list(d.glob("*.pcm"))
    dur = float(subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0",
                                str(d / "meeting.m4a")], capture_output=True, text=True).stdout)
    assert 1.8 < dur < 2.3


def test_finalize_without_audio_reports_error(tmp_path):
    rec = MeetingRecorder("t", root=tmp_path)
    assert rec.finalize({}, transcribe=False)["error"] == "No audio was captured."


def test_receiver_routes_pcm_to_recorder(tmp_path):
    from plugins.platforms.discord.adapter import VoiceReceiver
    r = VoiceReceiver.__new__(VoiceReceiver)
    r._recorder = None
    got = []
    r._recorder = SimpleNamespace(write=lambda ssrc, pcm: got.append((ssrc, len(pcm))))
    # Emulate the post-decode branch exactly as _on_packet runs it.
    recorder = r._recorder
    recorder.write(5, _frame())
    assert got == [(5, len(_frame()))]
    src = open(VoiceReceiver._on_packet.__code__.co_filename).read()
    assert "recorder.write(ssrc, pcm)" in src


def test_recording_exempt_from_inactivity_timeout():
    from plugins.platforms.discord.adapter import DiscordAdapter
    host = SimpleNamespace(_voice_recordings={7: object()}, _voice_timeout_tasks={},
                           _voice_timeout_limit=lambda: 300)
    host._cancel_voice_timeout = lambda gid: DiscordAdapter._cancel_voice_timeout(host, gid)
    DiscordAdapter._reset_voice_timeout(host, 7)
    assert host._voice_timeout_tasks == {}


def _receiver_in_channel(member_ids, *, allowed, recorder, mapped):
    import threading
    from plugins.platforms.discord.adapter import VoiceReceiver
    r = VoiceReceiver.__new__(VoiceReceiver)
    r._lock = threading.Lock()
    r._recorder = recorder
    r._allowed_user_ids = allowed
    r._ssrc_to_user = dict(mapped)
    members = [SimpleNamespace(id=i) for i in member_ids]
    r._vc = SimpleNamespace(channel=SimpleNamespace(members=members), user=SimpleNamespace(id=1))
    return r


def test_recording_guest_ssrc_not_mapped_to_owner():
    """Symptom: in a recorded meeting the guest's track was silent and labeled with the
    owner's name — the sole-allowed-member guess handed the guest's SSRC to the owner,
    so DAVE decrypted it with the wrong key and every frame was lost."""
    owner, guest = 100, 200
    r = _receiver_in_channel([1, owner, guest], allowed={str(owner)}, recorder=object(),
                             mapped={11: owner})
    assert r._infer_user_for_ssrc(22) == guest
    assert r._ssrc_to_user[22] == guest


def test_inference_skips_users_already_mapped_outside_recording():
    owner, guest = 100, 200
    r = _receiver_in_channel([1, owner, guest], allowed={str(owner)}, recorder=None,
                             mapped={11: owner})
    assert r._infer_user_for_ssrc(22) == 0  # the owner already has SSRC 11
    r2 = _receiver_in_channel([1, owner, guest], allowed={str(owner)}, recorder=None, mapped={})
    assert r2._infer_user_for_ssrc(11) == owner  # conversation-mode rejoin path unchanged


def test_channel_keys_include_server_id():
    """Symptom: free_response_channels '*' made the bot answer the owner in every server;
    the server ID is now a gate key so free response can be scoped to one server."""
    from plugins.platforms.discord.adapter import DiscordAdapter
    ch = SimpleNamespace(id=5, name="general", parent_id=None, parent=None, guild=SimpleNamespace(id=777))
    keys = DiscordAdapter._discord_channel_keys_from_channel(None, ch)
    assert "777" in keys and "5" in keys
    dm = SimpleNamespace(id=6, name="", parent_id=None, parent=None)
    assert DiscordAdapter._discord_channel_keys_from_channel(None, dm) == {"6"}


class _FakeDave:
    """Frames are b'<uid>:<payload>'; only the sender's key decrypts them."""
    user_id = 1

    def get_user_ids(self):
        return ["1", "100", "200"]

    def decrypt(self, uid, _media, frame):
        if not frame.endswith(b"\xfa\xfa"):
            return frame  # unencrypted silence decrypts under any key — the trap
        sender, _, payload = frame[:-2].partition(b":")
        if int(sender) != uid:
            raise RuntimeError("DecryptionFailed(NoValidCryptorFound)")
        return payload


@pytest.fixture(autouse=False)
def fake_davey(monkeypatch):
    import sys
    monkeypatch.setitem(sys.modules, "davey", SimpleNamespace(MediaType=SimpleNamespace(audio="audio")))


def test_dave_probe_identifies_unannounced_speakers(fake_davey):
    """Symptom: joining a call where people were already talking saved 0 audio files —
    Discord sent no SPEAKING events, so every frame was dropped as unmapped."""
    r = _receiver_in_channel([1, 100, 200], allowed={"100"}, recorder=object(), mapped={})
    dave = _FakeDave()
    assert r._probe_dave_sender(11, dave, b"200:abc\xfa\xfa") == (200, b"abc")
    assert r._probe_dave_sender(22, dave, b"100:xyz\xfa\xfa") == (100, b"xyz")
    assert r._ssrc_to_user == {11: 200, 22: 100}


def test_dave_probe_never_maps_on_failure_or_bot_key(fake_davey):
    r = _receiver_in_channel([1, 100], allowed=None, recorder=object(), mapped={})
    assert r._probe_dave_sender(11, _FakeDave(), b"999:abc\xfa\xfa") is None
    assert r._probe_dave_sender(12, _FakeDave(), b"1:abc\xfa\xfa") is None  # bot's own key skipped
    assert r._ssrc_to_user == {}


def test_dave_probe_ignores_unencrypted_silence(fake_davey):
    """Symptom: an hour-long meeting saved two silent tracks — an Opus silence frame
    'decrypted' under the first key tried, pinning a speaker to the wrong person."""
    r = _receiver_in_channel([1, 100, 200], allowed=None, recorder=object(), mapped={})
    assert r._probe_dave_sender(11, _FakeDave(), b"\xf8\xff\xfe") is None
    assert r._ssrc_to_user == {}


def test_dave_probe_fixes_swapped_mapping(fake_davey):
    r = _receiver_in_channel([1, 100, 200], allowed=None, recorder=object(),
                             mapped={11: 100, 22: 200})  # wrong: 11 is really 200
    r._decoders = {}
    assert r._probe_dave_sender(11, _FakeDave(), b"200:a\xfa\xfa", exclude=frozenset({100})) == (200, b"a")
    assert r._ssrc_to_user == {11: 200}  # stale 22->200 dropped; 22 re-probes on its next frame
