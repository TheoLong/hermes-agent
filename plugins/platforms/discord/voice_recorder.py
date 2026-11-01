"""Meeting recorder for Discord voice channels (``/voice record``).

The bot joins silently and writes every speaker's decoded PCM to a per-speaker raw track, padded
with silence so all tracks stay aligned to the recording clock. On stop (``/voice leave``, the bot
being kicked/disconnected) the tracks are mixed into one ``meeting.m4a`` plus one lossless ``.flac`` per
speaker and the mix is transcribed locally. Everything stays on this machine.
"""
from __future__ import annotations

import datetime as dt
import logging
import os
import re
import subprocess
import threading
import time
from pathlib import Path
from typing import Callable, Optional

logger = logging.getLogger(__name__)

SAMPLE_RATE = 48000
CHANNELS = 2
BYTES_PER_SECOND = SAMPLE_RATE * CHANNELS * 2
FRAME_ALIGN = CHANNELS * 2
# Gaps shorter than this are jitter, not silence; padding them would stretch speech.
GAP_PAD_THRESHOLD = int(0.2 * BYTES_PER_SECOND) // FRAME_ALIGN * FRAME_ALIGN
DEFAULT_ROOT = Path.home() / "Documents" / "Meetings"


def _safe(name: str) -> str:
    return re.sub(r"[^A-Za-z0-9._-]+", "_", name).strip("_") or "unknown"


class MeetingRecorder:
    """Thread-safe per-SSRC PCM writer aligned to one monotonic clock."""

    def __init__(self, label: str, root: Optional[Path] = None, clock: Callable[[], float] = time.monotonic):
        stamp = dt.datetime.now().strftime("%Y-%m-%d_%H%M%S")
        self.dir = Path(root or DEFAULT_ROOT) / f"{stamp}_{_safe(label)}"
        self.dir.mkdir(parents=True, exist_ok=True)
        self._clock = clock
        self._start = clock()
        self.started_at = dt.datetime.now()
        self._lock = threading.Lock()
        self._tracks: dict[int, list] = {}  # ssrc -> [file handle, bytes written]
        self.closed = False

    def write(self, ssrc: int, pcm: bytes) -> None:
        if not pcm:
            return
        with self._lock:
            if self.closed:
                return
            track = self._tracks.get(ssrc)
            if track is None:
                track = [open(self.dir / f"ssrc_{ssrc}.pcm", "wb"), 0]
                self._tracks[ssrc] = track
            fh, written = track
            # Where this frame should END on the shared clock.
            target_end = int((self._clock() - self._start) * BYTES_PER_SECOND) // FRAME_ALIGN * FRAME_ALIGN
            gap = target_end - len(pcm) - written
            if gap >= GAP_PAD_THRESHOLD:
                fh.write(b"\x00" * gap)
                written += gap
            fh.write(pcm)
            track[1] = written + len(pcm)

    def ssrcs(self) -> list[int]:
        with self._lock:
            return list(self._tracks)

    def close(self) -> dict[int, Path]:
        with self._lock:
            self.closed = True
            out = {}
            for ssrc, (fh, _w) in self._tracks.items():
                fh.close()
                out[ssrc] = self.dir / f"ssrc_{ssrc}.pcm"
            return out

    def finalize(self, names: dict[int, str], ffmpeg: str = "ffmpeg", transcribe: bool = True) -> dict:
        """Close tracks, encode per-speaker .ogg + mixed meeting.m4a, transcribe. Blocking."""
        raw = self.close()
        result: dict = {"dir": str(self.dir), "speakers": [], "mix": None, "transcript": None, "error": None}
        raw = {s: p for s, p in raw.items() if p.stat().st_size > 0}
        if not raw:
            result["error"] = "No audio was captured."
            return result
        used: set[str] = set()
        speaker_files = []
        for ssrc, pcm_path in raw.items():
            base = _safe(names.get(ssrc) or f"speaker_{ssrc}")
            name, n = base, 2
            while name in used:
                name, n = f"{base}_{n}", n + 1
            used.add(name)
            # Lossless per-speaker track for later processing (mixing/denoise/diarization).
            flac = self.dir / f"{name}.flac"
            subprocess.run([ffmpeg, "-y", "-loglevel", "error", "-f", "s16le", "-ar", str(SAMPLE_RATE),
                            "-ac", str(CHANNELS), "-i", str(pcm_path), "-c:a", "flac", str(flac)],
                           check=True, timeout=3600, stderr=subprocess.PIPE)
            speaker_files.append(flac)
            result["speakers"].append(name)
        mix = self.dir / "meeting.m4a"
        cmd = [ffmpeg, "-y", "-loglevel", "error"]
        for f in speaker_files:
            cmd += ["-i", str(f)]
        if len(speaker_files) > 1:
            cmd += ["-filter_complex", f"amix=inputs={len(speaker_files)}:duration=longest:normalize=0"]
        cmd += ["-c:a", "aac", "-b:a", "96k", str(mix)]
        subprocess.run(cmd, check=True, timeout=3600, stderr=subprocess.PIPE)
        result["mix"] = str(mix)
        for p in raw.values():
            p.unlink(missing_ok=True)
        if transcribe:
            try:
                from tools.transcription_tools import transcribe_audio
                tr = transcribe_audio(str(mix), source="voice_record")
                if tr.get("success") and tr.get("transcript", "").strip():
                    tpath = self.dir / "transcript.txt"
                    tpath.write_text(tr["transcript"].strip() + "\n", encoding="utf-8")
                    result["transcript"] = str(tpath)
                else:
                    result["error"] = f"Transcription failed: {tr.get('error') or 'empty transcript'}"
            except Exception as e:  # recording is still saved
                logger.warning("Meeting transcription failed: %s", e, exc_info=True)
                result["error"] = f"Transcription failed: {e}"
        return result
