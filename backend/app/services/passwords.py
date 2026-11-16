"""Password provvisorie: create da sviluppatore (per i titolari) o titolare (per i collaboratori).
Non toccano mai la verifica in due passaggi."""
import secrets
from datetime import datetime, timedelta

from .. import audit
from ..db import get_db
from ..security import hash_password
from ..utils import now_utc

TEMP_HOURS = 48
EXPIRED = "La password provvisoria è scaduta (vale 48 ore). Chiedi un nuovo azzeramento."

ALPHABET = "ABCDEFGHJKLMNPQRSTUVWXYZabcdefghjkmnpqrstuvwxyz23456789"


def temporary_password() -> str:
    body = "".join(secrets.choice(ALPHABET) for _ in range(10))
    return f"{body[:5]}-{body[5:]}-{secrets.randbelow(90) + 10}"


def temp_expiry() -> str:
    return (now_utc() + timedelta(hours=TEMP_HOURS)).isoformat()


def temp_expired(user: dict) -> bool:
    exp = user.get("temp_password_expires_at")
    return bool(user.get("must_change_password") and exp and datetime.fromisoformat(exp) <= now_utc())


async def reset_password(actor: dict, target: dict) -> tuple[str, str]:
    temp = temporary_password()
    await get_db().users.update_one({"id": target["id"]}, {
        "$set": {"password_hash": hash_password(temp), "must_change_password": True,
                 "temp_password_expires_at": (expires := temp_expiry()), "failed_logins": 0, "locked_until": None},
        "$inc": {"token_version": 1}})
    await audit.log(actor, "password_azzerata", target=target["email"])
    return temp, expires
