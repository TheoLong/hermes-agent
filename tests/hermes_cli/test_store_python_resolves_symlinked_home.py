"""A sandbox HOME must not leak into the shared install launcher.

Symptom: a script ran Hermes under a temporary HOME whose ``.hermes/tools`` symlinked to the
real store. Launcher self-repair then rewrote the install's ``.hermes/bin/hermes`` to exec the
interpreter *through the temp HOME*; once that directory was deleted every start failed with
exit 127 and the gateway crash-looped.
"""
import json
from pathlib import Path

from hermes_cli import _launchers


def test_store_python_through_symlinked_home_is_published_as_real_path(tmp_path, monkeypatch):
    real_tools = tmp_path / "real" / "tools"
    entry = "python-3.99.0-test"
    py = real_tools / entry / "bin" / "python3"
    py.parent.mkdir(parents=True)
    py.write_text("#!/bin/sh\n")
    py.chmod(0o755)
    (real_tools / "facts.json").write_text(json.dumps({"packages": {"python": {"entry": entry}}}))

    sandbox_tools = tmp_path / "sandbox home" / ".hermes" / "tools"
    sandbox_tools.parent.mkdir(parents=True)
    sandbox_tools.symlink_to(real_tools, target_is_directory=True)
    monkeypatch.setattr(_launchers, "store_root", lambda _root: sandbox_tools)

    got = _launchers.resolve_store_python(tmp_path)
    assert got == real_tools.resolve() / entry / "bin" / "python3"
    assert "sandbox home" not in str(got)


def test_missing_interpreter_still_returns_none(tmp_path, monkeypatch):
    tools = tmp_path / "tools"
    tools.mkdir()
    (tools / "facts.json").write_text(json.dumps({"packages": {"python": {"entry": "absent"}}}))
    monkeypatch.setattr(_launchers, "store_root", lambda _root: tools)
    assert _launchers.resolve_store_python(tmp_path) is None
