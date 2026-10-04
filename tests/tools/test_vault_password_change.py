"""Password changes require explicit intent, separate handles and complete fields."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from agent.vault_store import VaultStore
from tools import browser_vault_tool as vault
from tools.registry import registry


def test_explicit_change_dispatch_is_secret_blind(tmp_path, monkeypatch):
    assert Path(vault.__file__).resolve().parents[1] == Path(__file__).resolve().parents[2]
    store = VaultStore(base_dir=tmp_path / "vault")
    monkeypatch.setattr("agent.vault_store.get_vault_store", lambda: store)
    handles = [store.add_item("login", label,
        {"identifier": "synthetic@example.test", "identifier_type": "email", "password": value},
        origin="https://example.test", generated=generated).id
        for label, value, generated in [("old", "synthetic-current-canary", False),
                                         ("new", "synthetic-new-canary", True)]]
    controls = [dict(index=i, formIndex=0, type="password", autocomplete="off", name=name, label=label)
                for i, (name, label) in enumerate([("oldPassword", "Old Password"),
                    ("newPassword1", "New Password"), ("newPassword2", "Re-Type New Password")])]
    monkeypatch.setattr(vault, "_focus_bound_origin", lambda *args: "https://example.test")
    monkeypatch.setattr(vault, "_current_page_origin", lambda *args: "https://example.test")
    monkeypatch.setattr(vault, "_eval_js", lambda *args: {"success": True, "result": json.dumps(controls)})
    sent = []
    def send(_task, expression):
        fills = json.loads(expression.split("const fills = ", 1)[1].split(";\n", 1)[0])
        sent.append(fills)
        return {"success": True, "result": json.dumps({"filled": len(fills)})}
    monkeypatch.setattr(vault, "_eval_js_secret", send)
    raw = registry.dispatch("browser_vault_fill", {
        "handle": handles[1], "mode": "password_change", "current_handle": handles[0]}, task_id="synthetic")
    result = json.loads(raw)
    assert result.get("filled_fields") == 3, result
    assert [f["value"] for f in sent[0]] == ["synthetic-current-canary", "synthetic-new-canary", "synthetic-new-canary"]
    assert not any(value in raw for value in ("synthetic-current-canary", "synthetic-new-canary"))
    assert result["submitted"] is False
