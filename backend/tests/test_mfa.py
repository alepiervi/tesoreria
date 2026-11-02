import time

import pyotp
import pytest

from app.config import settings
from app.seed import DEMO_PASSWORD


@pytest.fixture()
def mfa(monkeypatch):
    monkeypatch.setattr(settings, "require_2fa_login", True)


def _enroll(client, email):
    r = client.post("/api/auth/login", json={"email": email, "password": DEMO_PASSWORD})
    assert r.status_code == 200 and r.json()["setup_required"] and "access_token" not in r.json()
    token = r.json()["setup_token"]
    secret = client.post("/api/auth/2fa/enroll/start", json={"setup_token": token}).json()["secret"]
    return token, secret


def test_password_alone_never_gives_a_session(client, mfa):
    token, _ = _enroll(client, "amministrazione@demo.it")
    # il token di attivazione non vale come sessione
    assert client.get("/api/auth/me", headers={"Authorization": f"Bearer {token}"}).status_code == 401


def test_mandatory_enrollment_then_code_every_login(client, mfa):
    token, secret = _enroll(client, "amministrazione@demo.it")
    assert client.post("/api/auth/2fa/enroll/finish", json={"setup_token": token, "code": "000000"}).status_code == 401
    r = client.post("/api/auth/2fa/enroll/finish", json={"setup_token": token, "code": pyotp.TOTP(secret).now()})
    assert r.status_code == 200
    body = r.json()
    assert len(body["recovery_codes"]) == 10 and body["user"]["totp_enabled"]
    assert client.get("/api/auth/me", headers={"Authorization": f"Bearer {body['access_token']}"}).status_code == 200
    # accessi successivi: sempre il codice
    r = client.post("/api/auth/login", json={"email": "amministrazione@demo.it", "password": DEMO_PASSWORD})
    assert r.status_code == 401 and r.json()["detail"] == "2fa_required"
    later = pyotp.TOTP(secret).at(time.time() + 30)
    ok = client.post("/api/auth/login", json={"email": "amministrazione@demo.it", "password": DEMO_PASSWORD, "totp_code": later})
    assert ok.status_code == 200
    # stesso codice due volte: rifiutato
    again = client.post("/api/auth/login", json={"email": "amministrazione@demo.it", "password": DEMO_PASSWORD, "totp_code": later})
    assert again.status_code == 401
    # codice di recupero: vale una sola volta
    rc = body["recovery_codes"][0].replace("-", "").lower()
    assert client.post("/api/auth/login", json={"email": "amministrazione@demo.it", "password": DEMO_PASSWORD, "totp_code": rc}).status_code == 200
    assert client.post("/api/auth/login", json={"email": "amministrazione@demo.it", "password": DEMO_PASSWORD, "totp_code": rc}).status_code == 401
    # non si può disattivare quando è obbligatoria
    h = {"Authorization": f"Bearer {ok.json()['access_token']}"}
    assert client.post("/api/auth/2fa/disable", json={"code": "123456"}, headers=h).status_code == 400


def test_owner_can_reset_second_factor(client, mfa, monkeypatch):
    monkeypatch.setattr(settings, "require_2fa_login", False)
    owner = {"Authorization": f"Bearer {client.post('/api/auth/login', json={'email': 'titolare@demo.it', 'password': DEMO_PASSWORD}).json()['access_token']}"}
    monkeypatch.setattr(settings, "require_2fa_login", True)
    token, secret = _enroll(client, "commercialista@demo.it")
    client.post("/api/auth/2fa/enroll/finish", json={"setup_token": token, "code": pyotp.TOTP(secret).now()})
    target = next(m for m in client.get("/api/members", headers=owner).json() if m["email"] == "commercialista@demo.it")
    assert client.post(f"/api/members/{target['id']}/reset-2fa", headers=owner).status_code == 200
    r = client.post("/api/auth/login", json={"email": "commercialista@demo.it", "password": DEMO_PASSWORD})
    assert r.json().get("setup_required")


def test_security_headers(client):
    r = client.get("/api/health")
    assert r.headers["x-frame-options"] == "DENY" and r.headers["x-content-type-options"] == "nosniff"
