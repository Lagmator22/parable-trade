import sys
from urllib.parse import parse_qs, urlparse

import pytest
from fastapi import FastAPI, Request
from fastapi.testclient import TestClient

from parable import identity
from parable.config import Settings
from parable.db import execute, reset_db, rows
from parable.identity import current_seller, mask_email, router, upsert_seller
from parable.paypal import PayPalError, set_paypal
from parable.paypal_mock import MockPayPal


class FakeLedger:
    def __init__(self):
        self.entries = []

    def append(self, kind, subject, data):
        self.entries.append({"kind": kind, "subject": subject, "data": data})
        return self.entries[-1]


class FakeLivePayPal:
    def __init__(self, info=None, exchange_error=None):
        self.info = info or {"payer_id": "PAYER1", "name": "Ada", "email": "ada@example.com", "verified": True}
        self.exchange_error = exchange_error
        self.codes = []

    def oauth_authorize_url(self, state, redirect_uri):
        return f"https://www.sandbox.paypal.com/signin/authorize?state={state}&redirect_uri={redirect_uri}"

    def exchange_code(self, code):
        self.codes.append(code)
        if self.exchange_error:
            raise self.exchange_error
        return "user-token"

    def userinfo(self, user_token):
        return self.info


def settings_with(**values):
    return Settings(_env_file=None, **{"session_secret": "test-secret", **values})


@pytest.fixture
def ledger(monkeypatch):
    fake = FakeLedger()
    monkeypatch.setitem(sys.modules, "parable.ledger", fake)
    return fake


@pytest.fixture(autouse=True)
def isolated(monkeypatch):
    reset_db(":memory:")
    monkeypatch.setattr(identity, "get_settings", lambda: settings_with())
    set_paypal(MockPayPal(public_base_url="http://localhost:8000"))
    yield
    set_paypal(None)


@pytest.fixture
def client(ledger):
    app = FastAPI()
    app.include_router(router)
    return TestClient(app, follow_redirects=False)


def sign_in_demo(client, name="Ada Lovelace", email="ada@example.com"):
    return client.post("/paypal/mock-login", data={"name": name, "email": email})


def test_mask_email_hides_the_local_part():
    assert mask_email("ada@example.com") == "a***@example.com"
    assert mask_email("not-an-email") == ""
    assert mask_email(None) == ""


def test_me_is_anonymous_by_default(client):
    assert client.get("/api/me").json() == {"seller": None, "paypal_mode": "mock",
                                           "free_tries": {"limit": 5, "used": 0, "remaining": 5}}


def test_me_reports_real_mode_when_client_is_not_mock(client, monkeypatch):
    set_paypal(FakeLivePayPal())
    monkeypatch.setattr(identity, "paypal_mode", lambda: "sandbox")
    assert client.get("/api/me").json()["paypal_mode"] == "sandbox"


def test_mock_login_page_explains_the_demo(client):
    page = client.get("/paypal/mock-login")
    assert page.status_code == 200
    assert "text/html" in page.headers["content-type"]
    assert "sandbox keys are not configured" in page.text
    assert "demo sign-in" in page.text.lower()
    assert 'name="email"' in page.text and 'name="name"' in page.text


def test_login_redirects_to_mock_form_when_mocked(client):
    response = client.get("/paypal/login")
    assert response.status_code == 302
    assert response.headers["location"] == "/paypal/mock-login"


def test_mock_sign_in_creates_seller_and_session(client, ledger):
    response = sign_in_demo(client)
    assert response.status_code == 302
    assert response.headers["location"] == "/#sell"
    assert "parable_session" in response.headers["set-cookie"]
    assert "HttpOnly" in response.headers["set-cookie"]
    assert "samesite=lax" in response.headers["set-cookie"].lower()
    me = client.get("/api/me").json()
    assert me["seller"]["name"] == "Ada Lovelace"
    assert me["seller"]["verified"] is True
    assert me["seller"]["email_masked"] == "a***@example.com"
    assert me["seller"]["id"].startswith("s_")
    assert "email" not in me["seller"]


def test_first_sign_in_writes_ledger_entry_without_email(client, ledger):
    sign_in_demo(client)
    sign_in_demo(client)
    assert len(ledger.entries) == 1
    entry = ledger.entries[0]
    assert entry["kind"] == "seller.joined"
    assert entry["subject"].startswith("seller:s_")
    assert entry["data"] == {"name": "Ada Lovelace", "verified": True}
    assert "ada@example.com" not in str(entry)


def test_same_email_maps_to_same_seller_and_updates_name(client):
    sign_in_demo(client, name="Ada")
    first = client.get("/api/me").json()["seller"]["id"]
    sign_in_demo(client, name="Ada L.")
    me = client.get("/api/me").json()["seller"]
    assert me["id"] == first and me["name"] == "Ada L."
    assert len(rows("SELECT id FROM sellers")) == 1


def test_different_emails_make_different_sellers(client):
    sign_in_demo(client, email="a@example.com")
    sign_in_demo(client, email="b@example.com")
    assert len(rows("SELECT id FROM sellers")) == 2


@pytest.mark.parametrize("form", [{"name": "", "email": "a@example.com"}, {"name": "Ada", "email": "nope"}, {}])
def test_mock_sign_in_rejects_invalid_forms(client, form):
    response = client.post("/paypal/mock-login", data=form)
    assert response.status_code == 400
    assert "Enter a name and a valid email" in response.text
    assert rows("SELECT id FROM sellers") == []


def test_mock_sign_in_escapes_submitted_values(client):
    response = client.post("/paypal/mock-login", data={"name": '"><script>x</script>', "email": "bad"})
    assert "<script>x</script>" not in response.text


def test_mock_sign_in_is_disabled_when_paypal_is_real(client):
    set_paypal(FakeLivePayPal())
    assert client.get("/paypal/mock-login").status_code == 404
    assert sign_in_demo(client).status_code == 404


def test_logout_clears_the_session(client):
    sign_in_demo(client)
    response = client.post("/api/logout")
    assert response.json() == {"ok": True}
    assert client.get("/api/me").json()["seller"] is None


def test_tampered_session_cookie_is_anonymous(client):
    sign_in_demo(client)
    token = client.cookies.get("parable_session")
    client.cookies.clear()
    client.cookies.set("parable_session", token[:-3] + "abc")
    assert client.get("/api/me").json()["seller"] is None


def test_session_signed_with_another_secret_is_anonymous(client, monkeypatch):
    sign_in_demo(client)
    monkeypatch.setattr(identity, "get_settings", lambda: settings_with(session_secret="other"))
    assert client.get("/api/me").json()["seller"] is None


def test_expired_session_is_anonymous(client, monkeypatch):
    sign_in_demo(client)
    monkeypatch.setattr(identity, "SESSION_MAX_AGE", -1)
    assert client.get("/api/me").json()["seller"] is None


def test_session_for_deleted_seller_is_anonymous(client):
    sign_in_demo(client)
    execute("DELETE FROM sellers")
    assert client.get("/api/me").json()["seller"] is None


def test_current_seller_reads_the_session_cookie(client):
    sign_in_demo(client)
    seen = {}
    app = FastAPI()

    @app.get("/who")
    def who(request: Request):
        seen["seller"] = current_seller(request)
        return {}

    probe = TestClient(app)
    probe.cookies.update(client.cookies)
    probe.get("/who")
    assert seen["seller"]["name"] == "Ada Lovelace"
    assert seen["seller"]["email"] == "ada@example.com"


def test_secure_cookie_flag_follows_public_url(client, monkeypatch):
    monkeypatch.setattr(identity, "get_settings", lambda: settings_with(public_base_url="https://parable.example"))
    response = sign_in_demo(client)
    assert "Secure" in response.headers["set-cookie"]


def test_empty_secret_falls_back_to_a_random_one(client, monkeypatch):
    monkeypatch.setattr(identity, "get_settings", lambda: Settings(_env_file=None, session_secret=""))
    sign_in_demo(client)
    assert client.get("/api/me").json()["seller"]["name"] == "Ada Lovelace"


def test_upsert_seller_keeps_existing_email_when_blank(ledger):
    created = upsert_seller("PAYER1", "Ada", "ada@example.com", False)
    updated = upsert_seller("PAYER1", "", "", True)
    assert updated["id"] == created["id"]
    assert updated["name"] == "Ada" and updated["email"] == "ada@example.com" and updated["verified"] == 1
    assert rows("SELECT verified, email FROM sellers") == [{"verified": 1, "email": "ada@example.com"}]
    assert len(ledger.entries) == 1


def test_real_login_redirects_to_paypal_with_signed_state(client):
    set_paypal(FakeLivePayPal())
    response = client.get("/paypal/login")
    assert response.status_code == 302
    target = urlparse(response.headers["location"])
    assert target.netloc == "www.sandbox.paypal.com"
    query = parse_qs(target.query)
    assert query["redirect_uri"] == ["http://localhost:8000/paypal/callback"]
    assert query["state"][0]
    assert "parable_oauth_state" in response.headers["set-cookie"]


def start_real_login(client, paypal):
    set_paypal(paypal)
    response = client.get("/paypal/login")
    return parse_qs(urlparse(response.headers["location"]).query)["state"][0]


def test_real_callback_creates_seller_and_sets_session(client, ledger):
    paypal = FakeLivePayPal()
    state = start_real_login(client, paypal)
    response = client.get("/paypal/callback", params={"code": "CODE1", "state": state})
    assert response.status_code == 302
    assert response.headers["location"] == "/#sell"
    assert paypal.codes == ["CODE1"]
    assert client.get("/api/me").json()["seller"]["name"] == "Ada"
    assert ledger.entries[0]["data"] == {"name": "Ada", "verified": True}


def test_real_callback_rejects_wrong_or_missing_state(client):
    start_real_login(client, FakeLivePayPal())
    assert client.get("/paypal/callback", params={"code": "C", "state": "forged"}).status_code == 400
    assert client.get("/paypal/callback", params={"code": "C"}).status_code == 400
    client.cookies.clear()
    assert client.get("/paypal/callback", params={"code": "C", "state": "x"}).status_code == 400
    assert rows("SELECT id FROM sellers") == []


def test_real_callback_requires_a_code(client):
    state = start_real_login(client, FakeLivePayPal())
    response = client.get("/paypal/callback", params={"state": state})
    assert response.status_code == 400
    assert response.json() == {"detail": "missing code"}


def test_real_callback_maps_paypal_errors_to_502(client):
    failing = FakeLivePayPal(exchange_error=PayPalError(400, "invalid_grant", "expired"))
    state = start_real_login(client, failing)
    response = client.get("/paypal/callback", params={"code": "C", "state": state})
    assert response.status_code == 502
    assert response.json() == {"detail": "paypal: invalid_grant"}


def test_real_callback_without_payer_id_is_rejected(client):
    state = start_real_login(client, FakeLivePayPal(info={"payer_id": "", "name": "", "email": "", "verified": False}))
    response = client.get("/paypal/callback", params={"code": "C", "state": state})
    assert response.status_code == 502
    assert rows("SELECT id FROM sellers") == []


def test_real_callback_with_denied_consent_goes_home(client):
    start_real_login(client, FakeLivePayPal())
    response = client.get("/paypal/callback", params={"error": "access_denied"})
    assert response.status_code == 302
    assert response.headers["location"] == "/#sell"
    assert client.get("/api/me").json()["seller"] is None
