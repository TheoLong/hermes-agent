"""Dashboard credential-vault routes (``hermes_cli/web_routers/vault.py``).

The vault page lets an operator manage saved logins, cards and addresses from the web
dashboard instead of the Desktop app. These pin the contracts that make that safe:

* no route ever returns a submitted secret value: password, card number, CVC, address
  line or authenticator seed;
* the session token gates every route;
* the item lands in the NAMED profile's vault, and removal refuses an unnamed profile on a
  multi-profile host like every other destructive route;
* password-manager items are not removable from here.
"""

import json

import pytest

SECRET_PASSWORD = "Pw-correct-horse-battery-91"
SECRET_SEED = "JBSWY3DPEHPK3PXP"
SECRET_CARD = "4111111111111111"
SECRET_CVC = "737"


@pytest.fixture(autouse=True)
def _multiplex_state_is_per_test():
    import agent.secret_scope as secret_scope
    from tui_gateway import launch_profile_policy

    was_active = secret_scope.is_multiplex_active()
    snapshot = launch_profile_policy._snapshot
    secret_scope.set_multiplex_active(False)
    launch_profile_policy._snapshot = None
    try:
        yield
    finally:
        secret_scope.set_multiplex_active(was_active)
        launch_profile_policy._snapshot = snapshot


@pytest.fixture
def homes(monkeypatch, _isolate_hermes_home):
    from hermes_cli import profiles
    from hermes_constants import get_hermes_home

    launch = get_hermes_home()
    root = launch / "profiles"
    beta = root / "worker_beta"
    beta.mkdir(parents=True)
    (beta / ".env").write_text("BETA=1\n", encoding="utf-8")
    monkeypatch.setattr(profiles, "_get_default_hermes_home", lambda: launch)
    monkeypatch.setattr(profiles, "_get_profiles_root", lambda: root)
    return {"launch": launch, "worker_beta": beta}


@pytest.fixture
def client(monkeypatch, homes):
    try:
        from starlette.testclient import TestClient
    except ImportError:
        pytest.skip("fastapi/starlette not installed")
    import hermes_state
    from hermes_cli.web_server import app, _SESSION_HEADER_NAME, _SESSION_TOKEN

    monkeypatch.setattr(hermes_state, "DEFAULT_DB_PATH", homes["launch"] / "state.db")
    c = TestClient(app)
    c.headers[_SESSION_HEADER_NAME] = _SESSION_TOKEN
    return c


def _login(**over):
    body = {"kind": "login", "label": "Example", "origin": "https://example.com/login",
            "secret": {"identifier_type": "email", "identifier": "op@example.com",
                       "password": SECRET_PASSWORD, "otp_secret": SECRET_SEED}}
    body.update(over)
    return body


def _no_secret(text: str) -> None:
    for value in (SECRET_PASSWORD, SECRET_SEED, SECRET_CARD, SECRET_CVC):
        assert value not in text


def test_add_login_returns_metadata_only_and_lists(client):
    r = client.post("/api/vault/items", json=_login())
    assert r.status_code == 200, r.text
    _no_secret(r.text)
    item = r.json()["item"]
    assert item["origin"] == "https://example.com"
    assert item["identifier"] == "op@example.com"
    assert item["has_otp"] is True

    listed = client.get("/api/vault/items")
    assert listed.status_code == 200
    _no_secret(listed.text)
    assert [i["id"] for i in listed.json()["items"]] == [item["id"]]


def test_add_payment_never_echoes_card_values(client):
    r = client.post("/api/vault/items", json={
        "kind": "payment", "label": "Visa",
        "secret": {"card_number": SECRET_CARD, "exp_month": "12", "exp_year": "2031", "cvc": SECRET_CVC}})
    assert r.status_code == 200, r.text
    _no_secret(r.text)
    _no_secret(client.get("/api/vault/items").text)


def test_validation_error_is_scrubbed(client):
    """A rejected payload must not bounce its secret back in the error detail."""
    r = client.post("/api/vault/items", json=_login(secret={
        "identifier_type": "email", "identifier": "op@example.com",
        "password": SECRET_PASSWORD, "otp_secret": SECRET_PASSWORD}))
    assert r.status_code == 400
    _no_secret(r.text)


def test_stored_secret_is_the_submitted_one(client):
    """Metadata-only responses must not mean the secret was dropped on the way in."""
    from agent.vault_store import get_vault_store

    item_id = client.post("/api/vault/items", json=_login()).json()["item"]["id"]
    assert get_vault_store().resolve_secret(item_id)["password"] == SECRET_PASSWORD


def test_routes_require_the_session_token(client):
    from hermes_cli.web_server import _SESSION_HEADER_NAME

    client.headers.pop(_SESSION_HEADER_NAME)
    assert client.get("/api/vault/items").status_code == 401
    assert client.post("/api/vault/items", json=_login()).status_code == 401
    assert client.delete("/api/vault/items/vault_abc").status_code == 401


def test_remove_deletes_and_404s_after(client):
    item_id = client.post("/api/vault/items", json=_login()).json()["item"]["id"]
    assert client.delete(f"/api/vault/items/{item_id}").json() == {"ok": True}
    assert client.get("/api/vault/items").json()["items"] == []
    assert client.delete(f"/api/vault/items/{item_id}").status_code == 404


def test_manager_items_are_not_removable_here(client):
    r = client.delete("/api/vault/items/op:abc123")
    assert r.status_code == 400


def test_item_lands_in_the_named_profile(client, homes):
    from agent.vault_store import VaultStore

    r = client.post("/api/vault/items?profile=worker_beta", json=_login())
    assert r.status_code == 200, r.text
    assert client.get("/api/vault/items").json()["items"] == []
    beta_items = client.get("/api/vault/items?profile=worker_beta").json()["items"]
    assert [i["id"] for i in beta_items] == [r.json()["item"]["id"]]
    assert (homes["worker_beta"] / "vault").is_dir()


def test_unnamed_remove_is_refused_on_a_multi_profile_host(client):
    import agent.secret_scope as secret_scope

    item_id = client.post("/api/vault/items", json=_login()).json()["item"]["id"]
    secret_scope.set_multiplex_active(True)
    assert client.delete(f"/api/vault/items/{item_id}").status_code == 400
    assert client.delete(f"/api/vault/items/{item_id}?profile=current").status_code in (200, 404)


def test_sources_lists_local_and_reports_managers_as_status(client):
    rows = client.get("/api/vault/sources").json()["sources"]
    assert rows[0]["name"] == "local" and rows[0]["unlocked"] is True
    assert all({"name", "enabled", "installed", "unlocked"} <= set(r) for r in rows)
    json.dumps(rows)
