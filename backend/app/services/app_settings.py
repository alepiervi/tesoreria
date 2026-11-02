"""Impostazioni del gruppo salvate nel database (oggi: casella email per l'invio). Le password sono cifrate."""
import base64
import hashlib

from cryptography.fernet import Fernet, InvalidToken

from ..config import settings
from ..db import get_db
from ..utils import now_iso

EMAIL_ID = "email"
ARUBA = {"host": "smtps.aruba.it", "port": 465, "ssl": True}


def _fernet() -> Fernet:
    key = hashlib.sha256(("nureal-settings|" + settings.jwt_secret).encode()).digest()
    return Fernet(base64.urlsafe_b64encode(key))


def encrypt(value: str) -> str:
    return _fernet().encrypt(value.encode()).decode()


def decrypt(token: str) -> str | None:
    try:
        return _fernet().decrypt(token.encode()).decode()
    except (InvalidToken, ValueError):
        return None


async def get_email_config() -> dict | None:
    """Configurazione completa (con password in chiaro) solo per l'invio; None se non attiva."""
    doc = await get_db().app_settings.find_one({"id": EMAIL_ID}, {"_id": 0})
    if not doc or not doc.get("enabled") or not doc.get("password_enc"):
        return None
    password = decrypt(doc["password_enc"])
    if password is None:
        return None
    return {**doc, "password": password}


async def public_email_config() -> dict:
    doc = await get_db().app_settings.find_one({"id": EMAIL_ID}, {"_id": 0}) or {}
    return {
        "enabled": bool(doc.get("enabled")), "host": doc.get("host", ARUBA["host"]), "port": doc.get("port", ARUBA["port"]),
        "ssl": doc.get("ssl", ARUBA["ssl"]), "user": doc.get("user", ""), "from_addr": doc.get("from_addr", ""),
        "from_name": doc.get("from_name", "Nureal-Amministrazione"), "has_password": bool(doc.get("password_enc")),
        "password_ok": bool(doc.get("password_enc")) and decrypt(doc["password_enc"]) is not None,
        "updated_at": doc.get("updated_at"), "last_test": doc.get("last_test"),
    }


async def save_email_config(data: dict, password: str | None, user_id: str):
    update = {**data, "id": EMAIL_ID, "updated_at": now_iso(), "updated_by": user_id}
    if password:
        update["password_enc"] = encrypt(password)
    await get_db().app_settings.update_one({"id": EMAIL_ID}, {"$set": update}, upsert=True)


async def email_mode() -> str:
    if await get_email_config():
        return "smtp"
    return "smtp" if settings.email_provider == "smtp" else "non_configurata"
