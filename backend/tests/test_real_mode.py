import pytest

from app.config import settings
from tests.conftest import login


@pytest.fixture()
def real_mode(monkeypatch):
    for k in ("banking_provider", "sdi_provider", "payments_provider", "whatsapp_provider", "email_provider"):
        monkeypatch.setattr(settings, k, "none")


def _company(client, h):
    return client.get("/api/companies", headers=h).json()[0]["id"]


def test_automatic_functions_are_off_and_never_create_fake_data(client, real_mode):
    h = login(client, "titolare@demo.it")
    cid = _company(client, h)
    feats = client.get("/api/auth/me", headers=h).json()["user"]["features"]
    assert feats["bank_auto"] is False and feats["sdi_auto"] is False and feats["payments_auto"] is False
    assert client.post(f"/api/companies/{cid}/bank-accounts/connect", json={"bank_name": "X"}, headers=h).status_code == 400
    assert client.post(f"/api/companies/{cid}/invoices/sync-sdi", headers=h).status_code == 400


def test_manual_payment_authorization_keeps_deadline_to_pay(client, real_mode):
    h = login(client, "titolare@demo.it")
    items = client.get("/api/deadlines", headers=h).json()
    items = items.get("items", items) if isinstance(items, dict) else items
    d = next(x for x in items if x["status"] == "da_pagare" and x.get("iban") and x["kind"] != "incasso")
    acc = next(a for a in client.get(f"/api/companies/{d['company_id']}/bank-accounts", headers=h).json())
    r = client.post(f"/api/deadlines/{d['id']}/authorize", json={"account_id": acc["id"]}, headers=h)
    assert r.status_code == 200 and r.json()["manual"] is True
    items = client.get("/api/deadlines", headers=h).json()
    items = items.get("items", items) if isinstance(items, dict) else items
    after = next(x for x in items if x["id"] == d["id"])
    assert after["status"] == "da_pagare" and after["authorized_at"]


def test_email_settings_owner_only_and_password_never_returned(client):
    h = login(client, "titolare@demo.it")
    body = {"host": "smtps.aruba.it", "port": 465, "ssl": True, "user": "info@esempio.it",
            "password": "segreta-123", "from_addr": "info@esempio.it", "from_name": "Prova"}
    r = client.put("/api/settings/email", json=body, headers=h)
    assert r.status_code == 200 and "password" not in r.json() and r.json()["password_ok"]
    assert "segreta-123" not in r.text
    assert client.get("/api/settings/email", headers=login(client, "commercialista@demo.it")).status_code == 403
    from app.services.app_settings import decrypt, encrypt
    token = encrypt("segreta-123")
    assert "segreta" not in token and decrypt(token) == "segreta-123"
