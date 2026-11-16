import asyncio

import pyotp

from app.db import get_db
from app.seed import DEMO_PASSWORD
from tests.conftest import login


def _member(client, h, email):
    return next(m for m in client.get("/api/members", headers=h).json() if m["email"] == email)


def test_owner_resets_collaborator_password_keeping_2fa(client):
    owner = login(client, "titolare@demo.it")
    target = _member(client, owner, "commercialista@demo.it")
    asyncio.run(get_db().users.update_one({"id": target["id"]}, {"$set": {"totp_enabled": True, "totp_secret": pyotp.random_base32()}}))
    r = client.post(f"/api/members/{target['id']}/reset-password", headers=owner)
    assert r.status_code == 200
    temp = r.json()["temporary_password"]
    u = asyncio.run(get_db().users.find_one({"id": target["id"]}))
    assert u["totp_enabled"] and u["totp_secret"] and u["must_change_password"]
    assert client.post("/api/auth/login", json={"email": "commercialista@demo.it", "password": DEMO_PASSWORD}).status_code == 401
    # 2FA ancora richiesta con la password provvisoria
    assert client.post("/api/auth/login", json={"email": "commercialista@demo.it", "password": temp}).json()["detail"] == "2fa_required"
    asyncio.run(get_db().users.update_one({"id": target["id"]}, {"$set": {"totp_enabled": False}}))
    tok = client.post("/api/auth/login", json={"email": "commercialista@demo.it", "password": temp}).json()["access_token"]
    h = {"Authorization": f"Bearer {tok}"}
    assert client.get("/api/auth/me", headers=h).json()["user"]["must_change_password"] is True
    assert client.get("/api/companies", headers=h).status_code == 403
    assert client.post("/api/auth/password", json={"current_password": temp, "new_password": temp}, headers=h).status_code == 400
    r = client.post("/api/auth/password", json={"current_password": temp, "new_password": "NuovaPassword2026"}, headers=h)
    h = {"Authorization": f"Bearer {r.json()['access_token']}"}
    assert client.get("/api/companies", headers=h).status_code == 200
    asyncio.run(get_db().users.update_one({"id": target["id"]}, {"$set": {"password_hash": u["password_hash"]}}))


def test_owner_cannot_reset_another_owner_or_self(client):
    owner = login(client, "titolare@demo.it")
    me = client.get("/api/auth/me", headers=owner).json()["user"]
    assert client.post(f"/api/members/{me['id']}/reset-password", headers=owner).status_code == 400
    assert client.post(f"/api/members/{me['id']}/reset-password", headers=login(client, "amministrazione@demo.it")).status_code == 403


def test_temporary_password_expires_after_48_hours(client):
    owner = login(client, "titolare@demo.it")
    target = _member(client, owner, "amministrazione@demo.it")
    original = asyncio.run(get_db().users.find_one({"id": target["id"]}))
    r = client.post(f"/api/members/{target['id']}/reset-password", headers=owner).json()
    temp = r["temporary_password"]
    from datetime import datetime, timedelta, timezone
    exp = datetime.fromisoformat(r["expires_at"])
    assert timedelta(hours=47) < exp - datetime.now(timezone.utc) <= timedelta(hours=48)
    ok = client.post("/api/auth/login", json={"email": "amministrazione@demo.it", "password": temp})
    assert ok.status_code == 200
    past = (datetime.now(timezone.utc) - timedelta(minutes=1)).isoformat()
    asyncio.run(get_db().users.update_one({"id": target["id"]}, {"$set": {"temp_password_expires_at": past}}))
    r = client.post("/api/auth/login", json={"email": "amministrazione@demo.it", "password": temp})
    assert r.status_code == 401 and "scaduta" in r.json()["detail"]
    h = {"Authorization": f"Bearer {ok.json()['access_token']}"}
    assert client.post("/api/auth/password", json={"current_password": temp, "new_password": "Altra2026pass"}, headers=h).status_code == 401
    asyncio.run(get_db().users.update_one({"id": target["id"]}, {"$set": {
        "password_hash": original["password_hash"], "must_change_password": False, "temp_password_expires_at": None,
        "token_version": original.get("token_version", 0)}}))
