"""Real supervised WebSocket vault fills, exclusively ephemeral HTTP/Chromium.

Run with HERMES_E2E_BROWSER=1 scripts/run_tests.sh -m integration <this file>.
The receipt contains booleans and metadata only, never synthetic credential values.
"""
from __future__ import annotations

import argparse
import http.server
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import threading
import time
import uuid
from types import SimpleNamespace

import pytest

from agent.vault_store import VaultStore
from hermes_cli import vault as cli
from tools import browser_vault_tool as vault
from tools.browser_supervisor import SUPERVISOR_REGISTRY
from tools.registry import registry

pytestmark = [pytest.mark.integration, pytest.mark.skipif(
    os.environ.get("HERMES_E2E_BROWSER") != "1", reason="explicit real-browser opt-in required")]


@pytest.fixture(scope="module")
def browser(tmp_path_factory):
    binary = shutil.which("google-chrome") or shutil.which("chromium")
    if not binary:
        pytest.skip("Chrome/Chromium not installed")
    root = tmp_path_factory.mktemp("vault-browser")
    profile = root / "profile"
    state = SimpleNamespace(html="", submitted=0, requests=[], records=[])

    class Handler(http.server.BaseHTTPRequestHandler):
        def do_GET(self):
            state.requests.append(self.path)
            self.send_response(200)
            self.send_header("Content-Type", "text/html")
            self.end_headers()
            self.wfile.write(state.html.encode())

        def do_POST(self):
            state.submitted += 1
            self.send_response(204)
            self.end_headers()

        def log_message(self, format, *args):
            pass

    server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    state.origin = f"http://127.0.0.1:{server.server_port}"
    proc = subprocess.Popen([binary, "--headless=new", "--remote-debugging-port=0",
        f"--user-data-dir={profile}", "--no-first-run", "--no-default-browser-check",
        "--disable-background-networking", "about:blank"],
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    task = "synthetic-vault-" + uuid.uuid4().hex
    state.task = task
    try:
        deadline = time.monotonic() + 15
        while not (profile / "DevToolsActivePort").exists():
            assert proc.poll() is None, "ephemeral Chromium exited"
            assert time.monotonic() < deadline, "ephemeral Chromium CDP timeout"
            time.sleep(0.1)
        lines = (profile / "DevToolsActivePort").read_text().splitlines()
        state.sup = SUPERVISOR_REGISTRY.get_or_start(
            task_id=task, cdp_url=f"ws://127.0.0.1:{lines[0]}{lines[1]}")
        yield state
    finally:
        SUPERVISOR_REGISTRY.stop(task)
        proc.terminate()
        try:
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.wait(timeout=5)
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)
        receipt = Path(tempfile.mkdtemp(prefix="vault-password-change-receipt-")) / "receipt.json"
        receipt.write_text(json.dumps({"module": str(Path(vault.__file__).resolve()),
            "chromium_binary": binary, "profile": str(profile), "browser_exit_code": proc.returncode,
            "post_count": state.submitted, "cases": state.records}, indent=2))
        print(f"VAULT_CHANGE_RECEIPT={receipt}")


def evaluate(browser, expression, **kwargs):
    result = browser.sup.evaluate_runtime(expression, **kwargs)
    assert result.get("ok"), "supervised evaluation failed"
    return result.get("result")


def navigate(browser, html):
    path = "/synthetic-" + uuid.uuid4().hex
    browser.html = '<!doctype html><title>synthetic vault</title>' + html + '''
<script>window.submits=0; document.addEventListener('submit', e=>{e.preventDefault();window.submits++});</script>'''
    evaluate(browser, "location.href=" + json.dumps(browser.origin + path))
    deadline = time.monotonic() + 10
    while True:
        result = browser.sup.evaluate_runtime("location.pathname + ':' + document.readyState")
        if result.get("result") == path + ":complete":
            return
        assert time.monotonic() < deadline, "synthetic page navigation timeout"
        time.sleep(0.05)


OLD = '<label>Old Password<input type=password name=oldPassword autocomplete=off></label>'
NEW = '<label>New Password<input type=password name=newPassword1 autocomplete=off></label>'
CONFIRM = '<label>Re-Type New Password<input type=password name=newPassword2 autocomplete=off></label>'


def form(fields):
    return '<form method=post>' + fields + '<button>Change Password</button></form>'


@pytest.fixture
def credentials(browser, tmp_path, monkeypatch, capsys):
    store = VaultStore(base_dir=tmp_path / "vault")
    monkeypatch.setattr("agent.vault_store.get_vault_store", lambda: store)
    parser = argparse.ArgumentParser()
    cli.register_cli(parser)
    for label in ("current", "new"):
        cli.vault_command(parser.parse_args(["generate-login", "--origin", browser.origin,
            "--identifier", "synthetic@example.test", "--label", label]))
    items = {item.label: item for item in store.list_items()}
    values = {label: store.resolve_secret(item.id)["password"] for label, item in items.items()}
    output = capsys.readouterr().out
    assert not any(secret in output for secret in values.values()), "CLI leaked a generated password"
    assert all(item.generated for item in items.values())
    return store, items, values


@pytest.mark.parametrize("case", ["change", "change_without_current", "signup_off", "signup_tokens",
    "signup_single", "login", "ordinary_new_excluded", "ordinary_confirmation_excluded", "otp_excluded"])
def test_real_fill_and_secret_blindness(browser, credentials, case):
    store, items, values = credentials
    expected = []
    args = {"handle": items["new"].id}
    if case.startswith("change"):
        html = form(OLD + NEW + CONFIRM)
        args["mode"] = "password_change"
        if case == "change":
            args["current_handle"] = items["current"].id
            expected = [values["current"], values["new"], values["new"]]
        else:
            expected = ["", values["new"], values["new"]]
    elif case.startswith("signup"):
        html = form(NEW + ("" if case == "signup_single" else CONFIRM))
        if case == "signup_tokens":
            html = html.replace('autocomplete=off', 'autocomplete=new-password')
        args["mode"] = "signup"
        expected = [values["new"]] * (1 if case == "signup_single" else 2)
    else:
        regular = store.add_item("login", "ordinary", {"identifier_type": "email",
            "identifier": "synthetic@example.test", "password": values["current"]}, origin=browser.origin)
        args["handle"] = regular.id
        html = {"login": form(OLD + NEW + CONFIRM),
                "ordinary_new_excluded": form(NEW.replace('autocomplete=off', 'autocomplete=new-password')),
                "ordinary_confirmation_excluded": form(CONFIRM.replace('Re-Type New Password', 'Re-Type Password')),
                "otp_excluded": form('<input type=password autocomplete=one-time-code>')}[case]
        expected = [values["current"], "", ""] if case == "login" else [""]
    navigate(browser, html)
    # The page cannot override the supervisor's isolated-world natives.
    evaluate(browser, "void Object.defineProperty(HTMLInputElement.prototype, 'value', {set(){throw Error('page setter')},get(){return 'page-world'}})")
    raw = registry.dispatch("browser_vault_fill", args, task_id=browser.task)
    assert isinstance(raw, str)
    result = json.loads(raw)
    should_fill = case in ("change", "change_without_current", "signup_off", "signup_tokens", "signup_single", "login")
    assert result["success"] is should_fill, result
    actual = evaluate(browser, "Array.from(document.querySelectorAll('input')).map(e=>e.value)", world_name=vault._VAULT_ISOLATED_WORLD)
    assert actual == expected, "password targets/values differ"
    if should_fill:
        assert result["filled_fields"] == sum(bool(value) for value in expected)
        assert evaluate(browser, "document.querySelectorAll('[data-hermes-vault-slot]').length") == 0
    assert not any(secret in raw for secret in values.values()), "tool response leaked a password"
    from tools.browser_cdp_tool import _redact_cdp_output
    scrubbed = json.dumps(_redact_cdp_output({"result": {"value": actual}}))
    assert not any(secret in scrubbed for secret in values.values()), "CDP egress leaked a password"
    assert evaluate(browser, "window.submits") == 0
    assert browser.submitted == 0
    browser.records.append({"case": case, "passed": True, "filled_fields": result.get("filled_fields", 0),
                            "secret_blind": True, "submitted": False})


@pytest.mark.parametrize("case", ["origin", "identity", "handle_origin", "same_handle", "missing_handle", "ordinary_new",
    "multiform", "ambiguous", "hidden", "disabled", "readonly", "otp", "conflicting_roles", "missing_confirmation",
    "race_disabled", "race_hidden", "race_readonly", "race_type", "race_label", "race_autocomplete", "race_form",
    "race_clone", "race_extra", "race_origin", "maxlength"])
def test_refusal_is_atomic(browser, credentials, monkeypatch, case):
    store, items, values = credentials
    html = form(OLD + NEW + CONFIRM)
    args = {"handle": items["new"].id, "mode": "password_change", "current_handle": items["current"].id}
    if case in ("identity", "handle_origin", "ordinary_new"):
        other = store.add_item("login", "other", {"identifier_type": "email",
            "identifier": "other@example.test" if case == "identity" else "synthetic@example.test",
            "password": values["current"]},
            origin=browser.origin.replace("127.0.0.1", "localhost") if case == "handle_origin" else browser.origin)
        args["handle" if case == "ordinary_new" else "current_handle"] = other.id
    if case == "same_handle":
        args["current_handle"] = args["handle"]
    if case == "missing_handle":
        args["current_handle"] = "vault_missing"
    html = {"multiform": html + form(NEW + CONFIRM),
            "ambiguous": form(OLD + '<input type=password name=unknown>' + CONFIRM),
            "hidden": form(OLD + NEW + CONFIRM.replace('name=newPassword2', 'name=newPassword2 hidden')),
            "disabled": form(OLD + NEW + '<fieldset disabled>' + CONFIRM + '</fieldset>'),
            "readonly": form(OLD + NEW + CONFIRM.replace('name=newPassword2', 'name=newPassword2 readonly')),
            "otp": form(OLD + NEW + CONFIRM.replace('autocomplete=off', 'autocomplete=one-time-code')),
            "conflicting_roles": form(OLD + NEW.replace('autocomplete=off', 'autocomplete=current-password') + CONFIRM),
            "missing_confirmation": form(OLD + NEW),
            "maxlength": form(OLD + NEW + CONFIRM.replace('name=newPassword2', 'name=newPassword2 maxlength=2'))}.get(case, html)
    navigate(browser, html)
    if case == "origin":
        evaluate(browser, 'location.href=' + json.dumps(browser.origin.replace('127.0.0.1', 'localhost') + '/wrong-origin'))
        deadline = time.monotonic() + 5
        while evaluate(browser, 'location.hostname') != 'localhost':
            assert time.monotonic() < deadline
            time.sleep(0.05)
    mutations = {
        "race_disabled": 'e.disabled=true', "race_hidden": 'e.style.display="none"',
        "race_readonly": 'e.readOnly=true', "race_type": 'e.type="text"',
        "race_label": 'e.setAttribute("aria-label","different")',
        "race_autocomplete": 'e.autocomplete="one-time-code"',
        "race_form": 'const f=document.createElement("form"); document.body.append(f);f.append(e)',
        "race_clone": 'e.replaceWith(e.cloneNode(true))',
        "race_extra": 'const x=document.createElement("input");x.type="password";e.form.append(x)',
    }
    if case.startswith("race_"):
        original = vault._eval_js_secret
        def race(task, expression):
            if case == "race_origin":
                evaluate(browser, 'location.href=' + json.dumps(browser.origin.replace('127.0.0.1', 'localhost') + '/race'))
                deadline = time.monotonic() + 5
                while evaluate(browser, 'location.hostname') != 'localhost':
                    assert time.monotonic() < deadline
                    time.sleep(0.05)
            else:
                evaluate(browser, '(() => {const e=document.querySelector("[name=newPassword2]");' + mutations[case] + '})()')
            return original(task, expression)
        monkeypatch.setattr(vault, "_eval_js_secret", race)
    raw = registry.dispatch("browser_vault_fill", args, task_id=browser.task)
    assert isinstance(raw, str)
    result = json.loads(raw)
    assert not result["success"], result
    assert result.get("error_type"), result
    assert not any(secret in raw for secret in values.values()), "refusal leaked a password"
    assert evaluate(browser, "Array.from(document.querySelectorAll('input')).every(e=>!e.value)") is True
    assert evaluate(browser, "window.submits || 0") == 0
    assert browser.submitted == 0
    browser.records.append({"case": case, "passed": True, "error_type": result["error_type"],
                            "no_partial_writes": True, "submitted": False})
