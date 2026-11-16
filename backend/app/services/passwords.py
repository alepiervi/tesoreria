"""Password provvisorie: create da sviluppatore (per i titolari) o titolare (per i collaboratori).
Non toccano mai la verifica in due passaggi."""
import secrets

from .. import audit
from ..db import get_db
from ..security import hash_password

ALPHABET = "ABCDEFGHJKLMNPQRSTUVWXYZabcdefghjkmnpqrstuvwxyz23456789"


def temporary_password() -> str:
    body = "".join(secrets.choice(ALPHABET) for _ in range(10))
    return f"{body[:5]}-{body[5:]}-{secrets.randbelow(90) + 10}"


async def reset_password(actor: dict, target: dict) -> str:
    temp = temporary_password()
    await get_db().users.update_one({"id": target["id"]}, {
        "$set": {"password_hash": hash_password(temp), "must_change_password": True,
                 "failed_logins": 0, "locked_until": None},
        "$inc": {"token_version": 1}})
    await audit.log(actor, "password_azzerata", target=target["email"])
    return temp
